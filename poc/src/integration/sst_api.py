"""
SST Hanger Selector — Direct API Client
Replaces Playwright automation with a direct HTTP call to:
  POST https://api.strongtie.com/gws/hanger-selector/hangers

Enum mappings reverse-engineered from live DevTools capture.
"""

import requests
from dataclasses import dataclass, field
from typing import Optional, Union

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------

SST_API_URL = "https://api.strongtie.com/gws/hanger-selector/hangers"

# material: 1 = Solid Sawn, 2 = Glulam, 3 = LSL, 4 = LVL,
#           5 = Truss, 6 = I-Joist, 7 = Floor Truss, 10 = Concrete, 11 = Steel
MATERIAL_SOLID_SAWN = 1
MATERIAL_TRUSS      = 5

# ansitpi (root level): 0=Off, 3=End Connection, 6=Interior Connection
ANSITPI_OFF      = 0
ANSITPI_END      = 3
ANSITPI_INTERIOR = 6

# style (hanger type): 0 = All, 1 = Face Mount, 2 = Top Flange, 3 = Concealed
STYLE_ALL           = 0
STYLE_FACE_MOUNT    = 1
STYLE_TOP_FLANGE    = 2
STYLE_CONCEALED     = 3

# fastenerType: 0 = All, 1 = Nails, 2 = Bolts, 3 = Screws
FASTENER_ALL   = 0

# buildingCode: 0 = None, 10 = IBC2018, 20 = IRC2018, 30 = IBC2021, 40 = IRC2021
BUILDING_CODE_IRC2018 = 20

# downloadDurationType (load duration factor × 10): 90=Dead, 100=Floor, 115=Snow, 125=Roof, 160=Wind/Quake
DL_DURATION_MAP = {
    "Dead (90)":         90,
    "Floor (100)":      100,
    "Snow (115)":       115,
    "Roof (125)":       125,
    "Quake/Wind (160)": 160,
}

# upliftLoadDurationType
UL_DURATION_MAP = {
    "Normal (100)":      100,
    "Quake/Wind (160)":  160,
}

# flushOption: "TOP" = Flush Top (joist), "BOTTOM" = Flush Bottom (truss)
FLUSH_TOP    = "TOP"
FLUSH_BOTTOM = "BOTTOM"

# topChord (carrying member top chord type): 1 = Single, 2 = Double, 3 = Hip
TOP_CHORD_SINGLE = 1

# skewType / slopeType: 0 = None, 1 = Left, 2 = Right
SKEW_TYPE_NONE  = 0
SKEW_TYPE_LEFT  = 1
SKEW_TYPE_RIGHT = 2

SLOPE_TYPE_NONE = 0
SLOPE_TYPE_UP   = 1
SLOPE_TYPE_DOWN = 2


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class HangerResult:
    model_name: str
    cost: str = ""
    width: str = ""
    height: str = ""
    bearing: str = ""
    download_load: Optional[float] = None
    uplift_load: Optional[float] = None
    series: str = ""
    sku: str = ""


@dataclass
class SSTAPIResult:
    success: bool
    connection_type: str
    hangers: list[HangerResult] = field(default_factory=list)
    error: Optional[str] = None
    raw: Optional[dict] = None


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------

def _depth_inches(sst_depth_label: str) -> float:
    """Extract actual depth from SST label like '4 (3 1/2")' → 3.5"""
    import re
    m = re.search(r'\(([\d\s/]+)"\)', sst_depth_label)
    if not m:
        return 3.5
    frac = m.group(1).strip()
    if ' ' in frac:
        whole, numer_denom = frac.split(' ', 1)
        n, d = numer_denom.split('/')
        return float(whole) + float(n) / float(d)
    if '/' in frac:
        n, d = frac.split('/')
        return float(n) / float(d)
    return float(frac)


def _width_inches(sst_width_label: str) -> float:
    """Extract actual width from SST label like '2x (1 1/2")' → 1.5"""
    return _depth_inches(sst_width_label)


def _dl_duration(label: str) -> int:
    return DL_DURATION_MAP.get(label, 125)


def _ul_duration(label: str) -> int:
    return UL_DURATION_MAP.get(label, 160)


