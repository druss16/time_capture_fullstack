"""
Fold a client into another client, either as a project under it or as a plain
merge.

Firms import their project list as clients: "Acme Spring Campaign", "Acme
Brand Refresh" and a dozen more beside the real client, Acme Motors. That splits
the customer's time across a dozen "clients", and it makes the customer's own
name useless to the matcher: a title that says "Acme" names a dozen clients, so
nothing is matched and the block goes to a guess.

Two modes:

  project  The folded client becomes a project of the parent (same name). Its
           blocks, timecard rows and training examples that had no project get
           that project; the rest keep the project they had, which moves under
           the parent with them.
  merge    A duplicate of the parent ("ACME-Acme Motors" beside
           "Acme Motors"). Everything moves to the parent and
           no project is made.

Every other row that points at the folded client is repointed at the parent,
found by introspection so a newly added model is never silently missed, except:

  history  ClassificationAudit and AccuracySample record what happened, so
           they keep pointing at the old client. ClientDailyRollup is derived;
           the days it covered are rebuilt from blocks after the move.
  identity In project mode, the old client's links to an outside system
           (external client mapping, billing profile, QBO company) describe a
           campaign, not the customer, so they stay on the old client to be
           sorted by hand. In merge mode they move.
  conflict A row the parent already has an equivalent of (a unique
           constraint) stays on the old client and is reported.

The folded client is deactivated, never deleted. Writes use queryset
.update(), which fires no signals: moving a block must not re-run the
classifier on it.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from django.db import IntegrityError, models, transaction

from tracker.models import Block, Client, Project

MODE_PROJECT = "project"
MODE_MERGE = "merge"

# (model name, field name) left pointing at the old client.
HISTORY_FIELDS = {
    ("ClassificationAudit", "client_before"),
    ("ClassificationAudit", "client_after"),
    ("AccuracySample", "booked_client"),
    ("AccuracySample", "correct_client"),
    ("ClientDailyRollup", "client"),
}
# Left on the old client in project mode only.
IDENTITY_FIELDS = {
    ("ExternalClientMapping", "client"),
    ("ClientBillingProfile", "client"),
    ("QboCompanyMapping", "client"),
}
# Handled explicitly below (client + project are set together).
CLIENT_PROJECT_PAIRS = {
    ("Block", "client"): "project",
    ("TimecardEntry", "client"): "project",
    ("AITrainingExample", "correct_client"): "correct_project",
}
PROJECT_NAME_MAX = Project._meta.get_field("name").max_length


class ConversionError(ValueError):
    pass


@dataclass
class ConversionReport:
    old_id: int
    old_name: str
    parent_id: int
    parent_name: str
    mode: str
    project_id: int | None = None
    project_name: str = ""
    project_source: str = ""          # created | existing on parent | moved from old client
    block_count: int = 0
    block_minutes: int = 0
    blocks_given_project: int = 0
    moved_projects: list[str] = field(default_factory=list)
    moved: Counter = field(default_factory=Counter)        # "Model.field" -> rows
    left_identity: Counter = field(default_factory=Counter)
    left_conflict: Counter = field(default_factory=Counter)
    aliases_left: list[str] = field(default_factory=list)
    days: set = field(default_factory=set)                 # rollup days to rebuild


def _key(rel) -> tuple[str, str]:
    return rel.related_model.__name__, rel.field.name


def _repoint(qs, values: dict) -> tuple[int, int]:
    """Update qs with values. On a unique-constraint clash, fall back to one row
    at a time and leave the clashing rows where they are. Returns (moved, left)."""
    try:
        with transaction.atomic():
            return qs.update(**values), 0
    except IntegrityError:
        pass
    moved = left = 0
    for pk in list(qs.values_list("pk", flat=True)):
        try:
            with transaction.atomic():
                moved += qs.model._base_manager.filter(pk=pk).update(**values)
        except IntegrityError:
            left += 1
    return moved, left


def _validate(old: Client, parent: Client, mode: str) -> None:
    if mode not in (MODE_PROJECT, MODE_MERGE):
        raise ConversionError(f"unknown mode {mode!r}")
    if old.pk == parent.pk:
        raise ConversionError(f"client {old.pk} cannot be folded into itself")
    if old.org_id != parent.org_id:
        raise ConversionError(
            f"client {old.pk} is in org {old.org_id}, parent {parent.pk} is in org {parent.org_id}")
    if not parent.is_active:
        raise ConversionError(f"parent client {parent.pk} {parent.name!r} is inactive")
    from tracker.utils.client_name_match import is_internal_client
    if is_internal_client(old.name):
        raise ConversionError(f"client {old.pk} {old.name!r} is an Internal client")


def _target_project(old: Client, parent: Client, report: ConversionReport) -> Project:
    """The parent's project named after the old client: reuse one the parent
    already has, else take the old client's own project of that name, else make one."""
    name = old.name[:PROJECT_NAME_MAX]
    proj = Project.objects.filter(org_id=parent.org_id, client=parent, name=name).first()
    if proj:
        report.project_source = "existing on parent"
    else:
        proj = Project.objects.filter(org_id=old.org_id, client=old, name=name).first()
        if proj:
            Project.objects.filter(pk=proj.pk).update(client=parent)
            report.project_source = "moved from old client"
        else:
            proj = Project.objects.create(org_id=parent.org_id, client=parent, name=name)
            report.project_source = "created"
    if not proj.is_active:
        Project.objects.filter(pk=proj.pk).update(is_active=True)
    report.project_id, report.project_name = proj.pk, proj.name
    return proj


