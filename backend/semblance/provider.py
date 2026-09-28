"""Read-only Base chain data adapter. Never logs or returns provider credentials."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Any

import httpx


BASE_CHAIN_ID = 8453
MAX_UINT256 = 2**256 - 1
APPROVAL_TOPIC = "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


class ProviderError(Exception):
    """A sanitized, public-facing provider failure."""


@dataclass(frozen=True)
class TransferRecord:
    event_id: str
    tx_hash: str
    block: int
    timestamp: str | None
    from_address: str
    to_address: str
    value: str
    asset: str
    category: str
    token_address: str | None = None


@dataclass(frozen=True)
class ApprovalRecord:
    event_id: str
    tx_hash: str
    block: int
    timestamp: str | None
    owner: str
    spender: str
    token: str
    value: str
    allowance: str | None
    verification: str


@dataclass(frozen=True)
class HistoryResult:
    transfers: list[TransferRecord]
    partial: bool


@dataclass(frozen=True)
class ScanResult:
    transfers: list[TransferRecord]
    approvals: list[ApprovalRecord]


def _address(value: str) -> str:
    if not isinstance(value, str) or not ADDRESS_RE.fullmatch(value):
        raise ProviderError("Invalid chain address")
    return value.lower()


def _hash(value: str) -> str:
    if not isinstance(value, str) or not HASH_RE.fullmatch(value):
        raise ProviderError("Invalid provider response")
    return value.lower()


def _hex_int(value: Any) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]+", value):
        raise ProviderError("Invalid provider response")
    return int(value, 16)


def _topic_address(value: str) -> str:
    return "0x" + "0" * 24 + _address(value)[2:]


class BaseProvider:
    def __init__(
        self,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
        max_history_pages: int = 3,
    ) -> None:
        if not api_key or not isinstance(api_key, str):
            raise ValueError("Alchemy API key required")
        if max_history_pages < 1:
            raise ValueError("max_history_pages must be positive")
        self._client = httpx.AsyncClient(
            base_url="https://base-mainnet.g.alchemy.com",
            transport=transport,
            timeout=10.0,
        )
        self._path = f"/v2/{api_key}"
        self._max_history_pages = max_history_pages
        self._chain_checked = False

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _rpc(self, method: str, params: list[Any]) -> Any:
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        for attempt in range(3):
            try:
                response = await self._client.post(self._path, json=body)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 2:
                        await asyncio.sleep(0.1 * (2**attempt))
                        continue
                    raise ProviderError("Chain data temporarily unavailable")
                if response.status_code >= 400:
                    raise ProviderError("Chain data unavailable")
                payload = response.json()
            except ProviderError:
                raise
            except (httpx.RequestError, ValueError, TypeError):
                if attempt < 2:
                    await asyncio.sleep(0.1 * (2**attempt))
                    continue
                raise ProviderError("Chain data temporarily unavailable") from None
            if not isinstance(payload, dict) or "error" in payload or "result" not in payload:
                raise ProviderError("Invalid provider response")
            return payload["result"]
        raise ProviderError("Chain data temporarily unavailable")

    async def _check_chain(self) -> None:
        if self._chain_checked:
            return
        chain_id = _hex_int(await self._rpc("eth_chainId", []))
        if chain_id != BASE_CHAIN_ID:
            raise ProviderError("Wrong chain returned by provider")
        self._chain_checked = True

    async def safe_head(self) -> tuple[int, str]:
        await self._check_chain()
        result = await self._rpc("eth_getBlockByNumber", ["safe", False])
        if not isinstance(result, dict):
            raise ProviderError("Invalid provider response")
        return _hex_int(result.get("number")), _hash(result.get("hash"))

    async def block_hash(self, number: int) -> str:
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise ProviderError("Invalid block number")
        await self._check_chain()
        result = await self._rpc("eth_getBlockByNumber", [hex(number), False])
        if not isinstance(result, dict) or _hex_int(result.get("number")) != number:
            raise ProviderError("Invalid provider response")
        return _hash(result.get("hash"))

    @staticmethod
    def _transfer(item: Any) -> TransferRecord:
        if not isinstance(item, dict):
            raise ProviderError("Invalid provider response")
        category = item.get("category")
        raw = item.get("rawContract")
        if category not in ("external", "erc20") or not isinstance(raw, dict):
            raise ProviderError("Invalid provider response")
        raw_value = _hex_int(raw.get("value"))
        raw_decimals = raw.get("decimal")
        if raw_decimals is None and category == "external":
            decimals = 18  # Base native ETH has 18 decimal places.
        elif raw_decimals is None:
            decimals = None
        else:
            decimals = _hex_int(raw_decimals)
            if decimals > 255:
                raise ProviderError("Invalid provider response")
        if decimals is None:
            value = str(raw_value)
        else:
            # Decimal's default 28-digit context could round large uint256 values.
            with localcontext() as context:
                context.prec = max(len(str(raw_value)), decimals) + 2
                value = format(Decimal(raw_value).scaleb(-decimals), "f")
                if "." in value:
                    value = value.rstrip("0").rstrip(".")
        tx_hash = _hash(item.get("hash"))
        event_id = item.get("uniqueId")
        if not isinstance(event_id, str) or not event_id:
            raise ProviderError("Invalid provider response")
        metadata = item.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ProviderError("Invalid provider response")
        timestamp = metadata.get("blockTimestamp")
        if timestamp is not None and not isinstance(timestamp, str):
            raise ProviderError("Invalid provider response")
        asset = item.get("asset")
        if not isinstance(asset, str):
            asset = ""
        token_address = _address(raw.get("address")) if category == "erc20" else None
        if decimals is None:
            asset = f"{asset or 'Token'} (raw units)"
        elif category == "external" and not asset:
            asset = "ETH"
        return TransferRecord(
            event_id=event_id,
            tx_hash=tx_hash,
            block=_hex_int(item.get("blockNum")),
            timestamp=timestamp,
            from_address=_address(item.get("from")),
            to_address=_address(item.get("to")),
            value=value,
            asset=asset,
            category=category,
            token_address=token_address,
        )

    async def _transfers(
        self, address: str, start: int, end: int, *, page_limit: int | None, order: str
    ) -> tuple[list[TransferRecord], bool]:
        collected: dict[str, TransferRecord] = {}
        partial = False
        for direction in ("fromAddress", "toAddress"):
            page_key: str | None = None
            pages = 0
            seen_keys: set[str] = set()
            while True:
                params: dict[str, Any] = {
                    "fromBlock": hex(start), "toBlock": hex(end),
                    direction: address, "category": ["external", "erc20"],
                    "excludeZeroValue": False, "withMetadata": True,
                    "maxCount": "0x3e8", "order": order,
                }
                if page_key:
                    params["pageKey"] = page_key
                result = await self._rpc("alchemy_getAssetTransfers", [params])
                if not isinstance(result, dict) or not isinstance(result.get("transfers"), list):
                    raise ProviderError("Invalid provider response")
                for item in result["transfers"]:
                    transfer = self._transfer(item)
                    if not start <= transfer.block <= end:
                        raise ProviderError("Invalid provider response")
                    collected[transfer.event_id] = transfer
                pages += 1
                page_key = result.get("pageKey") or None
                if page_key is not None and (not isinstance(page_key, str) or page_key in seen_keys):
                    raise ProviderError("Invalid provider response")
                if not page_key:
                    break
                if page_limit is not None and pages >= page_limit:
                    partial = True
                    break
                if pages >= 1000:
                    raise ProviderError("Chain scan exceeds page limit")
                seen_keys.add(page_key)
        return list(collected.values()), partial

    async def history(self, address: str, through_block: int) -> HistoryResult:
        address = _address(address)
        if isinstance(through_block, bool) or not isinstance(through_block, int) or through_block < 0:
            raise ProviderError("Invalid block number")
        await self._check_chain()
        transfers, partial = await self._transfers(
            address, 0, through_block, page_limit=self._max_history_pages, order="desc"
        )
        transfers.sort(key=lambda t: (t.block, t.event_id), reverse=True)
        return HistoryResult(transfers, partial)

    async def _allowance(self, token: str, owner: str, spender: str, block: int) -> tuple[str | None, str]:
        call_data = "0xdd62ed3e" + _topic_address(owner)[2:] + _topic_address(spender)[2:]
        try:
            result = await self._rpc("eth_call", [{"to": token, "data": call_data}, hex(block)])
            if not isinstance(result, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", result):
                raise ProviderError("Invalid provider response")
            return str(int(result, 16)), "verified"
        except ProviderError:
            return None, "unverified"

    async def scan(self, address: str, start: int, end: int) -> ScanResult:
        address = _address(address)
        if (
            isinstance(start, bool) or isinstance(end, bool)
            or not isinstance(start, int) or not isinstance(end, int)
            or start < 0 or end < start
        ):
            raise ProviderError("Invalid block range")
        await self._check_chain()
        transfers, _ = await self._transfers(address, start, end, page_limit=None, order="asc")
        approvals: dict[str, ApprovalRecord] = {}
        for first in range(start, end + 1, 10):
            last = min(first + 9, end)
            logs = await self._rpc("eth_getLogs", [{
                "fromBlock": hex(first), "toBlock": hex(last),
                "topics": [APPROVAL_TOPIC, _topic_address(address)],
            }])
            if not isinstance(logs, list):
                raise ProviderError("Invalid provider response")
            for log in logs:
                if not isinstance(log, dict) or log.get("removed") is True:
                    continue
                topics = log.get("topics")
                if not isinstance(topics, list) or len(topics) != 3:
                    continue  # ERC-721 Approval has four topics.
                if not all(isinstance(topic, str) and HASH_RE.fullmatch(topic) for topic in topics):
                    raise ProviderError("Invalid provider response")
                if topics[0].lower() != APPROVAL_TOPIC or topics[1].lower() != _topic_address(address):
                    continue
                token = _address(log.get("address"))
                spender_topic = topics[2]
                if not isinstance(spender_topic, str) or not HASH_RE.fullmatch(spender_topic) or not spender_topic[2:26] == "0" * 24:
                    raise ProviderError("Invalid provider response")
                spender = _address("0x" + spender_topic[-40:])
                value = _hex_int(log.get("data"))
                block = _hex_int(log.get("blockNumber"))
                if not first <= block <= last:
                    raise ProviderError("Invalid provider response")
                tx_hash = _hash(log.get("transactionHash"))
                log_index = _hex_int(log.get("logIndex"))
                event_id = f"{tx_hash}:{log_index}"
                allowance: str | None = str(value)
                verification = "event_only"
                if value == MAX_UINT256:
                    allowance, verification = await self._allowance(token, address, spender, block)
                approvals[event_id] = ApprovalRecord(
                    event_id, tx_hash, block, None, address, spender, token,
                    str(value), allowance, verification,
                )
        transfers.sort(key=lambda t: (t.block, t.event_id))
        return ScanResult(transfers, sorted(approvals.values(), key=lambda a: (a.block, a.event_id)))
