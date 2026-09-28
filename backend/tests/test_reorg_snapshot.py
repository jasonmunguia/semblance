"""Reject observations collected across two different canonical chain snapshots."""

import pytest
from sqlalchemy import select

from semblance.config import Settings
from semblance.db import Alert, BrowserSession, Monitor, Transfer, Watch, database
from semblance.provider import HistoryResult, ProviderError, ScanResult, TransferRecord
from semblance.worker import scan_monitor


WALLET = "0x" + "a" * 40
RECIPIENT = "0x" + "b" * 40
OLD_HASH = "0x" + "1" * 64
NEW_HASH = "0x" + "2" * 64
CURSOR_HASH = "0x" + "9" * 64


class ReorgDuringScan:
    def __init__(self, head, end):
        self.head = head
        self.end = end
        self.reorganized = False

    async def safe_head(self):
        return self.head, NEW_HASH if self.reorganized else OLD_HASH

    async def block_hash(self, number):
        if number == 90:
            return CURSOR_HASH
        return NEW_HASH if self.reorganized else OLD_HASH

    async def history(self, address, through_block):
        return HistoryResult([], False)

    async def scan(self, address, start, end):
        assert end == self.end
        if self.reorganized:
            return ScanResult([], [])
        # The data request saw the old chain, but the next hash read sees its replacement.
        self.reorganized = True
        orphan = TransferRecord(
            "orphan-event", OLD_HASH, end, None, WALLET, RECIPIENT, "1", "ETH", "external"
        )
        return ScanResult([orphan], [])


@pytest.mark.asyncio
@pytest.mark.parametrize("cursor,head,end", [(None, 100, 100), (90, 100, 100), (90, 200, 120)])
async def test_reorg_during_scan_preserves_cursor_and_rejects_orphans(tmp_path, cursor, head, end):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'snapshot.sqlite'}", scan_blocks=30)
    engine, factory = database(settings.database_url)
    try:
        with factory.begin() as db:
            db.add(BrowserSession(id="snapshot-session"))
            db.add(Monitor(address=WALLET, cursor=cursor, cursor_hash=CURSOR_HASH if cursor else None))
            db.flush()
            db.add(Watch(session_id="snapshot-session", address=WALLET, label="Watched wallet"))
            if cursor is not None:
                db.add(Transfer(id="previous-transfer", address=WALLET, block=80, data={
                    "from_address": WALLET, "to_address": RECIPIENT,
                    "category": "external", "value": "1",
                }))
                db.add(Alert(id="previous-alert", address=WALLET, block=80, data={"kind": "lookalike"}))

        provider = ReorgDuringScan(head, end)
        with pytest.raises(ProviderError, match="Chain changed during collection"):
            await scan_monitor(factory, provider, WALLET, settings)

        with factory() as db:
            monitor = db.get(Monitor, WALLET)
            assert monitor.cursor == cursor
            assert monitor.cursor_hash == (CURSOR_HASH if cursor else None)
            assert monitor.last_checked is None
            assert monitor.coverage_start is None
            expected_transfers = ["previous-transfer"] if cursor is not None else []
            expected_alerts = ["previous-alert"] if cursor is not None else []
            assert list(db.scalars(select(Transfer.id))) == expected_transfers
            assert list(db.scalars(select(Alert.id))) == expected_alerts

        # A later coherent snapshot can advance without recovering the rejected orphan.
        await scan_monitor(factory, provider, WALLET, settings)
        with factory() as db:
            monitor = db.get(Monitor, WALLET)
            assert monitor.cursor == end
            assert monitor.cursor_hash == NEW_HASH
            assert monitor.status == ("monitoring" if end == head else "catching_up")
            assert list(db.scalars(select(Transfer.id))) == expected_transfers
            assert list(db.scalars(select(Alert.id))) == expected_alerts
    finally:
        engine.dispose()
