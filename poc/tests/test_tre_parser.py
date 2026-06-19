"""
Unit tests for TRE parser.
Run from poc/ directory:
    python -m pytest tests/ -v
"""

import math
import pytest
from pathlib import Path

from src.parsers.tre_parser import parse_tre, _parse_height_str, TREData

TRE_DIR = Path(r"D:\DataBridge-PoC\DataBridge from MiTek Drawings to SST solutions\5. TRE & IFC")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def tre(filename: str) -> TREData:
    return parse_tre(TRE_DIR / filename)


# ---------------------------------------------------------------------------
# _parse_height_str
# ---------------------------------------------------------------------------

class TestParseHeightStr:
    def test_basic(self):
        assert _parse_height_str("7-7-13") == pytest.approx(7 * 12 + 7 + 13 / 16)

    def test_small(self):
        assert _parse_height_str("1-11-13") == pytest.approx(1 * 12 + 11 + 13 / 16)

    def test_zero(self):
        assert _parse_height_str("") == 0.0

    def test_4ft(self):
        assert _parse_height_str("4-11-13") == pytest.approx(4 * 12 + 11 + 13 / 16)


# ---------------------------------------------------------------------------
# j02.tre — Jack-Closed (joist)
# ---------------------------------------------------------------------------

class TestJ02:
    @pytest.fixture(scope="class")
    def data(self):
        return tre("j02.tre")

    def test_filename(self, data):
        assert data.filename == "j02.tre"

    def test_truss_type_code(self, data):
        assert data.truss_type_code == 9  # Jack-Closed

    def test_span(self, data):
        assert data.span_inches == pytest.approx(29.250071, abs=0.001)

    def test_pitch_tan(self, data):
        assert data.pitch_tan == pytest.approx(0.463648, abs=0.0001)

    def test_pitch_degrees(self, data):
        expected = math.degrees(math.atan(0.463648))
        assert data.pitch_degrees == pytest.approx(expected, abs=0.1)

    def test_truss_type_label(self, data):
        assert "Jack" in data.truss_type_label or "jack" in data.truss_type_label.lower()

    def test_reactions(self, data):
        assert data.reaction1_lbs == 64
        assert data.reaction2_lbs == 115

    def test_uplifts(self, data):
        assert data.uplift1_lbs == 21   # stored positive
        assert data.uplift2_lbs == 38

    def test_ply(self, data):
        assert data.ply == 1

    def test_not_girder(self, data):
        assert data.is_girder is False

    def test_overall_height(self, data):
        assert data.overall_height_str == "1-11-13"
        assert data.heel_height_inches == pytest.approx(1 * 12 + 11 + 13 / 16, abs=0.01)

    def test_skew_zero(self, data):
        assert data.skew_degrees == pytest.approx(0.0, abs=0.5)

    def test_bottom_chord_exists(self, data):
        bc = data.bottom_chord
        assert bc is not None
        assert bc.member_type_code == 3
        assert bc.actual_width == pytest.approx(1.5, abs=0.01)
        assert bc.species == "SP"

    def test_members_parsed(self, data):
        assert len(data.members) > 0


# ---------------------------------------------------------------------------
# t01.tre — Common roof truss
# ---------------------------------------------------------------------------

class TestT01:
    @pytest.fixture(scope="class")
    def data(self):
        return tre("t01.tre")

    def test_filename(self, data):
        assert data.filename == "t01.tre"

    def test_truss_type_code(self, data):
        assert data.truss_type_code == 10  # Common (symmetric)

    def test_span(self, data):
        assert data.span_inches == pytest.approx(330.5, abs=0.1)

    def test_truss_type_label(self, data):
        assert "Common" in data.truss_type_label

    def test_reactions(self, data):
        assert data.reaction1_lbs == 895
        assert data.reaction2_lbs == 895

    def test_uplifts(self, data):
        assert data.uplift1_lbs == 176
        assert data.uplift2_lbs == 176

    def test_ply(self, data):
        assert data.ply == 1

    def test_not_girder(self, data):
        assert data.is_girder is False

    def test_overall_height(self, data):
        assert data.overall_height_str == "7-7-13"
        assert data.heel_height_inches == pytest.approx(91.8125, abs=0.01)

    def test_bottom_chord(self, data):
        bc = data.bottom_chord
        assert bc is not None
        assert bc.actual_width == pytest.approx(1.5, abs=0.01)
        assert bc.species == "SP"


