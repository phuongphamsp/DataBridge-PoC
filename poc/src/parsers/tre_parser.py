"""
MiTek TRE File Parser
Extracts engineering data needed to populate SST Hanger Selector.

TRE format: plain text, proprietary MiTek format.
Units: Imperial (inches, degrees, lbs).
"""

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MemberInfo:
    """A single truss member (top chord, bottom chord, web, etc.)."""
    index: int
    label: str          # e.g. T1, B1, W1, EV1
    member_type_code: int  # 2=top chord, 3=bottom chord, 4=web, etc.
    size: str           # e.g. "2x4"
    grade: str          # e.g. "No.2"
    species: str        # e.g. "SP"
    actual_width: float   # inches, e.g. 1.50
    actual_height: float  # inches, e.g. 3.50
    # Polygon vertices in inches (X,Y pairs), from Line 4 of member block
    coords: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class BearingInfo:
    """A single bearing point."""
    index: int          # 0 = left, 1 = right
    x_pos: float        # x position (inches from left)
    y_pos: float        # y position
    width: float        # bearing width (inches)
    orientation_rad: float  # bearing angle in radians (1.5708 = 90° = perpendicular)


@dataclass
class TREData:
    """All extracted data from a single TRE file."""
    filename: str

    # --- ROOF BASICS (line 5) ---
    truss_type_code: int        # 1=Common, 9=Jack-Closed, 10=Common(sym), etc.
    span_inches: float          # overall span
    pitch_tan: float            # pitch as tangent (rise/run)
    left_heel_inches: float     # left overhang (horizontal)
    right_heel_inches: float    # right overhang (horizontal)

    # --- TRUSS INFO ---
    truss_type_label: str       # e.g. "Common", "Hip", "Jack-Closed", "Monopitch Girder"
    is_girder: bool
    span_carried_inches: float  # > 0 means this truss carries another truss

    # --- MEMBER INFO ---
    members: list[MemberInfo] = field(default_factory=list)

    # --- BEARING INFO ---
    bearings: list[BearingInfo] = field(default_factory=list)

    # --- REACTION INFO (max envelope across all load cases) ---
    reaction1_lbs: int = 0      # max download at bearing 1 (left)
    reaction2_lbs: int = 0      # max download at bearing 2 (right)
    uplift1_lbs: int = 0        # max uplift at bearing 1 (negative in file → stored positive)
    uplift2_lbs: int = 0        # max uplift at bearing 2

    # --- ADDITIONAL ---
    ply: int = 1                # number of plies
    plies_on_girder: int = 1
    overall_height_str: str = ""   # e.g. "7-7-13"
    code_standard: str = ""        # e.g. "IRC2015/TPI2014"
    date: str = ""
    left_heel_height: float = 3.5   # vertical heel height at left bearing (from ROOF BASICS pos 10)
    right_heel_height: float = 3.5  # vertical heel height at right bearing (from ROOF BASICS pos 11)

    # --- DERIVED ---
    @property
    def pitch_degrees(self) -> float:
        return round(math.degrees(math.atan(abs(self.pitch_tan))), 2)

    @property
    def is_negative_pitch(self) -> bool:
        """Monopitch sloping down to the right."""
        return self.pitch_tan < 0

    @property
    def bottom_chord(self) -> Optional[MemberInfo]:
        """Return the first bottom chord member (type_code 3)."""
        for m in self.members:
            if m.member_type_code == 3 and m.actual_width > 0:
                return m
        return None

    @property
    def top_chord(self) -> Optional[MemberInfo]:
        """Return the first top chord member (type_code 2)."""
        for m in self.members:
            if m.member_type_code == 2 and m.actual_width > 0:
                return m
        return None

    @property
    def heel_height_inches(self) -> float:
        """Parse 'ft-in-16ths' string → decimal inches."""
        return _parse_height_str(self.overall_height_str)

    @property
    def skew_degrees(self) -> float:
        """
        Derive skew from bearing orientation.
        Standard perpendicular bearing = π/2 rad (90°) → skew = 0°.
        Any deviation from π/2 is the skew angle.
        """
        if not self.bearings:
            return 0.0
        # Use bearing 0 (left) as reference
        orient = self.bearings[0].orientation_rad
        skew = abs(math.degrees(orient) - 90.0)
        return round(skew, 1)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_height_str(s: str) -> float:
    """
    Parse MiTek height string 'ft-in-16ths' → decimal inches.
    e.g. '7-7-13' → 7*12 + 7 + 13/16 = 91.8125
    e.g. '1-11-13' → 1*12 + 11 + 13/16 = 23.8125
    """
    s = s.strip()
    if not s:
        return 0.0
    parts = s.split("-")
    if len(parts) == 3:
        try:
            ft = int(parts[0])
            inch = int(parts[1])
            sixteenth = int(parts[2])
            return ft * 12.0 + inch + sixteenth / 16.0
        except ValueError:
            pass
    return 0.0


