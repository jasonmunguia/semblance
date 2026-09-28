# Release verification — 2026-09-27

Public pilot: https://semblance-omega.vercel.app
Source: https://github.com/jasonmunguia/semblance

## Verified

- Vercel production deploy returned READY. Site, health, example and private-state routes returned HTTP 200.
- Hosted recipient comparison returned a lookalike warning for two addresses differing by one character.
- Vercel plan: Hobby. Neon resource: Free. Alchemy signup: Free; Base Mainnet enabled. No paid subscription or domain purchased.
- Real Alchemy history and recent-range reads passed. These establish connectivity, not detection accuracy.
- Hosted live collector returned HTTP 200, processed one test wallet, persisted its cursor and displayed stored transfers with `monitoring` status.
- `uv run pytest -q`: 49 passed, exit 0.
- `npm --prefix frontend test`: 9 passed, exit 0.
- `npm --prefix frontend run build`: exit 0.
- `node --test scheduler/worker.test.mjs`: 2 passed, exit 0.
- Scoped quality ratchet, Ruff, diff whitespace and staged secret checks: exit 0.
- Full frontend npm audit: zero reported vulnerabilities.
- Desktop/mobile browser checks: no page errors or horizontal overflow; example recipient warning works in a real browser.
- GitHub Checks run 36375451960: success.

## Pending

Cloudflare account exists; deployment tool authorization has not completed. The scheduler bundle passes a dry run, but its scheduled trigger has not been published and no unattended cycle has been observed. Background monitoring must not be described as operational until that gate is cleared.

## Pilot limits

Three unique monitored wallets across the installation, three per browser session. Five-minute target schedule after activation, with provider and safe-block delay. Free-tier quotas can pause operation. Anonymous sessions are browser-specific; clearing the cookie loses access. PostgreSQL transaction locks serialize collector work and quota changes, but full load/concurrency testing is not claimed. In-memory rate limiting is per process and must be replaced before wider deployment.

No precision/recall, latency guarantee, user adoption or prevented-loss metric is claimed. Incident replay and automated provider fixtures are simulated.
