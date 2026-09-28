"""User-visible API and durable-monitor behavior against an isolated SQLite database."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from semblance.api import create_app
from semblance.config import Settings
from semblance.db import Alert, BrowserSession, Monitor, Transfer, Watch, database
from semblance.provider import ApprovalRecord, HistoryResult, ProviderError, ScanResult, TransferRecord
from semblance.worker import run_once, scan_monitor


WALLET = "0x" + "a" * 40
REFERENCE = "0x1234" + "5" * 32 + "abcd"
LOOKALIKE = "0x1234" + "6" * 32 + "abcd"
OTHER = "0x" + "b" * 40
TOKEN = "0x" + "c" * 40
SPENDER = "0x" + "d" * 40
TX = "0x" + "e" * 64
MAX = str(2**256 - 1)


@pytest.fixture
def settings(tmp_path):
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'state.sqlite'}",
        session_secret="test-session-secret-over-32-characters",
        alchemy_key="test-key",
        scan_blocks=30,
    )


@pytest.fixture
def storage(settings):
    engine, factory = database(settings.database_url)
    yield factory
    engine.dispose()


def make_transfer(uid, block, sender, recipient, value="1", category="external"):
    return TransferRecord(uid, TX, block, None, sender, recipient, value, "ETH", category)


def make_approval(uid, block, *, allowance=MAX, verification="verified"):
    return ApprovalRecord(uid, TX, block, None, WALLET, SPENDER, TOKEN, MAX, allowance, verification)


class FakeProvider:
    def __init__(self, history=None, scans=None, head=100):
        self.history_items = history or []
        self.scan_items = scans or []
        self.head = head
        self.hashes = {}
        self.fail_scan = False
        self.calls = []

    async def safe_head(self):
        return self.head, await self.block_hash(self.head)

    async def block_hash(self, number):
        return self.hashes.get(number, "0x" + format(number, "064x"))

    async def history(self, address, through_block):
        self.calls.append(("history", address, through_block))
        return HistoryResult(self.history_items, False)

    async def scan(self, address, start, end):
        self.calls.append(("scan", address, start, end))
        if self.fail_scan:
            raise ProviderError("Chain data unavailable")
        return ScanResult(self.scan_items, []) if not isinstance(self.scan_items, ScanResult) else self.scan_items


def add_monitor(factory):
    with factory.begin() as db:
        db.add(BrowserSession(id="test-session"))
        db.add(Monitor(address=WALLET))
        db.add(Watch(session_id="test-session", address=WALLET, label="Mine"))


def test_api_session_ownership_and_cookie_tampering(settings):
    app = create_app(settings)
    with TestClient(app) as alice, TestClient(app) as bob:
        wallet = alice.post("/api/wallets", json={"address": WALLET, "label": "Mine"})
        assert wallet.status_code == 201
        wallet_id = wallet.json()["id"]
        assert alice.cookies.get("semblance_session")
        assert "HttpOnly" in wallet.headers["set-cookie"]
        assert bob.get("/api/state").json()["wallets"] == []
        assert bob.delete(f"/api/wallets/{wallet_id}").status_code == 404
        assert bob.post("/api/check", json={"destination": OTHER, "wallet_id": wallet_id}).status_code == 404
        contact = alice.post("/api/trusted", json={"address": REFERENCE}).json()
        assert bob.delete(f"/api/trusted/{contact['id']}").status_code == 404
        alice.cookies.set("semblance_session", "tampered")
        assert alice.get("/api/state").json()["wallets"] == []
        assert alice.delete(f"/api/wallets/{wallet_id}").status_code == 404


def test_api_recipient_check_validation_and_language(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        no_history = client.post("/api/check", json={"destination": LOOKALIKE})
        assert no_history.status_code == 200
        assert no_history.json()["status"] == "insufficient_history"
        invalid = client.post("/api/check", json={"destination": "0x123"})
        assert invalid.status_code == 422
        mixed_bad = "0xAbCd" + "5" * 32 + "aBcD"
        assert client.post("/api/check", json={"destination": mixed_bad}).status_code == 422
        exact = client.post("/api/check", json={"destination": REFERENCE.upper().replace("0X", "0x"),
                                                 "reference_addresses": [REFERENCE]}).json()
        assert exact["status"] == "exact_match"
        assert "not a safety guarantee" in exact["action"]
        close = client.post("/api/check", json={"destination": LOOKALIKE,
                                                 "reference_addresses": [REFERENCE]}).json()
        assert close["status"] == "lookalike"
        assert close["matches"][0]["differing_indices"]
        far = client.post("/api/check", json={"destination": OTHER,
                                               "reference_addresses": [REFERENCE]}).json()
        assert far["status"] == "no_match"
        assert "Verify this recipient independently" in far["action"]
        assert "safety" in far["coverage_note"].lower()


def test_api_mutation_rejects_cross_site_origin(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post("/api/wallets", json={"address": WALLET},
                               headers={"Origin": "https://other.example"})
        assert response.status_code == 403
        assert client.get("/api/state").json()["wallets"] == []


@pytest.mark.asyncio
async def test_worker_initial_scan_deduplicates_and_alerts(storage, settings):
    add_monitor(storage)
    past = make_transfer("past", 60, WALLET, REFERENCE)
    incoming = make_transfer("incoming", 80, LOOKALIKE, WALLET)
    provider = FakeProvider([past], ScanResult([incoming, incoming], [make_approval("approval", 80)]))
    await scan_monitor(storage, provider, WALLET, settings)
    with storage() as db:
        monitor = db.get(Monitor, WALLET)
        assert (monitor.cursor, monitor.coverage_start, monitor.status) == (100, 71, "monitoring")
        assert len(db.scalars(select(Transfer)).all()) == 2
        alerts = db.scalars(select(Alert)).all()
        assert {a.data["kind"] for a in alerts} == {"lookalike", "unlimited_approval"}
        assert all("proof of fraud" in a.data.get("explanation", "") or
                   "does not prove an attack" in a.data.get("explanation", "") for a in alerts)
    await scan_monitor(storage, provider, WALLET, settings)
    with storage() as db:
        assert len(db.scalars(select(Transfer)).all()) == 2
        assert len(db.scalars(select(Alert)).all()) == 2


@pytest.mark.asyncio
async def test_failed_scan_preserves_cursor_and_observations(storage, settings):
    add_monitor(storage)
    provider = FakeProvider([make_transfer("past", 60, WALLET, REFERENCE)])
    await scan_monitor(storage, provider, WALLET, settings)
    provider.head = 105
    provider.fail_scan = True
    assert (await run_once(storage, provider, settings))["processed"] == 0
    with storage() as db:
        monitor = db.get(Monitor, WALLET)
        assert monitor.cursor == 100
        assert monitor.status == "error"
        assert len(db.scalars(select(Transfer)).all()) == 1


@pytest.mark.asyncio
async def test_reorg_purges_orphan_observations_and_rebuilds(storage, settings):
    add_monitor(storage)
    provider = FakeProvider([make_transfer("old", 60, WALLET, REFERENCE)])
    await scan_monitor(storage, provider, WALLET, settings)
    provider.head = 101
    provider.hashes[100] = "0x" + "f" * 64
    provider.history_items = [make_transfer("new", 90, WALLET, OTHER)]
    await scan_monitor(storage, provider, WALLET, settings)
    with storage() as db:
        assert db.get(Monitor, WALLET).cursor == 101
        transfers = db.scalars(select(Transfer)).all()
        assert len(transfers) == 1
        assert transfers[0].data["to_address"] == OTHER
    assert [call[0] for call in provider.calls].count("history") == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", [
    make_transfer("future", 95, WALLET, REFERENCE),
    make_transfer("zero", 60, WALLET, REFERENCE, value="0"),
    make_transfer("token", 60, WALLET, REFERENCE, category="erc20"),
])
async def test_worker_does_not_use_future_zero_or_token_outgoing_as_reference(storage, settings, reference):
    add_monitor(storage)
    incoming = make_transfer("incoming", 80, LOOKALIKE, WALLET)
    provider = FakeProvider([reference], [incoming])
    await scan_monitor(storage, provider, WALLET, settings)
    with storage() as db:
        assert db.scalars(select(Alert)).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("approval, expected", [
    (make_approval("verified", 80), "reported that allowance"),
    (make_approval("unverified", 80, allowance=None, verification="unverified"),
     "could not be confirmed"),
])
async def test_worker_approval_alert_preserves_verification_status(storage, settings, approval, expected):
    add_monitor(storage)
    provider = FakeProvider(scans=ScanResult([], [approval]))
    await scan_monitor(storage, provider, WALLET, settings)
    with storage() as db:
        alert = db.scalar(select(Alert))
        assert expected in alert.data["explanation"]
        assert alert.data["evidence"]["verification"] == approval.verification


@pytest.mark.parametrize("reference, expected_status", [
    (make_transfer("native", 60, WALLET, REFERENCE), "lookalike"),
    (make_transfer("token", 60, WALLET, REFERENCE, category="erc20"), "insufficient_history"),
    (make_transfer("zero", 60, WALLET, REFERENCE, value="0"), "insufficient_history"),
    (make_transfer("inbound", 60, REFERENCE, WALLET), "insufficient_history"),
])
def test_api_uses_only_positive_outgoing_native_recipients(settings, reference, expected_status):
    app = create_app(settings)
    with TestClient(app) as client:
        wallet = client.post("/api/wallets", json={"address": WALLET}).json()
        with app.state.sessions.begin() as db:
            db.add(Transfer(id=reference.event_id, address=WALLET, block=reference.block,
                            data={key: value for key, value in vars(reference).items() if key != "event_id"}))
        result = client.post("/api/check", json={"destination": LOOKALIKE,
                                                  "wallet_id": wallet["id"]})
        assert result.status_code == 200
        assert result.json()["status"] == expected_status


def test_confirmed_zero_allowance_is_distinct_from_failed_read():
    from semblance.domain import approval_alert

    zero = approval_alert(make_approval("zero", 80, allowance="0", verification="verified"))
    failed = approval_alert(make_approval("failed", 80, allowance=None, verification="unverified"))
    assert zero is not None
    assert failed is not None
    assert zero["explanation"] != failed["explanation"]
    assert "zero" in zero["explanation"].lower() or "0" in zero["explanation"]


def test_alert_acknowledgement_requires_wallet_ownership(settings):
    app = create_app(settings)
    with TestClient(app) as alice, TestClient(app) as bob:
        wallet = alice.post("/api/wallets", json={"address": WALLET}).json()
        with app.state.sessions.begin() as db:
            db.add(Alert(id="alert-owned-by-alice", address=WALLET, block=80,
                         data={"kind": "lookalike", "title": "Possible lookalike"}))
        assert bob.post("/api/alerts/alert-owned-by-alice/acknowledge").status_code == 404
        assert bob.get("/api/state").json()["alerts"] == []
        assert alice.post("/api/alerts/alert-owned-by-alice/acknowledge").status_code == 200
        shown = alice.get("/api/state").json()["alerts"]
        assert len(shown) == 1
        assert shown[0]["wallet_id"] == wallet["id"]
        assert shown[0]["acknowledged"] is True


def test_deleting_last_watch_releases_global_slot_without_provider(settings):
    settings.alchemy_key = ""
    settings.max_global_wallets = 1
    app = create_app(settings)
    with TestClient(app) as client:
        first = client.post("/api/wallets", json={"address": WALLET})
        assert first.status_code == 201
        assert first.json()["status"] == "unavailable"
        assert client.post("/api/wallets", json={"address": OTHER}).status_code == 409
        assert client.delete(f"/api/wallets/{first.json()['id']}").status_code == 200
        second = client.post("/api/wallets", json={"address": OTHER})
        assert second.status_code == 201
        assert [w["address"] for w in client.get("/api/state").json()["wallets"]] == [OTHER]


@pytest.mark.asyncio
async def test_one_wallet_timeout_does_not_starve_other_wallet(storage, settings):
    add_monitor(storage)
    with storage.begin() as db:
        db.add(Monitor(address=OTHER))
        db.add(Watch(session_id="test-session", address=OTHER, label="Other"))
    settings.collector_budget_seconds = 1

    class SlowWalletProvider(FakeProvider):
        async def history(self, address, through_block):
            if address == WALLET:
                await asyncio.sleep(2)
            return await super().history(address, through_block)

    result = await run_once(storage, SlowWalletProvider(), settings)
    assert result == {"processed": 1, "busy": False}
    with storage() as db:
        slow = db.get(Monitor, WALLET)
        later = db.get(Monitor, OTHER)
        assert slow.cursor is None and slow.status == "error"
        assert later.cursor == 100 and later.status == "monitoring"
