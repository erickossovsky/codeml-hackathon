"""Deterministic identities: match key string -> UUID5 -> IFC-compressed GlobalId."""

import uuid

_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"
_NAMESPACE = uuid.UUID("6f1d2c3e-0000-4000-8000-00000000a2c1")


def _b64(value: int, length: int) -> str:
    return "".join(_CHARS[(value // (64**i)) % 64] for i in range(length))[::-1]


def compress_guid(hex32: str) -> str:
    """Compress a 32-char hex GUID to the 22-char IFC GlobalId form."""
    b = [int(hex32[i : i + 2], 16) for i in range(0, 32, 2)]
    parts = [_b64(b[0], 2)]
    for i in range(1, 16, 3):
        parts.append(_b64((b[i] << 16) + (b[i + 1] << 8) + b[i + 2], 4))
    return "".join(parts)


def global_id(key_str: str) -> str:
    """Same key string always yields the same 22-character id."""
    return compress_guid(uuid.uuid5(_NAMESPACE, key_str).hex)
