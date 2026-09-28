# Release verification — 2026-09-27

Public pilot: https://semblance-omega.vercel.app
Source: https://github.com/jasonmunguia/semblance

## Verified

- Vercel production deploy returned READY. Site, health, example and private-state routes returned HTTP 200.
- Hosted recipient comparison returned a lookalike warning for two addresses differing by one character.
- Vercel plan: Hobby. Neon resource: Free. Alchemy signup: Free; Base Mainnet enabled. Cloudflare Workers dashboard: Free ($0), current plan. No paid subscription or domain purchased.
- Real Alchemy history and recent-range reads passed. These establish connectivity, not detection accuracy.
- Hosted live collector returned HTTP 200, processed one test wallet, persisted its cursor and displayed stored transfers with `monitoring` status.
- `uv run pytest -q`: 92 passed, exit 0.
- `npm --prefix frontend test`: 10 passed, exit 0.
- `npm --prefix frontend run build`: exit 0.
- `node --test scheduler/worker.test.mjs`: 2 passed, exit 0.
- Scoped quality ratchet, Ruff, diff whitespace and staged secret checks: exit 0.
- Full frontend npm audit: zero reported vulnerabilities.
- Desktop/mobile browser checks: no page errors or horizontal overflow; example recipient warning works in a real browser.
- GitHub Checks run 36387317808 (coverage upgrade) and 36387591034 (initial cache regression): success.

## Scheduled monitoring verified

Cloudflare deployment authorization succeeded. `wrangler deploy` returned exit 0, publishing version `20cf929c-b02e-4366-ab3e-4c03e1566430` with schedule `*/5 * * * *`; the collector secret was installed successfully. The public Worker endpoint is disabled.

An unattended cron invocation completed at 2026-09-28 04:41 UTC (September 27, 9:41 PM PDT). Cloudflare tail reported `outcome: ok`, `processed: 1`, `busy: false`, `budgetReached: false`, and no exceptions. A separate hosted-state read verified the temporary watch changed from `pending` to `monitoring`, with cursor 51890535, a stored check time, and 200 displayed transfers. The verification command returned exit 0. The temporary watch was then removed and empty state verified, restoring pilot capacity.

The five-minute schedule is active. This verifies one real unattended cycle, not a continuous-availability or latency guarantee. New Cloudflare cron configurations can take up to 15 minutes to propagate ([official documentation](https://developers.cloudflare.com/workers/configuration/cron-triggers/)).

## Pilot limits

Three unique monitored wallets across the installation, three per browser session. Five-minute target schedule, with provider and safe-block delay. Free-tier quotas can pause operation. Anonymous sessions are browser-specific; clearing the cookie loses access. PostgreSQL transaction locks serialize collector work and quota changes, but full load/concurrency testing is not claimed. In-memory rate limiting is per process and must be replaced before wider deployment.

No precision/recall, latency guarantee, user adoption or prevented-loss metric is claimed. Incident replay and automated provider fixtures are simulated.

## Historical detection validation

See [the reproducible real-Base case study](../evaluation/README.md). Two explorer-labeled poisoning cases triggered collector alerts and pre-send warnings; real unlimited, finite, and zero USDC approvals behaved as expected. The previously missed outgoing zero-value lookalike event now triggers an alert using an independently verified earlier direct token transfer as its reference. The saved before/after results document the change. Forged token events are excluded from recipient references; delayed verification rechecks retained events. Router and smart-wallet token sends remain outside reference verification. This is not a representative accuracy benchmark, and no confirmed malicious approval was validated.

## Coverage upgrade

The coverage upgrade deployed successfully as `dpl_Di8jrYwSsXTLtuMPrvUsz8ur8HRr`. Live route checks and the recipient warning passed. A hosted collection completed in 3.12 seconds, processed one public wallet, persisted cursor 51894014, returned 200 stored transfers, and independently verified two direct token transfers. This is one observed run, not a latency guarantee.

Browser verification exposed a separate deployment-cache issue: normalized file timestamps and equal HTML sizes let static-file validators return stale HTML referencing a removed asset. The entry page now returns an unconditional response with `Cache-Control: no-store`; a regression test changes the asset reference while preserving file size and timestamp. The final production deployment `dpl_GtksNxhSFvrnxcbguEuAozWppszL` returned READY. HTML validators were also removed because the hosting layer could otherwise issue a 304 despite the application returning 200. A real conditional request with the old validators now returns HTTP 200, `no-store`, and the current assets. Both referenced assets and health/demo/state routes returned 200. The previously blank tab rendered after a normal reload.

Native Arc browser checks verified the example comparison warning, new outgoing-token alert detail, and the last incident replay step. The in-app browser rendered but its automation clicks were ineffective, so interaction verification used Arc. Visual evidence was saved locally at `/tmp/semblance-coverage-upgrade.png`.

The unattended collector advanced the temporary wallet to block 51894127 at 2026-09-28 06:41:16 UTC, after the manual scan at 06:37:23. It remained in `monitoring` state without an error. The temporary watch was removed and empty state verified; pilot capacity was restored. All hosted verification commands returned exit 0 after correcting the checks to use the actual API response field names. No paid service was introduced.
