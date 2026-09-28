"""Read-only historical checks. Run: PYTHONPATH=backend uv run python evaluation/check_real_base.py.

Uses the existing private .env.provider file. Never writes to the hosted database,
sends a chain transaction, or invents chain records. Results are case studies,
not a representative estimate of fraud-detection accuracy.
"""
import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from semblance.config import Settings
from semblance.db import Alert, Monitor, Transfer, database
from semblance.domain import approval_alert, check_recipient, compare_addresses
from semblance.provider import APPROVAL_TOPIC, BaseProvider
from semblance.worker import positive, scan_monitor


POISONING = [
    ("0x52f0b91f44b70f090d6980fd5d74d09ce13bd3fac650cd67f15a4ab3cf077f78",
     "0xd9718744c3873a6ef315a03f4b8882e33f1b670d"),
    ("0x999b0df035d3cad3695585bd009ffda8d6202d2eb549ad8ba5228cb1a4bcfc6e",
     "0xfcbf6311589262d16d06835a417665541f7ff863"),
]
APPROVALS = [
    ("finite", "0x7d6a80b836b63e2b740720d631f7a20233b380842b08bfc84185a8fd208c7f92"),
    ("zero", "0x5058dbc91f7221ac62a5e2f83216fcf6ba7523730c19022bfefa618624274411"),
    ("unlimited", "0xc59b414c60c3dd75af774174460652eb66e08c90da52e00990a4d7ffefd49fc3"),
]


class HistoricalProvider(BaseProvider):
    """Pin the collector's head to an actual historical block, retaining live reads."""

    head: int

    async def safe_head(self):
        return self.head, await self.block_hash(self.head)


async def replay(provider, address, block):
    provider.head = block
    engine, factory = database("sqlite:///:memory:")
    try:
        with factory.begin() as db:
            db.add(Monitor(address=address))
        # One historical block isolates the case. This is not a throughput test.
        await scan_monitor(factory, provider, address, Settings(scan_blocks=1))
        with factory() as db:
            return {
                "alerts": [a.data for a in db.scalars(select(Alert))],
                "transfers": [t.data for t in db.scalars(select(Transfer))],
                "history_partial": db.get(Monitor, address).history_partial,
                "cursor": db.get(Monitor, address).cursor,
            }
    finally:
        engine.dispose()