def _move_own_projects(old: Client, parent: Client, report: ConversionReport) -> None:
    """The old client's projects move under the parent; a name the parent already
    uses gets the old client's name appended."""
    taken = set(Project.objects.filter(org_id=parent.org_id, client=parent)
                .values_list("name", flat=True))
    for p in Project.objects.filter(client=old):
        name = p.name
        if name in taken:
            name = f"{p.name} ({old.name})"[:PROJECT_NAME_MAX]
            if name in taken:
                report.left_conflict["Project.client"] += 1
                continue
        Project.objects.filter(pk=p.pk).update(client=parent, name=name)
        taken.add(name)
        report.moved["Project.client"] += 1
        report.moved_projects.append(name if name == p.name else f"{p.name} -> {name}")


def _fold(old: Client, parent: Client, mode: str) -> ConversionReport:
    report = ConversionReport(old.pk, old.name, parent.pk, parent.name, mode)

    blocks = Block.objects.filter(client=old)
    agg = blocks.aggregate(n=models.Count("id"), m=models.Sum("minutes"))
    report.block_count, report.block_minutes = agg["n"] or 0, agg["m"] or 0
    report.days |= set(d for d in blocks.values_list("day", flat=True).distinct() if d)
    from tracker.analytics_v2.rollups.models import ClientDailyRollup
    report.days |= set(ClientDailyRollup.objects.filter(client=old)
                       .values_list("day", flat=True).distinct())

    proj = _target_project(old, parent, report) if mode == MODE_PROJECT else None
    _move_own_projects(old, parent, report)

    for rel in Client._meta.related_objects:
        key = _key(rel)
        label = f"{key[0]}.{key[1]}"
        model = rel.related_model
        if rel.many_to_many:
            accessor = rel.get_accessor_name()
            for obj in getattr(old, accessor).all():
                getattr(obj, rel.field.name).add(parent)
                getattr(obj, rel.field.name).remove(old)
                report.moved[label] += 1
            continue
        if key in HISTORY_FIELDS or key == ("Project", "client"):
            continue
        qs = model._base_manager.filter(**{rel.field.name: old})
        if not qs.exists():
            continue
        if mode == MODE_PROJECT and key in IDENTITY_FIELDS:
            report.left_identity[label] += qs.count()
            continue
        project_field = CLIENT_PROJECT_PAIRS.get(key)
        if proj is not None and project_field:
            n, _ = _repoint(qs.filter(**{f"{project_field}__isnull": True}),
                            {rel.field.name: parent, project_field: proj})
            report.moved[label] += n
            if key == ("Block", "client"):
                report.blocks_given_project = n
        n, left = _repoint(qs, {rel.field.name: parent})
        report.moved[label] += n
        if left:
            report.left_conflict[label] += left

    report.aliases_left = list(old.aliases or [])
    Client.objects.filter(pk=old.pk).update(is_active=False)
    return report


def fold_clients(org_id: int, parent_id: int, client_ids: list[int], *,
                 mode: str = MODE_PROJECT, apply: bool = False) -> list[ConversionReport]:
    """Fold each client into the parent. Without apply, everything runs and is
    then rolled back, so the report shows exactly what apply would do."""
    parent = Client.objects.get(pk=parent_id, org_id=org_id)
    olds = list(Client.objects.filter(pk__in=client_ids, org_id=org_id))
    missing = set(client_ids) - {c.pk for c in olds}
    if missing:
        raise ConversionError(f"clients not found in org {org_id}: {sorted(missing)}")
    for old in olds:
        _validate(old, parent, mode)

    reports: list[ConversionReport] = []

    class _DryRun(Exception):
        pass

    try:
        with transaction.atomic():
            for old in olds:
                reports.append(_fold(old, parent, mode))
            if not apply:
                raise _DryRun
    except _DryRun:
        pass

    if apply:
        rebuild_rollups(org_id, set().union(*(r.days for r in reports)) if reports else set())
    return reports


def rebuild_rollups(org_id: int, days: set) -> int:
    """Rebuild the client daily rollup for each day the moved time touched."""
    from tracker.analytics_v2.rollups.tasks import _rollup_client_daily_for_org_date
    from tracker.models import Organization
    org = Organization.objects.get(pk=org_id)
    for d in sorted(days):
        _rollup_client_daily_for_org_date(org, d)
    return len(days)
