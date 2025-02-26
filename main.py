# -*- coding: utf-8 -*-
"""
The scripts reads in a .las/.laz file. Several functions filtering the .las/.laz can be called
    to acquire the desired output of the file. If a function is used it adds an abbrevation
    describing the function actions. 

output are stored in .csv files for convenience.

At last the a .tif file can be made with a size of 1x1m from the remaining points. The Z
    value of the raster cells are based on the mean, modus or median (user-defined) value of 
    points in the cell.

"""

import os
from typing import List

import numpy as np
import pandas as pd
import geopandas as gpd
import laspy
import contextily as ctx
import matplotlib.pyplot as plt
from pyproj import Transformer

from src.get_waterdelen import get_waterdelen
from src.filter_spatial import filter_spatial
from src.generate_raster import generate_raster
from src.filter_functions import filter_by_z_value, filter_by_proximity_to_centerline
from src.plot_frequency import plot_frequency


def load_data(las_name, data_dir=r"data/raw/", in_extension=".laz", crs="EPSG:28992"):
    """
    Loads the .las files and converts them to a geopandas dataframe.
    Also loads the geometries used for filtering the .las files.

    Args:
        las_name (str): The name of the .las file to load.
        data_dir (str, optional): The directory where the .las file is located. Defaults to "data/raw/".
        in_extension (str, optional): The extension of the .las file. Defaults to ".laz".
        crs (str, optional): The coordinate reference system to use. Defaults to "EPSG:28992".

    Returns:
        tuple: A tuple containing the points dataframe, the waterdelen dataframe, and the lasX array.
    """
    # Bouw het pad correct op
    las_file = las_name + in_extension
    laz_file = os.path.join(data_dir, las_file)
    
    # Controleer of het bestand bestaat
    if not os.path.exists(laz_file):
        raise FileNotFoundError(f"Het bestand '{laz_file}' bestaat niet. Controleer of het pad correct is.")
    
    las = laspy.read(laz_file)

    # Print important header parameters in a readable format
    print("\nLAS Header Information:")
    print(f"Version: {las.header.version}")
    print(f"Point Format: {las.header.point_format}")
    print(f"Number of points: {las.header.point_count}")
    print(f"Bounds: \n  min: {las.header.mins}\n  max: {las.header.maxs}")
    print(f"Scale factors: {las.header.scales}")

    # Convert the las file to a geopandas dataframe using the scale factors and offset from header
    las_x = np.array(las.X * las.header.scales[0] + las.header.offsets[0])
    las_y = np.array(las.Y * las.header.scales[1] + las.header.offsets[1]) 
    las_z = np.array(las.Z * las.header.scales[2] + las.header.offsets[2])

    # additional data can be added to the dataframe here
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
        print("Geen waterdelen gevonden via PDOK API")
        waterdelen = gpd.GeoDataFrame(
            columns=["geometry"], crs=crs
        )

    return points, waterdelen, las_x


def apply_filters(
    points,
    waterdelen,
    filter_geometries,
    filter_minmax,
    min_peil,
    max_peil,
    filter_centerline,
    dist_centerline,
    output_file_name,
):
    """
    Applies filters to the points dataframe.

    Args:
        points (GeoDataFrame): The points dataframe.
        waterdelen (GeoDataFrame): The waterdelen dataframe.
        filter_geometries (bool): Whether to filter geometries.
        filter_minmax (bool): Whether to filter minmax.
        min_peil (int): The minimum peil.
        max_peil (int): The maximum peil.
        filter_centerline (bool): Whether to filter the centerline.
        dist_centerline (int): The distance of the centerline.
        output_file_name (List[str]): The name of the output file.

    Returns:
        tuple: A tuple containing the filtered points dataframe and the output file name.
    """
    if filter_geometries:
        points = filter_spatial(points, waterdelen)
        print("Files are filtered within geometries")
        output_file_name.append("spatial")

    if filter_minmax:
        points = filter_by_z_value(points, min_peil, max_peil)
        print("Points are filtered between a predefined minimum and maximum mNAP")
        output_file_name.append("minmax")

    if filter_centerline:
        centerline = gpd.read_file("data/external/centerline_test.shp")
        points = filter_by_proximity_to_centerline(points, centerline, dist_centerline)
        print("Points are filtered around a distance of " + str(dist_centerline) + "m")
        output_file_name.append("centerline")

    print("Number of points after filtering: ", len(points))
    return points, output_file_name


