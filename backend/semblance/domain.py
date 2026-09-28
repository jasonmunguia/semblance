from eth_utils import is_address, is_checksum_address


MAX_ALLOWANCE = str(2**256 - 1)


def normalize_address(value: str) -> str:
    value = value.strip()
    if not value.startswith("0x") or not is_address(value):
        raise ValueError("Enter a complete 0x address with 40 hexadecimal characters")
    body = value[2:]
    if body != body.lower() and body != body.upper() and not is_checksum_address(value):
        raise ValueError("Mixed-case address has an invalid checksum; verify the original address")
    return value.lower()


def compare_addresses(candidate: str, reference: str) -> dict:
    a, b = normalize_address(candidate)[2:], normalize_address(reference)[2:]
    differences = [i + 2 for i, (x, y) in enumerate(zip(a, b)) if x != y]
    prefix = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), 40)
    suffix = next((i for i, (x, y) in enumerate(zip(a[::-1], b[::-1])) if x != y), 40)
    return {"exact": not differences, "lookalike": bool(differences) and
            ((prefix >= 4 and suffix >= 4) or len(differences) <= 2),
            "matching_prefix": prefix, "matching_suffix": suffix, "differing_indices": differences}


def check_recipient(destination: str, references: list[dict], coverage_note: str) -> dict:
    destination = normalize_address(destination)
    unique = {}
    for reference in references:
        address = normalize_address(reference["address"])
        unique.setdefault(address, {**reference, "address": address})
    matches, exact = [], []
    for address, reference in unique.items():
        result = compare_addresses(destination, address)
        item = {**reference, **{k: v for k, v in result.items() if k not in ("exact", "lookalike")}}
        if result["exact"]:
            exact.append(item)
        elif result["lookalike"]:
            matches.append(item)
    status = "exact_match" if exact else "lookalike" if matches else "no_match" if unique else "insufficient_history"
    actions = {
        "exact_match": "This matches a reference address. Confirm the recipient and transaction independently; a match is not a safety guarantee.",
        "lookalike": "Pause and verify the entire address through a separate trusted channel before sending.",
        "no_match": "No resemblance was found in the available references. Verify this recipient independently.",
        "insufficient_history": "Add a trusted or reference address, or wait for monitored history to load, then check again.",
    }
    return {"status": status, "matches": exact or matches, "checked_references": len(unique),
            "coverage_note": coverage_note, "action": actions[status]}


def lookalike_alert(candidate: str, reference: str) -> dict | None:
    comparison = compare_addresses(candidate, reference)
    if not comparison["lookalike"]:
        return None
    return {"kind": "lookalike", "severity": "warning", "title": "Possible lookalike address",
            "explanation": "An incoming sender resembles an address this wallet previously sent funds to. This pattern can be used to poison transaction history; resemblance alone does not prove an attack.",
            "action": "Do not copy this sender from transaction history. Verify the full recipient address independently.",
            "evidence": {"candidate": candidate, "reference": reference, "reference_kind": "previous_recipient",
                         **{k: v for k, v in comparison.items() if k not in ("exact", "lookalike")}}}


def approval_alert(record) -> dict | None:
    if record.value != MAX_ALLOWANCE:
        return None
    verified = record.verification == "verified" and record.allowance == MAX_ALLOWANCE
    confirmation = ("The token contract reported that allowance at the observed block. " if verified else
                    f"The token contract reported a reduced allowance of {record.allowance} at the observed block, so the unlimited event was no longer effective at block end. "
                    if record.verification == "verified" and record.allowance is not None else
                    "The maximum allowance could not be confirmed at the observed block because the contract read was unavailable. ")
    return {"kind": "unlimited_approval", "severity": "warning", "title": "Unlimited spending approval",
            "explanation": "A token approval event requested the maximum spending allowance. " +
                confirmation +
                "Unlimited approval can be intentional; it is exposure to review, not proof of fraud.",
            "action": "Check whether you recognize the spender. Review current permissions in your wallet; Semblance cannot revoke them.",
            "evidence": {"token": record.token, "spender": record.spender, "allowance": record.allowance,
                         "event_value": record.value, "verification": record.verification, "observed_block": record.block}}
