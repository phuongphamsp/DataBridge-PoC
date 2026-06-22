"""
MiTek MMDL Parser (carve ZIP and extract high-level metadata)

This parser does NOT fully decode MiTek's proprietary binary formats. It
performs safe, non-invasive extraction steps:
  1) Identify the embedded ZIP from the first PK\x03\x04 header
  2) List entries inside the ZIP (e.g., job, jobProps, trusses, ...)
  3) Extract printable ASCII strings as heuristics to reveal IDs/marks

Return a compact JSON-like dict suitable for diagnostics and future mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
import io
import zipfile
import string


PRINTABLE = set(string.printable)


def _find_pk_offset(data: bytes) -> int | None:
    """Return index of first ZIP local header 'PK\x03\x04'."""
    sig = b"PK\x03\x04"
    idx = data.find(sig)
    return idx if idx >= 0 else None


def _extract_strings(data: bytes, min_len: int = 6, limit: int = 200) -> list[str]:
    """Return up to `limit` printable ASCII strings of length >= min_len."""
    out: list[str] = []
    buf: list[str] = []
    for b in data:
        ch = chr(b)
        if ch in PRINTABLE and ch not in "\r\x0b\x0c":
            buf.append(ch)
        else:
            if len(buf) >= min_len:
                s = "".join(buf)
                out.append(s)
                if len(out) >= limit:
                    return out
            buf = []
    if len(buf) >= min_len and len(out) < limit:
        out.append("".join(buf))
    return out


def parse_mmdl(path: str | Path) -> dict:
    """
    Carve embedded ZIP from a .mmdl file and return a high-level summary:
      - zip_offset: byte index where PK header is found
      - entries: [{name, size}]
      - strings: a small sample of printable strings from key entries

    NOTE: This does not parse proprietary record formats; it only reveals hints
    that can be used to correlate with TRE files (e.g., truss marks/IDs).
    """
    p = Path(path)
    data = p.read_bytes()
    pk_off = _find_pk_offset(data)
    if pk_off is None:
        raise ValueError("Embedded ZIP signature not found in MMDL file")

    zdata = data[pk_off:]
    bio = io.BytesIO(zdata)
    with zipfile.ZipFile(bio, "r") as zf:
        entries = [{"name": i.filename, "size": zf.getinfo(i.filename).file_size} for i in zf.infolist()]

        def _read(name: str) -> bytes | None:
            try:
                with zf.open(name, "r") as f:
                    return f.read()
            except KeyError:
                return None

        # Heuristic string samples from common parts
        targets = [
            "trusses",
            "trussdesignresults",
            "job",
            "jobProps",
            "images+PlanViewPng",
        ]
        strings: dict[str, list[str]] = {}
        for t in targets:
            b = _read(t)
            if not b:
                continue
            strings[t] = _extract_strings(b, min_len=6, limit=80)

        # Try to guess potential marks/IDs: short alnum tokens from 'trusses'
        suggested_marks: list[str] = []
        truss_strs = strings.get("trusses", [])
        for s in truss_strs:
            s2 = s.strip()
            if 2 <= len(s2) <= 16 and all(c.isalnum() or c in "-_" for c in s2):
                suggested_marks.append(s2)
            if len(suggested_marks) >= 40:
                break

    return {
        "zip_offset": pk_off,
        "entries": entries,
        "strings": strings,
        "suggested_marks": list(dict.fromkeys(suggested_marks)),  # de-dup preserve order
    }
