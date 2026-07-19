# Idea evaluation criteria — pre-seed / seed

**Status: reference document, not yet wired into code.** See "Wiring notes" at the end.

## Why this exists

The repo scores **founders** thoroughly (`vc_brain/sourcing/github_evaluator.py`, six weighted
dimensions; `vc_brain/memory/founder_score.py`, explicit point formulas) but has no criteria for
judging the **idea**. `prompts/system/screener.txt` names an "IDEA vs MARKET" axis and defines it
in one sentence — and that file is never loaded by `screener.py`, which uses a shorter inline
string. The live prompt asks for `idea_score: 0-100` with no criteria attached and hardcodes
`confidence=0.5`.

This document collects what real pre-seed/seed investors publicly say they look for, so that axis
can be given substance.

## Scope and assumptions

- **Stage:** pre-seed and seed. Usually pre-revenue, often pre-product. There is no traction to
  measure, which is *why* the weights below sit on qualitative dimensions.
- **Whose capital:** a small early check. This matters — Bill Payne's scorecard actively
  *penalises* a company needing >$100M five-year revenue ("will require significant additional
  funding"), while a large fund requires the opposite. Any rubric has to state whose money it
  assumes; this one assumes a small fund writing early checks.
- **Founders are scored elsewhere.** Founder-market fit appears below only as *evidence about the
  idea* (did they live the problem?), not as a founder assessment.

## How to use it

1. **Never blend the dimensions into one number.** This matches the rule already in
   `screener.txt` ("Never average the three axes into a single number"). Hustle Fund is explicit
   that there is no minimum score, and that a company scoring top marks everywhere can still be a
   pass.
2. **Disagreement is signal, not noise.** Elizabeth Yin: *"the best companies are the ones with
   strong theses… potential investors will be very bifurcated in their opinions."* Hustle Fund's
   own partner scores vary widely on the same dimension (Yin averages 2.01 on Product; Shiyan Koh
   averages 3.05 on Market). **A rubric that averages disagreement away will systematically
   filter out the outliers.** Record the spread; do not resolve it.
3. **Every score needs a "because".** Hustle Fund requires a justification note per score. A score
   without cited evidence is an opinion wearing a number.
4. **Method beats magnitude.** Across sources, a *bottom-up* market estimate backed by evidence
   scores higher than a bigger top-down number. Leo Polovets' top anchor is "a plausible bottom-up
   analysis, backed by experiments and data" — not a large TAM.

## Hard gates — check these first

These are cheap disqualifiers. Run them before scoring anything.

| Gate | Rule | Source |
|---|---|---|
| **LUV** | Problem must be **L**arge, **U**rgent, **V**aluable. "One of three and you don't have a business. Two of three and you have a business, perhaps just not venture-scale… Three of three and I'm interested." | Homebrew / Hunter Walk |
| **At least one problem attribute at threshold** | See the six attributes below. At least one must clear its bar; more is better. | Kevin Hale, YC |
| **SISP** | "Solution In Search of a Problem" — if the pitch starts at the solution and reverse-engineers a problem, stop. | Kevin Hale, YC |
| **Tar pit** | "If a problem has existed for a while, usually there is a structural reason previous founders failed to solve it." Has this been tried? Why did it fail? What changed? | Dalton Caldwell, YC |
| **"We have no competition"** | Named red flag. Real answer required for what people do *today instead* (substitutes). | Angel Capital Association / Golden Seeds |
| **Risk count** | "There's market risk, people risk, and then technology risk. I'm generally okay with taking risk on one of those." Two or more live risks is usually a pass. | Andy McLoughlin, Uncork |

### Kevin Hale's six problem attributes (with his stated ideals)

| Attribute | Ideal |
|---|---|
| Popular | 1M+ people have it |
| Growing | 20% / year |
| Urgent | Needed right now |
| Expensive | $B of spend |
| Mandatory | Law changed |
| Frequent | Encountered hourly |

## The dimensions

Weights are adapted from **Hustle Fund's published pre-seed scorecard** — the only source found
that publishes weights summing to 100 specifically for pre-seed (team 25, market 25, insight 10,
traction 10, product 10, moat 5, GTM 5, economics 5, deal 3, risks 2). Team is removed here
(scored elsewhere in this repo) and the remainder re-based, adjusted toward the cross-source
consensus ranking.

| # | Dimension | Weight | Why this weight |
|---|---|---|---|
| 1 | Problem quality | 25% | The most consistent axis across every source, and the only one that survives having no data |
| 2 | Market size & path | 20% | Hustle Fund weights market 25%; $1B bottom-up is the recurring threshold |
| 3 | Why now / timing | 15% | Near-universal in modern fund writing; absent from older angel scorecards |
| 4 | Insight / unfair advantage | 15% | Hale: "You need one." Hustle Fund weights insight 10% |
| 5 | Competition & substitutes | 10% | Payne weights competitive environment 10% |
| 6 | Distribution & business model | 10% | Janz, Naval, Yin all treat this as a gate, not a nicety |
| 7 | Defensibility / moat | 5% | Hustle Fund weights moat 5% — deliberately low this early |

**Product and traction are deliberately near-zero weight.** This is counter-intuitive and
well-evidenced: Payne ranks product below team and market; Berkus assigns a working prototype only
1/5 of value; and Hustle Fund's *funded* companies average their **lowest** score on Product
(2.32) and their highest on Team (2.98). Judge the problem, not the demo.

---

### 1. Problem quality — 25%

Is this a painkiller or a vitamin, and how precisely is it named?

The most scoreable proxy at pre-seed is **problem specificity**, because you cannot measure a
market from a pitch but you *can* measure how precisely the founder has named it. Elizabeth Yin's
ladder:

- **V1** — "Helping online marketers get customers profitably"
- **V3** — "Helping directors of marketing at series B companies who have previously bought ads in
  email lists get customers profitably"

*"At the pre-seed stage, a big way to stand out is if you have a V3 statement (as opposed to a V1
statement)."*

