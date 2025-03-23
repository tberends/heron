import os
import logging
import laspy
import pandas as pd
import geopandas as gpd
import numpy as np
from pyproj import Transformer

from src.get_waterdelen import get_waterdelen

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def load_data(lasfile, data_dir=r"data/raw/", crs="EPSG:28992"):
    """
    Loads the .las files and converts them to a geopandas dataframe.
    Also loads the geometries used for filtering the .las files.

    Args:
        lasfile (str): The complete filename of the .las/.laz file to load.
        data_dir (str, optional): The directory where the .las file is located. Defaults to "data/raw/".
        crs (str, optional): The coordinate reference system to use. Defaults to "EPSG:28992".

    Returns:
        tuple: A tuple containing the points dataframe, the water bodies dataframe, and the lasX array.
    """
    laz_file = os.path.join(data_dir, lasfile)
    las = laspy.read(laz_file)

    # Log important header parameters
    logger.info("LAS Header Information:")
    logger.info(f"Version: {las.header.version}")
    logger.info(f"Point Format: {las.header.point_format}")
    logger.info(f"Number of points: {las.header.point_count}")
    logger.info(f"Bounds:  min: {las.header.mins}  max: {las.header.maxs}")
    logger.info(f"Scale factors: {las.header.scales}")

    # Convert the las file to a geopandas dataframe using the scale factors and offset from header
    las_x = np.array(las.X * las.header.scales[0] + las.header.offsets[0])
    las_y = np.array(las.Y * las.header.scales[1] + las.header.offsets[1]) 
    las_z = np.array(las.Z * las.header.scales[2] + las.header.offsets[2])

    # Additional data can be added to the dataframe here
    data_coord = pd.DataFrame({"X": las_x, "Y": las_y, "Z": las_z})

    # Load points data
    points = gpd.GeoDataFrame(
        data_coord, geometry=gpd.points_from_xy(data_coord.X, data_coord.Y), crs=crs
    )

    # Calculate bounding box from points with some buffer
    bounds = points.total_bounds
    bbox_buffer = 100  # 100 meter buffer
    bbox = (
        bounds[0] - bbox_buffer,
        bounds[1] - bbox_buffer,
        bounds[2] + bbox_buffer,
        bounds[3] + bbox_buffer
    )
    # Transform the bounding box to EPSG:28992 for PDOK API
    transformer = Transformer.from_crs(crs, "EPSG:28992", always_xy=True)
    bbox = transformer.transform_bounds(*bbox)

    # Get waterdelen for the area
    waterdelen = get_waterdelen(bbox)
    if waterdelen is None:
        logger.warning("No water bodies found via PDOK API")
        waterdelen = gpd.GeoDataFrame(
            columns=["geometry"], crs=crs
        )

    return points, waterdelen, las_x