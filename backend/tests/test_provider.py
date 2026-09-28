import json

import httpx
import pytest

from semblance.provider import (
    APPROVAL_TOPIC,
    MAX_UINT256,
    BaseProvider,
    ProviderError,
)


A = "0x" + "a" * 40
B = "0x" + "b" * 40
C = "0x" + "c" * 40
TX = "0x" + "d" * 64
BLOCK_HASH = "0x" + "e" * 64


def transfer(uid="one", block="0x10"):
    return {
        "uniqueId": uid, "hash": TX, "blockNum": block,
        "from": A, "to": B, "category": "erc20", "asset": "USDC",
        "rawContract": {"value": "0xff", "address": C, "decimal": "0x6"},
        "metadata": {"blockTimestamp": "2026-09-27T00:00:00Z"},
    }


def approval(value=MAX_UINT256, index="0x0"):
    return {
        "address": C, "transactionHash": TX, "blockNumber": "0x10",
        "logIndex": index, "data": hex(value),
        "topics": [APPROVAL_TOPIC, "0x" + "0" * 24 + A[2:], "0x" + "0" * 24 + B[2:]],
    }


def provider(handler, **kwargs):
    return BaseProvider("SECRET-KEY", httpx.MockTransport(handler), **kwargs)


@pytest.mark.asyncio
async def test_safe_head_and_wrong_chain():
    def handler(req):
        assert req.url.path == "/v2/SECRET-KEY"
        method = json.loads(req.content)["method"]
        if method == "eth_chainId":
            return httpx.Response(200, json={"result": "0x2105"})
        return httpx.Response(200, json={"result": {"number": "0x10", "hash": BLOCK_HASH}})
    p = provider(handler)
    assert await p.safe_head() == (16, BLOCK_HASH)
    assert await p.block_hash(16) == BLOCK_HASH
    await p.aclose()
    p = provider(lambda req: httpx.Response(200, json={"result": "0x1"}))
    with pytest.raises(ProviderError, match="Wrong chain"):
        await p.safe_head()
    await p.aclose()


@pytest.mark.asyncio
async def test_history_bounds_and_partial_deduplication():
    calls = []
    def handler(req):
        body = json.loads(req.content)
        if body["method"] == "eth_chainId":
            return httpx.Response(200, json={"result": "0x2105"})
        params = body["params"][0]
        calls.append(params)
        if "fromAddress" in params:
            key = params.get("pageKey")
            result = {"transfers": [transfer("two" if key else "one")], "pageKey": "next2" if key else "next"}
        else:
            result = {"transfers": [transfer("one")], "pageKey": ""}
        return httpx.Response(200, json={"result": result})
    p = provider(handler, max_history_pages=2)
    result = await p.history(A, 16)
    assert result.partial is True
    assert {t.event_id for t in result.transfers} == {"one", "two"}
    assert result.transfers[0].value == "0.000255"
    assert len(calls) == 3
    assert all(c["order"] == "desc" and c["excludeZeroValue"] is False for c in calls)
    await p.aclose()


@pytest.mark.asyncio
async def test_scan_chunks_logs_and_reads_max_allowance():
    ranges = []
    def handler(req):
        body = json.loads(req.content)
        method = body["method"]
        if method == "eth_chainId":
            result = "0x2105"
        elif method == "alchemy_getAssetTransfers":
            result = {"transfers": [], "pageKey": ""}
        elif method == "eth_getLogs":
            params = body["params"][0]
            ranges.append((int(params["fromBlock"], 16), int(params["toBlock"], 16)))
            result = [approval()] if len(ranges) == 1 else []
        elif method == "eth_call":
            assert body["params"][1] == "0x10"
            result = hex(MAX_UINT256)
        return httpx.Response(200, json={"result": result})
    p = provider(handler)
    result = await p.scan(A, 16, 36)
    assert ranges == [(16, 25), (26, 35), (36, 36)]
    assert len(result.approvals) == 1
    assert result.approvals[0].verification == "verified"
    assert result.approvals[0].allowance == str(MAX_UINT256)
    await p.aclose()


@pytest.mark.asyncio
async def test_failed_allowance_is_explicitly_unverified():
    def handler(req):
        method = json.loads(req.content)["method"]
        if method == "eth_chainId":
            result = "0x2105"
        elif method == "alchemy_getAssetTransfers":
            result = {"transfers": []}
        elif method == "eth_getLogs":
            result = [approval()]
        else:
            return httpx.Response(200, json={"error": {"message": "SECRET-KEY"}})
        return httpx.Response(200, json={"result": result})
    p = provider(handler)
    result = await p.scan(A, 16, 16)
    assert result.approvals[0].verification == "unverified"
    assert result.approvals[0].allowance is None
    await p.aclose()


@pytest.mark.asyncio
async def test_scan_transfer_failure_never_returns_partial_data_or_secret():
    def handler(req):
        method = json.loads(req.content)["method"]
        if method == "eth_chainId":
            return httpx.Response(200, json={"result": "0x2105"})
        return httpx.Response(429, text="SECRET-KEY")
    p = provider(handler)
    with pytest.raises(ProviderError) as exc:
        await p.scan(A, 16, 16)
    assert "SECRET-KEY" not in str(exc.value)
    await p.aclose()