def _parse_member_line(line: str) -> Optional[tuple["MemberInfo", int]]:
    """
    Parse a member data line like:
      2x4,No.2,SP, 1.50, 3.50, 22.7500, 26.2500, 29.2501, 29.2500,5,B1,3,36.00,0,0,0
    Returns (MemberInfo, n_pts) or None if line doesn't match.
    n_pts is the number of XY coordinate pairs on the following line.
    """
    # Pattern: size,grade,species, width, height, ...lengths..., n_pts, label, type_code, ...
    pattern = r'^(\dx\d+),(No\.\d+|MSR[\d.]+|[\w.]+),(\w+),\s*([\d.]+),\s*([\d.]+),\s*[\d.]+,\s*[\d.]+,\s*[\d.]+,\s*[\d.]+,(\d+),([\w]+),(\d+),'
    m = re.match(pattern, line.strip())
    if not m:
        return None
    n_pts = int(m.group(6))
    member = MemberInfo(
        index=-1,
        label=m.group(7),
        member_type_code=int(m.group(8)),
        size=m.group(1),
        grade=m.group(2),
        species=m.group(3),
        actual_width=float(m.group(4)),
        actual_height=float(m.group(5)),
    )
    return member, n_pts


def _parse_coord_line(line: str, n_pts: int) -> list[tuple[float, float]]:
    """
    Parse a member coordinate line like:
      93.472, 46.986, 91.907, 50.117, 165.250, 86.788, 165.250, 82.875
    Returns list of (x, y) tuples (n_pts pairs).
    """
    try:
        vals = [float(v.strip()) for v in line.split(',') if v.strip()]
        pairs = [(vals[i], vals[i+1]) for i in range(0, min(len(vals)-1, n_pts*2), 2)]
        return pairs
    except (ValueError, IndexError):
        return []


