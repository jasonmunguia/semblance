# Semblance implementation plan

Goal: build and verify the agreed read-only monitor and recipient checker, with clear separation between example and live data.
Architecture: React frontend served by FastAPI, SQLAlchemy persistence, separate Python polling worker, Alchemy provider adapter. SQLite local / PostgreSQL hosted.
Spec: `docs/ARCHITECTURE.md`; browser contract: `docs/API.md`.
Execution: native lead implementation and review, scoped mechanical frontend/provider work delegated according to Jason's standing model-routing instruction. User has explicitly requested implementation; no additional design approval loop.

## Constraints and review focus
- Never sign/send a transaction or collect wallet secrets.
- Never disguise simulated or incomplete data as live/clean.
- Preserve per-browser ownership of labels, watchlists and trusted contacts.
- Keep provider keys out of logs, errors, browser bundles, and Git.
- No unsupported claims about detection quality, latency, user counts or production readiness.
- Verify cursor does not move after collection failure, deduplication across retries, time ordering of reference recipients, reorg recovery, and bounded data usage.

## Task 1: domain and persistence
- [ ] Create `backend/semblance/domain.py` pure address/approval rules and simulated example data.
- [ ] Test exact address vs case-only changes, lookalike mismatch indices, invalid checksum, limited and unlimited approvals, and insufficient references in `backend/tests/test_domain.py`.
- [ ] Create settings and database models with explicit uniqueness and session ownership.
- [ ] Run `uv run pytest backend/tests/test_domain.py` and resolve actual failures.

## Task 2: provider adapter
- [ ] Create `provider.py` typed records and HTTPX adapter. Calls: safe_head(), block_hash(number), history(address), scan(address,start,end), allowance(token,owner,spender,block).
- [ ] Test paginated bounded history, 10-block Approval log windows, error redaction, exact uint decoding, and pagination truncation via HTTPX MockTransport.
- [ ] Return explicit partial-history metadata; reject partial monitoring scan without advancing caller cursor.

## Task 3: API and worker
- [ ] Implement routes exactly as `docs/API.md`, signed anonymous cookies, origin checks, limits, and session-resource checks.
- [ ] Implement worker transaction boundary: collect first, persist observations/alerts/cursor together, rollback on failure, retain sanitized error status.
- [ ] Test two isolated browser clients, tampered cookies, unauthorized IDs, malformed requests, delete operations, provider-unavailable state, deduplication and restart/reorg paths.

## Task 4: website
- [ ] Implement React/TypeScript website with mode switch, recipient checker, watchlist, alert inspector and stepped incident replay.
- [ ] Use plain explanatory copy and full-address comparison, useful empty/error states, keyboard focus and mobile layout.
- [ ] Run TypeScript/build and meaningful component tests. Exercise screenshot and API flows in a local browser.

## Task 5: packaging, review and handoff
- [ ] Add locked dependencies, container build, PostgreSQL compose deployment, health checks, startup commands, CI, ignored environment template and runbook.
- [ ] Run all backend tests, frontend build/tests, scoped quality ratchet and diff check; inspect browser desktop/mobile.
- [ ] Review external-source-data boundaries and public-resource abuse limits.
- [ ] Document real-account/live-production gates separately from local test results. Publish only once secrets/hosting access and recurring costs are resolved.
