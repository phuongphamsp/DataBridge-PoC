"""
SST Mapper
Converts parsed TREData → SST Hanger Selector input models.

Handles:
- Connection type detection (joist / truss / multiTruss)
- Lumber size/species/depth lookup tables
- Unit conversions (pitch tangent → degrees, ft-in-16ths → inches)
- Bearing → skew angle derivation
"""

import math
from typing import Union

from src.parsers.tre_parser import TREData, MemberInfo
from src.models.sst_input import (
    SSTJoistInput, SSTTrussInput, SSTMultiTrussInput,
    SSTJobSettings, SSTHangerOptions, SSTHipMember,
    SPECIES_OPTIONS, WIDTH_OPTIONS, DEPTH_OPTIONS,
    DOWNLOAD_DURATIONS,
)

SSTInput = Union[SSTJoistInput, SSTTrussInput, SSTMultiTrussInput]


# ---------------------------------------------------------------------------
# Lookup tables
# ---------------------------------------------------------------------------

# TRE species code → SST dropdown label
SPECIES_MAP: dict[str, str] = {
    "SP":  "SP (Southern Pine)",
    "DF":  "DF (Douglas Fir)",
    "HF":  "HF (Hem Fir)",
    "SPF": "SPF (Spruce Pine Fir)",
    "SYP": "SP (Southern Pine)",   # alias
}

# Actual width (inches) → SST dropdown label
WIDTH_MAP: dict[float, str] = {
    1.5: '2x (1 1/2")',
    2.5: '3x (2 1/2")',
    3.5: '4x (3 1/2")',
    5.5: '6x (5 1/2")',
    7.5: '8x (7 1/2")',
}

# Actual depth (inches) → SST dropdown label (nominal lumber depths)
DEPTH_MAP: dict[float, str] = {
    3.5:  '4 (3 1/2")',
    4.5:  '5 (4 1/2")',
    5.5:  '6 (5 1/2")',
    7.25: '8 (7 1/4")',
    9.25: '10 (9 1/4")',
    11.25: '12 (11 1/4")',
    13.25: '14 (13 1/4")',
    15.25: '16 (15 1/4")',
}

# TRE truss type label keywords → SST connection type
# Evaluated in order; first match wins.
# NOTE: "Jack" trusses are roof trusses that bear on a girder truss via their
# bottom chord (Flush Bottom) — they are NOT floor joists.  Only true floor/
# ceiling joists (rare in this dataset) should use the Flush-Top joist path.
_JOIST_KEYWORDS = ["joist", "floor"]          # "jack" removed — Jack trusses → truss
_MULTI_TRUSS_KEYWORDS = ["hip set", "multi"]   # reserved for future layout-level detection

# TRE member type code → role
# 2 = top chord, 3 = bottom chord, 4 = web, 8 = plate/connector, 9 = dummy, 11 = strut, 18 = block
CHORD_CODES = {2, 3}


# ---------------------------------------------------------------------------
# Connection type detection
# ---------------------------------------------------------------------------

def detect_connection_type(tre: TREData) -> str:
    """
    Returns 'joist', 'truss', or 'multiTruss'.

    Rules (from observed TRE data):
    - 'Jack-Closed' in label → truss  (bears on girder via bottom chord, Flush Bottom)
    - 'Hip' (non-girder) → truss  (single hip truss; multi-truss needs layout)
    - Everything else with real members → truss
    - multiTruss: deferred to layout-level analysis (not in single TRE)
    """
    label_lower = tre.truss_type_label.lower()

    for kw in _JOIST_KEYWORDS:
        if kw in label_lower:
            return "joist"

    return "truss"


# ---------------------------------------------------------------------------
# Value converters
# ---------------------------------------------------------------------------

def map_species(species_code: str) -> str:
    """TRE species code → SST label. Falls back to DF if unknown."""
    result = SPECIES_MAP.get(species_code.upper())
    if result:
        return result
    # Fuzzy: if code contains known substring
    code_up = species_code.upper()
    if "SP" in code_up and "SPF" not in code_up:
        return "SP (Southern Pine)"
    if "SPF" in code_up:
        return "SPF (Spruce Pine Fir)"
    if "DF" in code_up:
        return "DF (Douglas Fir)"
    if "HF" in code_up:
        return "HF (Hem Fir)"
    return "DF (Douglas Fir)"   # safe default


