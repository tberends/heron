"""
This module provides functionality to filter points based on Z value and proximity to a centerline.
"""

import logging
from typing import Any
import geopandas as gpd

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


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
    points: gpd.GeoDataFrame, centerline: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """
    Filters points that are within a certain distance of a centerline.

    Parameters:
    points (gpd.GeoDataFrame): A GeoDataFrame containing the points to be filtered.
    centerline (gpd.GeoDataFrame): A GeoDataFrame containing the centerline.

    Returns:
    gpd.GeoDataFrame: A GeoDataFrame containing only the points that are within buffer_size of the centerline.
    """

    if "index_right" in points.columns:
        # Drop the 'index_right' column
        points = points.drop(columns=["index_right"])

    points_near_centerline = gpd.sjoin(points, centerline, predicate="within")
    logger.info("Filtered points around a centerline")
    return points_near_centerline
