"""
This module provides functionality to filter points within geometries.
"""

import geopandas as gpd


def filter_spatial(
    points: gpd.GeoDataFrame, geometries: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """
    Filters points that lie within the given geometries.

    Parameters:
    points (gpd.GeoDataFrame): A GeoDataFrame containing the points to be filtered.
    geometries (gpd.GeoDataFrame): A GeoDataFrame containing the geometries within which to filter points.

    Returns:
    gpd.GeoDataFrame: A GeoDataFrame containing only the points that lie within the given geometries.
    """
    # Join the dataframes based on points that lie within the geometries GeoDataFrame
    points_within_geometries = gpd.sjoin(points, geometries, predicate="within")

    # Filter out unique combinations of X,Y coordinates (dependent on precision of data)
    unique_points_mask = ~points_within_geometries.duplicated(subset=["X", "Y"])
    unique_points_within_geometries = points_within_geometries[unique_points_mask]

    return unique_points_within_geometries
