"""
SST Hanger Selector Input Models
Mirrors the exact field names and allowed values from https://app.strongtie.com/hs
"""

from dataclasses import dataclass, field
from typing import Literal, Optional


# ---------------------------------------------------------------------------
# Allowed value sets (from live site extraction)
# ---------------------------------------------------------------------------

HANGER_TYPES = ["All Types", "Face Mount", "Top Flange", "Concealed Flange"]
FASTENER_TYPES = ["All", "Nails", "Bolts", "Screws"]
DOWNLOAD_DURATIONS = ["Dead (90)", "Floor (100)", "Snow (115)", "Roof (125)", "Quake/Wind (160)"]
UPLIFT_DURATIONS = ["Normal (100)", "Quake/Wind (160)"]
ANSITPI_OPTIONS = ["Off", "On (End Connection)", "On (Interior Connection)"]
CONFIGURATIONS = ["Left Center Right", "Left Right", "Left Center", "Center Right"]

MEMBER_TYPES_HEADER = [
    "Solid Sawn", "Glulam", "Laminated Strand Lumber", "Laminated Veneer Lumber",
    "Parallel Strand Lumber", "I-Joist", "Floor Truss", "Ledger",
    "Masonry - Mid-Wall", "Masonry - Top-of-Wall", "Concrete", "Structural Steel",
    "Nailer", "Wall, Sheathed Flush", "Wall, Sheathed Gap",
    "Wall, 1-ply Drywall Flush", "Wall, 1-ply Drywall Flush @ Stud",
    "Wall, 1-ply Drywall Gap", "Wall, 2-ply Drywall Flush",
    "Wall, 2-ply Drywall Flush @ Stud",
]

MEMBER_TYPES_JOIST = [
    "Solid Sawn", "Glulam", "Laminated Strand Lumber", "Laminated Veneer Lumber",
    "Parallel Strand Lumber", "I-Joist", "Floor Truss",
]

MEMBER_TYPES_GIRDER = [
    "Truss", "Glulam", "Laminated Strand Lumber", "Laminated Veneer Lumber",
    "Parallel Strand Lumber", "Ledger", "Masonry", "Concrete",
]

MEMBER_TYPES_TRUSS = [
    "Truss", "Glulam", "Laminated Strand Lumber", "Laminated Veneer Lumber",
    "Parallel Strand Lumber", "I-Joist", "Floor Truss",
]

SPECIES_OPTIONS = [
    "DF (Douglas Fir)", "HF (Hem Fir)", "SP (Southern Pine)", "SPF (Spruce Pine Fir)",
]

WIDTH_OPTIONS = ['2x (1 1/2")', '3x (2 1/2")', '4x (3 1/2")', '6x (5 1/2")', '8x (7 1/2")']

DEPTH_OPTIONS = [
    '4 (3 1/2")', '5 (4 1/2")', '6 (5 1/2")', '8 (7 1/4")',
    '10 (9 1/4")', '12 (11 1/4")', '14 (13 1/4")', '16 (15 1/4")',
]

OFFSET_DIRECTIONS = ["Centered (No Offset)", "Left (Flush Right)", "Right (Flush Left)"]
FLUSH_OPTIONS = ["Low", "Center", "High"]


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------

@dataclass
class SSTJobSettings:
    hanger_type: str = "All Types"
    fastener_type: str = "All"
    download_duration: str = "Roof (125)"
    uplift_duration: str = "Quake/Wind (160)"
    job_id: str = "Job 1"
    quantity: int = 1


@dataclass
class SSTHangerOptions:
    skew_angle: float = 0.0
    slope_angle: float = 0.0
    top_flange_bend: float = 0.0
    top_flange_slope: float = 0.0
    offset_direction: str = "Centered (No Offset)"
    flush_position: str = "Center"


@dataclass
class SSTJoistInput:
    """Input model for Connection Type: Joist (Flush Top)"""
    connection_type: str = "joist"
    job: SSTJobSettings = field(default_factory=SSTJobSettings)

    # Header (carrying member)
    header_type: str = "Solid Sawn"
    header_species: str = "DF (Douglas Fir)"
    header_width: str = '2x (1 1/2")'
    header_depth: str = '6 (5 1/2")'
    header_ply: int = 1
    header_member_id: str = "Header 1"
    header_rough_sawn: bool = False

    # Joist (carried member)
    joist_type: str = "Solid Sawn"
    joist_species: str = "DF (Douglas Fir)"
    joist_width: str = '2x (1 1/2")'
    joist_depth: str = '6 (5 1/2")'
    joist_ply: int = 1
    joist_member_id: str = "Joist 1"
    joist_load: float = 0.0
    joist_uplift: float = 0.0
    joist_rough_sawn: bool = False

    hanger: SSTHangerOptions = field(default_factory=SSTHangerOptions)


@dataclass
class SSTTrussInput:
    """Input model for Connection Type: Truss (Flush Bottom)"""
    connection_type: str = "truss"
    job: SSTJobSettings = field(default_factory=SSTJobSettings)
    ansitpi: str = "On (Interior Connection)"

    # Girder (carrying member)
    girder_type: str = "Truss"
    girder_species: str = "DF (Douglas Fir)"
    girder_width: str = '2x (1 1/2")'
    girder_depth: str = '6 (5 1/2")'
    girder_ply: int = 1
    girder_king_width: float = 0.0
    girder_total_height: float = 24.0
    girder_member_id: str = "Girder 1"

    # Truss (carried member)
    truss_type: str = "Truss"
    truss_species: str = "DF (Douglas Fir)"
    truss_width: str = '2x (1 1/2")'
    truss_heel_height: float = 5.5
    truss_ply: int = 1
    truss_member_id: str = "Truss 1"
    truss_load: float = 0.0
    truss_uplift: float = 0.0

    hanger: SSTHangerOptions = field(default_factory=SSTHangerOptions)


@dataclass
class SSTHipMember:
    """A single hip/jack truss member for Multi-Truss."""
    member_type: str = "Truss"
    species: str = "DF (Douglas Fir)"
    width: str = '2x (1 1/2")'
    ply: int = 1
    heel_height: float = 5.5
    member_id: str = "Jack 1"
    load: float = 0.0
    uplift: float = 0.0
    skew_angle: float = 0.0
    slope_angle: float = 0.0


@dataclass
class SSTMultiTrussInput:
    """Input model for Connection Type: Multi-Truss (Flush Bottom)"""
    connection_type: str = "multiTruss"
    job: SSTJobSettings = field(default_factory=SSTJobSettings)
    ansitpi: str = "On (Interior Connection)"
    configuration: str = "Left Center Right"

    # Girder (carrying member) — same as Truss
    girder_type: str = "Truss"
    girder_species: str = "DF (Douglas Fir)"
    girder_width: str = '2x (1 1/2")'
    girder_depth: str = '6 (5 1/2")'
    girder_ply: int = 1
    girder_king_width: float = 0.0
    girder_total_height: float = 24.0
    girder_member_id: str = "Girder 1"

    jack: SSTHipMember = field(default_factory=lambda: SSTHipMember(member_id="Jack 1"))
    left_hip: SSTHipMember = field(default_factory=lambda: SSTHipMember(member_id="L.Hip 1", skew_angle=45.0))
    right_hip: SSTHipMember = field(default_factory=lambda: SSTHipMember(member_id="R.Hip 1", skew_angle=45.0))
