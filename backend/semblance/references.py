"""Shared recipient-intent rules. A reference is never a safety endorsement."""
from decimal import Decimal, InvalidOperation
from collections import defaultdict


VERIFIED_TOKEN = "verified_direct_token_transfer"


def positive(value):
    try:
        amount = Decimal(value)
        return amount.is_finite() and amount > 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def zero(value):
    try:
        amount = Decimal(value)
        return amount.is_finite() and amount == 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def reference_kind(data, wallet):
    if data["from_address"] != wallet or data["to_address"] == wallet or not positive(data["value"]):
        return None
    if data["category"] == "external":
        return "previous_recipient"
    if data["category"] == "erc20" and data.get("recipient_verification") == VERIFIED_TOKEN:
        return "verified_token_recipient"
    return None


class ReferenceIndex:
    """Lossless prefilter for the lookalike rule; avoids a full history cross-product.

    With at most two changed characters, at least one of three disjoint chunks
    must be identical. Prefix/suffix matches use a separate exact bucket.
    """

    def __init__(self, references):
        self.buckets = defaultdict(set)
        self.references = {address: (block, address, kind) for block, address, kind in references}
        for address in self.references:
            for key in self.keys(address):
                self.buckets[key].add(address)

    @staticmethod
    def keys(address):
        body = address[2:].lower()
        return (("ends", body[:4] + body[-4:]), ("a", body[:14]),
                ("b", body[14:27]), ("c", body[27:]))

    def candidates(self, address):
        matches = set()
        for key in self.keys(address):
            matches.update(self.buckets.get(key, ()))
        return [self.references[match] for match in sorted(matches)]
