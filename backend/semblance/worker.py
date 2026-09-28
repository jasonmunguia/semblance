"""A single read-only collector; observations and cursor commit together."""
import argparse
import asyncio
import hashlib
import logging
import time
from dataclasses import asdict

from sqlalchemy import delete, select, text

from .config import get_settings
from .db import Alert, BrowserSession, Monitor, Transfer, Watch, database
from .domain import approval_alert, lookalike_alert
from .provider import BaseProvider, ProviderError
from .references import ReferenceIndex, VERIFIED_TOKEN, positive, reference_kind, zero

logger = logging.getLogger(__name__)


def event_key(address, event_id):
    return hashlib.sha256(f"{address}:{event_id}".encode()).hexdigest()


async def verify_references(provider, address, candidates):
    """Bound optional enrichment so unavailable proofs cannot halt core collection.

    Persisted definitive rejections allow older records to progress on later
    passes. Transient failures remain retryable. No unverified event is trusted.
    """
    selected, hashes = [], set()
    for key, data in sorted(candidates.items(), key=lambda item: item[1]["block"], reverse=True):
        if (data["category"] != "erc20" or data["from_address"] != address
                or data["to_address"] == address or not positive(data["value"])
                or data.get("recipient_verification") in (VERIFIED_TOKEN, "not_direct_transfer")):
            continue
        if data["tx_hash"] not in hashes and len(hashes) >= 12:
            continue
        # At most twelve records and twelve transactions per pass.
        if len(selected) >= 12:
            break
        hashes.add(data["tx_hash"])
        selected.append((key, data))
    outcomes = {}
    semaphore = asyncio.Semaphore(4)

    async def verify(key, data):
        async with semaphore:
            outcomes[key] = await provider.verify_token_reference(data, address)

    try:
        await asyncio.wait_for(asyncio.gather(*(verify(key, data) for key, data in selected)), timeout=3)
    except TimeoutError:
        pass
    return outcomes


def persist_transfers(db, address, transfers):
    keyed = {event_key(address, item.event_id): item for item in transfers}
    existing = set(db.scalars(select(Transfer.id).where(Transfer.id.in_(keyed)))) if keyed else set()
    for key, item in keyed.items():
        if key not in existing:
            data = asdict(item)
            data.pop("event_id")
            db.add(Transfer(id=key, address=address, block=item.block, data=data))
    db.flush()


