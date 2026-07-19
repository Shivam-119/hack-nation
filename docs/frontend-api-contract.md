# Frontend API contract

The four screens under `frontend/templates/` run on mocked data served from
`/api/mock/*`. This document is the handover: what the real endpoints must return for the UI to
keep working when the mock is removed.

**How to use it.** Implement a route at the real `/api/*` path with the shape below, then delete
that route's entry from `MOCKED` in `frontend/static/api.js`. No page code changes — the client
switches path automatically. Setting `USE_MOCK = false` forces every call to the real routes.

| Screen | Route |
|---|---|
| Investor criteria | `/investor` |
| Candidate application | `/apply` |
| VC inbox | `/inbox` |
| Application detail | `/inbox/{id}` |

Reference implementation of every shape: `vc_brain/api/mock_routes.py`.
Documented types: `frontend/static/api.js`.

## Four additions the backend does not have today

### 1. `AxisScore` needs strengths and weaknesses

Today (`vc_brain/intelligence/screener.py`):

```python
class AxisScore(BaseModel):
    score: float = 0.0
    sentiment: str = "neutral"
    trend: Trend = Trend.STABLE
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.5
```

`evidence` is a flat list of strings with no positive/negative split, so the detail screen has
nothing to render under "Strengths" and "Weaknesses". Add two fields:

```python
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
```

**Keep `evidence`.** The brief requires every claim to trace to a source; strengths and weaknesses
are the readable summary, evidence is the citation. Replacing one with the other loses traceability.

### 2. Applications must accept a deck upload

No endpoint anywhere accepts a file. `python-multipart` is installed but unused, and
`ingest_application` only reads a server-local `deck_path`, so `deck_text` is always `""` for
anything created over HTTP — meaning the screener's "Deck excerpt" and diligence's "Deck content"
are always empty in the current API.

The brief makes *"deck + company name"* the minimum application bar, so this is required.
`POST /api/applications` should accept `multipart/form-data`:

| Field | Required | Notes |
|---|---|---|
| `company_name` | yes | |
| `deck` | yes | `UploadFile`, `.pdf` / `.pptx` |
| `one_liner`, `sector`, `stage`, `geography`, `website`, `product_url`, `raising`, `why_now`, `accelerator`, `prior_companies` | no | |
| `founders` | no | JSON string: `[{name, email, github, twitter, linkedin}]` |

Returns `{application_id, status, applicability}`.

The founder handles are the point of the extra fields — each one feeds a scanner that already
exists (`github_evaluator`, `sourcing/socials`, `sourcing/reputation`).

### 3. The inbox listing needs a company name

`GET /api/applications` returns `{id, company_id, status, source, submitted_at}`. With no company
name the inbox can only show hex ids, and there is no `GET /api/companies` to join against. Add
`company_name`, plus `sector`, `stage`, `geography`, `applicability` and `screening` (nullable).

Also needed: **`GET /api/applications/{id}`**, which does not exist. Only the list route and the
POST action routes are available today, so the detail screen has nothing to call.

### 4. Applicability — a fit score plus a viability flag

Nothing models this. Deliberately **two independent judgements**: `fit_score` answers *how well
does this match what the fund said it wants*, `sanity` answers *is this a venture-scale company at
all*. Keeping both is what stops an ice cream truck and an excellent off-sector fintech from
looking identical at the bottom of the list.

```jsonc
"applicability": {
  "fit_score": 25,                    // 0-100
  "sanity": { "passed": true, "note": "Real company, live app, credible team." },
  "breakdown": [
    { "label": "Sector",    "weight": 40, "awarded": 0,  "note": "'consumer marketplace' matches no thesis tag" },
    { "label": "Stage",     "weight": 25, "awarded": 25, "note": "seed is in mandate" },
    { "label": "Geography", "weight": 20, "awarded": 0,  "note": "Paris is outside the Germany/DACH focus" },
    { "label": "Desires",   "weight": 15, "awarded": 0,  "note": "Adjacent to the stated 'not consumer social'" }
  ]
}
```

**`breakdown` must sum to `fit_score`.** The UI renders it as a segmented bar plus a per-criterion
table, so the number is explainable rather than oracular — the same reason axis scores carry
evidence. Weights are the mock's choice (sector 40 · stage 25 · geography 20 · desires 15); the
real scorer should earn them rather than inherit them.

