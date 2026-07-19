# Fund intake form — what the VC fills in before sourcing starts

**Status: specification. Not yet built.**

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
- **Vocabulary-constrained where the code demands it.** Sectors and Stage silently match nothing if
  the form lets the investor type freely — each field below states its rule.

## The form

| # | Field | Control | Vocabulary / constraint |
|---|---|---|---|
| 1 | Fund name | text | identity label for the saved config |
| 2 | Sectors | multi-tag, **broad tags only** | presets + free text, one or two words each |
| 3 | Stage | multi-select | **exactly** `pre-seed` \| `seed` |
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
cosmetic: matching runs candidate-inward, so a *more precise* thesis matches **fewer** candidates.

### 3. Stage

Checkboxes, both on by default:

- `pre-seed`
- `seed`

These exact strings, lowercase — matching is exact equality, so `pre seed` or `preseed` fail. The
candidate-side form still offers `series-a`; that is correct and unchanged — a candidate may
simply be out of mandate.

### 4. Geographies

Free-text tags: `Germany`, `DACH`, `Europe`, `Berlin`, `Remote`. Matching is substring-based in the
same direction as sectors, so broader is safer (`Germany` matches `Berlin, Germany`; `Berlin,
Germany` does not match `Germany`).

### 5. Risk appetite

One of `conservative` / `moderate` / `aggressive`, default `moderate`.

Its intended job is to modulate how harshly a thin or unproven opportunity is treated.

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
them into one list is safe **only because the consumer is a language model**, which reads the
negation correctly.

> **Constraint on any future wiring: Desires must be interpreted by a model, never `in`-matched.**
> A literal substring match would see *"no agencies"* match a candidate that mentions **agencies**
> and conclude the fund wants it — inverting the intent. Cheap literal filtering, if ever needed,
> requires a separate explicitly-polarised field, not this one.

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