# ---------------------------------------------------------------------------
# t04.tre — Girder truss (Ply=2)
# ---------------------------------------------------------------------------

class TestT04:
    @pytest.fixture(scope="class")
    def data(self):
        return tre("t04.tre")

    def test_is_girder(self, data):
        assert data.is_girder is True

    def test_ply(self, data):
        assert data.ply == 2

    def test_reactions(self, data):
        assert data.reaction1_lbs == 2399
        assert data.reaction2_lbs == 2399

    def test_uplifts(self, data):
        assert data.uplift1_lbs == 674
        assert data.uplift2_lbs == 674

    def test_overall_height(self, data):
        assert data.overall_height_str == "4-11-13"
        assert data.heel_height_inches == pytest.approx(4 * 12 + 11 + 13 / 16, abs=0.01)


# ---------------------------------------------------------------------------
# Mapper smoke tests
# ---------------------------------------------------------------------------

class TestMapper:
    def test_joist_connection_type(self):
        from src.mappers.sst_mapper import map_tre_to_sst
        data = tre("j02.tre")
        result = map_tre_to_sst(data)
        assert result.connection_type == "joist"

    def test_truss_connection_type(self):
        from src.mappers.sst_mapper import map_tre_to_sst
        data = tre("t01.tre")
        result = map_tre_to_sst(data)
        assert result.connection_type == "truss"

    def test_joist_species_mapped(self):
        from src.mappers.sst_mapper import map_tre_to_sst
        data = tre("j02.tre")
        result = map_tre_to_sst(data)
        assert result.joist_species == "SP (Southern Pine)"

    def test_truss_species_mapped(self):
        from src.mappers.sst_mapper import map_tre_to_sst
        data = tre("t01.tre")
        result = map_tre_to_sst(data)
        assert result.truss_species == "SP (Southern Pine)"

    def test_joist_load(self):
        from src.mappers.sst_mapper import map_tre_to_sst
        data = tre("j02.tre")
        result = map_tre_to_sst(data)
        assert result.joist_load == pytest.approx(64.0)

    def test_truss_load(self):
        from src.mappers.sst_mapper import map_tre_to_sst
        data = tre("t01.tre")
        result = map_tre_to_sst(data)
        assert result.truss_load == pytest.approx(895.0)

    def test_joist_uplift(self):
        from src.mappers.sst_mapper import map_tre_to_sst
        data = tre("j02.tre")
        result = map_tre_to_sst(data)
        assert result.joist_uplift == pytest.approx(21.0)

    def test_truss_uplift(self):
        from src.mappers.sst_mapper import map_tre_to_sst
        data = tre("t01.tre")
        result = map_tre_to_sst(data)
        assert result.truss_uplift == pytest.approx(176.0)

    def test_width_mapped(self):
        from src.mappers.sst_mapper import map_width
        assert map_width(1.5) == '2x (1 1/2")'

    def test_species_map_sp(self):
        from src.mappers.sst_mapper import map_species
        assert map_species("SP") == "SP (Southern Pine)"

    def test_species_map_df(self):
        from src.mappers.sst_mapper import map_species
        assert map_species("DF") == "DF (Douglas Fir)"

    def test_depth_map(self):
        from src.mappers.sst_mapper import map_depth
        assert map_depth(3.5) == '4 (3 1/2")'
        assert map_depth(5.5) == '6 (5 1/2")'
        assert map_depth(7.25) == '8 (7 1/4")'
