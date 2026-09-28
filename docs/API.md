# Browser API contract

All routes use `/api`. Cookie session, same origin. JSON bodies. Errors: `{ "detail": "human readable message" }`. GET state creates the cookie before mutations. No external outbound messages.

## State
GET `/api/state` and GET `/api/demo` return:

```json
{
  "mode":"live",
  "configured":false,
  "coverage":["Native transfers and ERC-20 transfers", "New ERC-20 approvals from monitoring start", "NFTs and internal contract movements excluded"],
  "limits":{"max_wallets":3,"max_global_wallets":3,"poll_seconds":300},
  "wallets":[{"id":"uuid","address":"0x...","label":"My wallet","status":"pending","last_checked":null,"coverage_start":null,"cursor":null,"error":null,"history_partial":false}],
  "trusted":[{"id":"uuid","address":"0x...","label":"Treasury"}],
  "transfers":[{"id":"uuid","wallet_id":"uuid","tx_hash":"0x...","block":123,"timestamp":"2026-09-27T12:00:00Z","from_address":"0x...","to_address":"0x...","value":"1.0","asset":"ETH","category":"external","token_address":null,"demo":false}],
  "alerts":[{"id":"uuid","wallet_id":"uuid","kind":"lookalike","severity":"warning","title":"Possible lookalike address","explanation":"...","action":"Verify the full address directly with the recipient.","tx_hash":"0x...","block":123,"timestamp":"2026-09-27T12:00:00Z","evidence":{"candidate":"0x...","reference":"0x...","reference_kind":"previous_recipient","differing_indices":[7,8]},"acknowledged":false,"demo":false}]
}
```

Wallet status: pending, monitoring, catching_up, stale, error, unavailable. `configured` is live provider availability, not successful deployment. `mode: demo` always means simulated data. Only real transaction hashes get `https://basescan.org/tx/<hash>` links. Approval evidence may contain token, spender, allowance, verification, observed_block instead of candidate/reference. Timestamps nullable. Never display a clean/safe verdict on a stale or unavailable read.

Transfer records can include `raw_value` (the unscaled integer amount) and `recipient_verification`. Only `verified_direct_token_transfer` permits a positive outgoing ERC-20 record to become a payment reference. `not_direct_transfer` records a definitive rejection; `unavailable` or an absent field provides no proof and remains retryable. Verification compares the wallet-originated direct token call with its successful receipt and matching event, including recipient, amount, token, transaction hash, and block identifiers. Arbitrary token events and routed/smart-wallet token calls are not references.

Lookalike evidence includes `direction`: `incoming` compares a sender; `outgoing_token_event` compares the recipient of a zero-value ERC-20 event listing the watched wallet as sender. The latter does **not** establish that the wallet owner initiated a transaction. `reference_kind` is `previous_recipient` for an earlier positive native payment or `verified_token_recipient` for an independently verified direct token payment. Evidence also includes `reference_block`, `token` (nullable), and `event_value`. Both directions require the payment reference to precede the event's block.

Token proof enrichment is bounded to 12 records per wallet pass, four concurrent jobs, and three seconds; therefore stored references and warnings can lag ordinary collection. Newly verified references cause retained events within monitoring coverage to be rechecked. Old zero-value outgoing events are reviewed in batches of up to 100 per pass and marked `lookalike_review_version: 2`. No scan reset is required; the 10,000-transfer retention bound still applies.

POST `/api/wallets` `{address,label}` returns watch. DELETE `/api/wallets/{id}` returns `{ok:true}`.
POST `/api/trusted` `{address,label}` returns trusted contact. DELETE `/api/trusted/{id}` returns `{ok:true}`.
POST `/api/alerts/{id}/acknowledge` returns `{ok:true}`. No live mutation of demo objects.

POST `/api/check` accepts `{destination, wallet_id?: string, reference_addresses?: string[], demo?: boolean}`. Returns:
```json
{"status":"lookalike","matches":[{"address":"0x...","kind":"previous_recipient","label":"Previous recipient","matching_prefix":4,"matching_suffix":4,"differing_indices":[7,8]}],"checked_references":1,"coverage_note":"Compared with stored recipients; this does not establish overall safety.","action":"Verify the full address directly with the recipient."}
```
Status: lookalike, exact_match, no_match, insufficient_history. `reference_addresses` are user-supplied references, maximum 20, never automatically persisted as trusted. `demo:true` uses only example references. Exact match is not a safe verdict. Even without a provider, explicit reference comparisons work. The page should include an optional reference input for that local comparison flow.

Stored payment match kinds include `previous_recipient` and `verified_token_recipient`; trusted contacts and explicit references retain their separate source kinds. `coverage_note` states that native payments and verified direct token payments are used, token verification is bounded, and routed/smart-wallet payments are excluded. No-match results describe the available references only.

GET `/health` returns `{status:"ok",live_configured:false}`.

POST `/internal/collect` requires a constant-time checked bearer collector secret. It runs a bounded read-only collection pass, returns progress/busy/budget state, and is not a browser or public action.