async def main():
    settings = Settings(_env_file=".env.provider")
    provider = HistoricalProvider(settings.alchemy_key)
    results = {"checked_at": datetime.now(timezone.utc).isoformat(), "chain_id": 8453,
               "method": "Unmodified production scan_monitor, live historical RPC reads, isolated local SQLite, one-block scan",
               "poisoning": [], "approvals": [], "coverage_probe": None}
    try:
        for tx_hash, labeled_sender in POISONING:
            tx = await provider._rpc("eth_getTransactionByHash", [tx_hash])
            assert tx and tx["from"] == labeled_sender
            receipt = await provider._rpc("eth_getTransactionReceipt", [tx_hash])
            assert receipt["status"] == "0x1"
            block, victim = int(tx["blockNumber"], 16), tx["to"]
            run = await replay(provider, victim, block)
            alerts = [a for a in run["alerts"] if a["tx_hash"] == tx_hash]
            references = [t for t in run["transfers"] if t["from_address"] == victim
                          and t["category"] == "external" and positive(t["value"])
                          and t["block"] < block
                          and compare_addresses(labeled_sender, t["to_address"])["lookalike"]]
            assert references and any(a["kind"] == "lookalike" for a in alerts)
            reference = max(references, key=lambda t: t["block"])
            ref = [{"address": reference["to_address"], "kind": "previous_recipient"}]
            check = check_recipient(labeled_sender, ref, "Historical reference")
            exact = check_recipient(reference["to_address"], ref, "Historical reference")
            different = check_recipient(victim, ref, "Historical reference")
            assert check["status"] == "lookalike" and exact["status"] == "exact_match"
            assert different["status"] == "no_match"
            results["poisoning"].append({
                "tx_hash": tx_hash, "block": block, "victim": victim,
                "label_source": f"https://basescan.org/address/{labeled_sender}",
                "label_quality": "Explorer-reported poisoning address; cases may share a campaign",
                "reference_transfer": reference, "alerts": alerts,
                "pre_send": check["status"], "exact_reference_control": exact["status"],
                "dissimilar_address_control": different["status"],
                "history_partial": run["history_partial"],
            })
            print("PASS historical poisoning replay", tx_hash, flush=True)

        for kind, tx_hash in APPROVALS:
            tx = await provider._rpc("eth_getTransactionByHash", [tx_hash])
            assert tx
            block = int(tx["blockNumber"], 16)
            receipt = await provider._rpc("eth_getTransactionReceipt", [tx_hash])
            assert receipt["status"] == "0x1"
            log = next(log for log in receipt["logs"]
                       if len(log["topics"]) == 3 and log["topics"][0] == APPROVAL_TOPIC
                       and log["address"] == "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913")
            # Smart-wallet execution can have a transaction sender other than
            # the token owner. Monitor the owner encoded in the actual event.
            owner = "0x" + log["topics"][1][-40:]
            scan = await provider.scan(owner, block, block)
            records = [a for a in scan.approvals if a.tx_hash == tx_hash]
            assert records
            alerts = [approval_alert(a) for a in records]
            assert any(alerts) == (kind == "unlimited")
            if kind == "unlimited":
                assert records[0].verification == "verified"
                assert records[0].allowance == records[0].value
            results["approvals"].append({"kind": kind, "tx_hash": tx_hash,
                                        "records": [asdict(a) for a in records], "alerts": alerts})
            print("PASS real approval", kind, tx_hash, flush=True)

        # Probe a different shape found in real history. This address has no
        # independently verified scam label; resemblance is not proof of fraud.
        probe_hash = "0x5a9e9c1e9de7e265c6ba561867657e2e23a7026ebe9f4516b30b4e3737b7acdb"
        victim = "0x0b07f64abc342b68aec57c0936e4b6fd4452967e"
        tx = await provider._rpc("eth_getTransactionByHash", [probe_hash])
        block = int(tx["blockNumber"], 16)
        run = await replay(provider, victim, block)
        events = [t for t in run["transfers"] if t["tx_hash"] == probe_hash]
        emitted = [a for a in run["alerts"] if a["tx_hash"] == probe_hash]
        zero_event = next(t for t in events if t["from_address"] == victim and t["value"] == "0")
        earlier = [t for t in run["transfers"] if t["category"] == "external"
                   and t["from_address"] == victim and positive(t["value"])
                   and t["block"] < block
                   and compare_addresses(zero_event["to_address"], t["to_address"])["lookalike"]]
        token_reference = next(t for t in run["transfers"]
                               if t["tx_hash"] == "0x9600fb0421f1fb7d5df035fba0a6c45d8fa30e1d96bcfd43da45f5cc498e67b8")
        reference_tx = await provider._rpc("eth_getTransactionByHash", [token_reference["tx_hash"]])
        results["coverage_probe"] = {
            "tx_hash": probe_hash, "block": block, "transaction_sender": tx["from"],
            "label_quality": "Unlabeled real outgoing zero-value/lookalike pattern, not a confirmed scam",
            "events": events, "alerts": emitted,
            "earlier_native_reference": max(earlier, key=lambda t: t["block"]) if earlier else None,
            "earlier_token_reference": token_reference,
            "reference_transaction_sender": reference_tx["from"],
            "result": "Outgoing zero-value lookalike detected using an independently verified direct token-payment reference",
        }
        assert any(t["from_address"] == victim and t["value"] == "0" for t in events)
        assert token_reference.get("recipient_verification") == "verified_direct_token_transfer"
        assert reference_tx["from"] == victim
        assert any(a["evidence"]["direction"] == "outgoing_token_event"
                   and a["evidence"]["reference_kind"] == "verified_token_recipient" for a in emitted)
        print("PASS previously missed outgoing zero-value pattern:", len(emitted), "alert", flush=True)
    finally:
        await provider.aclose()
    Path("evaluation/results.json").write_text(json.dumps(results, indent=2) + "\n")
    print("Saved evaluation/results.json; case checks passed. No population accuracy claim.")


if __name__ == "__main__":
    asyncio.run(main())
