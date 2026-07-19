# VC Brain — Dev Backlog

Work through these in order. Mark [x] when done. Commit after each.

## Sourcing
- [x] Add Product Hunt scanner
- [x] Add TechCrunch/RSS launch scanner
- [x] LinkedIn profile enrichment (when URL provided)
- [x] arXiv paper scanner for AI researchers
- [x] Improve GitHub evaluator — fetch README content for quality scoring

## Intelligence
- [x] Load prompts from `prompts/system/*.txt` instead of inline strings
- [x] Screener should use thesis engine constraints in scoring
- [x] Add validator agent — cross-references claims against external data
- [x] Cold-start founder handling — explicit path for zero-history applicants

## Memory
- [x] Switch from JSON file to SQLite
- [x] Add search indexing for faster founder lookups
- [x] Track sourcing channel effectiveness (which sources produce best founders)

## API
- [x] Add `POST /api/sourcing/evaluate/{username}` endpoint for single GitHub eval
- [x] Add deck upload endpoint (PDF ingestion)
- [x] WebSocket for real-time pipeline status

## Frontend
- [x] Show 6-dimension radar chart for founder evaluation
- [x] Add thesis configuration form
- [x] Show `not_measurable` gaps in founder detail view
- [x] Pipeline progress indicator (sourcing → screening → diligence → decision)

## Quality
- [ ] Add tests for github_evaluator
- [ ] Add tests for github_agent
- [ ] Add tests for screener
- [ ] Error handling for GitHub rate limits
