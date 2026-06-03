"""Integration tests against the real IOMOD-AD5593R-v2_0.f3z sample file."""

import pytest
from pathlib import Path

from fusionextractor import BomEntry, FusionProject, FusionExtractorError, FileNotFoundInArchiveError
from tests.conftest import SAMPLE_F3Z


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def project():
    with FusionProject(SAMPLE_F3Z) as p:
        yield p


# ---------------------------------------------------------------------------
# Design metadata
# ---------------------------------------------------------------------------

def test_design_name(project):
    assert project.design_name == "IOMOD-AD5593R-v2_0"


# ---------------------------------------------------------------------------
# Schematic
# ---------------------------------------------------------------------------

def test_get_schematic_returns_bytes(project):
    data = project.get_schematic()
    assert isinstance(data, bytes)
    assert len(data) > 0


def test_get_schematic_is_xml(project):
    data = project.get_schematic()
    assert data.startswith(b"<?xml")


def test_get_schematic_size(project):
    assert len(project.get_schematic()) == 174726


# ---------------------------------------------------------------------------
# Board
# ---------------------------------------------------------------------------

def test_get_board_returns_bytes(project):
    data = project.get_board()
    assert isinstance(data, bytes)
    assert len(data) > 0


def test_get_board_is_xml(project):
    data = project.get_board()
    assert data.startswith(b"<?xml")


def test_get_board_size(project):
    assert len(project.get_board()) == 303904


# ---------------------------------------------------------------------------
# Previews
# ---------------------------------------------------------------------------

def test_get_previews_returns_list(project):
    previews = project.get_previews()
    assert isinstance(previews, list)
    assert len(previews) > 0


def test_get_previews_have_required_fields(project):
    for preview in project.get_previews():
        assert isinstance(preview.source, str) and preview.source
        assert isinstance(preview.path, str) and preview.path
        assert isinstance(preview.data, bytes) and len(preview.data) > 0


def test_get_previews_includes_thumbnails(project):
    previews = project.get_previews()
    thumbnail_paths = [p.path for p in previews]
    assert any("Previews/small.png" in path for path in thumbnail_paths)


def test_get_previews_includes_large_images_by_default(project):
    previews = project.get_previews()
    assert any("Images.BlobParts" in p.path for p in previews)


def test_get_previews_excludes_large_images_when_false(project):
    previews = project.get_previews(include_large_images=False)
    assert not any("Images.BlobParts" in p.path for p in previews)


def test_get_previews_small_only_count(project):
    previews = project.get_previews(include_large_images=False)
    assert len(previews) == 3


def test_get_previews_sources(project):
    sources = {p.source for p in project.get_previews(include_large_images=False)}
    assert sources == {"schematic", "board", "project"}


def test_get_previews_thumbnails_are_png(project):
    for preview in project.get_previews(include_large_images=False):
        assert preview.data[:8] == b"\x89PNG\r\n\x1a\n", (
            f"Expected PNG magic bytes for {preview.source}/{preview.path}"
        )


# ---------------------------------------------------------------------------
# extract_schematic
# ---------------------------------------------------------------------------

def test_extract_schematic_to_dir(project, tmp_path):
    result = project.extract_schematic(tmp_path)
    assert result.exists()
    assert result.suffix == ".sch"
    assert result.stat().st_size == 174726


def test_extract_schematic_to_explicit_path(project, tmp_path):
    out = tmp_path / "my_schematic.sch"
    result = project.extract_schematic(out)
    assert result == out
    assert out.exists()


def test_extract_schematic_content_matches_get(project, tmp_path):
    result = project.extract_schematic(tmp_path)
    assert result.read_bytes() == project.get_schematic()


# ---------------------------------------------------------------------------
# extract_board
# ---------------------------------------------------------------------------

def test_extract_board_to_dir(project, tmp_path):
    result = project.extract_board(tmp_path)
    assert result.exists()
    assert result.suffix == ".brd"
    assert result.stat().st_size == 303904


def test_extract_board_to_explicit_path(project, tmp_path):
    out = tmp_path / "my_board.brd"
    result = project.extract_board(out)
    assert result == out
    assert out.exists()


def test_extract_board_content_matches_get(project, tmp_path):
    result = project.extract_board(tmp_path)
    assert result.read_bytes() == project.get_board()


