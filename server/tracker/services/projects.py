"""
Which projects a firm's time can be filed under.

Two sources, one answer:

  · MIRRORED — a Project that reflects a practice-management record (a Clio
    matter, via ExternalMatterMapping). Live while the external record is open.
    The external system owns the list; a project it does not know cannot push.

  · LOCAL — a Project kept in TimeTracker itself: created by hand, from a CSV,
    or inline from Daily Review. Live while `is_active`. Only counts for
    verticals that organise work this way (industry_categories.
    INDUSTRY_LOCAL_PROJECTS), because older code paths auto-create Project rows
    ("(General)") for every firm and those were never meant to be chosen.

Everything that asks "which projects can this client's time go to" — the
Daily Review queue, the picker, the attribution pass — asks here, so the rule
cannot drift between the screen that shows a project and the job that fills it.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

OPEN_STATUSES = {'open', 'pending', ''}


@dataclass
class ProjectOption:
    project_id: int
    client_id: int
    name: str
    mapped: bool
    # Mirrored-only detail. Blank for local projects.
    display_number: str = ''
    description: str = ''
    status: str = ''
    billing_method: str = ''
    requires_utbms: bool = False
    open_date: object = None
    responsible_attorney: str = ''
    practice_area: str = ''


def org_tracks_local_projects(org) -> bool:
    from tracker.industry_categories import tracks_local_projects
    return tracks_local_projects(getattr(org, 'industry_type', None))


def org_uses_projects(org) -> bool:
    """True when this firm files time under projects at all."""
    if org_tracks_local_projects(org):
        return True
    from tracker.models_task_type_sets import ExternalMatterMapping
    return ExternalMatterMapping.objects.filter(integration__organization=org).exists()


def selectable_projects(org, *, client_ids=None, include_ids=()) -> dict[int, list[ProjectOption]]:
    """client_id -> live projects, mirrored first then local, by name.

    `include_ids` keeps a project in the answer even when it has closed — the
    one a block already points at must stay visible in its own picker.
    """
    from tracker.models import Project
    from tracker.models_task_type_sets import ExternalMatterMapping

    include_ids = set(include_ids or ())
    out: dict[int, list[ProjectOption]] = defaultdict(list)

    mq = (ExternalMatterMapping.objects
          .filter(integration__organization=org)
          .select_related('project'))
    if client_ids is not None:
        mq = mq.filter(project__client_id__in=list(client_ids))
    mapped_ids = set()
    for m in mq:
        mapped_ids.add(m.project_id)
        live = (m.external_status or '').lower() in OPEN_STATUSES
        if not (live or m.project_id in include_ids):
            continue
        out[m.project.client_id].append(ProjectOption(
            project_id=m.project_id,
            client_id=m.project.client_id,
            name=m.display_number or m.project.name,
            mapped=True,
            display_number=m.display_number or '',
            description=m.external_name or '',
            status=m.external_status or '',
            billing_method=m.billing_method or '',
            requires_utbms=bool(m.requires_utbms),
            open_date=m.open_date,
            responsible_attorney=m.responsible_attorney or '',
            practice_area=m.practice_area or '',
        ))

    if org_tracks_local_projects(org):
        lq = Project.objects.filter(org=org).exclude(id__in=mapped_ids)
        if client_ids is not None:
            lq = lq.filter(client_id__in=list(client_ids))
        for p in lq.only('id', 'client_id', 'name', 'is_active'):
            if not (p.is_active or p.id in include_ids):
                continue
            out[p.client_id].append(ProjectOption(
                project_id=p.id, client_id=p.client_id, name=p.name, mapped=False,
                status='' if p.is_active else 'archived',
            ))

    for opts in out.values():
        opts.sort(key=lambda o: (not o.mapped, o.name.lower()))
    return dict(out)