def build_payload(sst_input) -> dict:
    """
    Convert SSTJoistInput or SSTTrussInput → API JSON payload.
    Matches exact structure captured from DevTools.
    """
    conn = sst_input.connection_type   # "joist" or "truss"
    job  = sst_input.job
    h    = sst_input.hanger

    # ── Flush option ──
    flush = FLUSH_TOP if conn == "joist" else FLUSH_BOTTOM

    # ── Download / uplift duration ──
    dl_dur = _dl_duration(job.download_duration)
    ul_dur = _ul_duration(job.uplift_duration)

    # ── Skew / slope ──
    skew  = abs(float(h.skew_angle  or 0))
    slope = abs(float(h.slope_angle or 0))
    skew_type  = SKEW_TYPE_LEFT  if skew  > 0 else SKEW_TYPE_NONE
    slope_type = SLOPE_TYPE_DOWN if slope > 0 else SLOPE_TYPE_NONE

    # ── Carried member ──
    if conn == "joist":
        carried_material = MATERIAL_SOLID_SAWN
        carried_width = _width_inches(sst_input.joist_width)
        carried_depth = _depth_inches(sst_input.joist_depth)
        carried_ply   = sst_input.joist_ply
        load          = int(round(sst_input.joist_load   or 0))
        uplift        = int(round(sst_input.joist_uplift or 0))
    else:
        carried_material = MATERIAL_TRUSS
        carried_width = _width_inches(sst_input.truss_width)
        carried_depth = float(sst_input.truss_heel_height or 3.5)
        carried_ply   = sst_input.truss_ply
        load          = int(round(sst_input.truss_load   or 0))
        uplift        = int(round(sst_input.truss_uplift or 0))

    # ── Carrying member ──
    if conn == "joist":
        carrying_material = MATERIAL_SOLID_SAWN
        carrying_width = _width_inches(sst_input.header_width)
        carrying_depth = _depth_inches(sst_input.header_depth)
        carrying_ply   = sst_input.header_ply
        king_height    = max(carrying_depth, 24.0)
    else:
        carrying_material = MATERIAL_TRUSS
        carrying_width = _width_inches(sst_input.girder_width)
        carrying_depth = _depth_inches(sst_input.girder_depth)
        carrying_ply   = sst_input.girder_ply
        # kingHeight = overall girder height; must be >= carrying depth
        # Use 24.0 as safe default (SST UI default) when not available
        raw_kh = float(getattr(sst_input, "girder_total_height", 0) or 0)
        king_height = max(raw_kh, carrying_depth, 24.0)

    base = {
        "style":        STYLE_ALL,
        "buildingCode": BUILDING_CODE_IRC2018,
        "concealed":    0,
        "fastenerType": FASTENER_ALL,
        "sort":         0,
        "ledger":       0,
        "designInformations": {
            "downloadDurationType":   dl_dur,
            "upliftLoadDurationType": ul_dur,
        },
        "filters": {
            "depth":         0,
            "model":         "",
            "series":        "",
            "webStiffeners": 0,
            "width":         0,
        },
        "carriedMembers": [
            {
                "material": carried_material,
                "width":    carried_width,
                "depth":    carried_depth,
                "ply":      carried_ply,
                "loads": {
                    "load":   load,
                    "uplift": uplift,
                },
                "angle": {
                    "skewAngle":  skew,
                    "skewType":   skew_type,
                    "slopeAngle": slope,
                    "slopeType":  slope_type,
                },
            }
        ],
        "flushOption": flush,
    }

    if conn == "joist":
        # Joist (Flush Top): Solid Sawn header, topChord=1, hangerOptions present, no ansitpi
        base["carryingMember"] = {
            "material": carrying_material,
            "width":    carrying_width,
            "depth":    carrying_depth,
            "ply":      carrying_ply,
            "topChord": 1,
        }
        base["hangerOptions"] = {
            "topFlangeOptions": {
                "topFlangeOpenClosedAngle": 0,
                "topFlangeOpenClosedType":  0,
                "topFlangeSlopedDownAngle": 0,
                "topFlangeSlopedDownType":  0,
                "topFlangeOffset":          0,
            }
        }
    else:
        # Truss (Flush Bottom): Truss carrying member, kingHeight, ansitpi=6, no hangerOptions
        base["carryingMember"] = {
            "material":    carrying_material,
            "width":       carrying_width,
            "depth":       carrying_depth,
            "ply":         carrying_ply,
            "topChord":    0,
            "topChordPly": 0,
            "kingWidth":   0,
            "kingHeight":  king_height,
        }
        base["ansitpi"] = ANSITPI_INTERIOR

    return base


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def parse_response(data: dict, conn_type: str) -> SSTAPIResult:
    """
    Parse the API JSON response into a list of HangerResult objects.

    Actual response structure:
    {
      "errors": "",
      "status": {"code": 0, "error": false, "text": ""},
      "lstHangerOutput": [
        {
          "model": "LUS24",
          "modelSpec": "LUS24",
          "load": 1105,
          "uplift": 495,
          "wSize": 1.563,   -- width
          "hSize": 3.125,   -- height
          "bSize": 1.75,    -- bearing
          "msrp": 0.0,
          "catalog": "C24106X.pdf",
          "ici": 100,       -- installation complexity index
          ...
        }
      ]
    }
    """
    # Check API-level error
    status = data.get("status") or {}
    if status.get("error"):
        return SSTAPIResult(
            success=False,
            connection_type=conn_type,
            error=status.get("text") or "SST API returned an error",
            raw=data,
        )

    hangers_raw = data.get("lstHangerOutput") or []
    hangers = []
    for h in hangers_raw:
        model = h.get("model") or h.get("modelSpec") or "—"
        w     = h.get("wSize")
        ht    = h.get("hSize")
        b     = h.get("bSize")
        dl    = h.get("load")
        ul    = h.get("uplift")
        msrp  = h.get("msrp")

        cost = f"${msrp:.2f}" if msrp is not None and msrp > 0 else ""

        hangers.append(HangerResult(
            model_name    = str(model),
            cost          = cost,
            width         = f'{w}"'  if w  is not None else "",
            height        = f'{ht}"' if ht is not None else "",
            bearing       = f'{b}"'  if b  is not None else "",
            download_load = float(dl) if dl is not None else None,
            uplift_load   = float(ul) if ul is not None else None,
            series        = h.get("catalog") or "",
            sku           = h.get("modelID") or "",
        ))

    return SSTAPIResult(
        success        = True,
        connection_type= conn_type,
        hangers        = hangers,
        raw            = data,
    )