@pytest.mark.asyncio
async def test_non_erc20_approval_ignored():
    def handler(req):
        method = json.loads(req.content)["method"]
        if method == "eth_chainId":
            result = "0x2105"
        elif method == "alchemy_getAssetTransfers":
            result = {"transfers": []}
        else:
            item = approval()
            item["topics"].append("0x" + "0" * 64)
            result = [item]
        return httpx.Response(200, json={"result": result})
    p = provider(handler)
    assert (await p.scan(A, 16, 16)).approvals == []
    await p.aclose()


@pytest.mark.asyncio
async def test_scan_paginates_all_transfers_before_returning():
    calls = []
    def handler(req):
        body = json.loads(req.content)
        if body["method"] == "eth_chainId":
            result = "0x2105"
        elif body["method"] == "alchemy_getAssetTransfers":
            params = body["params"][0]
            calls.append(params)
            if "fromAddress" in params and "pageKey" not in params:
                result = {"transfers": [transfer("one")], "pageKey": "more"}
            elif "fromAddress" in params:
                result = {"transfers": [transfer("two")], "pageKey": ""}
            else:
                result = {"transfers": [transfer("one")], "pageKey": ""}
        else:
            result = []
        return httpx.Response(200, json={"result": result})
    p = provider(handler)
    result = await p.scan(A, 16, 16)
    assert {t.event_id for t in result.transfers} == {"one", "two"}
    assert len(calls) == 3
    await p.aclose()


@pytest.mark.asyncio
async def test_malformed_response_fails_closed():
    def handler(req):
        method = json.loads(req.content)["method"]
        if method == "eth_chainId":
            return httpx.Response(200, json={"result": "0x2105"})
        return httpx.Response(200, json={"result": {"transfers": "bad"}})
    p = provider(handler)
    with pytest.raises(ProviderError, match="Invalid provider response"):
        await p.scan(A, 16, 16)
    await p.aclose()


@pytest.mark.asyncio
async def test_timeout_retries_bounded_and_redacted():
    count = 0
    def handler(req):
        nonlocal count
        count += 1
        raise httpx.ReadTimeout("SECRET-KEY", request=req)
    p = provider(handler)
    with pytest.raises(ProviderError) as exc:
        await p.safe_head()
    assert count == 3
    assert "SECRET-KEY" not in str(exc.value)
    await p.aclose()


def test_transfer_decimals_are_exact_display_units():
    native = transfer()
    native["category"] = "external"
    native["asset"] = "ETH"
    native["rawContract"] = {"value": hex(10**18), "address": None}
    parsed = BaseProvider._transfer(native)
    assert parsed.value == "1"
    assert parsed.asset == "ETH"
    native["rawContract"]["value"] = "0x0"
    assert BaseProvider._transfer(native).value == "0"

    token = transfer()
    token["rawContract"] = {"value": hex(123456789), "decimal": "0x6", "address": C}
    parsed = BaseProvider._transfer(token)
    assert parsed.value == "123.456789"
    assert parsed.asset == "USDC"


def test_unknown_token_decimals_explicitly_mark_raw_units():
    token = transfer()
    token["rawContract"] = {"value": "0xff", "address": C, "decimal": None}
    parsed = BaseProvider._transfer(token)
    assert parsed.value == "255"
    assert parsed.asset == "USDC (raw units)"


def test_high_precision_decimals_do_not_round():
    token = transfer()
    token["rawContract"] = {"value": hex(2**256 - 1), "decimal": "0xff", "address": C}
    parsed = BaseProvider._transfer(token)
    assert parsed.value.startswith("0.")
    assert len(parsed.value.split(".")[1]) == 255
    assert parsed.value[2:].lstrip("0") == str(2**256 - 1)


@pytest.mark.parametrize("decimal", ["18", "0x100", "0xnope", -1, 18])
def test_malformed_raw_decimals_rejected(decimal):
    token = transfer()
    token["rawContract"] = {"value": "0xff", "decimal": decimal, "address": C}
    with pytest.raises(ProviderError, match="Invalid provider response"):
        BaseProvider._transfer(token)


@pytest.mark.parametrize("raw_value", [None, "255", "0xnothex", -1])
def test_malformed_raw_values_rejected(raw_value):
    token = transfer()
    token["rawContract"] = {"value": raw_value, "decimal": "0x6", "address": C}
    with pytest.raises(ProviderError, match="Invalid provider response"):
        BaseProvider._transfer(token)


def test_erc20_contract_identity_survives_symbol_collision():
    first = transfer("first")
    second = transfer("second")
    second["rawContract"]["address"] = B.upper().replace("0X", "0x")
    first_record = BaseProvider._transfer(first)
    second_record = BaseProvider._transfer(second)
    assert first_record.asset == second_record.asset == "USDC"
    assert first_record.token_address == C
    assert second_record.token_address == B
    assert first_record.token_address != second_record.token_address


def test_native_transfer_has_no_token_contract():
    native = transfer()
    native["category"] = "external"
    native["rawContract"] = {"value": "0x1", "address": C, "decimal": "0x12"}
    assert BaseProvider._transfer(native).token_address is None


@pytest.mark.parametrize("contract", [None, "0x123", "not-an-address", 17])
def test_erc20_without_valid_contract_identity_rejected(contract):
    token = transfer()
    token["rawContract"]["address"] = contract
    with pytest.raises(ProviderError, match="Invalid chain address"):
        BaseProvider._transfer(token)
