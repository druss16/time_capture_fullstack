# Alias Suggestions — spec

**Status:** proposed · **Date:** 2026-07-01

## Problem

New firms hit a burst of "the client name is right there but it landed wrong /
No-Client" during their first ~30–60 days, because the org's client list has
short names, abbreviations, and QB-file names the matcher hasn't seen yet
(e.g. QB says "Franciscan Church of the Assumption", client is "Assumption
Church"). After onboarding this tapers off — it's a long tail of one-off
aliases/rules, not a steady stream.

We proved (2026-07-01) that a fully-automatic resolver **can't** safely close
this — it false-matches place-names and news ("Baldwinsville" → Atlantic
Seafood, "Syracuse Weather" → Syracuse Fitness). The safe pattern is
**human-in-the-loop**: the machine *suggests* an alias, a human *approves* it.

## Key insight: the signal already exists — corrections

When a reviewer moves a block to the right client ("Assign client → X"), they've
already given the answer. We don't need a new "flag" button or any new behavior
from the team — we mine the corrections they already make. A human made the call
(the correction) and a human confirms the generalization (the alias), so it's
safe by construction — no false-match risk.

## How it works

1. **Capture (already happens).** A reviewer corrects a block to client X. We
   already write `ClassificationAudit` with `corrected_by_user=True`,
   `client_before`, `client_after`.

2. **Extract a candidate alias (nightly job / on-demand).** For each recent
   correction to X where the block did NOT already match X deterministically:
   - normalize the block's title/file (`_normalize_name`),
   - find the distinctive phrase that identifies X but isn't yet a name/alias of
     X — reuse the resolver's phrase logic: a contiguous multi-word phrase, or a
     rarity-gated (`wordfreq zipf < 3.7`) single token, that is **unique to X**
     across the roster,
   - skip if it's generic, a place-name-only token, or already an alias.
   - Aggregate identical suggestions and count occurrences.

3. **Admin inbox.** A small admin surface: a list of suggestions like
   > `"franciscan church of the assumption" → Assumption Church (169) · seen 6× · [Add alias] [Dismiss]`
   One click adds it to `Client.aliases`; dismiss suppresses it (don't resurface).

4. **Effect.** Once added, the alias flows through the existing matcher — every
   future block with that phrase attributes to X deterministically. No code
   change per alias; it's data.

## Why not other designs

- **Auto-add aliases from corrections** — unsafe: a single correction can be a
  one-off; auto-generalizing risks bad aliases. Human approval is the guard.
- **A "flag / suggest alias" button in the UI** — more to teach and one more
  click; corrections are free and a *stronger* signal. Offer it later as an
  optional "always call this ___" toggle that just bumps the suggestion's
  priority.
- **Learn patterns automatically (Stage 9 style)** — that's the poisoning risk
  we're gating; this is the human-approved alternative.

## Data model

Reuse existing tables; add one:

```
AliasSuggestion
  org (FK)
  client (FK)                 # suggested home
  phrase (str)                # normalized candidate alias
  occurrence_count (int)      # how many corrections produced it
  example_block_ids (json)    # for the admin to eyeball
  status (enum: pending | added | dismissed)
  created_at, updated_at
  unique (org, client, phrase)
```

## Build outline

- **Job** `build_alias_suggestions(org, since)` — iterates recent corrected
  audits, extracts unique/rarity-gated phrases, upserts `AliasSuggestion`
  (increment count).
- **API** `GET /alias-suggestions/` (pending, by count desc);
  `POST /alias-suggestions/<id>/add` (append to `client.aliases`, mark added);
  `POST /alias-suggestions/<id>/dismiss`.
- **UI** small admin card/inbox (Settings or Daily Review admin), count badge.
- Schedule the job nightly; also run on-demand from the inbox ("refresh").

## Decay / lifecycle

Suggestions are naturally front-loaded (weeks 1–4) and taper as the roster's
names get covered — matching the observed 30–60 day pattern. No ongoing
maintenance once the tail is covered.

## Safety

- Only ever *suggests*; never writes a client attribution.
- Every alias is human-approved.
- Dismissed suggestions never resurface (respect the human "no").
- Extraction reuses the same normalize + uniqueness + rarity gates as the
  resolver, so suggested aliases are distinctive by construction.
```
