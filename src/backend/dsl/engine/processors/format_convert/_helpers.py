"""Shared helpers для format_convert package (S53 W1 extraction)."""

from __future__ import annotations

from typing import Any


def _to_text(data: Any) -> str:
    """bytes/bytearray → str (utf-8 best-effort)."""
    if isinstance(data, (bytes, bytearray)):
        return data.decode("utf-8", errors="replace")
    return data


# ── Bencode (BitTorrent metafile format, stdlib only) ────────────────
# Format spec: https://wiki.theory.org/BitTorrentSpecification#Bencoding
# - str/bytes: <len>:<bytes>  (e.g. b"4:spam")
# - int:       i<number>e     (e.g. b"i42e")
# - list:      l<items>e      (e.g. b"l4:spam4:eggse")
# - dict:      d<k1><v1>...e  (keys must be bytes/str, sorted lexicographically)


def _bencode(data: Any) -> bytes:
    """Python object → bencoded bytes (no external deps)."""
    if isinstance(data, bool):
        # Note: bool is subclass of int — handle before int branch
        data = int(data)
    if isinstance(data, int):
        return f"i{data}e".encode("ascii")
    if isinstance(data, (bytes, bytearray)):
        raw = bytes(data)
        return f"{len(raw)}:".encode("ascii") + raw
    if isinstance(data, str):
        raw = data.encode("utf-8")
        return f"{len(raw)}:".encode("ascii") + raw
    if isinstance(data, (list, tuple)):
        return b"l" + b"".join(_bencode(item) for item in data) + b"e"
    if isinstance(data, dict):
        # Keys must be bytes/str; sort lexicographically
        items: list[tuple[bytes, Any]] = []
        for k, v in data.items():
            if isinstance(k, str):
                kb = k.encode("utf-8")
            elif isinstance(k, (bytes, bytearray)):
                kb = bytes(k)
            else:
                raise TypeError(
                    f"bencode dict key must be str/bytes, got {type(k).__name__}"
                )
            items.append((kb, v))
        items.sort(key=lambda kv: kv[0])
        return b"d" + b"".join(_bencode(k) + _bencode(v) for k, v in items) + b"e"
    raise TypeError(f"bencode: unsupported type {type(data).__name__}")


def _bdecode(data: bytes, pos: int = 0) -> tuple[Any, int]:
    """Parse bencoded bytes at ``pos`` → (value, new_pos). Recursive."""
    if pos >= len(data):
        raise ValueError("bencode: unexpected end of data")
    c = data[pos : pos + 1]
    if c == b"i":
        end = data.index(b"e", pos)
        return int(data[pos + 1 : end]), end + 1
    if c == b"l":
        pos += 1
        out: list[Any] = []
        while data[pos : pos + 1] != b"e":
            item, pos = _bdecode(data, pos)
            out.append(item)
        return out, pos + 1
    if c == b"d":
        pos += 1
        out_dict: dict[Any, Any] = {}
        while data[pos : pos + 1] != b"e":
            k, pos = _bdecode(data, pos)
            v, pos = _bdecode(data, pos)
            out_dict[k] = v
        return out_dict, pos + 1
    if c.isdigit():
        colon = data.index(b":", pos)
        length = int(data[pos:colon])
        start = colon + 1
        return bytes(data[start : start + length]), start + length
    raise ValueError(f"bencode: unexpected byte {c!r} at pos {pos}")
