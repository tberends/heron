"""
This module provides functionality to filter points within geometries.
"""

import logging
from typing import Optional
from shapely.geometry import Point
import geopandas as gpd
import numpy as np
import xarray

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


def calculate_polygon_statistics(
    raster_points: xarray.DataArray,
    polygon_file: str,
    statistic: str = "mean"
) -> gpd.GeoDataFrame:
    """
    Calculates statistics (mean or median) per polygon based on raster points.

    Args:
        raster_points (xarray.DataArray): DataArray containing raster points
        polygon_file (str): Path to the .gdb or .gpkg file containing polygons
        statistic (str, optional): Type of statistic to calculate ("mean" or "median"). Defaults to "mean".

    Returns:
        gpd.GeoDataFrame: GeoDataFrame containing the calculated statistics per polygon

    Raises:
        ValueError: If the input parameters are invalid
        FileNotFoundError: If the polygon file does not exist
    """
    # Validate input parameters
    if not isinstance(raster_points, xarray.DataArray):
        raise ValueError("raster_points must be an xarray.DataArray")
    
    if not isinstance(polygon_file, str):
        raise ValueError("polygon_file must be a string")
    
    if statistic not in ["mean", "median"]:
        raise ValueError("statistic must be either 'mean' or 'median'")

    # Check if required dimensions exist
    required_dims = ["X", "Y"]
    if not all(dim in raster_points.dims for dim in required_dims):
        raise ValueError(f"raster_points must have dimensions: {required_dims}")

    try:
        # Read the polygon file
        geom = gpd.read_file(polygon_file, layer="geom")
        polygons = gpd.read_file(polygon_file, layer="streefpeil")
    except FileNotFoundError:
        logger.error(f"Polygon file not found: {polygon_file}")
        raise
    except Exception as e:
        logger.error(f"Error reading polygon file: {str(e)}")
        raise

    # Connect peilafwijkingid of layer streefpeil to globalid of layer geom
    polygons = polygons.merge(geom, left_on="PEILAFWIJKINGGEBIEDID", right_on="GLOBALID", how="left")
    polygons = gpd.GeoDataFrame(polygons, geometry="geometry")
    
    # Get the coordinates from the DataArray
    x_coords = raster_points.X.values
    y_coords = raster_points.Y.values

    # Create a meshgrid of coordinates
    X, Y = np.meshgrid(x_coords, y_coords)
    
    # Get the Z values
    Z = raster_points.values

    # Create points GeoDataFrame
    points_data = {
        'X': X.flatten(),
        'Y': Y.flatten(),
        'Z': Z.flatten()
    }
    points_gdf = gpd.GeoDataFrame(
        points_data,
        geometry=[Point(x, y) for x, y in zip(X.flatten(), Y.flatten())],
        crs=polygons.crs
    )

    # Ensure both GeoDataFrames have the same CRS
    if points_gdf.crs != polygons.crs:
        points_gdf = points_gdf.to_crs(polygons.crs)
        
    # Remove points where Z is nan
    points_gdf = points_gdf[~np.isnan(points_gdf['Z'])]
    
    if points_gdf.empty:
        logger.warning("No valid points found after removing NaN values")
        return gpd.GeoDataFrame()
    
    # Perform spatial join
    joined = gpd.sjoin(points_gdf, polygons, how="inner", predicate="within")

    # Logging the number of points before and after spatial join
    logger.info(f"Number of points before spatial join: {len(points_gdf)} and after spatial join: {len(joined)}")

    if joined.empty:
        logger.warning("No points found within any polygons")
        return gpd.GeoDataFrame()

    # Group by polygon and calculate statistics
    if statistic == "mean":
        stats = joined.groupby('CODE').agg({
            'Z': 'mean'
        }).reset_index()
    else:  # median
        stats = joined.groupby('CODE').agg({
            'Z': 'median'
        }).reset_index()
    
    # Add geometries to the results
    result = polygons.merge(stats, on='CODE')
    
    logger.info(f"Statistics calculated for {len(result)} polygons")
    return result
    

