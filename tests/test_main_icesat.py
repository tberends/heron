"""ICESat branch in main: no chunking, mocked NASA fetch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point

pytest.importorskip("geopandas")

import main as main_module


@pytest.fixture(autouse=True)
def _ensure_data_dirs():
    Path("data/processed").mkdir(parents=True, exist_ok=True)
    Path("data/output").mkdir(parents=True, exist_ok=True)


@pytest.fixture
def sample_icesat_gdf():
    xs = np.array([10.0, 10.0, 11.0], dtype=float)
    ys = np.array([20.0, 20.0, 21.0], dtype=float)
    zs = np.array([1.0, 2.0, 4.0], dtype=float)
    return gpd.GeoDataFrame(
        {"X": xs, "Y": ys, "Z": zs, "delta_time": np.zeros(3), "beam": ["gt1l"] * 3},
        geometry=gpd.points_from_xy(xs, ys),
        crs="EPSG:28992",
    )


@patch("main.load_dotenv")
@patch("main.split_las_file")
@patch("main.fetch_icesat_points_gdf")
def test_main_icesat_skips_las_chunking(mock_fetch, mock_split, _mock_dotenv, sample_icesat_gdf):
    empty_wd = gpd.GeoDataFrame(geometry=[], crs="EPSG:28992")
    mock_fetch.return_value = (sample_icesat_gdf, empty_wd, sample_icesat_gdf["X"].to_numpy())

    main_module.main(
        data_source="icesat",
        icesat_temporal=("2024-01-01", "2024-01-31"),
        filter_geometries=False,
        filter_minmax=False,
        filter_centerline=False,
        create_tif=False,
        frequencydiagram=False,
        polygon_file=None,
    )

    mock_split.assert_not_called()
    mock_fetch.assert_called_once()


@patch("main.load_dotenv")
@patch("main.fetch_icesat_points_gdf")
def test_main_icesat_requires_temporal(_mock_fetch, _mock_dotenv):
    with patch("main.split_las_file") as mock_split:
        main_module.main(data_source="icesat", icesat_temporal=None)
    mock_split.assert_not_called()
