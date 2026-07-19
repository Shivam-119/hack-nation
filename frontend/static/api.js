/* VC Brain — API client and contract.
 *
 * The backend for these screens does not exist yet. Every call below is served
 * by mock fixtures at /api/mock/* so the UI can be built and reviewed now.
 *
 * THIS FILE IS THE SPEC. Each function documents the request and response
 * shape the real endpoint must produce. When backend implements a route at the
 * real path, delete it from MOCKED below — no page code changes.
 */

/** Flip to false to hit the real /api/* routes instead of the fixtures. */
const USE_MOCK = true;

/** Routes still mocked. Shrink this list as backend lands each one. */
const MOCKED = new Set([
    'GET /api/thesis',
    'PUT /api/thesis',
    'GET /api/applications',
    'GET /api/applications/{id}',
    'POST /api/applications',
]);

function path(method, route, actual) {
    const mocked = USE_MOCK && MOCKED.has(`${method} ${route}`);
    return mocked ? `/api/mock${actual.replace(/^\/api/, '')}` : actual;
}

async function request(method, route, actual, body) {
    const url = path(method, route, actual);
    const opts = { method, headers: {} };

    if (body instanceof FormData) {
        opts.body = body;                       // browser sets the boundary
    } else if (body !== undefined) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
    }

    const res = await fetch(url, opts);
    const data = await res.json().catch(() => ({ error: `${res.status} ${res.statusText}` }));

    // Note: this API answers "not found" with HTTP 200 + {error}, so the
    // presence of `error` is what matters, not the status code.
    if (data && data.error) throw new Error(data.error);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return data;
}

/* ------------------------------------------------------------------ thesis */

/**
 * The fund's criteria — filled in before any candidate is sourced.
 * @returns {Promise<{
 *   name: string,
 *   sectors: string[],      // broad tags: "AI", not "AI Infrastructure"
 *   stages: string[],       // exactly "pre-seed" | "seed"
 *   geographies: string[],
 *   risk_appetite: string,  // "conservative" | "moderate" | "aggressive"
 *   desires: string[]       // wants AND won't-touches, plain language
 * }>}
 */
export const getThesis = () => request('GET', '/api/thesis', '/api/thesis');

/** Same shape in, same shape back. */
export const saveThesis = (thesis) => request('PUT', '/api/thesis', '/api/thesis', thesis);

/* ------------------------------------------------------ applications: read */

/**
 * Inbox listing.
 *
 * NOTE FOR BACKEND — today's GET /api/applications returns
 * {id, company_id, status, source, submitted_at} with no company name and no
 * applicability. Both additions below are required for this screen.
 *
 * @returns {Promise<Array<{
 *   id: string,
 *   company_name: string,          // ADDITION — listing currently has only company_id
 *   company_id: string,
 *   sector: string,
 *   stage: string,
 *   geography: string,
 *   status: string,                // received | screening | diligence | decision | funded | passed
 *   source: string,                // inbound | outbound-github | ...
 *   submitted_at: string,          // ISO 8601
 *   applicability: Applicability,  // ADDITION — see below
 *   screening: ScreeningResult|null
 * }>>}
 */
export const listApplications = () =>
    request('GET', '/api/applications', '/api/applications');

/**
 * One application, in full.
 *
 * NOTE FOR BACKEND — no GET /api/applications/{id} exists today; only the
 * list route and the POST action routes.
 *
 * @returns {Promise<Object>} listing row + {answers, deck, founders}
 */
export const getApplication = (id) =>
    request('GET', '/api/applications/{id}', `/api/applications/${id}`);

/* ----------------------------------------------------- applications: write */

/**
 * Submit an application.
 *
 * NOTE FOR BACKEND — must accept multipart/form-data. No endpoint accepts a
 * file today (python-multipart is installed but unused), so deck_text is
 * always empty for anything created over HTTP. The brief makes "deck +
 * company name" the minimum bar, so this is required, not optional.
 *
 * Fields: company_name (required), deck (required, File), website, one_liner,
 * sector, stage, geography, why_now, accelerator, prior_companies,
 * product_url, raising, founders (JSON string — array of
 * {name, email, github, twitter, linkedin}).
 *
 * @returns {Promise<{application_id: string, status: string, applicability: Applicability}>}
 */
export const submitApplication = (formData) =>
    request('POST', '/api/applications', '/api/applications', formData);

/* --------------------------------------------------------------- typedefs */

/**
 * Is this worth the partner's attention?
 *
 * NOTE FOR BACKEND — nothing models this today. Deliberately TWO independent
 * judgements: a company can match the thesis perfectly and still be nonsense,
 * and the partner needs to see which check failed.
 *
 * @typedef {Object} Applicability
 * @property {boolean} applicable
 * @property {'in_scope'|'out_of_scope'|'not_viable'} verdict
 * @property {string[]} reasons
 * @property {boolean|null} thesis_fit                    // sector/stage/geography match
 * @property {{passed: boolean, note: string}} sanity     // "is this a real company at all"
 */

/**
 * One screening axis.
 *
 * NOTE FOR BACKEND — AxisScore today is
 * {score, sentiment, trend, evidence: string[], confidence}. `strengths` and
 * `weaknesses` are additions. `evidence` stays: the brief requires every claim
 * to trace to a source, so citations must not be replaced by prose.
 *
 * @typedef {Object} AxisScore
 * @property {number} score           // 0-100
 * @property {string} sentiment       // bullish | neutral | bear
 * @property {string} trend           // improving | stable | declining
 * @property {number} confidence      // 0-1
 * @property {string[]} strengths     // ADDITION
 * @property {string[]} weaknesses    // ADDITION
 * @property {string[]} evidence      // citations, kept for traceability
 */

/**
 * The three axes are independent and MUST NOT be averaged — the brief is
 * explicit, and collapsing them hides the disagreement a partner most needs
 * to see. There is deliberately no overall score in this shape.
 *
 * @typedef {Object} ScreeningResult
 * @property {AxisScore} founder_axis
 * @property {AxisScore} market_axis
 * @property {AxisScore} idea_vs_market_axis
 * @property {boolean} passes_screen
 * @property {string[]} rejection_reasons
 */

/* ---------------------------------------------------------------- helpers */

export const scoreClass = (n) => (n >= 60 ? 'hi' : n >= 35 ? 'mid' : 'lo');

export const VERDICT = {
    in_scope:     { label: 'In scope',     cls: 'pill--in' },
    out_of_scope: { label: 'Out of scope', cls: 'pill--out' },
    not_viable:   { label: 'Not viable',   cls: 'pill--dead' },
};

export const TREND = { improving: '↑', stable: '→', declining: '↓' };

export const fmtDate = (iso) =>
    new Date(iso).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });

/** Escape before interpolating anything user-supplied into HTML. */
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
));

export { USE_MOCK };
