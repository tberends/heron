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
from typing import List, Optional, Union
import logging
from pathlib import Path
from datetime import datetime, date

import numpy as np
import pandas as pd
import geopandas as gpd
import laspy
import contextily as ctx
import matplotlib.pyplot as plt
from pyproj import Transformer

from src.chunk_files import split_las_file
from src.import_data import load_data
from src.filter_spatial import filter_spatial, calculate_centerline, calculate_polygon_statistics
from src.generate_raster import generate_raster
from src.filter_functions import filter_by_z_value, filter_by_proximity_to_centerline
from src.create_plots import plot_frequency, plot_map
from src.get_waterdelen import get_waterdelen


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
    for ext in ['.las', '.laz', '.LAS', '.LAZ']:
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


def main(
    filter_geometries: bool = False,
    filter_minmax: bool = False,
    min_peil: int = -1,
    max_peil: int = 1,
    waterdelen_reference_date: Optional[Union[str, datetime, date]] = None,
    filter_centerline: bool = False,
    buffer_distance: float = 1.0,
    raster_averaging_mode: str = "mode",
    create_tif: bool = True,
    output_file_name: List[str] = [],
    frequencydiagram: bool = False,
    coordinates: tuple = (126012.5, 500481),
    polygon_file: Optional[str] = None,
    polygon_statistic: str = "mean",
):
    """
    The main function that processes all LAS/LAZ files in the data/raw directory.

    Args:
        filter_geometries (bool, optional): Whether to filter geometries. Defaults to False.
        filter_minmax (bool, optional): Whether to filter minmax. Defaults to False.
        min_peil (int, optional): The minimum water level. Defaults to -1.
        max_peil (int, optional): The maximum water level. Defaults to 1.
        waterdelen_reference_date (str, datetime, date, optional): Reference date for filtering waterdelen.
                                                                    Only returns water bodies valid on this date.
                                                                    Defaults to None (returns all).
        filter_centerline (bool, optional): Whether to filter the centerline. Defaults to False.
        buffer_distance (float, optional): The buffer distance for centerline filtering. Defaults to 1.0.
        raster_averaging_mode (str, optional): The raster averaging mode. Defaults to "mode", can also be "mean" or "median".
        create_tif (bool, optional): Whether to create a .tif file. Defaults to True.
        output_file_name (List[str], optional): The name of the output file. Defaults to [].
        frequencydiagram (bool, optional): Whether to plot the frequency. Defaults to False.
        coordinates (tuple, optional): The coordinates in RD to plot the frequency. Defaults to (126012.5, 500481).
        polygon_file (Optional[str], optional): Path to the .gdb or .gpkg file containing polygons. Defaults to None.
        polygon_statistic (str, optional): Type of statistic to calculate ("mean" or "median"). Defaults to "mean".
    """

    # Clear processed data directory and output directory
    [os.remove(os.path.join("data/processed/", f)) for f in os.listdir("data/processed/") if f.endswith(".las")]
    [os.remove(os.path.join("data/output/", f)) for f in os.listdir("data/output/") if f.endswith(".png") or f.endswith(".tif") or f.endswith(".gpkg")]

    # Find all LAS/LAZ files to process
    las_files = find_las_files()
    
    if not las_files:
        logger.error("No files to process. Exiting.")
        return
    
    # Chunk files if needed in size of 1000x1000 and 1 million points per iteration
    for lasfile in las_files:
        logger.info(f"Splitting file: {lasfile}")
        lasfile = os.path.join("data/raw/", lasfile)
        split_las_file(lasfile, "data/processed/", (1000, 1000), 10**6)

    processed_files = find_las_files("data/processed/")
    if not processed_files:
        logger.error("No files to process. Exiting.")
        return
    
    # Process each file and collect results
    all_results = []
    for lasfile in processed_files:
        try:
            logger.info(f"Starting processing of file: {lasfile}")
            points, waterdelen, las_x = load_data(
                lasfile, 
                data_dir="data/processed/", 
                reference_date=waterdelen_reference_date
            )

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
            
            plot_map(raster_points, points, waterdelen, os.path.splitext(lasfile)[0], out_name_full)
            if create_tif:
                save_tif(raster_points, os.path.splitext(lasfile)[0], out_name_full)

            output_file_name = []
            logger.info(f"Finished processing file: {lasfile}")
            
            all_results.append({
                'points': points,
                'waterdelen': waterdelen,
                'filters': output_file_name,
            })
            
        except Exception as e:
            logger.error(f"Error processing file {lasfile}: {str(e)}")
            continue
    
    # Create combined outputs
    if all_results:
        combined_points = pd.concat([r['points'] for r in all_results])
        combined_waterdelen = pd.concat([r['waterdelen'] for r in all_results]).drop_duplicates()
        output_file_name = 'combined_results_' + '_'.join(all_results[0]['filters'])
        
        # Generate raster for combined points
        combined_raster_points = None
        if create_tif and combined_points.shape[0] > 0:
            combined_raster_points = generate_raster(combined_points, raster_averaging_mode)
            logger.info(f"Combined points are averaged based on their {raster_averaging_mode} value")
        
        # Create combined plot and TIF
        out_name_full = ""
        if combined_raster_points is not None:
            plot_map(
                combined_raster_points,
                combined_points,
                combined_waterdelen,
                output_file_name,
                out_name_full
            )
            
            if create_tif:
                save_tif(
                    combined_raster_points,
                    output_file_name,
                    out_name_full
                )

            # Calculate statistics per polygon if a polygon file is provided
            if polygon_file and combined_raster_points is not None:
                try:
                    polygon_stats = calculate_polygon_statistics(
                        combined_raster_points,
                        polygon_file,
                        polygon_statistic
                    )
                    
                    # Save results as GeoPackage
                    output_stats = f"data/output/{output_file_name}_polygon_stats.gpkg"
                    polygon_stats.to_file(output_stats, driver="GPKG")
                    logger.info(f"Polygon statistics saved to: {output_stats}")
                    
                except Exception as e:
                    logger.error(f"Error calculating polygon statistics: {str(e)}")
            
    
    logger.info("Finished processing all files")


if __name__ == "__main__":
    main(
        filter_geometries=True,
        frequencydiagram=False,
        buffer_distance=1,
        waterdelen_reference_date="2023-01-01",
        filter_centerline=True,
        polygon_file="data/external/peilafwijking.gdb",  # Example usage
        polygon_statistic="mean"
    )
