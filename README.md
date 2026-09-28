# Semblance

**Check the address. Understand the warning.**

Semblance is a read-only wallet-security pilot for Base. Compare a destination against known addresses before sending, monitor public wallet activity, and inspect the evidence behind lookalike-address and unlimited-token-approval warnings.

## Try it

- **Check:** compare a pasted recipient with a manually entered reference, your saved contacts, or prior positive native-transfer recipients.
- **Monitor:** watch public Base addresses, inspect alerts, and mark them reviewed. Watchlists belong to an anonymous browser session; clearing its cookie loses access to that session.
- **Replay:** step through a clearly labeled simulated incident. Example data never counts as live detection or evaluation performance.

No wallet connection, private key, signature, or money movement is required. Semblance cannot block transactions or revoke permissions. Exact address matches and absent warnings are not safety certificates.

## Run locally

Requires Python 3.11+ with uv and Node 24 with npm.

```sh
uv sync --frozen
npm --prefix frontend ci
npm --prefix frontend run build
uv run uvicorn semblance.api:create_app --factory --app-dir backend --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. The example replay and manual recipient comparison work without a data-provider account. For hot reload, run `npm --prefix frontend run dev`; its `/api` proxy points to port 8000.

Copy `.env.example` to `.env` and set `SEMBLANCE_ALCHEMY_KEY` privately to enable live reads. Run the collector in another terminal:

```sh
PYTHONPATH=backend uv run python -m semblance.worker
```

The collector only starts with a configured key. `--once` performs one bounded pass. Keep one local SQLite collector running; hosted PostgreSQL uses a transaction-scoped collector lock.

## Hosted design

Vercel serves React and a Python FastAPI application at one origin. Neon stores watchlists, contacts, public observations, alerts, and scan cursors in PostgreSQL. A Cloudflare Worker cron invokes the secret-protected `/internal/collect` endpoint every five minutes. Each call has a 45-second work budget. The cursor advances only after a complete range is stored; failures preserve previous evidence and show an error/stale state.

Free service quotas make this a small pilot: three watched wallets per browser session, three unique monitored wallets across the installation. History is bounded. Timing is best effort and follows Base's `safe` block head, so warnings are delayed relative to chain execution. This is not a transaction interceptor.

Vercel Hobby's built-in daily cron is too infrequent for this collector. GitHub Actions runs tests only. The free Cloudflare scheduler and the data-provider account must both be configured before monitoring is operational.

### Environment and deployment

- `SEMBLANCE_PRODUCTION=true` requires a persistent PostgreSQL URL and a random `SEMBLANCE_SESSION_SECRET` of at least 32 characters.
- Vercel's Neon integration provides `DATABASE_URL`; the app selects the psycopg driver automatically.
- `SEMBLANCE_ALCHEMY_KEY` stays server-side.
- `SEMBLANCE_COLLECTOR_SECRET` and Cloudflare's `COLLECTOR_SECRET` must match. Never commit either.
- Deploy using `vercel deploy --prod`; the build command compiles the frontend. Update `scheduler/wrangler.toml` with the verified deployed address before publishing its worker.
- Database tables are created on startup. Schema changes beyond this initial release need an explicit migration; `create_all` does not upgrade existing columns.

## Detection boundaries

Address comparison uses normalized full addresses and validates mixed-case checksums. A different address is flagged when its first and last four hexadecimal characters match a reference, or at most two characters differ. This is an explainable heuristic, not an exhaustive attack classifier.

Automatic reference history uses **positive outgoing native transfers only**. Incoming addresses are never promoted to trusted contacts, and token events are not treated as proof of a recipient relationship: a token contract can emit misleading events. Alerts can examine incoming native/token transfers. Same-block outgoing references are conservatively excluded because block order alone does not prove event order.

Approval alerts inspect new ERC-20 `Approval` events from the displayed monitoring-start block. A maximum allowance is checked against the token contract at that block. The UI distinguishes confirmed maximum, reduced allowance, and unavailable reads. This is an observation at block end, not a current complete permission audit or proof the spender is malicious. NFT approvals and internal contract movements are excluded.

## Verification

```sh
uv run pytest -q
uv run ruff check backend app.py
npm --prefix frontend test
npm --prefix frontend run build
```

Tests cover malformed provider data, exact numeric scaling, pagination, bounded RPC log queries, failed reads, private session ownership, forged/zero/future reference exclusions, deduplication, and chain reorganization recovery. All provider tests use synthetic fixtures; they do not establish real-world detection accuracy.

See [architecture](docs/ARCHITECTURE.md), [API contract](docs/API.md), and [implementation plan](docs/IMPLEMENTATION_PLAN.md) for details.
