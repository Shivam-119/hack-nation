# Fund intake form — what the VC fills in before sourcing starts

**Status: specification. Not yet built.** See "Wiring notes" at the end for what blocks it.

## Purpose

The brief makes a configurable thesis one of the three scored MVP pillars:

> **Thesis Engine:** Investor sets sectors, stage, geography, check size, ownership targets, and
> risk appetite. Every recommendation is filtered and scored through this fund-specific lens.

and, in FAQ 15:

> Should the Thesis Engine be hardcoded to one fund, or configurable? **Configurable.** …A
> hardcoded thesis misses the point of the pillar.

This form is that lens. It is filled in **once, before any candidate is sourced or screened**, and
every downstream recommendation is filtered through it.

There is no such form today. The dashboard's only form is the *candidate* application, and nothing
in the frontend ever calls `PUT /api/thesis`.

## Design constraints

- **Short.** The brief warns *"over-collecting works against you"*, and scores UX at 15% against a
  *"Notion-level approachability"* bar. Six fields, all defaulted, under a minute to complete.
- **Vocabulary-constrained where the code demands it.** Two fields silently match nothing if the
  form lets the investor type freely — see Traps.
- **Honest about what works.** Half these fields currently change nothing. The form should not
  imply otherwise; the status table below is part of the spec.

## The form

| # | Field | Control | Vocabulary / constraint |
|---|---|---|---|
| 1 | Fund name | text | identity label for the saved config |
| 2 | Sectors | multi-tag, **broad tags only** | presets + free text — see Trap 1 |
| 3 | Stage | multi-select | **exactly** `pre-seed` \| `seed` — see Trap 2 |
| 4 | Geographies | multi-tag | free text: city, country or region |
| 5 | Risk appetite | single-select | `conservative` \| `moderate` \| `aggressive` |
| 6 | Desires | repeatable free text | what the fund wants *and* wants to avoid, in plain language |

### 1. Fund name

Plain label. Purely for identifying the saved configuration.

### 2. Sectors

**Helper text: "Use broad tags. `AI` will match `AI Infrastructure`, but `AI Infrastructure` will
not match `AI`."**

Suggested presets, deliberately one or two words each:

`AI` · `fintech` · `SaaS` · `devtools` · `health` · `bio` · `climate` · `energy` ·
`marketplace` · `consumer` · `security` · `robotics` · `space` · `crypto`

Free text is allowed, but the control should warn on entries longer than ~2 words. This is not
cosmetic — see Trap 1.

### 3. Stage

Checkboxes, both on by default:

- `pre-seed`
- `seed`

These exact strings, lowercase. The candidate-side application form offers the same two and
nothing later: the fund writes $100K cheques and does not invest beyond seed, so listing
`series-a` would only invite applications it can never fund.

### 4. Geographies

Free-text tags: `Germany`, `DACH`, `Europe`, `Berlin`, `Remote`. Matching is substring-based in the
same direction as sectors, so broader is safer (`Germany` matches `Berlin, Germany`; `Berlin,
Germany` does not match `Germany`).

### 5. Risk appetite

One of `conservative` / `moderate` / `aggressive`, default `moderate`.

Its intended job is to modulate how harshly a thin or unproven opportunity is treated. Note it has
no reader today (see status table).

### 6. Desires

A repeating list of short plain-language statements — **both what the fund wants and what it will
not touch, in one list**. Negation is expressed inline.

Examples:

```
technical co-founder
top-tier accelerator (YC, Techstars, EF)
sells to developers or engineering teams
no agencies or consultancies
not consumer social
avoid anything needing a regulatory licence to start
```

This replaces the separate "preferred signals" and "anti-signals" fields on `FundThesis`. Merging
them is safe **only because the consumer is a language model** — see Trap 3, which is a hard
constraint on how this field may ever be wired.

## Worked example

Illustrative only — not a statement of any real fund's mandate.

| Field | Value |
|---|---|
| Fund name | Maschmeyer Group — VC Brain |
| Sectors | `AI`, `fintech`, `SaaS`, `health` |
| Stage | `pre-seed`, `seed` |
| Geographies | `Germany`, `DACH`, `Europe` |
| Risk appetite | `aggressive` |
| Desires | technical co-founder · shipped something publicly · top-tier accelerator · no agencies · not consumer social |

Check size is not asked: it is fixed at **$100K**, the premise of the challenge itself
("Deploying $100K Checks in 24 Hours").

## Three traps the form must design around

### Trap 1 — sector matching runs candidate-inward

`ThesisEngine.fits_thesis` does:

```python
if sector and not any(s.lower() in sector.lower() for s in self.thesis.sectors):
```

The thesis entry must be a **substring of the candidate's** sector string. So:

| Thesis says | Candidate says | Match? |
|---|---|---|
| `AI` | `AI Infrastructure` | ✅ |
| `AI Infrastructure` | `AI` | ❌ |
| `AI Infrastructure for Enterprises` | `AI Infrastructure` | ❌ |

A well-meaning investor typing a precise thesis gets **fewer** matches, not more — the opposite of
what they expect. Hence broad-tag presets and a length warning.

### Trap 2 — stage matching is exact equality

```python
if stage and stage.lower() not in [s.lower() for s in self.thesis.stages]:
```

No substring logic. `pre seed`, `Pre-Seed ` (trailing space) or `preseed` all fail. The control
must be fixed-choice emitting exactly `pre-seed` / `seed`.

