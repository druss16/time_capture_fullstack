# Client Name Resolver — design doc

**Status:** proposed · Phase 1 in progress
**Author:** Dan + Claude · **Date:** 2026-07-01

## Problem

Blocks whose text plainly contains a client's name keep landing in **No Client**
(e.g. `Sacred Heart Basilica - QuickBooks … - [Enter Payroll Information]`,
`St. James Church - QuickBooks …`). Each incident has been fixed one at a time.
The reason it recurs: **"does this text name a client?" is answered in several
different places, each with its own logic.**

Known detection sites, pre-refactor:
- **Stage 3** (client matcher) — `_alias_matches_safely` + `_alias_match_score`
  + collision/tiebreak. The strong one.
- **Stage 0** (internal-work guard) — *was* a naive full-name substring
  (`name.lower() in text`); missed short/reordered forms. (Fixed to use the
  Stage-3 matcher in commit `4c4034b`.)
- **Normalization** — **two identical nested `_normalize` copies** inside the two
  matchers, plus other partial normalizers elsewhere. Two copies drifting is
  exactly what caused the `St.James` vs `St. James` bug.

Result: fix one path, the others still miss. Band-aid treadmill.

## Principle

**If the text contains a client's name, the block belongs to that client.**
Detection must be *one* capability, robust to abbreviations (`St.`/`St`/`Saint`),
word order, punctuation, possessives, short forms, and same-family ambiguity —
and it must be called by *every* stage, not re-implemented per stage.

## Architecture: one `ClientNameResolver`

A single component that is the **only** answer to "does this text name a client,
and which one?" Everything else calls it.

1. **Canonical normalization** — one function, the single source of truth.
   Abbreviation expansion (with/without trailing space), possessive stemming,
   punctuation/`&`/hyphen splitting, whitespace collapse. Applied *identically*
   to client names and to block text.

2. **Per-org specificity index** — built from the roster (cached per org):
   for every token and 2–3 word phrase, how many clients contain it →
   - **unique** (`basilica`) — safe to attribute on,
   - **shared-family** (`sacred heart`, `saint patrick`) — never attribute
     alone; route to the tiebreak/AI,
   - **generic** (`church`, `payroll`, `of`, `inc`) — never a client signal.
   Uniqueness alone isn't enough (`contracting llc` is unique in the roster but
   generic in the world), so specificity = **roster-unique × globally-rare**
   (the second signal is a generic-word list / frequency model). Self-maintaining:
   add a client and the index recomputes — no alias edits.

3. **`resolve(text) -> Decision`** — the one entry point:
   - unique signal present → attribute (confidence by contiguity/coverage),
   - 2+ same-family clients tie on shared tokens → **distinguishing-token
     tiebreak** (prefer file name over folders) → else **defer to AI**,
   - generic-only → No Client.
   The collision + tiebreak + normalization logic already on the branch **is**
   this — it just needs to live here and be fed by the index.

4. **Called everywhere** — Stage 3, the Stage 0 internal-work guard, and any
   future site. Detection is fixed once, universally.

## The one honest boundary

A client whose entire name is a **single common word** (`Grace`, `Assumption`)
appearing as *only* that bare word, with no other signal, cannot be safely
auto-attributed — `grace` is also an English word, and auto-billing every
occurrence is worse than a No-Client. The resolver attributes it the instant the
name appears **distinctively** — `Grace Episcopal`, the full name, or a file in
the client's folder (which covers ~every real case). When it genuinely can't
tell, it defers to the AI. That's correct behavior, not a miss.

## Phases (each shadow-tested firm-wide before deploy)

- **Phase 1 — canonical normalization.** Extract the one shared normalize;
  route both matchers through it. Behavior-preserving (the two copies are
  identical); kills future drift like `St.James`. Also already done:
  Stage 0 guard routed through the Stage-3 matcher (`4c4034b`).
- **Phase 2 — specificity index + `resolve()`.** Build the roster index; add
  `ClientNameResolver.resolve()`; migrate Stage 3 and the Stage 0 guard to call
  it. This is what retires per-client aliases for the unique-name cases.
- **Phase 3 — delete dead detection code.** Remove the old per-stage/substring
  detection paths now that everything routes through the resolver.

## Already-landed fixes (the correct logic, awaiting consolidation)

These branch commits are the resolver's behavior, currently living in Stage 3 /
Stage 0. Phases 1–2 move them into the shared component:
- `3605670` file-path collision + distinguishing-token tiebreak
- `152c3fa` title-collision tiebreak + Stage-9 learned-pattern guard
- `a979ac8` `St.` abbreviation expansion without a trailing space
- `4c4034b` Stage-0 internal-work guard uses the real matcher

## Shadow-test strategy

Every phase: run the change over all org-21 blocks, diff old vs new attribution,
and require **zero regressions** (no currently-correct block flips to wrong; new
matches are verified real). Refactors (Phase 1/3) must be behavior-identical.
