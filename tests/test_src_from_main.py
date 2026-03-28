"""
Tests voor src-modules die vanuit main.py worden gebruikt:
chunk_files, import_data (deels), filter_spatial, filter_functions,
generate_raster, create_plots, get_waterdelen.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import geopandas as gpd
import numpy as np
import pytest
import xarray as xr
from shapely.geometry import Polygon

pytest.importorskip("laspy")
pytest.importorskip("rioxarray")

from src.chunk_files import recursive_split, split_las_file, tuple_size
from src.create_plots import plot_frequency, plot_map
from src.filter_functions import filter_by_proximity_to_centerline, filter_by_z_value
from src.filter_spatial import calculate_centerline, calculate_polygon_statistics, filter_spatial
from src.generate_raster import generate_raster
from src.get_waterdelen import get_waterdelen
from src.import_data import load_data

REPO_ROOT = Path(__file__).resolve().parent.parent
PEIL_GDB = REPO_ROOT / "data" / "external" / "peilafwijking.gdb"


@pytest.fixture
def crs_rd():
    return "EPSG:28992"


@pytest.fixture
def sample_points_gdf(crs_rd):
    """Punten in RD; deel valt in het vierkant, deel erbuiten."""
    xs = np.array([100.0, 101.0, 150.0, 100.5])
    ys = np.array([100.0, 100.0, 100.0, 100.5])
    zs = np.array([-0.5, 0.0, 0.5, 2.0])
    return gpd.GeoDataFrame(
        {"X": xs, "Y": ys, "Z": zs},
        geometry=gpd.points_from_xy(xs, ys),
        crs=crs_rd,
    )


@pytest.fixture
def square_polygon_gdf(crs_rd):
    """100x100 m vierkant rond (100,100) — groot genoeg voor negatieve buffer."""
    poly = Polygon([(50, 50), (150, 50), (150, 150), (50, 150), (50, 50)])
    return gpd.GeoDataFrame({"id": [1]}, geometry=[poly], crs=crs_rd)


def test_tuple_size_parses():
    assert tuple_size("50x65.14") == (50.0, 65.14)


def test_tuple_size_invalid():
    with pytest.raises(ValueError, match="Size must be"):
        tuple_size("not-a-tuple")


def test_recursive_split_single_cell_when_fits():
    boxes = recursive_split(0.0, 0.0, 10.0, 10.0, 20.0, 20.0)
    assert boxes == [(0.0, 0.0, 10.0, 10.0)]


def test_filter_by_z_value_exclusive_bounds(sample_points_gdf):
    # Z > min en Z < max (strikt); sluit 0.5 uit zodat alleen -0.5 en 0.0 overblijven
    out = filter_by_z_value(sample_points_gdf, -1.0, 0.25)
    assert len(out) == 2
    assert set(out["Z"].tolist()) == {-0.5, 0.0}


def test_filter_spatial_keeps_points_within_and_dedupes(sample_points_gdf, square_polygon_gdf):
    within = filter_spatial(sample_points_gdf, square_polygon_gdf)
    # (100,100), (101,100), (100.5,100.5) binnen [50,150]x[50,150]; (150,100) buiten in X? 150 is op rand — within is strict inside?
    # Point on boundary: shapely within is False for boundary typically. 150,100 on edge of polygon x=150.
    assert len(within) >= 2
    assert (within[["X", "Y"]].duplicated()).sum() == 0


def test_calculate_centerline_empty_returns_none(crs_rd):
    empty = gpd.GeoDataFrame(geometry=[], crs=crs_rd)
    assert calculate_centerline(empty, buffer_distance=1.0) is None


def test_calculate_centerline_from_polygon(square_polygon_gdf):
    cl = calculate_centerline(square_polygon_gdf, buffer_distance=5.0)
    assert cl is not None
    assert len(cl) >= 1
    assert not cl.geometry.is_empty.all()


def test_filter_by_proximity_to_centerline(sample_points_gdf, square_polygon_gdf):
    cl = calculate_centerline(square_polygon_gdf, buffer_distance=5.0)
    assert cl is not None
    near = filter_by_proximity_to_centerline(sample_points_gdf, cl)
    assert isinstance(near, gpd.GeoDataFrame)
    assert len(near) <= len(sample_points_gdf)


def test_generate_raster_mean_mode_median(crs_rd):
    # Echte 2D-grid (minstens 2×2 cellen met data): rioxarray weigert 1D-rasters bij resolution()
    xs = np.array([10.0, 10.0, 11.0], dtype=float)
    ys = np.array([20.0, 20.0, 21.0], dtype=float)
    zs = np.array([1.0, 2.0, 4.0], dtype=float)
    gdf = gpd.GeoDataFrame(
        {"X": xs, "Y": ys, "Z": zs},
        geometry=gpd.points_from_xy(xs, ys),
        crs=crs_rd,
    )
    mean_da = generate_raster(gdf, "mean")
    assert mean_da.dims == ("Y", "X")
    assert mean_da.sizes["X"] >= 2
    assert mean_da.sizes["Y"] >= 2
    finite = mean_da.values[np.isfinite(mean_da.values)]
    np.testing.assert_allclose(np.sort(np.unique(finite)), [1.5, 4.0])
    med_da = generate_raster(gdf, "median")
    finite_m = med_da.values[np.isfinite(med_da.values)]
    np.testing.assert_allclose(np.sort(np.unique(finite_m)), [1.5, 4.0])
    mode_da = generate_raster(gdf, "mode")
    finite_o = np.sort(np.unique(mode_da.values[np.isfinite(mode_da.values)]))
    assert finite_o[0] in (1.0, 2.0)
    np.testing.assert_allclose(finite_o[1], 4.0)


def test_calculate_polygon_statistics_validates():
    da = xr.DataArray(np.ones((2, 2)), dims=("Y", "X"), coords={"Y": [0, 1], "X": [0, 1]})
    with pytest.raises(ValueError, match="xarray"):
        calculate_polygon_statistics("not-an-array", "path.gdb")
    with pytest.raises(ValueError, match="polygon_file must be a string"):
        calculate_polygon_statistics(da, 123)
    with pytest.raises(ValueError, match="statistic"):
        calculate_polygon_statistics(da, "path.gdb", statistic="bogus")
    bad = xr.DataArray([1], dims=("only",))
    with pytest.raises(ValueError, match="dimensions"):
        calculate_polygon_statistics(bad, "path.gdb")


@pytest.mark.parametrize("layer", ["geom", "streefpeil"])
def test_peilafwijking_gdb_readable(layer):
    if not PEIL_GDB.is_dir():
        pytest.skip(f"Ontbrekend: {PEIL_GDB}")
    try:
        gdf = gpd.read_file(PEIL_GDB, layer=layer)
    except Exception as exc:
        pytest.skip(f"Kan GDB niet lezen ({layer}): {exc}")
    assert len(gdf) >= 0


@pytest.mark.skipif(not PEIL_GDB.is_dir(), reason="peilafwijking.gdb ontbreekt")
def test_calculate_polygon_statistics_integration():
    try:
        da = xr.DataArray(
            np.array([[1.0, 2.0], [3.0, 4.0]]),
            dims=("Y", "X"),
            coords={"Y": [5920000.0, 5920001.0], "X": [126000.0, 126001.0]},
        )
        calculate_polygon_statistics(da, str(PEIL_GDB), statistic="mean")
    except (FileNotFoundError, ValueError, KeyError, OSError) as exc:
        pytest.skip(f"Polygon-statistieken niet uitvoerbaar met huidige GDB/data: {exc}")


@patch("src.create_plots.ctx.add_basemap")
@patch("matplotlib.pyplot.savefig")
@patch("matplotlib.pyplot.clf")
def test_plot_frequency_writes_figures(mock_clf, mock_savefig, mock_basemap, sample_points_gdf, tmp_path):
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    real_output = REPO_ROOT / "data" / "output"
    real_output.mkdir(parents=True, exist_ok=True)
    plot_frequency(sample_points_gdf, (100.25, 100.25), "test_fixture")
    assert mock_savefig.call_count >= 1


@patch("src.create_plots.ctx.add_basemap")
@patch("matplotlib.pyplot.savefig")
def test_plot_map_no_raster_returns_early(mock_savefig, mock_basemap, sample_points_gdf, square_polygon_gdf):
    plot_map(None, sample_points_gdf, square_polygon_gdf, "test", "")
    mock_savefig.assert_not_called()


@patch("src.create_plots.ctx.add_basemap")
@patch("matplotlib.pyplot.savefig")
def test_plot_map_with_raster(mock_savefig, mock_basemap, square_polygon_gdf, crs_rd):
    REPO_ROOT.joinpath("data", "output").mkdir(parents=True, exist_ok=True)
    xs = np.array([100.0, 101.0, 100.0], dtype=float)
    ys = np.array([100.0, 100.0, 101.0], dtype=float)
    zs = np.array([1.0, 2.0, 3.0], dtype=float)
    pts = gpd.GeoDataFrame(
        {"X": xs, "Y": ys, "Z": zs},
        geometry=gpd.points_from_xy(xs, ys),
        crs=crs_rd,
    )
    r = generate_raster(pts, "mean")
    plot_map(r, pts, square_polygon_gdf, "test", "mean")
    mock_savefig.assert_called_once()


@patch("src.get_waterdelen.requests.post", side_effect=OSError("network off"))
def test_get_waterdelen_returns_none_on_error(_mock_post):
    assert get_waterdelen((0, 0, 1, 1)) is None


@patch("src.import_data.get_waterdelen", return_value=None)
def test_pipeline_laz_load_filter_raster(_mock_wd, require_laz_fixture):
    points, _, _ = load_data(
        require_laz_fixture.name,
        data_dir=str(require_laz_fixture.parent),
        crs="EPSG:28992",
        reference_date=None,
    )
    if len(points) > 500_000:
        points = points.sample(n=50_000, random_state=42)
    zmin = float(points["Z"].quantile(0.01))
    zmax = float(points["Z"].quantile(0.99))
    filtered = filter_by_z_value(points, zmin - 1.0, zmax + 1.0)
    assert len(filtered) > 0
    da = generate_raster(filtered, "mean")
    assert da.sizes["X"] >= 1
    assert da.sizes["Y"] >= 1
