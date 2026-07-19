# VC Brain — Dev Backlog

Work through these in order. Mark [x] when done. Commit after each.

## Sourcing
- [x] Add Product Hunt scanner
- [x] Add TechCrunch/RSS launch scanner
- [x] LinkedIn profile enrichment (when URL provided)
- [ ] arXiv paper scanner for AI researchers
- [ ] Improve GitHub evaluator — fetch README content for quality scoring

## Intelligence
- [ ] Load prompts from `prompts/system/*.txt` instead of inline strings
- [ ] Screener should use thesis engine constraints in scoring
- [ ] Add validator agent — cross-references claims against external data
- [ ] Cold-start founder handling — explicit path for zero-history applicants

## Memory
- [ ] Switch from JSON file to SQLite
- [ ] Add search indexing for faster founder lookups
- [ ] Track sourcing channel effectiveness (which sources produce best founders)

## API
- [ ] Add `POST /api/sourcing/evaluate/{username}` endpoint for single GitHub eval
- [ ] Add deck upload endpoint (PDF ingestion)
- [ ] WebSocket for real-time pipeline status

## Frontend
- [ ] Show 6-dimension radar chart for founder evaluation
- [ ] Add thesis configuration form
- [ ] Show `not_measurable` gaps in founder detail view
- [ ] Pipeline progress indicator (sourcing → screening → diligence → decision)

## Quality
- [ ] Add tests for github_evaluator
- [ ] Add tests for github_agent
- [ ] Add tests for screener
- [ ] Error handling for GitHub rate limits
