"""Coverage regressions: verified intent, delayed proofs, and hostile token events."""
from dataclasses import asdict, replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from semblance.api import create_app
from semblance.config import Settings
from semblance.db import Alert, Monitor, Transfer, database
from semblance.references import ReferenceIndex, VERIFIED_TOKEN
from semblance.worker import scan_monitor, verify_references
from test_core import (
    WALLET, REFERENCE, LOOKALIKE, OTHER, TOKEN,
    FakeProvider, add_monitor, make_transfer,
)


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url=f"sqlite:///{tmp_path / 'coverage.sqlite'}", scan_blocks=30,
                    session_secret="coverage-test-session-secret-over-32-characters", alchemy_key="test-key")


@pytest.fixture
def storage(settings):
    engine, factory = database(settings.database_url)
    yield factory
    engine.dispose()


class IntentProvider(FakeProvider):
    verification = VERIFIED_TOKEN

    async def verify_token_reference(self, data, address):
        return self.verification


@pytest.mark.asyncio
async def test_verified_token_history_detects_both_directions_and_deduplicates(storage, settings):
    add_monitor(storage)
    reference = replace(make_transfer("reference", 60, WALLET, REFERENCE, category="erc20"),
                        token_address=TOKEN, raw_value="100")
    incoming = make_transfer("incoming", 80, LOOKALIKE, WALLET)
    outgoing = replace(make_transfer("outgoing", 81, WALLET, LOOKALIKE, value="0", category="erc20"),
                       token_address=TOKEN, raw_value="0")
    provider = IntentProvider([reference], [incoming, outgoing])
    await scan_monitor(storage, provider, WALLET, settings)
    provider.head = 101
    provider.scan_items = []
    await scan_monitor(storage, provider, WALLET, settings)
    with storage() as db:
        alerts = db.scalars(select(Alert)).all()
        assert len(alerts) == 2
        assert {a.data["evidence"]["direction"] for a in alerts} == {"incoming", "outgoing_token_event"}
        assert all(a.data["evidence"]["reference_kind"] == "verified_token_recipient" for a in alerts)
        outgoing_alert = next(a.data for a in alerts if a.data["evidence"]["direction"] == "outgoing_token_event")
        assert "do not prove you initiated" in outgoing_alert["explanation"]
        assert outgoing_alert["evidence"]["token"] == TOKEN


@pytest.mark.asyncio
async def test_delayed_proof_backfills_retained_events_without_rescanning_history(storage, settings):
    add_monitor(storage)
    reference = replace(make_transfer("reference", 60, WALLET, REFERENCE, category="erc20"), token_address=TOKEN)
    provider = IntentProvider([reference], [make_transfer("incoming", 80, LOOKALIKE, WALLET)])
    provider.verification = "unavailable"
    await scan_monitor(storage, provider, WALLET, settings)
    with storage() as db:
        assert db.scalars(select(Alert)).all() == []
        assert db.get(Monitor, WALLET).cursor == 100
    provider.verification = VERIFIED_TOKEN
    provider.head = 101
    provider.scan_items = []
    await scan_monitor(storage, provider, WALLET, settings)
    with storage() as db:
        assert len(db.scalars(select(Alert)).all()) == 1
    assert len([c for c in provider.calls if c[0] == "history"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reference_block, outgoing_value, expected", [(60, "0", 1), (81, "0", 0), (90, "0", 0), (60, "1", 0)])
async def test_zero_event_uses_only_strictly_earlier_references(storage, settings, reference_block, outgoing_value, expected):
    add_monitor(storage)
    reference = make_transfer("reference", reference_block, WALLET, REFERENCE)
    outgoing = make_transfer("zero", 81, WALLET, LOOKALIKE, value=outgoing_value, category="erc20")
    await scan_monitor(storage, FakeProvider([reference], [outgoing]), WALLET, settings)
    with storage() as db:
        assert len(db.scalars(select(Alert)).all()) == expected


@pytest.mark.parametrize("verification, status", [(VERIFIED_TOKEN, "lookalike"), ("not_direct_transfer", "insufficient_history"), ("unavailable", "insufficient_history")])
def test_api_token_references_require_proof(settings, verification, status):
    app = create_app(settings)
    with TestClient(app) as client:
        watch = client.post("/api/wallets", json={"address": WALLET}).json()
        ref = asdict(make_transfer("reference", 60, WALLET, REFERENCE, category="erc20"))
        ref["recipient_verification"] = verification
        with app.state.sessions.begin() as db:
            db.add(Transfer(id="reference", address=WALLET, block=60, data=ref))
        check = client.post("/api/check", json={"destination": LOOKALIKE, "wallet_id": watch["id"]})
        assert check.json()["status"] == status


@pytest.mark.asyncio
async def test_rejected_candidates_do_not_starve_older_references():
    provider = FakeProvider()
    candidates = {str(i): {**asdict(make_transfer(str(i), i, WALLET, OTHER, category="erc20")),
                          "tx_hash": "0x" + format(i, "064x")} for i in range(20)}
    first = await verify_references(provider, WALLET, candidates)
    assert len(first) == 12
    for key, outcome in first.items():
        candidates[key]["recipient_verification"] = outcome
    second = await verify_references(provider, WALLET, candidates)
    assert len(second) == 8 and not set(second).intersection(first)


@pytest.mark.asyncio
async def test_unavailable_reference_does_not_block_collection(storage, settings):
    add_monitor(storage)
    provider = IntentProvider([make_transfer("reference", 60, WALLET, REFERENCE, category="erc20")])
    provider.verification = "unavailable"
    await scan_monitor(storage, provider, WALLET, settings)
    with storage() as db:
        assert db.get(Monitor, WALLET).status == "monitoring"
        assert db.get(Monitor, WALLET).cursor == 100
        assert db.scalars(select(Alert)).all() == []


def test_reference_index_preserves_all_supported_similarity_shapes():
    import random
    from semblance.domain import compare_addresses

    rng = random.Random(8453)
    for _ in range(100):
        body = "".join(rng.choice("0123456789abcdef") for _ in range(40))
        reference = "0x" + body
        index = ReferenceIndex([(1, reference, "previous_recipient")])
        for count in (1, 2, 20):
            modified = list(body)
            eligible = range(4, 36) if count == 20 else range(40)
            for i in rng.sample(list(eligible), count):
                modified[i] = "f" if modified[i] != "f" else "e"
            candidate = "0x" + "".join(modified)
            assert compare_addresses(candidate, reference)["lookalike"]
            assert reference in [item[1] for item in index.candidates(candidate)]


@pytest.mark.asyncio
async def test_old_zero_event_migration_is_bounded_and_resumes(storage, settings):
    add_monitor(storage)
    history = [make_transfer("reference", 60, WALLET, REFERENCE)]
    history.extend(make_transfer(f"zero-{i}", 80, WALLET, LOOKALIKE, value="0", category="erc20")
                   for i in range(101))
    provider = FakeProvider(history)
    await scan_monitor(storage, provider, WALLET, settings)
    with storage() as db:
        rows = db.scalars(select(Transfer)).all()
        assert sum(t.data.get("lookalike_review_version") == 2 for t in rows) == 100
    provider.head = 101
    await scan_monitor(storage, provider, WALLET, settings)
    with storage() as db:
        rows = db.scalars(select(Transfer)).all()
        assert sum(t.data.get("lookalike_review_version") == 2 for t in rows) == 101
        assert len(db.scalars(select(Alert)).all()) == 1
