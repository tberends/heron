"""Unit tests for ICESat photon array → GeoDataFrame (no network)."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest

from src.icesat2.geodataframe import photon_recarray_to_points_gdf

pytest.importorskip("geopandas")


def test_photon_recarray_to_points_gdf_empty():
    empty = np.recarray(
        (0,),
        dtype=[
            ("lon", "f8"),
            ("lat", "f8"),
            ("rd_x", "f8"),
            ("rd_y", "f8"),
            ("h_nap", "f8"),
            ("delta_time", "f8"),
            ("ph_class", "i4"),
            ("beam", "O"),
        ],
    )
    gdf = photon_recarray_to_points_gdf(empty, crs_rd="EPSG:28992")
    assert gdf.empty
    assert gdf.crs.to_string() == "EPSG:28992"
    assert list(gdf.columns) == ["X", "Y", "Z", "geometry"]


def test_photon_recarray_to_points_gdf_columns_and_crs():
    n = 3
    rec = np.rec.fromarrays(
        [
            np.zeros(n),
            np.zeros(n),
            np.array([100.0, 101.0, 100.0], dtype=float),
            np.array([200.0, 200.0, 201.0], dtype=float),
            np.array([1.0, 2.0, 4.0], dtype=float),
            np.zeros(n),
            np.ones(n, dtype=np.int32),
            np.array(["gt1l", "gt1l", "gt2r"], dtype=object),
        ],
        names=["lon", "lat", "rd_x", "rd_y", "h_nap", "delta_time", "ph_class", "beam"],
    )
    gdf = photon_recarray_to_points_gdf(rec, crs_rd="EPSG:28992")
    assert len(gdf) == n
    assert gdf.crs.to_string() == "EPSG:28992"
    np.testing.assert_allclose(gdf["X"].to_numpy(), [100.0, 101.0, 100.0])
    np.testing.assert_allclose(gdf["Y"].to_numpy(), [200.0, 200.0, 201.0])
    np.testing.assert_allclose(gdf["Z"].to_numpy(), [1.0, 2.0, 4.0])
    assert gdf["beam"].tolist() == ["gt1l", "gt1l", "gt2r"]
    assert all(gdf.geometry.geom_type == "Point")
