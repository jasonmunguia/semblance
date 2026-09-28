# Historical Base validation — September 27, 2026

## Result

Semblance detected two historical native-ETH lookalike transfers from addresses
BaseScan labels as involved in address poisoning. A real unlimited USDC approval
triggered an exposure warning; real finite and zero approvals did not. This is a
small, deliberately selected case study, **not a measured scam-detection accuracy rate**.

An additional real outgoing zero-value token event produced no alert. It falls
outside two coverage boundaries: outgoing lookalike recipients are not checked,
and its earlier token-payment recipient is not an eligible native-ETH reference.
Its maliciousness is not independently labeled, so it is not counted as a
confirmed missed attack.

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
is fetched as of that historical head; only earlier positive native transfers
can establish recipient references. This verifies historical detection and
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
| [Outgoing zero-USDC/lookalike token events](https://basescan.org/tx/0x5a9e9c1e9de7e265c6ba561867657e2e23a7026ebe9f4516b30b4e3737b7acdb) | Coverage probe; no independent malicious label | No alert; outgoing lookalike recipients are outside the current monitor rule |

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
  payment is recorded separately in `results.json`. Thus this single observation
  cannot isolate the effect of incoming-only matching from native-only references.
- Native-only references miss relationships established exclusively through token
  payments. Incoming-only matching misses outgoing lookalike event recipients.
- No representative benign sample or held-out attack corpus was evaluated. Do not
  claim a false-positive rate, recall, precision, or prevented-loss metric.

## Recommended next work

Extend detection to outgoing zero-value token events with careful wording that
does not imply the wallet owner initiated a transfer. Add verified token-payment
references without trusting arbitrary token logs. Then evaluate a larger,
independently labeled dataset with unrelated campaigns and ordinary activity.
