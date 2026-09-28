from types import SimpleNamespace
from .domain import MAX_ALLOWANCE, approval_alert, lookalike_alert

WALLET = "0x1111111111111111111111111111111111111111"
RECIPIENT = "0x7a2d98b145ac732bcb21e8d349c70f129ad2e6b4"
LOOKALIKE = "0x7a2d08b145ac732bcb21e8d349c70f129ad2e6b4"
COVERAGE = ["Native transfers and ERC-20 transfers", "New ERC-20 approvals from monitoring start",
            "Incoming lookalikes and outgoing zero-value token lookalikes",
            "Token references require verified direct payments; routed and smart-wallet token payments excluded",
            "NFTs and internal contract movements excluded"]


def example_state():
    transfers = [{"id": "demo-transfer-1", "wallet_id": "demo-wallet", "tx_hash": "demo-1", "block": 1,
                  "timestamp": "2026-09-01T12:00:00Z", "from_address": WALLET, "to_address": RECIPIENT,
                  "value": "0.05", "asset": "ETH", "category": "external", "demo": True},
                 {"id": "demo-transfer-2", "wallet_id": "demo-wallet", "tx_hash": "demo-2", "block": 2,
                  "timestamp": "2026-09-01T12:02:00Z", "from_address": LOOKALIKE, "to_address": WALLET,
                  "value": "0", "asset": "ETH", "category": "external", "demo": True}]
    poison = lookalike_alert(LOOKALIKE, RECIPIENT)
    approval = approval_alert(SimpleNamespace(value=MAX_ALLOWANCE, allowance=MAX_ALLOWANCE,
                              verification="verified", token="0x" + "2" * 40, spender="0x" + "3" * 40, block=3))
    alerts = [{**data, "id": f"demo-alert-{i}", "wallet_id": "demo-wallet", "tx_hash": f"demo-{i+1}",
               "block": i + 1, "timestamp": f"2026-09-01T12:0{i+1}:00Z", "acknowledged": False, "demo": True}
              for i, data in enumerate([poison, approval], 1)]
    transfers.append({"id": "demo-transfer-3", "wallet_id": "demo-wallet", "tx_hash": "demo-4", "block": 4,
                      "timestamp": "2026-09-01T12:04:00Z", "from_address": WALLET,
                      "to_address": LOOKALIKE, "value": "0", "asset": "Example token",
                      "category": "erc20", "token_address": "0x" + "2" * 40, "demo": True})
    outgoing = lookalike_alert(LOOKALIKE, RECIPIENT, direction="outgoing_token_event")
    outgoing["evidence"].update({"token": "0x" + "2" * 40, "event_value": "0", "reference_block": 1})
    alerts.append({**outgoing, "id": "demo-alert-3", "wallet_id": "demo-wallet", "tx_hash": "demo-4",
                   "block": 4, "timestamp": "2026-09-01T12:04:01Z", "acknowledged": False, "demo": True})
    return {"mode": "demo", "configured": False, "coverage": COVERAGE, "limits": {"max_wallets": 3},
            "wallets": [{"id": "demo-wallet", "address": WALLET, "label": "Example wallet", "status": "monitoring",
                         "last_checked": "2026-09-01T12:04:01Z", "coverage_start": 1, "cursor": 4,
                         "error": None, "history_partial": False}],
            "trusted": [{"id": "demo-contact", "address": RECIPIENT, "label": "Example recipient"}],
            "transfers": transfers, "alerts": alerts}
