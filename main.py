# -*- coding: utf-8 -*-
"""
This script reads a .las/.laz file. Several functions can be called to filter the .las/.laz file
    to acquire the desired output. If a function is used, it adds an abbreviation
    describing the function's actions. 

Output is stored in .csv files for convenience.

Finally, a .tif file can be created with a size of 1x1m from the remaining points. The Z
    value of the raster cells is based on the mean, mode or median (user-defined) value of 
    points in the cell.
"""

import os
from typing import List, Optional
import logging
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import geopandas as gpd
import laspy
import contextily as ctx
import matplotlib.pyplot as plt
from pyproj import Transformer
from src.filter_spatial import filter_spatial
from src.generate_raster import generate_raster
from src.filter_functions import filter_by_z_value, filter_by_proximity_to_centerline
from src.plot_frequency import plot_frequency
from src.get_waterdelen import get_waterdelen
from src.merge_tif import merge_tif_files

# Configure logging
def setup_logging():
    """
    Sets up logging configuration to write logs to a file in the log directory.
    Creates a new log file for each run with timestamp in the filename.
    """
    # Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Create log filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"las_processing_{timestamp}.log"
    
    # Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create formatters
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # Create and configure file handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    
    # Create and configure console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    
    # Add handlers to root logger
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Get logger for this module
    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized. Log file: {log_file}")
    return logger

logger = setup_logging()


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


def apply_filters(
    points,
    waterdelen,
    filter_geometries,
    filter_minmax,
    min_peil,
    max_peil,
    filter_centerline,
    buffer_distance,
    output_file_name,
):
    """
    Applies filters to the points dataframe.

    Args:
        points (GeoDataFrame): The points dataframe.
        waterdelen (GeoDataFrame): The water bodies dataframe.
        filter_geometries (bool): Whether to filter geometries.
        filter_minmax (bool): Whether to filter minmax.
        min_peil (int): The minimum water level.
        max_peil (int): The maximum water level.
        filter_centerline (bool): Whether to filter the centerline.
        buffer_distance (float): The buffer distance for centerline filtering.
        output_file_name (List[str]): The name of the output file.

    Returns:
        tuple: A tuple containing the filtered points dataframe and the output file name.
    """
    if filter_geometries:
        points = filter_spatial(points, waterdelen)
        logger.info("Files are filtered within geometries")
        output_file_name.append("spatial")

    if filter_minmax:
        points = filter_by_z_value(points, min_peil, max_peil)
        logger.info("Points are filtered between a predefined minimum and maximum water level")
        output_file_name.append("minmax")

    if filter_centerline:
        centerline = calculate_centerline(waterdelen, buffer_distance)
        if centerline is not None:
            points = filter_by_proximity_to_centerline(points, centerline)
            logger.info(f"Points zijn gefilterd rond de centerline.")
            output_file_name.append("centerline")
        else:
            logger.warning("Skipping centerline filtering as no valid centerline could be calculated")

    logger.info(f"Number of points after filtering: {len(points)}")
    return points, output_file_name


def create_plot(raster_points, points, waterdelen, lasfile, out_name_full):
    """
    Creates a plot of the raster points and saves it as a .png file.

    Args:
        raster_points (GeoDataFrame): The raster points to plot.
        points (GeoDataFrame): The lidar points left after filtering.
        waterdelen (GeoDataFrame): The water bodies dataframe.
        lasfile (str): The name of the .las file.
        out_name_full (str): The full name of the output file.
    """
    # Check if raster_points is not None
    if raster_points is None:
        logger.info("No raster points to plot")
        return
    fig, ax = plt.subplots(figsize=(10, 10))
    waterdelen.plot(ax=ax, facecolor="lightgrey", alpha=0.3, edgecolor="blue")
    raster_points.plot(ax=ax, cmap="viridis")
    ctx.add_basemap(ax, crs=raster_points.rio.crs, source=ctx.providers.CartoDB.Voyager)
    ax.set_title(
        "File: "
        + lasfile
        + "\n"
        + "Number of lidar points: "
        + str(len(points))
        + "\n"
        + "Filter options: "
        + out_name_full,
    )

    FIG_DIR = r"data/output/"
    FIG_NAME = lasfile + "_" + out_name_full + ".png"
    FIG_PATH = os.path.join(FIG_DIR, FIG_NAME)
    plt.savefig(FIG_PATH)
    logger.info(f"Plot saved to: {FIG_PATH}")
    # plt.show()