def map_width(actual_width: float) -> str:
    """Actual width inches → SST dropdown label."""
    # Round to nearest 0.25 to handle floating point
    rounded = round(actual_width * 4) / 4
    result = WIDTH_MAP.get(rounded)
    if result:
        return result
    # Find closest
    closest = min(WIDTH_MAP.keys(), key=lambda k: abs(k - actual_width))
    return WIDTH_MAP[closest]


def map_depth(actual_depth: float) -> str:
    """Actual depth inches → SST dropdown label."""
    rounded = round(actual_depth * 4) / 4
    result = DEPTH_MAP.get(rounded)
    if result:
        return result
    closest = min(DEPTH_MAP.keys(), key=lambda k: abs(k - actual_depth))
    return DEPTH_MAP[closest]


def map_download_duration(truss_type_label: str) -> str:
    """
    Infer load duration from truss type.
    - Jack/floor trusses → Floor (100)
    - Roof trusses → Roof (125)
    """
    label_lower = truss_type_label.lower()
    if any(kw in label_lower for kw in ["jack", "floor"]):
        return "Floor (100)"
    return "Roof (125)"


def map_member_type_for_truss(size: str, grade: str) -> str:
    """
    Map TRE lumber type to SST carried member type for truss connection.
    All trusses in this dataset are wood trusses → 'Truss'.
    """
    return "Truss"


def map_member_type_for_joist(size: str, grade: str) -> str:
    """
    Map TRE lumber type to SST carried member type for joist connection.
    Jack-Closed trusses behave as joists → 'Solid Sawn' (they are sawn lumber).
    """
    return "Solid Sawn"


def map_girder_type(tre: TREData) -> str:
    """
    Map carrying (girder) member type.
    All girder trusses in this dataset are wood trusses → 'Truss'.
    """
    return "Truss"


# ---------------------------------------------------------------------------
# Hanger options
# ---------------------------------------------------------------------------

def build_hanger_options(tre: TREData, conn_type: str = "truss") -> SSTHangerOptions:
    """
    Build hanger options.

    Slope angle rules:
    - Joist (Flush Top): slope = pitch of the truss (top flange follows roof slope)
    - Truss (Flush Bottom): slope = 0 (bottom chord is horizontal; hanger is vertical)
    """
    slope = tre.pitch_degrees if conn_type == "joist" else 0.0
    return SSTHangerOptions(
        skew_angle=tre.skew_degrees,
        slope_angle=slope,
        top_flange_bend=0.0,
        top_flange_slope=0.0,
        offset_direction="Centered (No Offset)",
        flush_position="Center",
    )


# ---------------------------------------------------------------------------
# Main mapper
# ---------------------------------------------------------------------------

def map_tre_to_sst(tre: TREData) -> SSTInput:
    """
    Convert a parsed TREData object into the appropriate SST input model.
    Returns one of: SSTJoistInput, SSTTrussInput, SSTMultiTrussInput.
    """
    conn_type = detect_connection_type(tre)

    job = SSTJobSettings(
        hanger_type="All Types",
        fastener_type="All",
        download_duration=map_download_duration(tre.truss_type_label),
        uplift_duration="Quake/Wind (160)",
        job_id=tre.filename.replace(".tre", ""),
        quantity=1,
    )

    hanger = build_hanger_options(tre, conn_type)

    if conn_type == "joist":
        return _map_joist(tre, job, hanger)
    else:
        return _map_truss(tre, job, hanger)


