"""
DataBridge PoC - FastAPI Backend
Endpoints:
  POST /api/parse-tre   -> parse TRE file, return structured data + SST mapped inputs
  POST /api/parse-ifc   -> parse IFC file, return element list
  POST /api/submit-sst  -> submit mapped inputs to SST via Playwright, return hanger results
  GET  /api/batch-results -> return last batch results from output/results.json
  GET  /                -> serve index.html
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import types
import base64
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Bootstrap: load src modules (workaround for Python 3.14 Windows file lock)
# Strategy 1: env vars set by start_server.ps1 (base64-encoded source)
# Strategy 2: PowerShell subprocess to read file bytes
# Strategy 3: direct read (works if files are not locked)
# ---------------------------------------------------------------------------

SRC_DIR = Path(__file__).parent.parent / "src"
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

_ENV_KEYS = {
    "parsers/tre_parser.py":         "DATABRIDGE_TRE_PARSER",
    "models/sst_input.py":           "DATABRIDGE_SST_INPUT",
    "mappers/sst_mapper.py":         "DATABRIDGE_SST_MAPPER",
    "integration/sst_playwright.py": "DATABRIDGE_SST_PLAYWRIGHT",
    "integration/sst_api.py":        "DATABRIDGE_SST_API",
}

def _read_file_code(rel_path: str) -> str:
    full_path = SRC_DIR / rel_path

    # Strategy 1: env var (set by start_server.ps1)
    env_key = _ENV_KEYS.get(rel_path)
    if env_key:
        b64 = os.environ.get(env_key)
        if b64:
            return base64.b64decode(b64).decode("utf-8")

    # Strategy 2: direct read
    try:
        return full_path.read_text(encoding="utf-8")
    except PermissionError:
        pass

    # Strategy 3: PowerShell subprocess
    try:
        ps_path = str(full_path).replace("/", "\\")
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"[Convert]::ToBase64String([System.IO.File]::ReadAllBytes('{ps_path}'))"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            return base64.b64decode(result.stdout.strip()).decode("utf-8")
    except Exception as e:
        pass

    raise RuntimeError(
        f"Cannot read {full_path}.\n"
        "Run the server via start_server.ps1 which sets DATABRIDGE_* env vars."
    )


def _load_src_module(rel_path: str, module_name: str):
    code = _read_file_code(rel_path)
    m = types.ModuleType(module_name)
    exec(compile(code, str(SRC_DIR / rel_path), "exec"), m.__dict__)
    sys.modules[module_name] = m
    return m


# Create package stubs
for _pkg in ["src", "src.parsers", "src.models", "src.mappers", "src.integration"]:
    if _pkg not in sys.modules:
        sys.modules[_pkg] = types.ModuleType(_pkg)

_load_src_module("parsers/tre_parser.py",         "src.parsers.tre_parser")
_load_src_module("models/sst_input.py",           "src.models.sst_input")
_load_src_module("mappers/sst_mapper.py",         "src.mappers.sst_mapper")
_load_src_module("integration/sst_playwright.py", "src.integration.sst_playwright")
_load_src_module("integration/sst_api.py",        "src.integration.sst_api")
_load_src_module("parsers/mmdl_parser.py",        "src.parsers.mmdl_parser")

from src.parsers.tre_parser import parse_tre, TREData
from src.mappers.sst_mapper import map_tre_to_sst
from src.integration.sst_playwright import submit_to_sst
from src.integration.sst_api import submit_to_sst_api
from src.parsers.mmdl_parser import parse_mmdl, suggest_overlay_from_trusses

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="DataBridge PoC", version="0.1.0")

# In-memory token store (single user PoC)
_sst_bearer_token: str = ""
# In-memory MMDL context (last uploaded/parsed)
_mmdl_ctx: dict | None = None
# In-memory MMDL overlay: manual/enriched props per mark
_mmdl_overlay: dict[str, dict] = {}
# In-memory MMDL plan image bytes (PNG) if available
_mmdl_plan_png: bytes | None = None
# Cache last MMDL raw bytes for deeper analysis endpoints
_mmdl_bytes: bytes | None = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(Path(__file__).parent / "index.html"))


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

class TokenPayload(BaseModel):
    token: str

class JoinRequest(BaseModel):
    filenames: list[str]

class MMDLProps(BaseModel):
    mark: str
    girder_species: str | None = None
    girder_width: str | None = None
    girder_depth: str | None = None
    girder_ply: int | None = None
    king_height: float | None = None

@app.post("/api/set-token")
async def set_token(body: TokenPayload):
    global _sst_bearer_token
    t = body.token.strip()
    if t.startswith("Bearer "):
        t = t[7:].strip()
    _sst_bearer_token = t
    return JSONResponse({"ok": True, "token_length": len(t)})

@app.get("/api/token-status")
async def token_status():
    has = bool(_sst_bearer_token)
    preview = (_sst_bearer_token[:12] + "…") if has else ""
    return JSONResponse({"ok": True, "has_token": has, "preview": preview})


# ---------------------------------------------------------------------------
# TRE parse endpoint
# ---------------------------------------------------------------------------

def _tre_to_dict(tre: TREData) -> dict:
    bc = tre.bottom_chord
    tc = tre.top_chord
    return {
        "filename": tre.filename,
        "mmdl_mark": "",  # filled later if MMDL context available
        "truss_type_label": tre.truss_type_label,
        "truss_type_code": tre.truss_type_code,
        "span_inches": round(tre.span_inches, 3),
        "pitch_tan": round(tre.pitch_tan, 6),
        "pitch_degrees": tre.pitch_degrees,
        "is_negative_pitch": tre.is_negative_pitch,
        "left_heel_inches": round(tre.left_heel_inches, 3),
        "right_heel_inches": round(tre.right_heel_inches, 3),
        "left_heel_height": round(tre.left_heel_height, 3),
        "right_heel_height": round(tre.right_heel_height, 3),
        "overall_height_str": tre.overall_height_str,
        "heel_height_inches": round(tre.heel_height_inches, 4),
        "is_girder": tre.is_girder,
        "ply": tre.ply,
        "plies_on_girder": tre.plies_on_girder,
        "span_carried_inches": round(tre.span_carried_inches, 3),
        "reaction1_lbs": tre.reaction1_lbs,
        "reaction2_lbs": tre.reaction2_lbs,
        "uplift1_lbs": tre.uplift1_lbs,
        "uplift2_lbs": tre.uplift2_lbs,
        "skew_degrees": tre.skew_degrees,
        "code_standard": tre.code_standard,
        "date": tre.date,
        "bottom_chord": {
            "label": bc.label, "size": bc.size, "grade": bc.grade,
            "species": bc.species, "width": bc.actual_width, "height": bc.actual_height
        } if bc else None,
        "top_chord": {
            "label": tc.label, "size": tc.size, "grade": tc.grade,
            "species": tc.species, "width": tc.actual_width, "height": tc.actual_height
        } if tc else None,
        "member_count": len(tre.members),
        "bearing_count": len(tre.bearings),
    }


def _sst_to_dict(sst) -> dict:
    try:
        return asdict(sst)
    except Exception:
        return {"connection_type": getattr(sst, "connection_type", "unknown")}


@app.post("/api/parse-tre")
async def parse_tre_endpoint(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".tre"):
        raise HTTPException(400, "Only .tre files accepted")
    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".tre", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        tre = parse_tre(tmp_path)
        tre.filename = file.filename  # restore original upload name
        sst = map_tre_to_sst(tre)
        tre_out = _tre_to_dict(tre)
        # If MMDL context available, try to match mark
        global _mmdl_ctx
        try:
            if _mmdl_ctx and isinstance(_mmdl_ctx, dict):
                candidates = [x.lower() for x in _mmdl_ctx.get("truss_candidates", [])]
                base = (file.filename or "").lower().replace(".tre", "")
                # direct match or strip non-alnum
                alnum = "".join([c for c in base if c.isalnum()])
                mark = base if base in candidates else (alnum if alnum in candidates else "")
                if mark:
                    tre_out["mmdl_mark"] = mark
                    # Enrich SST input for preview if connection is truss and overlay available
                    ov = _mmdl_overlay.get(mark)
                    if ov and getattr(sst, "connection_type", "") == "truss":
                        if ov.get("girder_species"): sst.girder_species = ov["girder_species"]
                        if ov.get("girder_width"):   sst.girder_width   = ov["girder_width"]
                        if ov.get("girder_depth"):   sst.girder_depth   = ov["girder_depth"]
                        if ov.get("girder_ply") is not None: sst.girder_ply = int(ov["girder_ply"])  # type: ignore
                        if ov.get("king_height") is not None: sst.girder_total_height = float(ov["king_height"])  # type: ignore
        except Exception:
            pass
        return JSONResponse({"ok": True, "tre": tre_out, "sst_input": _sst_to_dict(sst)})
    except Exception as e:
        raise HTTPException(500, f"Parse error: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# IFC parse endpoint
# ---------------------------------------------------------------------------

@app.post("/api/parse-ifc")
async def parse_ifc_endpoint(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".ifc"):
        raise HTTPException(400, "Only .ifc files accepted")
    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".ifc", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        try:
            import ifcopenshell
            ifc = ifcopenshell.open(str(tmp_path))
            schema = ifc.schema
            elements = []
            for el in ifc.by_type("IfcProduct"):
                psets = {}
                try:
                    for rel in getattr(el, "IsDefinedBy", []):
                        if rel.is_a("IfcRelDefinesByProperties"):
                            pdef = rel.RelatingPropertyDefinition
                            if pdef.is_a("IfcPropertySet"):
                                for prop in pdef.HasProperties:
                                    if hasattr(prop, "NominalValue") and prop.NominalValue:
                                        psets[prop.Name] = str(prop.NominalValue.wrappedValue)
                except Exception:
                    pass
                elements.append({
                    "id": el.id(), "type": el.is_a(),
                    "name": getattr(el, "Name", None) or "",
                    "global_id": getattr(el, "GlobalId", ""),
                    "properties": psets,
                })
            return JSONResponse({
                "ok": True, "schema": schema,
                "element_count": len(elements),
                "elements": elements[:200],
                "ifc_bytes": len(content),
            })
        except ImportError:
            lines = content.decode("utf-8", errors="replace").splitlines()
            entity_lines = [l for l in lines if l.startswith("#")]
            return JSONResponse({
                "ok": True,
                "schema": "unknown (ifcopenshell not installed)",
                "element_count": len(entity_lines),
                "elements": [],
                "ifc_bytes": len(content),
                "note": "Install ifcopenshell for full element extraction",
            })
    except Exception as e:
        raise HTTPException(500, f"IFC parse error: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# MMDL parse endpoint (carve ZIP + heuristic strings)
# ---------------------------------------------------------------------------

@app.post("/api/parse-mmdl")
async def parse_mmdl_endpoint(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".mmdl"):
        raise HTTPException(400, "Only .mmdl files accepted")
    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".mmdl", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        info = parse_mmdl(tmp_path)
        # cache in memory for subsequent TRE requests
        global _mmdl_ctx, _mmdl_overlay, _mmdl_plan_png, _mmdl_bytes
        _mmdl_ctx = info
        _mmdl_bytes = content
        # Heuristic overlay suggestion from 'trusses'
        marks = [m for m in (info.get("truss_candidates") or []) if isinstance(m, str)]
        suggested = {}
        try:
            if marks:
                suggested = suggest_overlay_from_trusses(tmp_path, marks)
                # Merge into overlay without overwriting existing keys
                for mk, props in suggested.items():
                    low = (mk or "").lower()
                    if not low:
                        continue
                    cur = _mmdl_overlay.get(low, {})
                    for k, v in props.items():
                        if k not in cur:
                            cur[k] = v
                    _mmdl_overlay[low] = cur
        except Exception:
            pass
        # Try extract plan view image
        try:
            from zipfile import ZipFile
            import io
            data = Path(tmp_path).read_bytes()
            pk = data.find(b"PK\x03\x04")
            carved = None
            if pk >= 0:
                with ZipFile(io.BytesIO(data[pk:]), 'r') as zf:
                    # Prefer explicit PNG entries if any
                    names = [i.filename for i in zf.infolist()]
                    target = None
                    for n in names:
                        if n.lower().endswith('.png'):
                            target = n; break
                    if not target and 'images+PlanViewPng' in names:
                        target = 'images+PlanViewPng'
                    if target:
                        with zf.open(target, 'r') as f:
                            blob = f.read()
                        # Carve embedded PNG if necessary
                        sig = b"\x89PNG\r\n\x1a\n"
                        off = blob.find(sig)
                        if off >= 0:
                            carved = blob[off:]
                        else:
                            carved = blob  # hope it's already PNG bytes
            _mmdl_plan_png = carved
        except Exception:
            _mmdl_plan_png = None
        return JSONResponse({"ok": True, "filename": file.filename, **info, "overlay_suggested": suggested})
    except Exception as e:
        raise HTTPException(500, f"MMDL parse error: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# MMDL carrying graph (heuristic from embedded blobs)
# ---------------------------------------------------------------------------

def _infer_carry_graph_from_bytes(data: bytes, candidates: list[str]) -> dict:
    from zipfile import ZipFile
    import io, re
    # carve zip
    pk = data.find(b"PK\x03\x04")
    if pk < 0:
        return {"edges": [], "note": "No ZIP header found"}
    trusses = b""; design = b""
    with ZipFile(io.BytesIO(data[pk:]), 'r') as zf:
        for name in ["trusses", "trussdesignresults"]:
            try:
                with zf.open(name, 'r') as f:
                    if name == 'trusses': trusses = f.read()
                    else: design = f.read()
            except KeyError:
                pass
    blob = trusses + b"\n" + design
    text = blob.lower()
    toks = [str(x).lower() for x in (candidates or []) if isinstance(x, str)]
    # pick girder-like marks: ones ending with 'ge' or containing 'girder'
    girders = [t for t in toks if t.endswith('ge') or 'girder' in t]
    if not girders:
        # fallback: choose tokens starting with 't' that have the longest window density
        girders = toks[:3]
    edges: list[dict] = []
    for g in girders:
        # find first occurrence of girder token
        gi = text.find(g.encode('utf-8'))
        if gi < 0:
            continue
        win = text[max(0, gi-2048): gi+4096]
        # find other tokens in window
        carried = []
        for t in toks:
            if t == g:
                continue
            if win.find(t.encode('utf-8')) >= 0:
                carried.append(t)
        # extract numbers that look like inch offsets (<= 600)
        nums = [float(m.group(0)) for m in re.finditer(rb"\b\d{1,3}(?:\.\d+)?\b", win) if m]
        offsets = [x for x in nums if 0.0 < x <= 600.0]
        edges.append({
            "girder": g,
            "carried": sorted(list({*carried}))[:20],
            "offset_samples": offsets[:10],
            "counts": {"carried": len(set(carried)), "offset_samples": len(offsets)},
            "confidence": "heuristic-window"
        })
    return {"edges": edges, "note": "Heuristic from 'trusses'/'trussdesignresults' window search"}


@app.get("/api/mmdl-carry-graph")
async def mmdl_carry_graph():
    global _mmdl_bytes, _mmdl_ctx
    if not _mmdl_bytes:
        raise HTTPException(400, "No MMDL context loaded. Upload an .mmdl first.")
    candidates = []
    try:
        if _mmdl_ctx and isinstance(_mmdl_ctx, dict):
            candidates = _mmdl_ctx.get("truss_candidates") or []
    except Exception:
        candidates = []
    graph = _infer_carry_graph_from_bytes(_mmdl_bytes, candidates)
    return JSONResponse({"ok": True, **graph})


# ---------------------------------------------------------------------------
# TRE hangers extractor (from Hanger Loading Info.)
# ---------------------------------------------------------------------------

def _extract_hangers_from_tre_text(text: str) -> list[dict]:
    import re
    out: list[dict] = []
    lines = text.splitlines()
    in_section = False
    for ln in lines:
        s = ln.strip()
        if not in_section and ("[Hanger Loading Info.]" in s or "Hanger Loading Info" in s):
            in_section = True
            continue
        if in_section and s.startswith('[') and 'Hanger' not in s:
            break
        if in_section and s.upper().startswith('LG') and 'T=' in s:
            try:
                rhs = s.split('=', 1)[1].strip()
                parts = re.split(r"\s+", rhs)
                # Expected layout (from reference):
                # idx: 0 .. 2 => xInches at [2], label at [4], width [5], heel [6]
                x_inches = None
                label = None
                width = None
                heel_h = None
                # Extract label from T=...
                mlabel = re.search(r"(?i)T\s*=\s*([A-Za-z0-9_\-\.]+)", rhs)
                if mlabel:
                    label = mlabel.group(1).upper()
                # Try fixed positions first
                if len(parts) > 2:
                    try:
                        x_inches = float(str(parts[2]).replace('"',''))
                    except Exception:
                        x_inches = None
                if len(parts) > 5:
                    try:
                        width = float(str(parts[5]).replace('"',''))
                    except Exception:
                        width = None
                if len(parts) > 6:
                    try:
                        heel_h = float(str(parts[6]).replace('"',''))
                    except Exception:
                        heel_h = None
                # Fallbacks
                if x_inches is None:
                    # 1) Parentheses inches e.g. (24.75")
                    mp = re.search(r"\((\d+(?:\.\d+)?)\"\)", rhs)
                    if mp:
                        x_inches = float(mp.group(1))
                    else:
                        # 2) Feet-inches pattern e.g., 8'-0.75"
                        mf = re.search(r"(\d+)\'\s*[-–]?\s*(\d+(?:\.\d+)?)?\"", rhs)
                        if mf:
                            ft = float(mf.group(1) or 0)
                            inc = float(mf.group(2) or 0)
                            x_inches = ft * 12.0 + inc
                        else:
                            # 3) Any plain number fallback
                            mnum = re.search(r"(\d+(?:\.\d+)?)", rhs)
                            if mnum:
                                try:
                                    x_inches = float(mnum.group(1))
                                except Exception:
                                    x_inches = None
                if not label:
                    mlbl2 = re.search(r"(?i)([tj][0-9]{1,2}[a-z]{0,2})", rhs)
                    if mlbl2:
                        label = mlbl2.group(1).upper()
                if label and x_inches is not None:
                    out.append({
                        "label": label,
                        "x_inches": float(x_inches),
                        "width": width,
                        "heel_height": heel_h,
                        "raw": s,
                    })
            except Exception:
                continue
    out.sort(key=lambda h: h.get("x_inches", 0.0))
    return out


@app.post("/api/tre-hangers")
async def tre_hangers(files: list[UploadFile] = File(...)):
    results = []
    for uf in files:
        if not (uf.filename or '').lower().endswith('.tre'):
            continue
        content = await uf.read()
        text = content.decode('utf-8', errors='replace')
        hangers = _extract_hangers_from_tre_text(text)
        # parse is_girder from parse_tre for better signal
        with tempfile.NamedTemporaryFile(suffix=".tre", delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            tre = parse_tre(tmp_path)
            is_girder = bool(getattr(tre, 'is_girder', False))
        except Exception:
            is_girder = False
        finally:
            tmp_path.unlink(missing_ok=True)
        results.append({
            "filename": uf.filename,
            "is_girder": is_girder,
            "hanger_count": len(hangers),
            "hangers": hangers,
        })
    return JSONResponse({"ok": True, "files": results})


# ---------------------------------------------------------------------------
# IFC carry count (label presence cross-check) + TRE hangers labels
# ---------------------------------------------------------------------------

def _ifc_extract_labels_from_text(text: str) -> set[str]:
    import re
    labels = set()
    # Match IFCELEMENTASSEMBLY( ..., 'LABEL'
    for line in text.splitlines():
        m = re.search(r"IFCELEMENTASSEMBLY\s*\([^,]*,\s*[^,]*,\s*'([^']+)'", line, re.I)
        if m:
            labels.add(m.group(1).upper())
    return labels


@app.post("/api/ifc-carry-count")
async def ifc_carry_count(
    ifc: UploadFile = File(...),
    girder_label: str = Form(""),
    tre_files: list[UploadFile] | None = File(None),
):
    try:
        if not (ifc.filename or '').lower().endswith('.ifc'):
            raise HTTPException(400, "Only .ifc accepted for 'ifc'")
        ifc_bytes = await ifc.read()
        ifc_text = ifc_bytes.decode('utf-8', errors='replace')
        ifc_labels = _ifc_extract_labels_from_text(ifc_text)
        girder_in_ifc = bool(girder_label) and girder_label.upper() in ifc_labels

        tre_labels: list[str] = []
        hanger_counts: dict[str, int] = {}
        if tre_files:
            for uf in tre_files:
                try:
                    content = await uf.read()
                    text = content.decode('utf-8', errors='replace')
                    hangers = _extract_hangers_from_tre_text(text)
                    # Collect labels from TRE hangers when available
                    for h in hangers:
                        lab = (h.get('label') or '').strip().upper()
                        if lab:
                            tre_labels.append(lab)
                    hanger_counts[uf.filename] = len(hangers)
                except Exception:
                    hanger_counts[uf.filename] = 0

        # Presence intersection
        unique_tre_labels = sorted(list({*tre_labels}))
        present = [l for l in unique_tre_labels if l in ifc_labels]
        missing = [l for l in unique_tre_labels if l not in ifc_labels]

        return JSONResponse({
            "ok": True,
            "girder_label": girder_label,
            "girder_in_ifc": girder_in_ifc,
            "ifc_label_count": len(ifc_labels),
            "tre_carried_labels": unique_tre_labels,
            "present_in_ifc": present,
            "missing_in_ifc": missing,
            "tre_hanger_counts": hanger_counts,
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"IFC carry count error: {e}")


# ---------------------------------------------------------------------------
# Girder Summary: combine TRE girder hangers + carried TRE reaction/uplift, optional IFC presence
# ---------------------------------------------------------------------------

@app.post("/api/girder-summary")
async def girder_summary(
    girder_label: str = Form(...),
    tre_files: list[UploadFile] = File(...),
    ifc: UploadFile | None = File(None),
):
    if not tre_files:
        raise HTTPException(400, "Provide tre_files")

    # Helper: canonicalize mark token (e.g., 'T08', 'T09A')
    import re
    def _canon_mark(s: str | None) -> str | None:
        if not s:
            return None
        m = re.search(r"(?i)\b([tj][0-9]{1,2}[a-z]{0,2})\b", s)
        return m.group(1).upper() if m else None

    # Parse all TREs; identify girder TRE
    parsed: dict[str, TREData] = {}
    girder_tre: TREData | None = None
    girder_text: str | None = None
    for uf in tre_files:
        content = await uf.read()
        with tempfile.NamedTemporaryFile(suffix=".tre", delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            tre = parse_tre(tmp_path)
            tre.filename = uf.filename or tre.filename
            parsed[tre.filename] = tre
            base = (tre.filename or '').rsplit('.',1)[0].upper()
            if base == girder_label.upper():
                girder_tre = tre
                try:
                    girder_text = content.decode('utf-8', errors='replace')
                except Exception:
                    girder_text = None
            elif tre.is_girder and girder_tre is None:
                # fallback if exact not found yet
                girder_tre = tre
                try:
                    girder_text = content.decode('utf-8', errors='replace')
                except Exception:
                    girder_text = None
        except Exception:
            continue
        finally:
            tmp_path.unlink(missing_ok=True)

    if not girder_tre:
        raise HTTPException(400, f"Girder TRE not found for label '{girder_label}'")

    # Extract hangers from cached girder_text
    hanger_rows: list[dict] = []
    gbase = (girder_tre.filename or '').rsplit('.',1)[0].upper()
    hanger_list: list[dict] = []
    try:
        if girder_text:
            hanger_list = _extract_hangers_from_tre_text(girder_text)
    except Exception:
        hanger_list = []

    # Index carried TRE by base label for reaction lookup
    carried_map_exact: dict[str, TREData] = {}
    carried_map_canon: dict[str, TREData] = {}
    carried_map_nosuf: dict[str, TREData] = {}
    def _strip_suffix(mark: str | None) -> str | None:
        if not mark: return None
        m = re.search(r"(?i)\b([tj][0-9]{1,2})", mark)
        return m.group(1).upper() if m else None
    for fn, tre in parsed.items():
        base = (fn or '').rsplit('.',1)[0].upper()
        if base != gbase:
            canon = _canon_mark(base) or base
            nosuf = _strip_suffix(canon) or canon
            carried_map_exact[base] = tre
            carried_map_canon[canon] = tre
            carried_map_nosuf[nosuf] = tre

    # IFC presence set
    ifc_labels: set[str] = set()
    if ifc is not None:
        try:
            itxt = (await ifc.read()).decode('utf-8', errors='replace')
            raw_ifc = _ifc_extract_labels_from_text(itxt)
            ifc_labels = set()
            for lab in raw_ifc:
                c = _canon_mark(lab)
                if c:
                    ifc_labels.add(c)
        except Exception:
            ifc_labels = set()

    span = float(getattr(girder_tre, 'span_inches', 0.0) or 0.0)
    for h in hanger_list:
        raw_label = (h.get('label') or '').strip().upper()
        label = _canon_mark(raw_label) or raw_label or None
        x = float(h.get('x_inches') or 0.0)
        raw = h.get('raw')
        carr = None
        if label:
            carr = carried_map_canon.get(label)
            if carr is None:
                carr = carried_map_nosuf.get(_strip_suffix(label) or '')
            if carr is None:
                # last resort: scan exact map for startswith (e.g., T08-...)
                for k, v in carried_map_exact.items():
                    if k.startswith(label):
                        carr = v; break
        # Decide side by x; left if x <= span/2
        left_side = x <= (span / 2.0) if span > 0 else True
        down = None; up = None
        if carr is not None:
            if left_side:
                down = getattr(carr, 'reaction1_lbs', None)
                up   = getattr(carr, 'uplift1_lbs', None)
            else:
                down = getattr(carr, 'reaction2_lbs', None)
                up   = getattr(carr, 'uplift2_lbs', None)
        hanger_rows.append({
            "label": label or None,
            "offset_inches": x,
            "offset_feet_inches": (f"{int(x//12)}'-{round(x%12, 2)}\"" if x is not None else None),
            "side": "left" if left_side else "right",
            "download_lbs": down,
            "uplift_lbs": up,
            # IFC no longer a concern; keep field for backward-compat as null
            "present_in_ifc": None,
            "raw": raw,
        })

    return JSONResponse({
        "ok": True,
        "girder": {
            "label": gbase,
            "filename": girder_tre.filename,
            "span_inches": span,
            "hanger_count": len(hanger_list),
        },
        "rows": hanger_rows,
    })


# ---------------------------------------------------------------------------
# SST submit via direct API (fast — uses Bearer token)
# ---------------------------------------------------------------------------

@app.post("/api/debug-payload")
async def debug_payload_endpoint(file: UploadFile = File(...)):
    """Return the exact payload that would be sent to SST API — for debugging."""
    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".tre", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        tre = parse_tre(tmp_path)
        sst = map_tre_to_sst(tre)
        from src.integration.sst_api import build_payload
        payload = build_payload(sst)
        return JSONResponse({"ok": True, "connection_type": sst.connection_type, "payload": payload})
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        tmp_path.unlink(missing_ok=True)


@app.post("/api/submit-sst-api")
async def submit_sst_api_endpoint(file: UploadFile = File(...)):
    global _sst_bearer_token
    if not _sst_bearer_token:
        raise HTTPException(400, "No Bearer token set. Use POST /api/set-token first.")
    if not file.filename.lower().endswith(".tre"):
        raise HTTPException(400, "Only .tre files accepted")
    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".tre", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        tre = parse_tre(tmp_path)
        sst = map_tre_to_sst(tre)
        # Enrich from MMDL overlay if available
        try:
            base = (file.filename or "").lower().replace(".tre", "")
            alnum = "".join([c for c in base if c.isalnum()])
            global _mmdl_ctx, _mmdl_overlay
            mark = ""
            if _mmdl_ctx and isinstance(_mmdl_ctx, dict):
                candidates = [x.lower() for x in _mmdl_ctx.get("truss_candidates", [])]
                mark = base if base in candidates else (alnum if alnum in candidates else "")
            ov = _mmdl_overlay.get(mark) if mark else None
            if ov and getattr(sst, "connection_type", "") == "truss":
                if ov.get("girder_species"): sst.girder_species = ov["girder_species"]
                if ov.get("girder_width"):   sst.girder_width   = ov["girder_width"]
                if ov.get("girder_depth"):   sst.girder_depth   = ov["girder_depth"]
                if ov.get("girder_ply") is not None: sst.girder_ply = int(ov["girder_ply"])  # type: ignore
                if ov.get("king_height") is not None: sst.girder_total_height = float(ov["king_height"])  # type: ignore
        except Exception:
            pass
        result = await asyncio.get_event_loop().run_in_executor(
            None, submit_to_sst_api, sst, _sst_bearer_token
        )
        hangers = [h.__dict__ for h in result.hangers]
        return JSONResponse({
            "ok":              result.success,
            "filename":        file.filename,
            "connection_type": result.connection_type,
            "error":           result.error,
            "hanger_count":    len(hangers),
            "hangers":         hangers,
        })
    except Exception as e:
        raise HTTPException(500, f"API submit error: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# SST submit via Playwright (fallback — slow, ~30s)
# ---------------------------------------------------------------------------

@app.post("/api/submit-sst")
async def submit_sst_endpoint(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".tre"):
        raise HTTPException(400, "Only .tre files accepted")
    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".tre", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        tre = parse_tre(tmp_path)
        sst = map_tre_to_sst(tre)
        result = await submit_to_sst(sst, file.filename, headless=True, timeout_ms=45000)
        hangers = [h.__dict__ for h in result.hangers]
        return JSONResponse({
            "ok": result.success,
            "filename": file.filename,
            "connection_type": result.connection_type,
            "error": result.error,
            "hanger_count": len(hangers),
            "hangers": hangers,
        })
    except Exception as e:
        raise HTTPException(500, f"Submit error: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Truss geometry endpoint
# ---------------------------------------------------------------------------

# Member type code → display category
_MEMBER_TYPE_NAMES = {
    2: "top_chord",
    3: "bottom_chord",
    4: "web",
    5: "vertical",
    6: "hip_rafter",
    7: "hip_jack",
    8: "valley_rafter",
}

@app.post("/api/truss-geometry")
async def truss_geometry_endpoint(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".tre"):
        raise HTTPException(400, "Only .tre files accepted")
    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".tre", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        tre = parse_tre(tmp_path)
        tre.filename = file.filename

        members_out = []
        for m in tre.members:
            if not m.coords:
                continue
            members_out.append({
                "index": m.index,
                "label": m.label,
                "type": _MEMBER_TYPE_NAMES.get(m.member_type_code, f"type{m.member_type_code}"),
                "type_code": m.member_type_code,
                "size": m.size,
                "coords": [[round(x, 4), round(y, 4)] for x, y in m.coords],
            })

        bearings_out = []
        for b in tre.bearings:
            bearings_out.append({
                "index": b.index,
                "x": round(b.x_pos, 4),
                "y": round(b.y_pos, 4),
                "width": round(b.width, 4),
            })

        return JSONResponse({
            "ok": True,
            "filename": file.filename,
            "span_inches": round(tre.span_inches, 3),
            "truss_type_label": tre.truss_type_label,
            "members": members_out,
            "bearings": bearings_out,
        })
    except Exception as e:
        raise HTTPException(500, f"Geometry error: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Batch results endpoint
# ---------------------------------------------------------------------------

@app.get("/api/batch-results")
async def batch_results():
    results_file = OUTPUT_DIR / "results.json"
    if not results_file.exists():
        return JSONResponse({"ok": False, "error": "No batch results yet."})
    try:
        data = json.loads(results_file.read_text(encoding="utf-8"))
        return JSONResponse({"ok": True, "results": data})
    except Exception as e:
        raise HTTPException(500, f"Error reading results: {e}")


# ---------------------------------------------------------------------------
# MMDL ↔ TRE join endpoint (heuristic match marks)
# ---------------------------------------------------------------------------

@app.post("/api/mmdl-join")
async def mmdl_join(body: JoinRequest):
    global _mmdl_ctx
    if not _mmdl_ctx:
        return JSONResponse({"ok": False, "error": "No MMDL context loaded. Upload an .mmdl first."})
    candidates = [x.lower() for x in _mmdl_ctx.get("truss_candidates", [])]
    out = []
    for fn in body.filenames:
        base = (fn or "").lower().replace(".tre", "")
        alnum = "".join([c for c in base if c.isalnum()])
        mark = base if base in candidates else (alnum if alnum in candidates else "")
        out.append({
            "filename": fn,
            "mmdl_mark": mark,
            "matched": bool(mark),
        })
    return JSONResponse({"ok": True, "matches": out})


@app.post("/api/mmdl-suggest-overlay")
async def mmdl_suggest_overlay(body: JoinRequest):
    """Suggest girder props/king_height for matched marks using heuristic parser."""
    global _mmdl_ctx
    if not _mmdl_ctx:
        return JSONResponse({"ok": False, "error": "No MMDL context loaded."})
    # Try to locate the last uploaded MMDL file path is not retained; accept none → need re-upload to refresh ctx
    # We will rebuild a BytesIO from cached context is not available; fall back to simple error.
    return JSONResponse({"ok": False, "error": "Heuristic suggestion requires original .mmdl path; not persisted in ctx."})


# ---------------------------------------------------------------------------
# MMDL overlay: set/get enrichment properties for a mark
# ---------------------------------------------------------------------------

@app.post("/api/mmdl-set-props")
async def mmdl_set_props(body: MMDLProps):
    global _mmdl_overlay
    mk = (body.mark or "").lower().strip()
    if not mk:
        raise HTTPException(400, "mark is required")
    entry = _mmdl_overlay.get(mk, {})
    if body.girder_species is not None: entry["girder_species"] = body.girder_species
    if body.girder_width   is not None: entry["girder_width"]   = body.girder_width
    if body.girder_depth   is not None: entry["girder_depth"]   = body.girder_depth
    if body.girder_ply     is not None: entry["girder_ply"]     = int(body.girder_ply)
    if body.king_height    is not None: entry["king_height"]    = float(body.king_height)
    _mmdl_overlay[mk] = entry
    return JSONResponse({"ok": True, "mark": mk, "props": entry})


@app.get("/api/mmdl-overlay")
async def mmdl_get_overlay():
    return JSONResponse({"ok": True, "overlay": _mmdl_overlay})


@app.get("/api/mmdl-plan.png")
async def mmdl_plan_png():
    global _mmdl_plan_png
    if not _mmdl_plan_png:
        raise HTTPException(404, "No plan image available. Upload .mmdl first.")
    return Response(content=_mmdl_plan_png, media_type="image/png")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False)
