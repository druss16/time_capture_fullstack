"""
Suggest client ALIASES mined from the UN-ATTRIBUTED review pile (read-only).

Sibling to `suggest_aliases`, which mines *corrections*. This one mines the
blocks that are sitting in review with NO client — the ones the classifier
could not attribute. Many of those window titles literally name a client
(e.g. "St CA Foundation Chart AC.xlsx", "St Patirck_Chittenango_Budget
worksheet") but Stage 3 never matched because the name variant isn't a
registered alias yet.

For each distinctive work-subject found in the pile it tries to map the
subject to an existing client using the SAME token evidence Stage 3 uses,
then prints a ranked, human-approvable report:

  * MATCHED   — subject shares a distinctive token with exactly one client
                => candidate alias to add (recovers this + all future blocks)
  * UNMATCHED — distinctive subject that matches no single client
                => needs a manual client decision (nothing to auto-fix)

It writes NOTHING. To apply an accepted suggestion, use the existing
`suggest_aliases --org <id> --add <client_id> "<alias>"`.

Usage:
  python manage.py suggest_aliases_from_pile --org 21
  python manage.py suggest_aliases_from_pile --org 21 --start 2026-07-01 --end 2026-07-31
  python manage.py suggest_aliases_from_pile --org 21 --min-count 2
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from tracker.models import Block, Client, Organization
from tracker.services.classification_service import (
    ClassificationService as C,
    GENERIC_HAYSTACK_WORDS,
)
# Reuse the exact subject-extraction + distinctiveness gates from the
# corrections-based tool so both surfaces agree on what a "subject" is.
from tracker.management.commands.suggest_aliases import _subject, _is_distinctive


# Common English / business words that are >=4 chars and slip past
# GENERIC_HAYSTACK_WORDS but are NOT distinctive enough to identify a client
# on their own. A single one of these shared with a client name is almost
# always a false positive (proven against org 21's pile). Kept deliberately
# small and conservative — only words we actually saw cause bad matches.
_COMMON_STOPWORDS = {
    "plus", "with", "account", "used", "born", "park", "health", "being",
    "resource", "credit", "sale", "sales", "corporate", "corp", "home",
    "office", "services", "service", "employee", "report", "reports",
    "summary", "details", "detail", "review", "checking", "checks", "check",
    "bill", "bills", "statement", "statements", "accounting", "portal",
    "resources", "solutions", "energy", "advisor", "advisors", "experience",
    "experiences", "human", "parent", "pantry", "postal", "credits",
    "information", "message", "select", "print", "printing", "windows",
    "professional", "national", "general", "business", "banking", "family",
    "care", "caring", "twist", "painting", "round", "temps", "endowment",
}


def _distinctive_tokens(text: str) -> set[str]:
    """Normalized tokens >=4 chars that aren't generic/common vocabulary."""
    n = C._normalize_name(text or "")
    return {
        t for t in n.split()
        if len(t) >= 4
        and t not in GENERIC_HAYSTACK_WORDS
        and t not in _COMMON_STOPWORDS
    }