# ---------------------------------------------------------------------------
# extract_previews
# ---------------------------------------------------------------------------

def test_extract_previews_to_dir(project, tmp_path):
    paths = project.extract_previews(tmp_path)
    assert len(paths) > 0
    for p in paths:
        assert p.exists()
        assert p.stat().st_size > 0


def test_extract_previews_small_only(project, tmp_path):
    paths = project.extract_previews(tmp_path, include_large_images=False)
    assert len(paths) == 3


def test_extract_previews_filename_prefix(project, tmp_path):
    paths = project.extract_previews(tmp_path, include_large_images=False)
    names = [p.name for p in paths]
    assert all("__" in name for name in names)
    prefixes = {name.split("__")[0] for name in names}
    assert prefixes == {"schematic", "board", "project"}


def test_extract_previews_creates_dest_dir(project, tmp_path):
    dest = tmp_path / "new_subdir"
    assert not dest.exists()
    project.extract_previews(dest, include_large_images=False)
    assert dest.is_dir()


# ---------------------------------------------------------------------------
# BOM
# ---------------------------------------------------------------------------

def test_get_bom_returns_list(project):
    bom = project.get_bom()
    assert isinstance(bom, list)
    assert len(bom) > 0


def test_get_bom_entries_are_bom_entry(project):
    for entry in project.get_bom():
        assert isinstance(entry, BomEntry)


def test_get_bom_excludes_power_symbols_by_default(project):
    bom = project.get_bom()
    references = {e.reference for e in bom}
    assert not any(r.startswith("GND") or r.startswith("P+") for r in references)


def test_get_bom_default_count(project):
    assert len(project.get_bom()) == 10


def test_get_bom_include_power_symbols_count(project):
    assert len(project.get_bom(include_power_symbols=True)) == 25


def test_get_bom_known_component(project):
    bom = project.get_bom()
    u1 = next(e for e in bom if e.reference == "U1")
    assert u1.device == "AD5593R"
    assert u1.package == "TSSOP16"
    assert u1.library == "SuperHouse-ICs"


def test_get_bom_value_field(project):
    bom = project.get_bom()
    c1 = next(e for e in bom if e.reference == "C1")
    assert c1.value == "100nF"
    assert c1.package == "0603"


def test_get_bom_package_strips_leading_dash(project):
    bom = project.get_bom()
    for entry in bom:
        assert not entry.package.startswith("-")


def test_extract_bom_to_dir(project, tmp_path):
    result = project.extract_bom(tmp_path)
    assert result.exists()
    assert result.suffix == ".csv"
    assert result.stat().st_size > 0


def test_extract_bom_filename_uses_design_name(project, tmp_path):
    result = project.extract_bom(tmp_path)
    assert result.name == f"{project.design_name}_bom.csv"


def test_extract_bom_to_explicit_path(project, tmp_path):
    out = tmp_path / "components.csv"
    result = project.extract_bom(out)
    assert result == out
    assert out.exists()


def test_extract_bom_csv_headers(project, tmp_path):
    import csv as _csv
    result = project.extract_bom(tmp_path)
    with open(result, newline="") as f:
        reader = _csv.DictReader(f)
        assert reader.fieldnames == ["reference", "device", "package", "value", "library"]


def test_extract_bom_row_count_matches_get_bom(project, tmp_path):
    import csv as _csv
    result = project.extract_bom(tmp_path)
    with open(result, newline="") as f:
        rows = list(_csv.DictReader(f))
    assert len(rows) == len(project.get_bom())


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_file_not_found_raises():
    with pytest.raises(FileNotFoundError):
        FusionProject("nonexistent.f3z")


def test_not_a_zip_raises(tmp_path):
    bad_file = tmp_path / "bad.f3z"
    bad_file.write_bytes(b"this is not a zip file")
    with pytest.raises(FusionExtractorError):
        FusionProject(bad_file)


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

def test_context_manager_opens_and_closes():
    with FusionProject(SAMPLE_F3Z) as p:
        assert p.design_name  # accessible inside context
        first_entry = p._root_zip.namelist()[0]
    # zipfile raises ValueError on read after close; namelist() is cached so use read()
    with pytest.raises(ValueError, match="already closed"):
        p._root_zip.read(first_entry)


def test_context_manager_returns_self():
    with FusionProject(SAMPLE_F3Z) as p:
        assert isinstance(p, FusionProject)