| Score | Anchor |
|---|---|
| 1 | Vitamin. Vague beneficiary. Yin V1. Nobody is currently doing anything about it |
| 2 | Real but mild pain; users tolerate the status quo comfortably |
| 3 | Painkiller for a named segment; people hack together workarounds today |
| 4 | Yin V3 specificity; problem sits in the buyer's **top 3 priorities**; clears ≥1 Hale attribute |
| 5 | Urgent and frequent; users would adopt "a crappy version one made by a two-person startup they've never heard of"; ROI **5–10x** the likely price |

Supporting language: Payne's worksheet scores *"This product is a vitamin pill"* (worst) through
*"a pain killer with no side effects"* (best). Sequoia names "Pain killers" as an element: "Pick
the one thing that is of burning importance to the customer."

### 2. Market size & path — 20%

The recurring threshold is **$1B**, but *how* it's derived carries the score.

- ACA / Golden Seeds: *"Is there at least $1 billion being spent today in this sector? How has the
  company sized the market? Do we agree? **Can we size it ourselves?**"*
- Ulu Ventures: TAM >$1B **computed bottoms-up**.
- Sequoia: "A market on the path to a $1B potential allows for error and time for real margins."

Two important dissents to encode, or the rubric will reject good companies:

- **Small starting markets are fine if there's an exit path.** Paul Graham: *"If Mark Zuckerberg
  had built something that could only ever have appealed to Harvard students, it would not have
  been a good startup idea. Facebook was a good idea because it started with a small market there
  was a fast path out of."* Score the **wedge → expansion path**, not the starting size.
- **Winner-take-all markets can be smaller.** Point Nine notes a few-hundred-million market can
  work where the dynamics concentrate.

| Score | Anchor |
|---|---|
| 1 | Small and not growing; no path out of the niche |
| 2 | Top-down TAM only ("1% of a $50B market") with no bottom-up check |
| 3 | Plausible $1B+ market, sized top-down but sanity-checked |
| 4 | Bottom-up sizing from a named ICP and real price points; credible beachhead |
| 5 | Bottom-up analysis "backed by experiments and data"; explicit wedge with a fast path out |

### 3. Why now / timing — 15%

Sequoia: *"The best companies almost always have a clear why now?"*

