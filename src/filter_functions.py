"""
This module provides functionality to filter points based on Z value and proximity to a centerline.
"""

from typing import Any
import geopandas as gpd


def filter_by_z_value(
    points: gpd.GeoDataFrame, min_z: float, max_z: float
) -> gpd.GeoDataFrame:
    """
    Filters points based on the minimum and maximum Z value.

    Parameters:
    points (gpd.GeoDataFrame): A GeoDataFrame containing the points to be filtered.
    min_z (float): The minimum Z value.
    max_z (float): The maximum Z value.

    Returns:
    gpd.GeoDataFrame: A GeoDataFrame containing only the points that have a Z value between min_z and max_z.
    """
    filtered_points = points.loc[(points["Z"] > min_z) & (points["Z"] < max_z)]
    return filtered_points


def filter_by_proximity_to_centerline(
    points: gpd.GeoDataFrame, centerline: gpd.GeoDataFrame, buffer_size: float
) -> gpd.GeoDataFrame:
    """
    Filters points that are within a certain distance of a centerline.

    Parameters:
    points (gpd.GeoDataFrame): A GeoDataFrame containing the points to be filtered.
    centerline (gpd.GeoDataFrame): A GeoDataFrame containing the centerline.
    buffer_size (float): The distance from the centerline within which to filter points.

    Returns:
    gpd.GeoDataFrame: A GeoDataFrame containing only the points that are within buffer_size of the centerline.
    """
    centerline_buffered = centerline["geometry"].buffer(buffer_size, cap_style="flat")
    centerline_buffered = gpd.GeoDataFrame(geometry=centerline_buffered)

    if "index_right" in points.columns:
        # Drop the 'index_right' column
        points = points.drop(columns=["index_right"])

    points_near_centerline = gpd.sjoin(points, centerline_buffered, predicate="within")
    print("Filtered points around a centerline")
    return points_near_centerline
