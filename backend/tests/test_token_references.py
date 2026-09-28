"""Recipient intent requires a wallet-authored call and its matching receipt."""

import json

import httpx
import pytest
from eth_utils import keccak

from semblance.provider import BaseProvider
from semblance.references import VERIFIED_TOKEN


WALLET = "0x" + "11" * 20
RECIPIENT = "0x" + "22" * 20
TOKEN = "0x" + "33" * 20
ATTACKER = "0x" + "44" * 20
TX = "0x" + "55" * 32
BLOCK = "0x" + "66" * 32
OTHER_HASH = "0x" + "77" * 32
AMOUNT = 1_250_000


@pytest.fixture
def evidence():
    # Derive the Ethereum event signature independently of production constants.
    topic = "0x" + keccak(text="Transfer(address,address,uint256)").hex()
    calldata = "0xa9059cbb" + RECIPIENT[2:].rjust(64, "0") + f"{AMOUNT:064x}"
    data = {
        "category": "erc20", "from_address": WALLET, "to_address": RECIPIENT,
        "value": "1.25", "raw_value": str(AMOUNT), "token_address": TOKEN,
        "tx_hash": TX, "block": 100,
    }
    tx = {
        "hash": TX, "from": WALLET, "to": TOKEN, "input": calldata,
        "blockNumber": "0x64", "blockHash": BLOCK,
    }
    log = {
        "address": TOKEN, "transactionHash": TX, "blockNumber": "0x64",
        "blockHash": BLOCK, "logIndex": "0x0", "removed": False,
        "topics": [topic, "0x" + WALLET[2:].rjust(64, "0"),
                   "0x" + RECIPIENT[2:].rjust(64, "0")],
        "data": "0x" + f"{AMOUNT:064x}",
    }
    receipt = {
        "status": "0x1", "transactionHash": TX, "blockNumber": "0x64",
        "blockHash": BLOCK, "logs": [log],
    }
    return data, tx, receipt


async def verify(evidence):
    data, tx, receipt = evidence
    responses = {"eth_getTransactionByHash": tx, "eth_getTransactionReceipt": receipt}

    def handler(request):
        body = json.loads(request.content)
        assert body["params"] == [TX]
        return httpx.Response(200, json={"result": responses[body["method"]]})

    provider = BaseProvider("test-key", transport=httpx.MockTransport(handler))
    try:
        return await provider.verify_token_reference(data, WALLET)
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_wallet_authored_transfer_and_matching_receipt_prove_recipient(evidence):
    assert await verify(evidence) == VERIFIED_TOKEN


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "forged_sender", "wrong_call_token", "failed_receipt", "missing_log",
    "wrong_log_token", "wrong_event_signature", "wrong_event_sender",
    "wrong_event_recipient", "wrong_event_amount", "wrong_indexer_amount",
    "wrong_call_recipient", "removed_log", "noncanonical_address_padding",
    "trailing_calldata", "truncated_calldata", "wrong_method", "zero_amount",
])
async def test_untrusted_or_nonmatching_transfer_cannot_become_reference(evidence, case):
    data, tx, receipt = evidence
    log = receipt["logs"][0]
    if case == "forged_sender":
        # A malicious token can emit a Transfer claiming someone else's wallet sent it.
        tx["from"] = ATTACKER
    elif case == "wrong_call_token":
        tx["to"] = ATTACKER
    elif case == "failed_receipt":
        receipt["status"] = "0x0"
    elif case == "missing_log":
        receipt["logs"] = []
    elif case == "wrong_log_token":
        log["address"] = ATTACKER
    elif case == "wrong_event_signature":
        log["topics"][0] = "0x" + keccak(text="Approval(address,address,uint256)").hex()
    elif case == "wrong_event_sender":
        log["topics"][1] = "0x" + ATTACKER[2:].rjust(64, "0")
    elif case == "wrong_event_recipient":
        log["topics"][2] = "0x" + ATTACKER[2:].rjust(64, "0")
    elif case == "wrong_event_amount":
        log["data"] = "0x" + f"{AMOUNT + 1:064x}"
    elif case == "wrong_indexer_amount":
        data["raw_value"] = str(AMOUNT + 1)
    elif case == "wrong_call_recipient":
        tx["input"] = "0xa9059cbb" + ATTACKER[2:].rjust(64, "0") + f"{AMOUNT:064x}"
    elif case == "removed_log":
        log["removed"] = True
    elif case == "noncanonical_address_padding":
        tx["input"] = tx["input"][:10] + "1" + tx["input"][11:]
    elif case == "trailing_calldata":
        tx["input"] += "00"
    elif case == "truncated_calldata":
        tx["input"] = tx["input"][:-2]
    elif case == "wrong_method":
        tx["input"] = "0x095ea7b3" + tx["input"][10:]
    elif case == "zero_amount":
        tx["input"] = tx["input"][:-64] + "0" * 64
        log["data"] = "0x" + "0" * 64
        data["raw_value"] = "0"
    assert await verify(evidence) == "not_direct_transfer"


@pytest.mark.asyncio
@pytest.mark.parametrize("part,field,value", [
    ("tx", "hash", OTHER_HASH),
    ("receipt", "transactionHash", OTHER_HASH),
    ("tx", "blockNumber", "0x65"),
    ("receipt", "blockNumber", "0x65"),
    ("receipt", "blockHash", OTHER_HASH),
    ("log", "transactionHash", OTHER_HASH),
    ("log", "blockNumber", "0x65"),
    ("log", "blockHash", OTHER_HASH),
])
async def test_inconsistent_chain_snapshot_never_proves_reference(evidence, part, field, value):
    _, tx, receipt = evidence
    {"tx": tx, "receipt": receipt, "log": receipt["logs"][0]}[part][field] = value
    assert await verify(evidence) != VERIFIED_TOKEN


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["tx", "receipt"])
async def test_missing_chain_evidence_is_unavailable(evidence, missing):
    data, tx, receipt = evidence
    incomplete = (data, None if missing == "tx" else tx, None if missing == "receipt" else receipt)
    assert await verify(incomplete) == "unavailable"


@pytest.mark.asyncio
async def test_provider_error_is_unavailable_and_never_promotes_reference(evidence):
    def handler(_request):
        return httpx.Response(200, json={"error": {"message": "private provider detail"}})

    provider = BaseProvider("test-key", transport=httpx.MockTransport(handler))
    try:
        assert await provider.verify_token_reference(evidence[0], WALLET) == "unavailable"
    finally:
        await provider.aclose()
