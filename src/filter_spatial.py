"""
This module provides functionality to filter points within geometries.
"""

import logging
from typing import Optional
from shapely.geometry import Point
import geopandas as gpd

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def calculate_centerline(waterdelen: gpd.GeoDataFrame, buffer_distance: float = 1.0) -> Optional[gpd.GeoDataFrame]:
    """
    Calculates the centerline of water bodies by applying a negative buffer to the water polygons.

    Args:
        waterdelen (gpd.GeoDataFrame): GeoDataFrame containing water body polygons
        buffer_distance (float, optional): Distance for the negative buffer in meters. Defaults to 1.0.

    Returns:
        Optional[gpd.GeoDataFrame]: GeoDataFrame containing the centerlines, or None if no valid centerlines can be calculated
    """
    if waterdelen.empty:
        logger.warning("No water bodies found to calculate centerline from")
        return None
    
    try:
        # Apply negative buffer to get centerline
        centerlines = waterdelen.copy()
        centerlines['geometry'] = centerlines['geometry'].buffer(-buffer_distance)
        
        # Remove empty geometries
        centerlines = centerlines[~centerlines['geometry'].is_empty]
        
        if centerlines.empty:
            logger.warning("No valid centerlines could be calculated from the water bodies, try a smaller negative buffer distance")
            return None
            
        logger.info(f"Successfully calculated centerlines from {len(waterdelen)} water bodies")
        return centerlines
        
    except Exception as e:
        logger.error(f"Error calculating centerlines: {str(e)}")
        return None


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
