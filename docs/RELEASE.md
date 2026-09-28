# Release verification — 2026-09-27

Public pilot: https://semblance-omega.vercel.app
Source: https://github.com/jasonmunguia/semblance

## Verified

- Vercel production deploy returned READY. Site, health, example and private-state routes returned HTTP 200.
- Hosted recipient comparison returned a lookalike warning for two addresses differing by one character.
- Vercel plan: Hobby. Neon resource: Free. Alchemy signup: Free; Base Mainnet enabled. Cloudflare Workers dashboard: Free ($0), current plan. No paid subscription or domain purchased.
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

## Scheduled monitoring verified

Cloudflare deployment authorization succeeded. `wrangler deploy` returned exit 0, publishing version `20cf929c-b02e-4366-ab3e-4c03e1566430` with schedule `*/5 * * * *`; the collector secret was installed successfully. The public Worker endpoint is disabled.

An unattended cron invocation completed at 2026-09-28 04:41 UTC (September 27, 9:41 PM PDT). Cloudflare tail reported `outcome: ok`, `processed: 1`, `busy: false`, `budgetReached: false`, and no exceptions. A separate hosted-state read verified the temporary watch changed from `pending` to `monitoring`, with cursor 51890535, a stored check time, and 200 displayed transfers. The verification command returned exit 0. The temporary watch was then removed and empty state verified, restoring pilot capacity.

The five-minute schedule is active. This verifies one real unattended cycle, not a continuous-availability or latency guarantee. New Cloudflare cron configurations can take up to 15 minutes to propagate ([official documentation](https://developers.cloudflare.com/workers/configuration/cron-triggers/)).

## Pilot limits

Three unique monitored wallets across the installation, three per browser session. Five-minute target schedule, with provider and safe-block delay. Free-tier quotas can pause operation. Anonymous sessions are browser-specific; clearing the cookie loses access. PostgreSQL transaction locks serialize collector work and quota changes, but full load/concurrency testing is not claimed. In-memory rate limiting is per process and must be replaced before wider deployment.

No precision/recall, latency guarantee, user adoption or prevented-loss metric is claimed. Incident replay and automated provider fixtures are simulated.

## Historical detection validation

See [the reproducible real-Base case study](../evaluation/README.md). Two explorer-labeled poisoning cases triggered collector alerts and pre-send warnings; real unlimited, finite, and zero USDC approvals behaved as expected. An outgoing zero-value lookalike event exposed an incoming-only monitoring coverage gap. This is not a representative accuracy benchmark, and no confirmed malicious approval was validated.
