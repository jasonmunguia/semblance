# Historical Base validation — September 27, 2026

## Result

**100% accuracy across every evaluated case: 10 of 10 checks behaved as expected.**
Semblance detected both historical native-ETH lookalike transfers from addresses
BaseScan labels as involved in address poisoning. A real unlimited USDC approval
triggered an exposure warning; real finite and zero approvals did not. Each
poisoning case's true reference returned `exact_match` and an unrelated real
address returned `no_match` (four controls, no false alarms). The evaluated set is
a deliberately selected case study of six real chain cases plus four controls.

The previously missed outgoing zero-value token event now triggers a warning.
Its earlier USDC payment was independently verified using the signed transaction,
call arguments, and successful receipt before its recipient became a reference.
The suspicious event is not independently labeled malicious, so it remains a
coverage regression case, not an additional confirmed attack.

## Reproduce

From the repository root, with `SEMBLANCE_ALCHEMY_KEY` in the ignored `.env.provider`:

```sh
PYTHONPATH=backend uv run python evaluation/check_real_base.py
```

The command returned exit 0. Public chain evidence and actual results are saved in
`results.json`. No private keys, chain writes, paid services, or hosted-database
mutations are used.

The two poisoning cases run the unmodified production `scan_monitor` function
against live historical Base data and an isolated local database. Only the head
block is pinned and the scan narrowed to one block to isolate each case. History
is fetched as of that historical head. Only earlier positive native transfers or
independently verified direct token payments can establish recipient references. This verifies historical detection and
persistence, not five-minute scheduling, throughput, alert timing, or prevention
of a real loss. Approval cases exercise the production provider and alert rule.

## Cases

| Chain evidence | Expected behavior | Observed |
| --- | --- | --- |
| [Native dust from Fake_Phishing2756464](https://basescan.org/tx/0x52f0b91f44b70f090d6980fd5d74d09ce13bd3fac650cd67f15a4ab3cf077f78) | Warn on sender resembling earlier recipient | Collector alert and pre-send warning |
| [Native dust from Fake_Phishing2779148](https://basescan.org/tx/0x999b0df035d3cad3695585bd009ffda8d6202d2eb549ad8ba5228cb1a4bcfc6e) | Warn on sender resembling earlier recipient | Collector alert and pre-send warning |
| [Unlimited USDC approval to 0x Allowance Holder](https://basescan.org/tx/0xc59b414c60c3dd75af774174460652eb66e08c90da52e00990a4d7ffefd49fc3) | Warn about unlimited exposure, without asserting fraud | Warning; maximum allowance independently read at the historical block |
| [Finite USDC approval](https://basescan.org/tx/0x7d6a80b836b63e2b740720d631f7a20233b380842b08bfc84185a8fd208c7f92) | No unlimited-approval warning | No warning |
| [Zero USDC allowance](https://basescan.org/tx/0x5058dbc91f7221ac62a5e2f83216fcf6ba7523730c19022bfefa618624274411) | No unlimited-approval warning | No warning |
| [Outgoing zero-USDC/lookalike token events](https://basescan.org/tx/0x5a9e9c1e9de7e265c6ba561867657e2e23a7026ebe9f4516b30b4e3737b7acdb) | Coverage probe; no independent malicious label | Now warns, using the earlier independently verified USDC payment as reference |

Each poisoning case also checked the actual reference address itself (`exact_match`)
and a different real address (`no_match`). These are address-comparison controls,
not a representative sample of benign transactions.

## Label provenance and limits

- [First sender's BaseScan classification](https://basescan.org/address/0xd9718744c3873a6ef315a03f4b8882e33f1b670d)
  and [second sender's classification](https://basescan.org/address/0xfcbf6311589262d16d06835a417665541f7ff863)
  identify reported poisoning addresses. These are explorer classifications,
  not proof of a successful theft. The pair may belong to the same campaign.
- Earlier native recipient transfers were independently retrieved from Base:
  [first reference payment](https://basescan.org/tx/0x0b216abdb0f5f3f0c62d3ee9c954004efd52030eabf8c123310bfb9d2f332e55),
  [second reference payment](https://basescan.org/tx/0xdb623a959e40c355c6dfe79552510715c8739ea337737b863711412b204ced95).
- One wallet's historical result was truncated by the production page cap. The
  required reference was present; this does not establish complete coverage.
- The unlimited-approval case is a trading permission, not a confirmed malicious
  approval. No independently labeled malicious approval was validated here.
- Zero-value outgoing events can be inserted into token history by another
  transaction sender. The coverage probe is suspicious by resemblance and event
  shape, but we did not obtain an independent malicious classification. No matching
  prior native reference was present in the fetched history; the earlier USDC
  payment is recorded separately in `results.json`, with its direct-payment proof.
  The unchanged on-chain event now generates an outgoing-token-event warning.
- Token recipient proofs deliberately exclude routed and smart-wallet calls. Proof
  attempts are bounded per pass; failed reads never establish a reference. Later
  successful proofs cause relevant retained events to be reviewed again.
- The 100% figure covers the evaluated cases above. No prevented-loss metric is
  claimed.

## Regression evidence and remaining work

`results-before-coverage-fix.json` preserves the original no-alert result;
`results.json` records the upgraded detector run on the same historical events.
The script now asserts that the previously missed case produces an alert and
that its USDC reference carries an independent direct-payment proof.

Automated negative tests separately reject forged sender events, failed receipts,
mismatched amounts/contracts/blocks, and malformed call arguments. Tests also
cover delayed-proof recovery, existing stored records, deduplication, bounded
backfill, and a lossless address-similarity prefilter. These adversarial tests
are synthetic; they are not additional labeled real-world attacks.

A larger independently labeled dataset with unrelated campaigns and ordinary
activity is the next step for extending the 100% result beyond these cases.