def _map_joist(tre: TREData, job: SSTJobSettings, hanger: SSTHangerOptions) -> SSTJoistInput:
    """Map Jack-Closed truss → SSTJoistInput."""
    bc = tre.bottom_chord
    tc = tre.top_chord

    # Carried member (the jack truss itself acts as the joist)
    joist_species = map_species(bc.species) if bc else "SP (Southern Pine)"
    joist_width   = map_width(bc.actual_width) if bc else '2x (1 1/2")'
    # joist.depth = bottom chord actual height (lumber depth)
    joist_depth   = map_depth(bc.actual_height) if bc else '4 (3 1/2")'

    # Carrying member (header) — same species/width; depth = header's lumber depth
    # For jack trusses bearing on a girder truss, the header is also 2x lumber
    header_species = joist_species
    header_width   = joist_width
    header_depth   = joist_depth  # header is same lumber size as joist bottom chord

    return SSTJoistInput(
        connection_type="joist",
        job=job,
        # Header
        header_type="Solid Sawn",
        header_species=header_species,
        header_width=header_width,
        header_depth=header_depth,
        header_ply=tre.plies_on_girder,
        header_member_id=f"Header-{tre.filename.replace('.tre','')}",
        header_rough_sawn=False,
        # Joist
        joist_type="Solid Sawn",
        joist_species=joist_species,
        joist_width=joist_width,
        joist_depth=joist_depth,
        joist_ply=tre.ply,
        joist_member_id=tre.filename.replace(".tre", ""),
        joist_load=float(tre.reaction1_lbs),
        joist_uplift=float(tre.uplift1_lbs),
        joist_rough_sawn=False,
        hanger=hanger,
    )


def _map_truss(tre: TREData, job: SSTJobSettings, hanger: SSTHangerOptions) -> SSTTrussInput:
    """Map roof truss → SSTTrussInput.

    SST field semantics:
    - truss.depth      = bottom chord actual height (e.g. 3.5" for 2x4)
    - girder.depth     = girder bottom chord actual height
    - girder.kingHeight = overall height of the girder truss (for king post clearance)
    """
    bc = tre.bottom_chord

    truss_species    = map_species(bc.species) if bc else "SP (Southern Pine)"
    truss_width      = map_width(bc.actual_width) if bc else '2x (1 1/2")'
    # truss.depth = bottom chord actual height (lumber depth), NOT overall truss height
    truss_bc_height  = bc.actual_height if bc else 3.5

    overall_h = tre.heel_height_inches  # overall truss height → girder.kingHeight

    # Girder (carrying member) — same species/width as carried truss bottom chord
    # girder.depth = girder's bottom chord actual height (same lumber size in this dataset)
    girder_bc = _find_girder_bottom_chord(tre)
    if girder_bc:
        girder_species = map_species(girder_bc.species)
        girder_width   = map_width(girder_bc.actual_width)
        girder_depth   = map_depth(girder_bc.actual_height)
    else:
        girder_species = truss_species
        girder_width   = truss_width
        girder_depth   = map_depth(truss_bc_height)

    # girder_total_height = vertical heel height of the girder at the bearing point
    # = left_heel_height from ROOF BASICS (the vertical dimension of the bottom chord at bearing)
    girder_total_h = tre.left_heel_height if tre.left_heel_height > 0 else truss_bc_height

    return SSTTrussInput(
        connection_type="truss",
        job=job,
        ansitpi="On (Interior Connection)",
        # Girder (carrying member)
        girder_type=map_girder_type(tre),
        girder_species=girder_species,
        girder_width=girder_width,
        girder_depth=girder_depth,
        girder_ply=tre.plies_on_girder,
        girder_king_width=0.0,
        girder_total_height=girder_total_h,
        girder_member_id=f"Girder-{tre.filename.replace('.tre','')}",
        # Truss (carried member)
        truss_type="Truss",
        truss_species=truss_species,
        truss_width=truss_width,
        truss_heel_height=truss_bc_height,   # bottom chord actual height
        truss_ply=tre.ply,
        truss_member_id=tre.filename.replace(".tre", ""),
        truss_load=float(tre.reaction1_lbs),
        truss_uplift=float(tre.uplift1_lbs),
        hanger=hanger,
    )


def _find_girder_bottom_chord(tre: TREData) -> MemberInfo | None:
    """
    For a girder truss, the bottom chord is the member that the carried
    truss bears on. It's typically the B1 member with the largest actual_height.
    """
    bc_members = [m for m in tre.members if m.member_type_code == 3 and m.actual_width > 0]
    if not bc_members:
        return None
    # Return the one with the largest cross-section (girder chord is bigger)
    return max(bc_members, key=lambda m: m.actual_height * m.actual_width)