async def scan_monitor(factory, provider, address, settings):
    """Only one collector may call this at a time; run_once holds a Postgres advisory lock."""
    head, head_hash = await provider.safe_head()
    with factory() as db:
        monitor = db.get(Monitor, address)
        if monitor is None:
            return
        cursor, cursor_hash = monitor.cursor, monitor.cursor_hash
        candidates = {t.id: {**t.data, "block": t.block}
                      for t in db.scalars(select(Transfer).where(Transfer.address == address))}
    # Canonical hash mismatch: rebuild history and alerts rather than retain orphan evidence.
    reset = cursor is not None and (cursor > head or await provider.block_hash(cursor) != cursor_hash)
    history = None
    initialize = cursor is None or reset
    if initialize:
        cursor = max(0, head - settings.scan_blocks)
    if reset:
        candidates = {}
    end = min(head, cursor + settings.scan_blocks)
    expected_end_hash = head_hash if end == head else await provider.block_hash(end)
    if initialize:
        history = await provider.history(address, head)
    if end > cursor:
        result = await provider.scan(address, cursor + 1, end)
    else:
        from .provider import ScanResult
        result = ScanResult([], [])
    for item in (history.transfers if history is not None else []) + result.transfers:
        key = event_key(address, item.event_id)
        candidates.setdefault(key, asdict(item))
    proofs = await verify_references(provider, address, candidates)
    end_hash = await provider.block_hash(end)
    if end_hash != expected_end_hash:
        raise ProviderError("Chain changed during collection; retry without advancing the cursor")
    with factory.begin() as db:
        monitor = db.get(Monitor, address)
        if monitor is None:
            return
        if reset:
            db.execute(delete(Alert).where(Alert.address == address))
            db.execute(delete(Transfer).where(Transfer.address == address))
        if history is not None:
            persist_transfers(db, address, history.transfers)
            monitor.history_partial = history.partial
            monitor.coverage_start = cursor + 1
        persist_transfers(db, address, result.transfers)
        for key, verification in proofs.items():
            row = db.get(Transfer, key)
            if row is not None:
                row.data = {**row.data, "recipient_verification": verification}
        db.flush()
        stored = db.scalars(select(Transfer).where(Transfer.address == address).order_by(Transfer.block)).all()
        # Token references require independent evidence of direct recipient intent.
        earliest = {}
        for transfer in stored:
            t = transfer.data
            kind = reference_kind(t, address)
            if kind:
                earliest.setdefault(t["to_address"], (transfer.block, kind))
        references = [(block, recipient, kind) for recipient, (block, kind) in earliest.items()]
        previous_alerts = db.scalars(select(Alert).where(Alert.address == address)).all()
        existing_alerts = {a.id for a in previous_alerts}
        observed_patterns = {
            (a.data.get("tx_hash"), a.data.get("evidence", {}).get("candidate"),
             a.data.get("evidence", {}).get("reference"),
             a.data.get("evidence", {}).get("direction", "incoming"))
            for a in previous_alerts if a.data.get("kind") == "lookalike"
        }
        current_ids = {event_key(address, t.event_id) for t in result.transfers}
        newly_verified = {candidates[key]["to_address"] for key, value in proofs.items()
                          if value == VERIFIED_TOKEN}
        full_index = ReferenceIndex(references)
        new_index = ReferenceIndex([ref for ref in references if ref[1] in newly_verified])
        # A delayed proof must still recover retained events after monitoring began.
        # Recheck outgoing zero events too, including records collected before this rule shipped.
        coverage_start = monitor.coverage_start if monitor.coverage_start is not None else cursor + 1
        migration_remaining = 100
        for row in stored:
            if row.block < coverage_start:
                continue
            t = row.data
            if t["to_address"] == address and t["from_address"] != address:
                candidate, direction = t["from_address"], "incoming"
            elif (t["category"] == "erc20" and t["from_address"] == address
                  and t["to_address"] != address and zero(t["value"])):
                candidate, direction = t["to_address"], "outgoing_token_event"
            else:
                continue
            full_review = row.id in current_ids
            if (direction == "outgoing_token_event" and not full_review
                    and t.get("lookalike_review_version") != 2 and migration_remaining):
                full_review = True
                migration_remaining -= 1
            index = full_index if full_review else new_index
            for previous_block, reference, kind in index.candidates(candidate):
                if previous_block >= row.block:
                    continue
                pattern = (t["tx_hash"], candidate, reference, direction)
                if pattern in observed_patterns:
                    continue
                alert = lookalike_alert(candidate, reference, direction=direction, reference_kind=kind)
                if alert is None:
                    continue
                alert["evidence"].update({"reference_block": previous_block,
                                          "token": t.get("token_address"),
                                          "event_value": t["value"]})
                key = event_key(address, row.id + ":lookalike:" + reference)
                if key not in existing_alerts:
                    existing_alerts.add(key)
                    observed_patterns.add(pattern)
                    db.add(Alert(id=key, address=address, block=row.block,
                                 data={**alert, "tx_hash": t["tx_hash"], "block": row.block,
                                       "timestamp": t.get("timestamp")}))
            if full_review and direction == "outgoing_token_event":
                row.data = {**row.data, "lookalike_review_version": 2}
        for approval in result.approvals:
            alert = approval_alert(approval)
            key = event_key(address, approval.event_id + ":approval")
            if alert and key not in existing_alerts:
                existing_alerts.add(key)
                db.add(Alert(id=key, address=address, block=approval.block,
                             data={**alert, "tx_hash": approval.tx_hash, "block": approval.block,
                                   "timestamp": approval.timestamp}))
        # Bounded retention protects the free database. The coverage flag exposes truncation.
        if len(stored) > 10000:
            db.execute(delete(Transfer).where(Transfer.id.in_([t.id for t in stored[:-10000]])))
            monitor.history_partial = True
        db.flush()
        old_alerts = select(Alert.id).where(Alert.address == address).order_by(Alert.block.desc()).offset(1000)
        db.execute(delete(Alert).where(Alert.id.in_(old_alerts)))
        monitor.cursor, monitor.cursor_hash = end, end_hash
        monitor.last_checked, monitor.error = time.time(), None
        monitor.status = "monitoring" if end == head else "catching_up"


def cleanup(factory, session_days):
    with factory.begin() as db:
        if db.bind.dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(84530018)"))
        db.execute(delete(BrowserSession).where(BrowserSession.touched < time.time() - session_days * 86400))
        db.execute(delete(Monitor).where(~Monitor.address.in_(select(Watch.address))))


async def run_once(factory, provider, settings):
    engine = factory.kw["bind"]
    # Transaction-level lock also works through Neon transaction pooling.
    with engine.begin() as lock_connection:
        locked = False
        if engine.dialect.name == "postgresql":
            locked = bool(lock_connection.scalar(text("SELECT pg_try_advisory_xact_lock(84530017)")))
            if not locked:
                return {"processed": 0, "busy": True}
        try:
            cleanup(factory, settings.session_days)
            with factory() as db:
                addresses = list(db.scalars(select(Monitor.address).order_by(Monitor.last_checked.asc().nullsfirst())))
            processed = 0
            for address in addresses:
                try:
                    await asyncio.wait_for(
                        scan_monitor(factory, provider, address, settings),
                        timeout=settings.collector_budget_seconds * 0.85 / max(1, len(addresses)),
                    )
                    processed += 1
                except (ProviderError, TimeoutError):
                    with factory.begin() as db:
                        monitor = db.get(Monitor, address)
                        if monitor:
                            monitor.status = "error"
                            monitor.error = "Chain data unavailable. Previously stored observations may be out of date."
                    logger.warning("Provider scan failed; cursor preserved")
            return {"processed": processed, "busy": False}
        finally:
            pass  # The transaction releases the collector lock on exit.


async def main(once=False):
    settings = get_settings()
    if not settings.alchemy_key:
        raise SystemExit("Set SEMBLANCE_ALCHEMY_KEY to start live monitoring")
    engine, factory = database(settings.database_url)
    provider = BaseProvider(settings.alchemy_key)
    try:
        while True:
            print(await run_once(factory, provider, settings), flush=True)
            if once:
                break
            await asyncio.sleep(settings.poll_seconds)
    finally:
        await provider.aclose()
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.once))