def _parse_bearing_line(line: str) -> Optional[BearingInfo]:
    """
    Parse a bearing definition line from BEARING INFO section.
    Format: 0 <flag> <x_pos> <y_pos> 0.000000 <...> <width> 0 <skew_flag> -1.000000 <orient_rad> ...
    Example: 0 1 3.999996 0.000000 0.000000 1 3 2 0 0 BR1 BR2 0 <uuid> 1 0 0 0 0 1.500000 0 0 -1.000000 1.570796 1 0 0
    """
    parts = line.strip().split()
    if len(parts) < 22:
        return None
    try:
        # parts[0] = bearing index (0 or 1)
        # parts[2] = x_pos, parts[3] = y_pos
        # parts[19] = bearing width (1.500000)
        # parts[23] = orientation in radians (1.570796 = π/2 = 90°)
        idx = int(parts[0])
        x_pos = float(parts[2])
        y_pos = float(parts[3])
        width = float(parts[19])
        orient = float(parts[23])
        return BearingInfo(
            index=idx,
            x_pos=x_pos,
            y_pos=y_pos,
            width=width,
            orientation_rad=orient,
        )
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_tre(filepath: str | Path) -> TREData:
    """
    Parse a MiTek TRE file and return a TREData object.
    """
    path = Path(filepath)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    filename = path.name

    # -----------------------------------------------------------------------
    # Line 5 (index 4): ROOF BASICS
    # Format: <type_code> <span> <pitch_tan> 0.000000 <left_overhang> <right_overhang>
    #         1 1 1 8 <left_heel_height> <right_heel_height>
    # -----------------------------------------------------------------------
    roof_basics = lines[4].strip().split()
    truss_type_code = int(roof_basics[0])
    span_inches = float(roof_basics[1])
    pitch_tan = float(roof_basics[2])
    left_heel = float(roof_basics[4])    # horizontal overhang
    right_heel = float(roof_basics[5])   # horizontal overhang
    # Positions 10 and 11 are the vertical heel heights (bottom chord depth at bearing)
    left_heel_height  = float(roof_basics[10]) if len(roof_basics) > 10 else 3.5
    right_heel_height = float(roof_basics[11]) if len(roof_basics) > 11 else 3.5

    # -----------------------------------------------------------------------
    # Scan all lines for sections
    # -----------------------------------------------------------------------
    truss_type_label = ""
    is_girder = False
    span_carried = 0.0
    ply = 1
    plies_on_girder = 1
    overall_height_str = ""
    code_standard = ""
    date_str = ""
    reaction1 = 0
    reaction2 = 0
    uplift1 = 0
    uplift2 = 0

    members: list[MemberInfo] = []
    bearings: list[BearingInfo] = []

    in_member_info = False
    in_bearing_info = False
    in_reaction_info = False
    member_index = 0
    bearing_count_expected = 0
    bearing_lines_read = 0

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # --- Section markers ---
        if stripped == "MEMBER INFO":
            in_member_info = True
            in_bearing_info = False
            in_reaction_info = False
            i += 1
            continue

        if stripped == "BEARING INFO":
            in_member_info = False
            in_bearing_info = True
            in_reaction_info = False
            # Next line: "<count> <total_width>"
            i += 1
            if i < len(lines):
                bearing_header = lines[i].strip().split()
                bearing_count_expected = int(bearing_header[0])
            i += 1
            bearing_lines_read = 0
            continue

        if stripped == "REACTION INFO":
            in_member_info = False
            in_bearing_info = False
            in_reaction_info = True
            i += 1
            continue

        if stripped == "TRUSS INFO":
            in_member_info = False
            in_bearing_info = False
            in_reaction_info = False
            i += 1
            if i < len(lines):
                truss_type_label = lines[i].strip()
            i += 1
            continue

        # --- BEARING INFO: read bearing definition lines ---
        if in_bearing_info and bearing_lines_read < bearing_count_expected:
            b = _parse_bearing_line(stripped)
            if b is not None:
                b.index = bearing_lines_read
                bearings.append(b)
                bearing_lines_read += 1
                # Skip the next 2 lines (sub-data for this bearing)
                i += 3
                continue

        # --- MEMBER INFO: member data lines ---
        if in_member_info:
            result = _parse_member_line(stripped)
            if result is not None:
                m, n_pts = result
                m.index = member_index
                # Next line (i+1) is the coordinate polygon line
                if n_pts > 0 and i + 1 < len(lines):
                    m.coords = _parse_coord_line(lines[i + 1], n_pts)
                members.append(m)
                member_index += 1

        # --- Key-value fields (anywhere in file) ---
        if stripped.startswith("Girder="):
            is_girder = stripped.split("=", 1)[1].strip().upper() == "YES"

        elif stripped.startswith("Span Carried="):
            span_carried = float(stripped.split("=", 1)[1].strip())

        elif stripped.startswith("Ply="):
            try:
                ply = int(stripped.split("=", 1)[1].strip())
            except ValueError:
                pass

        elif stripped.startswith("Plies on Girder="):
            try:
                plies_on_girder = int(stripped.split("=", 1)[1].strip())
            except ValueError:
                pass

        elif stripped.startswith("Overall Truss Height:"):
            overall_height_str = stripped.split(":", 1)[1].strip()

        elif stripped.startswith("Reaction1="):
            try:
                reaction1 = int(stripped.split("=", 1)[1].strip())
            except ValueError:
                pass

        elif stripped.startswith("Reaction2="):
            try:
                reaction2 = int(stripped.split("=", 1)[1].strip())
            except ValueError:
                pass

        elif stripped.startswith("Max Uplift1="):
            try:
                uplift1 = abs(int(stripped.split("=", 1)[1].strip()))
            except ValueError:
                pass

        elif stripped.startswith("Max Uplift2="):
            try:
                uplift2 = abs(int(stripped.split("=", 1)[1].strip()))
            except ValueError:
                pass

        elif stripped.startswith("Date="):
            date_str = stripped.split("=", 1)[1].strip()

        elif re.match(r'^IRC\d+/TPI\d+', stripped) or re.match(r'^IBC\d+', stripped):
            code_standard = stripped

        i += 1

    return TREData(
        filename=filename,
        truss_type_code=truss_type_code,
        span_inches=span_inches,
        pitch_tan=pitch_tan,
        left_heel_inches=left_heel,
        right_heel_inches=right_heel,
        left_heel_height=left_heel_height,
        right_heel_height=right_heel_height,
        truss_type_label=truss_type_label,
        is_girder=is_girder,
        span_carried_inches=span_carried,
        members=members,
        bearings=bearings,
        reaction1_lbs=reaction1,
        reaction2_lbs=reaction2,
        uplift1_lbs=uplift1,
        uplift2_lbs=uplift2,
        ply=ply,
        plies_on_girder=plies_on_girder,
        overall_height_str=overall_height_str,
        code_standard=code_standard,
        date=date_str,
    )