A failed viability check **zeroes everything** and is displayed as a state, not a number: "6% fit"
invites comparison with a 25% that is merely off-sector, when the two mean completely different
things. `fit_score` is computable from `ThesisEngine.fits_thesis`; the viability check is a
judgement call that belongs in an LLM step, and the mock uses a keyword list only to show the shape.

### 5. A deck endpoint

`GET /api/applications/{id}/deck` returns the uploaded file as `application/pdf`. The mock keeps
uploaded bytes in memory and serves them back verbatim; fixture applications have no bytes, so it
generates a placeholder naming the company rather than serving a dead link.

## A real bug this exercise surfaced

**`ThesisEngine.fits_thesis` matches sectors by naked substring, which produces false positives.**

```python
if sector and not any(s.lower() in sector.lower() for s in self.thesis.sectors):
```

With a thesis sector of `"AI"`, this matches any candidate whose sector merely *contains* those two
letters:

| Thesis tag | Candidate sector | Matches? | Correct? |
|---|---|---|---|
| `AI` | `AI Infrastructure` | yes | yes |
| `AI` | `ice cream ret**ai**l` | **yes** | **no** |
| `AI` | `em**ai**l marketing` | **yes** | **no** |
| `AI` | `supply ch**ai**n` | **yes** | **no** |

This was found by accident: the ice-cream-truck fixture passed the sector check. It matters more
than it looks, because `docs/fund-intake-form.md` correctly tells investors to use *short broad
tags* — and the shorter the tag, the more spurious matches it produces. The two pieces of guidance
work against each other until the matching is fixed.

Suggested fix: match on word boundaries rather than raw substring, e.g. compare normalised token
sets, or `re.search(rf"\b{re.escape(tag)}\b", sector, re.I)`.

`vc_brain/api/mock_routes.py` reproduces the current behaviour faithfully, false positives
included, so the mock does not paper over it.

## Diligence

The diligence step is **removed from the UI** — the pipeline label, the button and its handler are
gone from the dashboard. What replaced it is the fit score above: a cheap, explainable check in
front of screening rather than a separate stage after it.

`vc_brain/intelligence/diligence.py` and `POST /api/applications/{id}/diligence` are **left
intact**. Deleting a module that `app.py` still imports is outside a frontend change, and the
claim-verification model behind it is worth keeping even if this UI no longer calls it.

## Three pre-existing bugs the real routes must resolve

These are not caused by the scaffold and are not fixed by it.

1. **`PUT /api/thesis` has never succeeded.** `ThesisUpdate` declares 8 fields; `FundThesis`
   requires 11, and `min_founder_score` / `preferred_signals` / `anti_signals` have no defaults, so
   `FundThesis(**update.model_dump())` raises `ValidationError` on every call. Consequence:
   `thesis` is always `None`.
2. **`POST /api/applications/{id}/screen` crashes when no thesis is set** — `app.py` dereferences
   `thesis.sectors` unguarded, so it raises `AttributeError` rather than returning the usual
   `{"error": ...}`.
3. **`POST /api/applications/{id}/memo` fails after diligence has run** — it does
   `DiligenceReport(company_id=company.id, **application.diligence_result)`, and the stored dict
   already contains `company_id`, so it raises `TypeError: got multiple values for keyword
   argument`. It "succeeds" only when diligence has *not* run.

## Conventions the mock follows

Matched to the existing API so the swap is invisible:

- **Errors are HTTP 200 with `{"error": "..."}`**, not 4xx. `api.js` keys on the presence of
  `error`, not the status code. If backend moves to real status codes, update `request()` in
  `api.js` — one function.
- **List endpoints return bare arrays**, no envelope, no pagination.
- Timestamps are naive UTC ISO strings (`datetime.utcnow().isoformat()`), no `Z` suffix.
- Ids are 12-character hex.

## What the mock deliberately does not do

- Persist anything. State is per-process and resets on reload.
- Run screening. Submitted applications get `"screening": null`, which the UI renders as
  "Not screened" rather than inventing zeros.
- Judge sanity properly — the keyword list exists to demonstrate the shape, nothing more.
