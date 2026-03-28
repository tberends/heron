from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd


def photon_recarray_to_points_gdf(
    points_rec: np.ndarray,
    crs_rd: str = "EPSG:28992",
) -> gpd.GeoDataFrame:
    """
    Convert ATL03 photon structured array (from read_atl03_points_from_hdf5) to a GeoDataFrame
    compatible with the LAS pipeline: X, Y, Z, geometry in RD.
    """
    if points_rec.size == 0:
        return gpd.GeoDataFrame(
            {"X": pd.Series(dtype=float), "Y": pd.Series(dtype=float), "Z": pd.Series(dtype=float)},
            geometry=gpd.GeoSeries(dtype="geometry"),
            crs=crs_rd,
        )

    rd_x = np.asarray(points_rec["rd_x"], dtype=float)
    rd_y = np.asarray(points_rec["rd_y"], dtype=float)
    h_nap = np.asarray(points_rec["h_nap"], dtype=float)

    data = {
        "X": rd_x,
        "Y": rd_y,
        "Z": h_nap,
        "delta_time": np.asarray(points_rec["delta_time"], dtype=float),
        "beam": np.asarray(points_rec["beam"], dtype=object),
    }
    df = pd.DataFrame(data)
    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["X"], df["Y"]), crs=crs_rd)
    return gdf
