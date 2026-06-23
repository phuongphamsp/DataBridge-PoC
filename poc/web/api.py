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

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse
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

from src.parsers.tre_parser import parse_tre, TREData
from src.mappers.sst_mapper import map_tre_to_sst
from src.integration.sst_playwright import submit_to_sst
from src.integration.sst_api import submit_to_sst_api

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="DataBridge PoC", version="0.1.0")

# In-memory token store (single user PoC)
_sst_bearer_token: str = ""

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
        return JSONResponse({"ok": True, "tre": _tre_to_dict(tre), "sst_input": _sst_to_dict(sst)})
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
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False)