def save_tif(raster_points, lasfile, out_name_full):
    """
    Saves the raster points to a .tif file.

    Args:
        raster_points (GeoDataFrame): The raster points to save.
        lasfile (str): The name of the .las file.
        out_name_full (str): The full name of the output file.
    """
    if raster_points is None:
        return
    TIF_DIR = r"data/output/"
    TIF_NAME = lasfile + "_" + out_name_full + ".tif"
    TIF_PATH = os.path.join(TIF_DIR, TIF_NAME)
    raster_points.rio.to_raster(TIF_PATH, recalc_transform=False)
    logger.info(f"TIF file saved to: {TIF_PATH}")


def find_las_files(data_dir: str = "data/raw/") -> List[str]:
    """
    Finds all .las and .laz files in the specified directory.

    Args:
        data_dir (str, optional): The directory to search in. Defaults to "data/raw/".

    Returns:
        List[str]: List of complete filenames including extension
    """
    las_files = []
    for ext in ['.las', '.laz']:
        for file in os.listdir(data_dir):
            if file.endswith(ext):
                las_files.append(file)
    
    # Remove duplicates (in case both .las and .laz exist for same file)
    # Keep .laz if both exist
    seen_names = set()
    unique_files = []
    for file in las_files:
        name = os.path.splitext(file)[0]
        if name not in seen_names:
            seen_names.add(name)
            unique_files.append(file)
    
    if not unique_files:
        logger.warning(f"No .las or .laz files found in {data_dir}")
    else:
        logger.info(f"Found {len(unique_files)} files to process")
    
    return unique_files


def process_single_file(
    lasfile: str,
    filter_geometries: bool = False,
    filter_minmax: bool = False,
    min_peil: int = -1,
    max_peil: int = 1,
    filter_centerline: bool = False,
    buffer_distance: float = 1.0,
    raster_averaging_mode: str = "mode",
    create_tif: bool = True,
    output_file_name: List[str] = [],
    frequencydiagram: bool = False,
    coordinates: tuple = (126012.5, 500481),
):
    """
    Processes a single LAS/LAZ file.

    Args:
        lasfile (str): The complete filename of the .las/.laz file to process.
        filter_geometries (bool, optional): Whether to filter geometries. Defaults to False.
        filter_minmax (bool, optional): Whether to filter minmax. Defaults to False.
        min_peil (int, optional): The minimum water level. Defaults to -1.
        max_peil (int, optional): The maximum water level. Defaults to 1.
        filter_centerline (bool, optional): Whether to filter the centerline. Defaults to False.
        buffer_distance (float, optional): The buffer distance for centerline filtering. Defaults to 1.0.
        raster_averaging_mode (str, optional): The raster averaging mode. Defaults to "mode", can also be "mean" or "median".
        create_tif (bool, optional): Whether to create a .tif file. Defaults to True.
        output_file_name (List[str], optional): The name of the output file. Defaults to [].
        frequencydiagram (bool, optional): Whether to plot the frequency. Defaults to False.
        coordinates (tuple, optional): The coordinates in RD to plot the frequency. Defaults to (126012.5, 500481).
    
    Returns:
        dict: A dictionary containing the processed data, or None if an error occurred
    """
    try:
        logger.info(f"Starting processing of file: {lasfile}")
        points, waterdelen, las_x = load_data(lasfile)

        points, output_file_name = apply_filters(
            points,
            waterdelen,
            filter_geometries,
            filter_minmax,
            min_peil,
            max_peil,
            filter_centerline,
            buffer_distance,
            output_file_name,
        )

        if frequencydiagram:
            plot_frequency(points, coordinates, os.path.splitext(lasfile)[0])

        raster_points = None
        if create_tif and points.shape[0] > 0:
            raster_points = generate_raster(points, raster_averaging_mode)
            logger.info(f"Points are averaged based on their {raster_averaging_mode} value")

        out_name_full = "_".join(output_file_name)
        
        # Individual file processing
        create_plot(raster_points, points, waterdelen, os.path.splitext(lasfile)[0], out_name_full)
        if create_tif:
            save_tif(raster_points, os.path.splitext(lasfile)[0], out_name_full)

        output_file_name = []
        logger.info(f"Finished processing file: {lasfile}")
        
        # Return the processed data
        return {
            'points': points,
            'waterdelen': waterdelen,
        }
        
    except Exception as e:
        logger.error(f"Error processing file {lasfile}: {str(e)}")
        return None


