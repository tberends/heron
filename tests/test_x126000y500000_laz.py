"""
Tests tegen het repofixture X126000Y500000.laz (RD-tile, LiDAR).

load_data() roept anders de PDOK BGT-API aan; die wordt hier gemockt zodat tests
offline en stabiel blijven.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

pytest.importorskip("laspy")
import laspy

pytest.importorskip("geopandas")

from src.chunk_files import recursive_split, split_las_file
from src.import_data import load_data

pytestmark = pytest.mark.laz_fixture


def _scaled_xyz(las: laspy.LasData) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    h = las.header
    x = np.array(las.X * h.scales[0] + h.offsets[0])
    y = np.array(las.Y * h.scales[1] + h.offsets[1])
    z = np.array(las.Z * h.scales[2] + h.offsets[2])
    return x, y, z


def test_laz_opens_and_has_points(require_laz_fixture: Path):
    las = laspy.read(require_laz_fixture)
    assert las.header.point_count > 0


def test_laz_coordinates_align_with_tile_name(require_laz_fixture: Path):
    """Bestandsnaam verwijst naar RD New ~126000 / 500000."""
    las = laspy.read(require_laz_fixture)
    x, y, _ = _scaled_xyz(las)
    assert np.nanmedian(x) == pytest.approx(126_000, abs=5_000)
    assert np.nanmedian(y) == pytest.approx(500_000, abs=5_000)


def test_laz_z_finite_and_reasonable_nap_band(require_laz_fixture: Path):
    _, _, z = _scaled_xyz(laspy.read(require_laz_fixture))
    assert np.all(np.isfinite(z))
    # NL NAP: ruime band voor onderzoeksdata (m onder zeeniveau mogelijk in polders)
    assert z.min() > -15
    assert z.max() < 400


@patch("src.import_data.get_waterdelen", return_value=None)
def test_load_data_builds_geodataframe_without_pdok(_mock_wd, require_laz_fixture: Path):
    import geopandas as gpd

    points, waterdelen, las_x = load_data(
        require_laz_fixture.name,
        data_dir=str(require_laz_fixture.parent),
        crs="EPSG:28992",
        reference_date=None,
    )
    assert len(points) == len(las_x)
    assert points.crs.to_string() == "EPSG:28992"
    assert isinstance(points, gpd.GeoDataFrame)
    assert waterdelen.crs == points.crs
    assert waterdelen.empty


def test_split_las_file_writes_non_empty_las_chunks(require_laz_fixture: Path, tmp_path: Path):
    """Splits naar .las-chunks; grote cellen => weinig bestanden, snelle test."""
    src = tmp_path / require_laz_fixture.name
    shutil.copy2(require_laz_fixture, src)
    out_dir = tmp_path / "chunks"
    out_dir.mkdir()

    split_las_file(str(src), str(out_dir), size=(50_000.0, 50_000.0), points_per_iter=500_000)

    written = list(out_dir.glob("*.las"))
    assert written, "split_las_file zou minstens één .las-chunk moeten schrijven"
    for path in written:
        sub = laspy.read(path)
        assert sub.header.point_count > 0


def test_recursive_split_covers_full_extent(require_laz_fixture: Path):
    """Unit-check: tiling-dekking op basis van de echte header-bounds."""
    las = laspy.read(require_laz_fixture)
    h = las.header
    boxes = recursive_split(h.x_min, h.y_min, h.x_max, h.y_max, 500.0, 500.0)
    assert boxes
    min_x = min(b[0] for b in boxes)
    min_y = min(b[1] for b in boxes)
    max_x = max(b[2] for b in boxes)
    max_y = max(b[3] for b in boxes)
    assert min_x <= h.x_min
    assert min_y <= h.y_min
    assert max_x >= h.x_max
    assert max_y >= h.y_max