# ---------------------------------------------------------------------------
# Main submit function
# ---------------------------------------------------------------------------

def submit_to_sst_api(sst_input, bearer_token: str) -> SSTAPIResult:
    """
    Submit SST input to the API and return results.

    Args:
        sst_input:     SSTJoistInput or SSTTrussInput
        bearer_token:  JWT token from browser session (DevTools → Network → Authorization header)

    Returns:
        SSTAPIResult with list of HangerResult
    """
    conn_type = getattr(sst_input, "connection_type", "truss")

    headers = {
        "Authorization": f"Bearer {bearer_token.strip()}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
        "Origin":        "https://app.strongtie.com",
        "Referer":       "https://app.strongtie.com/",
        "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    try:
        payload = build_payload(sst_input)
        resp = requests.post(SST_API_URL, json=payload, headers=headers, timeout=30)

        if resp.status_code == 401:
            return SSTAPIResult(
                success=False,
                connection_type=conn_type,
                error="401 Unauthorized — token expired. Get a fresh token from DevTools (open app.strongtie.com/hs, Network tab, any XHR → Authorization header).",
            )
        if resp.status_code == 403:
            return SSTAPIResult(
                success=False,
                connection_type=conn_type,
                error="403 Forbidden — token does not have access.",
            )
        if not resp.ok:
            try:
                err_body = resp.json()
            except Exception:
                err_body = resp.text[:500]
            return SSTAPIResult(
                success=False,
                connection_type=conn_type,
                error=f"HTTP {resp.status_code}: {err_body}",
            )

        data = resp.json()
        return parse_response(data, conn_type)

    except requests.exceptions.Timeout:
        return SSTAPIResult(success=False, connection_type=conn_type, error="Request timed out (30s)")
    except requests.exceptions.ConnectionError as e:
        return SSTAPIResult(success=False, connection_type=conn_type, error=f"Connection error: {e}")
    except Exception as e:
        return SSTAPIResult(success=False, connection_type=conn_type, error=str(e))
