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

from pathlib import Path
from typing import BinaryIO
import io
import zipfile
import string
import re
import struct

# Reuse width/depth label maps consistent with mapper expectations
WIDTH_LABELS = {
    1.5: '2x (1 1/2")',
    2.5: '3x (2 1/2")',
    3.5: '4x (3 1/2")',
    5.5: '6x (5 1/2")',
    7.5: '8x (7 1/2")',
}

DEPTH_LABELS = {
    3.5:  '4 (3 1/2")',
    4.5:  '5 (4 1/2")',
    5.5:  '6 (5 1/2")',
    7.25: '8 (7 1/4")',
    9.25: '10 (9 1/4")',
    11.25:'12 (11 1/4")',
    13.25:'14 (13 1/4")',
    15.25:'16 (15 1/4")',
}


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

        # Heuristic extraction of truss "marks" (dataset-style): j02, j03a, j06c, t14ge, t01, ...
        # Scan raw bytes for token-like segments as well
        truss_bytes = _read("trusses") or b""
        token_re = re.compile(rb"(?i)\b([tj][0-9]{1,2}(?:[a-z]{1,2})?)\b")
        token_hits = [m.group(1).decode("utf-8", "ignore") for m in token_re.finditer(truss_bytes)]
        # normalise to lower-case unique while preserving order
        seen: set[str] = set()
        truss_candidates: list[str] = []
        for tok in token_hits:
            k = tok.lower()
            if k not in seen:
                seen.add(k)
                truss_candidates.append(k)

    return {
        "zip_offset": pk_off,
        "entries": entries,
        "strings": strings,
        "suggested_marks": list(dict.fromkeys(suggested_marks)),  # de-dup preserve order
        "truss_candidates": truss_candidates,
    }


def _closest_label(val: float, table: dict[float, str]) -> str | None:
    if not table:
        return None
    key = min(table.keys(), key=lambda k: abs(k - val))
    # ensure reasonably close (within 0.3 in)
    if abs(key - val) <= 0.3:
        return table[key]
    return None


def suggest_overlay_from_trusses(path: str | Path, marks: list[str]) -> dict[str, dict]:
    """
    Heuristic extractor: for each mark, search its byte pattern in the 'trusses'
    entry and parse nearby little-endian 32-bit numbers to guess:
      - girder_width (label), girder_depth (label), girder_ply (int 1..4)
      - king_height (float in [18..60])

    Returns { mark: {girder_width, girder_depth, girder_ply, king_height} }
    Only fields with a confident guess are included.
    """
    p = Path(path)
    data = p.read_bytes()
    pk_off = _find_pk_offset(data)
    if pk_off is None:
        raise ValueError("Embedded ZIP signature not found in MMDL file")
    with zipfile.ZipFile(io.BytesIO(data[pk_off:]), "r") as zf:
        try:
            with zf.open("trusses", "r") as f:
                blob = f.read()
        except KeyError:
            return {}

    out: dict[str, dict] = {}
    window = 512  # bytes around the mark occurrence
    for mark in marks:
        if not mark:
            continue
        mbytes = mark.encode("utf-8")
        idx = blob.lower().find(mbytes.lower())
        if idx < 0:
            # try alnum version
            alnum = "".join([c for c in mark if c.isalnum()]).encode("utf-8")
            idx = blob.lower().find(alnum.lower()) if alnum else -1
        if idx < 0:
            continue
        start = max(0, idx - window)
        end = min(len(blob), idx + window)
        seg = blob[start:end]

        floats: list[float] = []
        ints: list[int] = []
        # parse as LE 32-bit across the window
        for i in range(0, len(seg) - 4, 4):
            chunk = seg[i:i+4]
            try:
                valf = struct.unpack('<f', chunk)[0]
                vali = struct.unpack('<i', chunk)[0]
                floats.append(valf)
                ints.append(vali)
            except struct.error:
                pass

        # Heuristics
        # ply: mode of small ints 1..4 in vicinity
        ply_cands = [n for n in ints if 1 <= n <= 4]
        girder_ply = None
        if ply_cands:
            # pick most frequent
            from collections import Counter
            c = Counter(ply_cands)
            girder_ply = c.most_common(1)[0][0]

        # width/depth candidates from typical lumber series
        width_label = None
        depth_label = None
        # look for near keys
        for fval in floats:
            wl = _closest_label(fval, WIDTH_LABELS)
            if wl and not width_label:
                width_label = wl
            dl = _closest_label(fval, DEPTH_LABELS)
            if dl and not depth_label:
                depth_label = dl
            if width_label and depth_label:
                break

        # king height: pick a plausible value range [18..60] inches
        kh = None
        kh_cands = [f for f in floats if 18.0 <= f <= 60.0]
        if kh_cands:
            kh = max(kh_cands)

        props: dict = {}
        if width_label:  props["girder_width"] = width_label
        if depth_label:  props["girder_depth"] = depth_label
        if girder_ply is not None: props["girder_ply"] = int(girder_ply)
        if kh is not None: props["king_height"] = float(round(kh, 2))
        if props:
            out[mark] = props

    return out
