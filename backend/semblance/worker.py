"""A single read-only collector; observations and cursor commit together."""
import argparse
import asyncio
import hashlib
import logging
import time
from dataclasses import asdict
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, select, text

from .config import get_settings
from .db import Alert, BrowserSession, Monitor, Transfer, Watch, database
from .domain import approval_alert, lookalike_alert
from .provider import BaseProvider, ProviderError

logger = logging.getLogger(__name__)


def event_key(address, event_id):
    return hashlib.sha256(f"{address}:{event_id}".encode()).hexdigest()


def positive(value):
    try:
        return Decimal(value) > 0
    except (InvalidOperation, TypeError):
        return False


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
    # Canonical hash mismatch: rebuild history and alerts rather than retain orphan evidence.
    reset = cursor is not None and (cursor > head or await provider.block_hash(cursor) != cursor_hash)
    history = None
    initialize = cursor is None or reset
    if initialize:
        cursor = max(0, head - settings.scan_blocks)
    end = min(head, cursor + settings.scan_blocks)
    expected_end_hash = head_hash if end == head else await provider.block_hash(end)
    if initialize:
        history = await provider.history(address, head)
    if end > cursor:
        result = await provider.scan(address, cursor + 1, end)
    else:
        from .provider import ScanResult
        result = ScanResult([], [])
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
        stored = db.scalars(select(Transfer).where(Transfer.address == address).order_by(Transfer.block)).all()
        # Native transfers establish references; token contracts can emit forged Transfer events.
        earliest = {}
        for transfer in stored:
            t = transfer.data
            if t["from_address"] == address and t["category"] == "external" and positive(t["value"]):
                earliest.setdefault(t["to_address"], transfer.block)
        references = [(block, recipient) for recipient, block in earliest.items()]
        existing_alerts = set(db.scalars(select(Alert.id).where(Alert.address == address)))
        for transfer in result.transfers:
            if transfer.to_address != address or transfer.from_address == address:
                continue
            for previous_block, reference in references:
                if previous_block >= transfer.block:
                    continue
                alert = lookalike_alert(transfer.from_address, reference)
                if alert is None:
                    continue
                key = event_key(address, transfer.event_id + ":lookalike:" + reference)
                if key not in existing_alerts:
                    existing_alerts.add(key)
                    db.add(Alert(id=key, address=address, block=transfer.block,
                                 data={**alert, "tx_hash": transfer.tx_hash, "block": transfer.block,
                                       "timestamp": transfer.timestamp}))
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