class Command(BaseCommand):
    help = "Suggest client aliases mined from the un-attributed review pile (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("--org", required=True, help="org id or name")
        parser.add_argument("--start", help="YYYY-MM-DD (default: no lower bound)")
        parser.add_argument("--end", help="YYYY-MM-DD (default: no upper bound)")
        parser.add_argument(
            "--min-count", type=int, default=1,
            help="Only report subjects seen at least this many times.",
        )
        parser.add_argument(
            "--min-shared", type=int, default=2,
            help="Require at least this many shared distinctive tokens between "
                 "the subject and the client before proposing an alias. 2 is "
                 "much safer than 1 (single common-word overlap = false positive).",
        )

    def _resolve_org(self, val):
        if str(val).isdigit():
            org = Organization.objects.filter(id=int(val)).first()
        else:
            org = Organization.objects.filter(name__icontains=val).first()
        if not org:
            raise CommandError(f"org not found: {val!r}")
        return org

    def handle(self, *args, **opts):
        org = self._resolve_org(opts["org"])

        # ---- Un-attributed review pile: no client, not committed/suppressed ----
        qs = Block.objects.filter(
            org=org,
            client__isnull=True,
            proposed_client__isnull=True,
        ).exclude(classification_state__in=["committed", "suppressed"])
        if opts.get("start"):
            qs = qs.filter(day__gte=dt.date.fromisoformat(opts["start"]))
        if opts.get("end"):
            qs = qs.filter(day__lte=dt.date.fromisoformat(opts["end"]))

        # ---- Build a token -> {client_ids} index from existing client names+aliases ----
        clients = list(Client.objects.filter(org=org, is_active=True))
        token_owners: dict[str, set[int]] = defaultdict(set)
        client_by_id = {}
        for c in clients:
            client_by_id[c.id] = c
            names = [c.name] + [a for a in (c.aliases or []) if isinstance(a, str)]
            for name in names:
                for tok in _distinctive_tokens(name):
                    token_owners[tok].add(c.id)

        # ---- Aggregate the pile by distinctive subject ----
        # subject -> {'count', 'minutes', 'examples'}
        subjects: dict[str, dict] = defaultdict(
            lambda: {"count": 0, "minutes": 0, "examples": []}
        )
        for b in qs.only("id", "window_title", "minutes"):
            subj = _subject(b.window_title)
            if not _is_distinctive(subj):
                continue
            rec = subjects[subj]
            rec["count"] += 1
            rec["minutes"] += b.minutes or 0
            if len(rec["examples"]) < 3:
                rec["examples"].append(b.id)

        matched = []    # (subject, client, count, minutes, shared_tokens)
        unmatched = []  # (subject, count, minutes)
        for subj, info in subjects.items():
            if info["count"] < opts["min_count"]:
                continue
            subj_tokens = _distinctive_tokens(subj)
            # Which existing clients share a distinctive token with this subject?
            owners: set[int] = set()
            shared: dict[int, set[str]] = defaultdict(set)
            for tok in subj_tokens:
                for cid in token_owners.get(tok, ()):
                    owners.add(cid)
                    shared[cid].add(tok)
            # Keep only clients sharing >= min-shared distinctive tokens.
            min_shared = opts["min_shared"]
            strong_owners = {cid for cid in owners if len(shared[cid]) >= min_shared}
            if len(strong_owners) == 1:
                cid = next(iter(strong_owners))
                # Guard: the subject must NOT already match that client safely
                # (else Stage 3 would have caught it and it wouldn't be here).
                c = client_by_id[cid]
                names = [c.name] + [a for a in (c.aliases or []) if isinstance(a, str)]
                if any(C._alias_matches_safely(n.lower(), subj.lower()) for n in names):
                    continue
                matched.append((subj, c, info, shared[cid]))
            else:
                # 0 owners => genuinely unknown; >1 => ambiguous across clients.
                unmatched.append((subj, info, owners))

        # ---- Report ----
        def _h(mins):
            return f"{mins/60:.1f}h"

        self.stdout.write(
            f"\n=== Alias suggestions from the un-attributed pile — "
            f"org {org.id} ({org.name}) ===\n"
        )

        matched.sort(key=lambda x: -x[2]["minutes"])
        self.stdout.write(self.style.SUCCESS(
            f"\nMATCHED — {len(matched)} subject(s) map to exactly one existing "
            f"client (candidate aliases):\n"
        ))
        for subj, c, info, toks in matched:
            self.stdout.write(
                f"  {info['count']:>3}x  {_h(info['minutes']):>6}  "
                f"add alias {subj!r}  ->  {c.name!r} (id {c.id})   "
                f"[shared: {', '.join(sorted(toks))}]  e.g. {info['examples']}"
            )
        if matched:
            self.stdout.write(
                "\n  Apply one with:\n"
                f"    python manage.py suggest_aliases --org {org.id} "
                f"--add <client_id> \"<subject>\"\n"
            )

        unmatched.sort(key=lambda x: -x[1]["minutes"])
        amb = [u for u in unmatched if u[2]]
        unk = [u for u in unmatched if not u[2]]
        self.stdout.write(self.style.WARNING(
            f"\nUNMATCHED — {len(unmatched)} distinctive subject(s) with no single "
            f"client ({len(amb)} ambiguous / {len(unk)} unknown) — need a manual "
            f"client decision:\n"
        ))
        for subj, info, owners in unmatched[:40]:
            tag = f"ambiguous across {len(owners)} clients" if owners else "unknown"
            self.stdout.write(
                f"  {info['count']:>3}x  {_h(info['minutes']):>6}  {subj!r}   ({tag})"
            )
        if len(unmatched) > 40:
            self.stdout.write(f"  ... and {len(unmatched) - 40} more")

        m_mins = sum(i["minutes"] for _, _, i, _ in matched)
        u_mins = sum(i["minutes"] for _, i, _ in unmatched)
        self.stdout.write(
            f"\nSummary: {_h(m_mins)} recoverable via {len(matched)} candidate "
            f"aliases; {_h(u_mins)} across {len(unmatched)} subjects need manual "
            f"assignment. (read-only — nothing written)\n"
        )