def main(
    filter_geometries: bool = False,
    filter_minmax: bool = False,
    min_peil: int = -1,
    max_peil: int = 1,
    filter_centerline: bool = False,
    buffer_distance: float = 1.0,
    raster_averaging_mode: str = "mode",
    create_tif: bool = True,
    output_file_name: List[str] = [],
    frequencydiagram: bool = False,
    coordinates: tuple = (126012.5, 500481),
):
    """
    The main function that processes all LAS/LAZ files in the data/raw directory.

    Args:
        filter_geometries (bool, optional): Whether to filter geometries. Defaults to False.
        filter_minmax (bool, optional): Whether to filter minmax. Defaults to False.
        min_peil (int, optional): The minimum water level. Defaults to -1.
        max_peil (int, optional): The maximum water level. Defaults to 1.
        filter_centerline (bool, optional): Whether to filter the centerline. Defaults to False.
        buffer_distance (float, optional): The buffer distance for centerline filtering. Defaults to 1.0.
        raster_averaging_mode (str, optional): The raster averaging mode. Defaults to "mode", can also be "mean" or "median".
        create_tif (bool, optional): Whether to create a .tif file. Defaults to True.
        output_file_name (List[str], optional): The name of the output file. Defaults to [].
        frequencydiagram (bool, optional): Whether to plot the frequency. Defaults to False.
        coordinates (tuple, optional): The coordinates in RD to plot the frequency. Defaults to (126012.5, 500481).
    """
    # Find all LAS/LAZ files to process
    las_files = find_las_files()
    
    if not las_files:
        logger.error("No files to process. Exiting.")
        return
    
    # Process each file and collect results
    all_results = []
    for lasfile in las_files:
        result = process_single_file(
            lasfile,
            filter_geometries,
            filter_minmax,
            min_peil,
            max_peil,
            filter_centerline,
            buffer_distance,
            raster_averaging_mode,
            create_tif,
            output_file_name.copy(),
            frequencydiagram,
            coordinates,
        )
        if result:
            all_results.append(result)
    
    # Create combined outputs
    if all_results:
        combined_points = pd.concat([r['points'] for r in all_results])
        combined_waterdelen = pd.concat([r['waterdelen'] for r in all_results]).drop_duplicates()
        
        # Generate raster for combined points
        combined_raster_points = None
        if create_tif and combined_points.shape[0] > 0:
            combined_raster_points = generate_raster(combined_points, raster_averaging_mode)
            logger.info(f"Combined points are averaged based on their {raster_averaging_mode} value")
        
        # Create combined plot and TIF
        out_name_full = ""
        if combined_raster_points is not None:
            create_plot(
                combined_raster_points,
                combined_points,
                combined_waterdelen,
                "combined_results",
                out_name_full
            )
            
            if create_tif:
                save_tif(
                    combined_raster_points,
                    "combined_results",
                    out_name_full
                )
    
    logger.info("Finished processing all files")


if __name__ == "__main__":
    main(filter_geometries=True, frequencydiagram=False, filter_centerline=True)