### Trap 3 — free-text negation only works because an LLM reads it

Merging preferred and anti-signals into one Desires list is safe **today** because the realistic
consumer is the screening prompt, where a model reads *"no agencies"* correctly.

It becomes actively wrong under literal string matching: an implementation doing
`if desire in candidate_description` would see *"no agencies"* match a candidate that mentions
**agencies** — and conclude the fund *wants* it. The intent inverts.

> **Constraint on any future wiring: Desires must be interpreted by a model, never `in`-matched.**
> If someone needs cheap literal filtering later, that requires a separate, explicitly-polarised
> field — not this one.

### Also worth knowing

- Empty candidate values behave inconsistently: `fits_thesis` auto-**passes** an empty sector
  (guarded by `if sector and ...`) while `score_alignment` auto-**fails** it (no guard).
- `score_alignment` has **zero callers** anywhere in the repo. It is dead code today.

## Field → consumer status

Honest accounting of what filling this form in actually changes right now.

| Field | Status | Consumer |
|---|---|---|
| Sectors | **live** | `fits_thesis`; and reaches the screening LLM via `thesis_context` |
| Stage | **live** | same |
| Geographies | **partly live** | read by `fits_thesis`, but **absent from `thesis_context`** — never reaches the screening LLM |
| Risk appetite | **stored, never read** | appears only on its two declaration lines (`thesis_engine.py:16`, `app.py:63`) |
| Desires | **no home yet** | would map onto `preferred_signals`; that field and `anti_signals` are read by nothing |
| Fund name | display only | echoed by `GET /api/thesis` |

**Two and a half of six fields currently do anything.** That is a statement about the wiring, not
about the form design — the fields are the ones the brief asks for.

## Divergences from the brief's list

The brief names *"sectors, stage, geography, check size, ownership targets, and risk appetite"*.
This form keeps four of the six and drops two, deliberately:

| Dropped | Why |
|---|---|
| **Check size** | Fixed at $100K — the challenge premise, not a variable. Documented as a constant instead of asked. There is also nothing to compare it against: `ApplicationRequest` carries no raise-amount field. |
| **Ownership target** | Dropped alongside check size as deal economics this fund does not vary. ⚠️ The brief names it explicitly, so this is a conscious divergence — trivially restored if wanted. |

Also removed, though not from the brief's list: **min founder score**. The Founder axis is scored
on its own merits rather than pre-gated by a number the investor guesses before seeing anyone.

## What this form deliberately does not ask

Each omission is a decision, not an oversight.

| Not asked | Why |
|---|---|
| Outbound sourcing config (languages, locations, min stars/repos, activity window, channels) | Out of scope this round. Note `InvestorCriteria` already declares `min_stars`, `min_repos`, `active_within_days`, `must_be_builder`, but `GitHubSearchRequest` does not expose them — so the API cannot set them regardless |
| Idea-rubric weights | Defaults already specified in [`idea-evaluation-criteria.md`](./idea-evaluation-criteria.md) |
| Fund size, reserves, follow-on policy | No model in the codebase represents portfolio construction |
| Diligence / memo preferences | `diligence.py` and `memo_generator.py` contain zero thesis references — nothing to configure |
| Founder-score dimension weights | Hardcoded in `founder_score.py`; no config surface exists |

## Wiring notes

Three pre-existing defects stand between this spec and a working form.

1. **`PUT /api/thesis` has never succeeded.** `ThesisUpdate` declares 8 fields; `FundThesis`
   requires 11. `min_founder_score`, `preferred_signals` and `anti_signals` have no defaults, so
   `FundThesis(**update.model_dump())` (`app.py:84`) raises `ValidationError` on **every** call —
   which means `thesis_engine` is always `None`.
   Because this form drops `min_founder_score` and merges the signal lists, the minimal fix is
   **giving those three fields defaults on `FundThesis`**, not adding them to the request model.

2. **`POST /api/applications/{id}/screen` crashes without a thesis.** `app.py:158` reads
   `thesis.sectors` unguarded while `thesis` is typed `FundThesis | None`, so screening raises
   `AttributeError` when none is configured. This form is a **prerequisite for screening**, not a
   convenience.

3. **The thesis does not persist.** It lives in a module-level global (`app.py:26`) and dies with
   the process. `MemoryStore` has no thesis table and `memory/models.py` has no thesis model. A
   form described as "filled in before the process starts" implies durability that does not exist
   yet.

### Cheapest way to make the form matter

`thesis_context` is a **free-text string** piped straight into the screening prompt, and today it
carries only two fields:

```python
thesis_context=f"Sectors: {thesis.sectors}, Stages: {thesis.stages}",
```

It is interpolated as `f"Fund thesis context: {thesis_context}"` in `screener.py:136` — with no
schema and no parsing. Widening that one f-string to include geographies, risk appetite and
Desires turns **three dead fields live with no schema work**, and is the correct home for Desires
given Trap 3. (Worth also formatting the lists properly: the model currently receives Python
`repr`, i.e. `Sectors: ['ai', 'fintech']`.)

## See also

- [`idea-evaluation-criteria.md`](./idea-evaluation-criteria.md) — the pre-seed/seed rubric for
  judging the idea itself. Its hard gates are the kind of thing Desires expresses, subject to
  Trap 3.