def create_plot(raster_points, waterdelen, las_name, lasX, out_name_full):
    """
    Creates a plot of the raster points and saves it as a .png file.

    Args:
        raster_points (GeoDataFrame): The raster points to plot.
        waterdelen (GeoDataFrame): The waterdelen dataframe.
        las_name (str): The name of the .las file.
        lasX (array): The lasX array.
        out_name_full (str): The full name of the output file.
    """
    # Check if raster_points is not None
    if raster_points is None:
        print("No raster points to plot")
        return
    fig, ax = plt.subplots(figsize=(10, 10))
    waterdelen.plot(ax=ax, facecolor="lightgrey", alpha=0.3, edgecolor="blue")
    raster_points.plot(ax=ax, cmap="viridis")
    ctx.add_basemap(ax, crs=raster_points.rio.crs, source=ctx.providers.CartoDB.Voyager)
    ax.set_title(
        "File: "
        + las_name
        + "\n"
        + "Number of lidar points: "
        + str(len(lasX))
        + "\n"
        + "Filter options: "
        + out_name_full,
    )

    FIG_DIR = r"data/output/"
    FIG_NAME = las_name + "_" + out_name_full + ".png"
    FIG_PATH = os.path.join(FIG_DIR, FIG_NAME)
    plt.savefig(FIG_PATH)
    # plt.show()


def save_tif(raster_points, las_name, out_name_full):
    """
    Saves the raster points to a .tif file.

    Args:
        raster_points (GeoDataFrame): The raster points to save.
        las_name (str): The name of the .las file.
        out_name_full (str): The full name of the output file.
    """
    if raster_points is None:
        return
    TIF_DIR = r"data/output/"
    TIF_NAME = las_name + "_" + out_name_full + ".tif"
    TIF_PATH = os.path.join(TIF_DIR, TIF_NAME)
    raster_points.rio.to_raster(TIF_PATH, recalc_transform=False)


def main(
    las_name: str = "X126000Y500000",
    in_extension: str = ".laz",
    filter_geometries: bool = False,
    filter_minmax: bool = False,
    min_peil: int = -1,
    max_peil: int = 1,
    filter_centerline: bool = False,
    dist_centerline: int = 2,
    raster_averaging_mode: str = "mode",
    create_tif: bool = True,
    output_file_name: List[str] = [],
    frequencydiagram: bool = False,
    coordinates: tuple = (126012.5, 500481),
):
    """
    The main function that loads the data, applies filters, and saves the output.

    Args:
        las_name (str, optional): The name of the .las file. Defaults to "X126000Y500000".
        in_extension (str, optional): The extension of the .las file. Defaults to ".laz".
        filter_geometries (bool, optional): Whether to filter geometries. Defaults to False.
        filter_minmax (bool, optional): Whether to filter minmax. Defaults to False.
        min_peil (int, optional): The minimum peil. Defaults to -1.
        max_peil (int, optional): The maximum peil. Defaults to 1.
        filter_centerline (bool, optional): Whether to filter the centerline. Defaults to False.
        dist_centerline (int, optional): The distance of the centerline. Defaults to 2.
        raster_averaging_mode (str, optional): The raster averaging mode. Defaults to "mode", can also be "mean" or "median".
        create_tif (bool, optional): Whether to create a .tif file. Defaults to True.
        output_file_name (List[str], optional): The name of the output file. Defaults to [].
        frequencydiagram (bool, optional): Whether to plot the frequency. Defaults to False.
        coordinates (tuple, optional): The coordinates in RD to plot the frequency. Defaults to (126012.5, 500481).
    """
    points, waterdelen, las_x = load_data(las_name, in_extension=in_extension)

    points, output_file_name = apply_filters(
        points,
        waterdelen,
        filter_geometries,
        filter_minmax,
        min_peil,
        max_peil,
        filter_centerline,
        dist_centerline,
        output_file_name,
    )

    if frequencydiagram:
        plot_frequency(points, coordinates, las_name)

    raster_points = None
    if create_tif and points.shape[0] > 0:
        raster_points = generate_raster(points, raster_averaging_mode)
        print("Points are averaged based on their", raster_averaging_mode, "value")

    out_name_full = "_".join(output_file_name)
    create_plot(raster_points, waterdelen, las_name, las_x, out_name_full)
    if create_tif:
        save_tif(raster_points, las_name, out_name_full)

    out_name_full = []


if __name__ == "__main__":
    main(filter_geometries=True, frequencydiagram=True)
    main(las_name="clouda404dd152634b782_Block_0", in_extension=".las",filter_geometries=True)
    main(las_name="126000_505000", in_extension=".las",filter_geometries=True)