NFX's Critical Mass Theory is the only decomposable version found — three preconditions that must
cross **together**:

1. **Enabling technology** — "Being ahead of your time can be the same thing as being wrong."
2. **Economic impetus** — "When something that was expensive becomes cheap it creates an economic
   impetus."
3. **Cultural acceptance** — e.g. "20 years of cultural reprogramming went into the success of
   Instagram."

And the scoring principle: *"What's important isn't whether you're earlier or later than your
competitors on an absolute basis — rather, it's all about who enters the market closest to the
critical mass point."*

| Score | Anchor |
|---|---|
| 1 | No why-now. This was equally buildable five years ago |
| 2 | Generic tailwind cited ("AI is big now") with no mechanism |
| 3 | One precondition clearly crossed |
| 4 | A specific shift in the last **3–36 months** that makes this newly possible; two preconditions |
| 5 | All three preconditions crossing together; explains why prior attempts failed and what changed |

### 4. Insight / unfair advantage — 15%

YC's application asks it best: *"What do you understand about your business that they don't?"*

Kevin Hale frames insight as an **unfair advantage**, of which you need at least one, each with a bar:

| Advantage | Bar |
|---|---|
| Founders | "1 of 10" — one of ten people in the world who can solve this |
| Market | Growing 20% / year |
| Product | 10x better |
| Acquisition | $0 CAC |
| Monopoly | Boolean — you have it or you don't |

Hustle Fund's bar: *"10x different and 10x better than all the other solutions."*
NFX: the biggest ideas are "non-consensus ideas, meaning most people didn't think they looked like
good ideas at the beginning."

| Score | Anchor |
|---|---|
| 1 | No stated insight; consensus view of a consensus market |
| 2 | Insight is a feature preference, not a belief about the world |
| 3 | A real observation, but one competitors likely share |
| 4 | A non-obvious belief the founder earned by living the problem; clears one Hale bar |
| 5 | Non-consensus and specific; explains a structural reason others are wrong |

### 5. Competition & substitutes — 10%

Ask two questions, not one:

- **What do people do today instead?** (YC: "What substitutes do people resort to because it
  doesn't exist yet?") Absence of a named competitor is not absence of a substitute.
- **Why did previous attempts fail?** (the tar-pit test)

Elad Gil's "looks crowded but isn't" is the counterweight — for an apparently crowded market ask:
are the incumbents actually good? do they have structural disadvantages? is there room?

| Score | Anchor |
|---|---|
| 1 | "We have no competition", or a crowded market with no differentiation |
| 2 | Competitors listed; no articulated plan to win |
| 3 | Honest map of direct + indirect competitors and substitutes |
| 4 | Names what incumbents structurally cannot do, and why |
| 5 | Credible "why the incumbent won't just crush this", plus why prior attempts failed |

### 6. Distribution & business model — 10%

Yin treats this as a pass/fail gate regardless of team or market: the business "has to print money
immediately" on a small check.

**Christoph Janz's animal taxonomy** maps price point to a *mandatory* channel — the useful part
is that the two must be consistent. To reach $100M ARR:

| Animal | Customers × ACV | Implied channel |
|---|---|---|
| Whales | 100 × $1M | Deep enterprise, long cycles |
| Elephants | 1,000 × $100k | Field sales, "tens of millions of dollars" to fund the cycle |
| Deer | 10,000 × $10k | Inside sales |
| Rabbits | 100,000 × $1k | Self-serve + marketing |
| Mice | 1,000,000 × $100 | Virality, SEO, UGC |

Governing rule: *"most customer acquisition channels are either scalable or profitable but not
both at the same time."*

| Score | Anchor |
|---|---|
| 1 | No model, or price point and channel are inconsistent (mice pricing, elephant sales motion) |
| 2 | Model stated; acquisition is "we'll do content and ads" |
| 3 | Coherent animal/channel pairing |
| 4 | A proprietary or structurally cheap channel (Naval: "clever viral marketing, or SEO, or partnership… that gives them a leg up") |
| 5 | Evidence the channel works; credible path to CAC well under LTV |

### 7. Defensibility / moat — 5%

Low weight on purpose: at pre-seed there is rarely a moat yet, only a plausible path to one.

NFX's four types — **network effects, brand, scale, embedding** — with network effects strongest.
Their Network Effects Bible ranks 16 types; notably **data network effects rank low**, "weaker
than many people want to believe." The practical test is **multi-homing**: do users single-home
(strong) or trivially run competitors in parallel (weak)? NFX discounts patents as a software moat.

| Score | Anchor |
|---|---|
| 1 | Easily copied; no path to any moat |
| 2 | Moat asserted as "execution speed" or "first mover" |
| 3 | A plausible mechanism identified but not yet started |
| 4 | Named moat type with a concrete accrual mechanism |
| 5 | Mechanism already compounding; users would have to single-home |

Note on first-mover: a16z — *"First to product/market fit is almost always the long-term winner"* —
so score time-to-PMF, not time-to-market.

## If there IS early evidence

Usually absent at pre-seed. When present, these are the published bars:

- **Sean Ellis test** — ≥40% of users "very disappointed" if they lost the product. Directionally
  valid from ~40 respondents; survey only users who used it at least twice in the last two weeks.
- **Retention over growth** — Michael Seibel's SocialCam counterexample: huge downloads with
  "horrible retention" is *not* product-market fit.
- **The absence signals** (Andreessen): "word of mouth isn't spreading, usage isn't growing that
  fast, press reviews are kind of 'blah', the sales cycle takes too long."
- **Point Nine, AI-first SaaS seed:** a few paid pilots is enough — *"No, MRR is not a
  requirement!"*

## Known failure modes to score against

From Bessemer's published anti-portfolio, read as a list of ways this rubric could be wrong:

| Miss | Failure mode |
|---|---|
| eBay — "Stamps? Coins? Comic books? You've GOT to be kidding" | Dismissing the market by dismissing the use case |
| Zoom — "crowded with entrenched incumbents" | Assuming a crowded market is closed |
| Facebook — "haven't you heard of Friendster?" | Pattern-matching to a failed predecessor |
| PayPal — "rookie team, regulatory nightmare" | Penalising the schlep |
| Instacart, Tesla | Over-weighting current unit economics |

That last one is Paul Graham's **schlep blindness** seen from the investor's side: *"if you pick an
ambitious idea, you'll have less competition, because everyone else will have been frightened off
by the challenges involved."* Consider treating unpleasant-but-necessary work as a mild **positive**.

## Sources and verification status

**Verified — fetched from the primary source:**

- Paul Graham, *How to Get Startup Ideas* — https://paulgraham.com/startupideas.html
- Paul Graham, *Schlep Blindness* — https://paulgraham.com/schlep.html
- Sequoia, *Writing a Business Plan* — https://www.sequoiacap.com/article/writing-a-business-plan/
- Sequoia, *Elements of Enduring Companies* — https://articles.sequoiacap.com/elements-of-enduring-companies
- Marc Andreessen, *The Only Thing That Matters* — https://pmarchive.com/guide_to_startups_part4.html
- a16z, *12 Things About Product-Market Fit* — https://a16z.com/12-things-about-product-market-fit/
- NFX, *Why Startup Timing Is Everything* — https://www.nfx.com/post/why-startup-timing-is-everything
- NFX, *The Four Types of Defensibility* — https://www.nfx.com/post/the-four-types-of-defensibility
- NFX, *Network Effects Bible* — https://www.nfx.com/post/network-effects-bible
- First Round, *12 Frameworks for Finding Startup Ideas* — https://review.firstround.com/12-frameworks-for-finding-startup-ideas-advice-for-future-founders/
- First Round, *How to Measure Product-Market Fit* — https://review.firstround.com/how-to-measure-product-market-fit/
- Bill Payne Scorecard Method — https://seedspot.org/wp-content/uploads/2021/02/Scorecard-Valuation-Methodology.pdf
- Berkus Method — https://berkus.com/the-berkus-method-valuing-an-early-stage-investment-2/
- Hustle Fund scorecard — https://www.hustlefund.vc/post/angel-squad-what-makes-a-startup-fundable-a-reusable-vc-style-scorecard
- Elizabeth Yin, *How I Invest as a Pre-Seed Investor* — https://elizabethyin.com/2018/02/12/how-i-invest-as-a-pre-seed-investor/
- Elizabeth Yin, *Data on How We Invest* — https://elizabethyin.com/2024/08/19/data-on-how-we-invest-at-hustle-fund/
- Christoph Janz, *Five Ways to Build a $100M Business* — http://christophjanz.blogspot.com/2014/10/five-ways-to-build-100-million-business.html
- Naval Ravikant, investment criteria — https://venturehacks.com/investment-criteria
- Leo Polovets, *How to De-Risk a Startup* — https://www.codingvc.com/p/how-to-de-risk-a-startup
- Ulu Ventures seed rubric — https://medium.com/ulu-ventures/a-rubric-for-evaluating-seed-stage-enterprise-startups-a1bf6faf460
- Homebrew / Hunter Walk on problem size — https://hunterwalk.com/2017/04/12/why-i-care-about-problem-size-more-than-market-size/
- Angel Capital Association Due Diligence Playbook — https://www.angelcapitalassociation.org/data/Documents/Members%20Only/BestPractices/E3e%20-%20Due%20Diligence%20Checklists%20and%20Reports/Due_Diligence_Playbook_Generic_with_Appendices.pdf
- Point Nine, AI-First SaaS Funding Napkin — https://medium.com/point-nine-news/the-ai-first-saas-funding-napkin-2cb138070ffc
- Uncork Capital — https://uncorkcapital.com/approach
- Bessemer Anti-Portfolio — https://www.bvp.com/anti-portfolio

**Use with caution — not from the primary source:**

- **Kevin Hale's problem attributes and unfair-advantage bars** came from a third-party PDF mirror
  of the YC lecture, not a YC-hosted page. Content is consistent with YC's published lecture, but
  verify before quoting externally. *(These are load-bearing in this document — they supply most of
  the numeric thresholds.)*
- **YC application Idea questions** came from an aggregator (shizune.co); the live set sits behind
  auth and YC revises it between batches.
- **Jason Calacanis** — from a reader's cheatsheet of *Angel*, not the book text. Not quoted above.
- **Dalton Caldwell's tar-pit framing** — from Lenny's Newsletter's write-up, not a YC primary page.
- **Michael Seibel's PMF quotes** — widely and consistently attributed, but the primary text was
  not read directly.
- **Point Nine's classic (non-AI) napkin numbers** — from a secondary aggregator. The AI-first
  figures cited above *are* from Point Nine directly.
- **Charles Hudson / Precursor** — no primary source retrieved. The widely repeated "founder 70% /
  idea 30%" split appears only in third-party profiles; **deliberately not used here.**
- **NFX timing essay authorship** is ambiguous across sources (James Currier vs Pete Flint) — the
  essay is cited, the author is not.

**Deliberately excluded:** TAM thresholds like "$500M floor" or "$10B+ or growing 50%+" that
surfaced only in SEO content farms; Village Global (their published criteria are explicitly
founder-only, backing founders "irrespective of the founders' specific idea").

## Wiring notes — what would have to change in code

This document is inert until something reads it. Three defects block that today:

1. **`screener.py` doesn't load `screener.txt`.** It uses an inline `SYSTEM` constant, so the
   written rubric never reaches the model. Load the prompt file (the pattern already exists in
   `vc_brain/sourcing/reputation/analyzer.py::_load_system_prompt`).
2. **`thesis_engine.py` declares `preferred_signals` / `anti_signals` but nothing reads them.**
   The hard gates above are exactly what those fields are for.
3. **`pdf_parser/` market research never reaches the screener.** It gathers TAM, competitors,
   regulatory and trend data, is explicitly forbidden from judging, and is not imported anywhere in
   `vc_brain/`. Dimensions 2 and 5 above need that data — the "separate downstream component" its
   prompt refers to is this rubric.

Also note `screener.py` hardcodes `confidence=0.5` regardless of evidence, and its pass thresholds
(founder ≥25, market ≥25, idea ≥20) carry no stated basis.
