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

from src.filter_spatial import filter_spatial
from src.generate_tif import generate_tif
from src.filter_functions import filter_by_z_value, filter_by_proximity_to_centerline


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
    las_loc = las_name + in_extension
    laz_file = os.path.join(data_dir, las_loc)
    las = laspy.read(laz_file)

    las_x = np.array(las.X / 1000)
    las_y = np.array(las.Y / 1000)
    las_z = np.array(las.Z / 1000)

    # additional data can be added to the dataframe here
    data_coord = pd.DataFrame({"X": las_x, "Y": las_y, "Z": las_z})

    points = gpd.GeoDataFrame(
        data_coord, geometry=gpd.points_from_xy(data_coord.X, data_coord.Y), crs=crs
    )
    print("Total points: ", len(las_x))

    # load geometries
    waterdelen = gpd.read_file("data/external/bgt_waterdeel.gml")

    # User can add more parts so they can join with additional information from polygon to points
    waterdelen = gpd.GeoDataFrame(
        waterdelen["geometry"], geometry=waterdelen["geometry"]
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
        print("files are filtered within geometries")
        output_file_name.append("spatial")

    if filter_minmax:
        points = filter_by_z_value(points, min_peil, max_peil)
        print("points are filtered between a predefined minimum and maximum mNAP")
        output_file_name.append("minmax")

    if filter_centerline:
        centerline = gpd.read_file("data/external/centerline_test.shp")
        points = filter_centerline(points, centerline, dist_centerline)
        print("points are filtered around a distance of " + str(dist_centerline) + "m")
        output_file_name.append("centerline")

    return points, output_file_name


def save_to_csv(points, LAS_NAME, output_file_name):
    """
    Saves the points dataframe to a .csv file.

    Args:
        points (GeoDataFrame): The points dataframe to save.
        LAS_NAME (str): The name of the .las file.
        output_file_name (str): The name of the output file.
    """
    WRITE_DIR = r"data/processed"
    WRITE_NAME = LAS_NAME + "_" + output_file_name + ".csv"
    WRITE_PATH = os.path.join(WRITE_DIR, WRITE_NAME)
    points.to_csv(WRITE_PATH, index=False)


def create_plot(raster_points, waterdelen, LAS_NAME, lasX, out_name_full):
    """
    Creates a plot of the raster points and saves it as a .png file.

    Args:
        raster_points (GeoDataFrame): The raster points to plot.
        waterdelen (GeoDataFrame): The waterdelen dataframe.
        LAS_NAME (str): The name of the .las file.
        lasX (array): The lasX array.
        out_name_full (str): The full name of the output file.
    """
    fig, ax = plt.subplots(figsize=(10, 10))
    ctx.add_basemap(
        ax, crs=raster_points.rio.crs, source=ctx.providers.OpenStreetMap.Mapnik
    )
    ctx.add_basemap(ax, crs=raster_points.rio.crs, source=ctx.providers.CartoDB.Voyager)
    waterdelen.plot(ax=ax, facecolor="lightgrey", alpha=0.3, edgecolor="blue")
    raster_points.plot(ax=ax, cmap="viridis")
    ax.set_title(
        "File: "
        + LAS_NAME
        + "\n"
        + "Number of lidar points: "
        + str(len(lasX))
        + "\n"
        + "Filter options: "
        + out_name_full,
    )

    FIG_DIR = r"data/output/"
    FIG_NAME = LAS_NAME + "_" + out_name_full + ".png"
    FIG_PATH = os.path.join(FIG_DIR, FIG_NAME)
    plt.savefig(FIG_PATH)
    plt.show()


def save_tif(raster_points, LAS_NAME, out_name_full):
    """
    Saves the raster points to a .tif file.

    Args:
        raster_points (GeoDataFrame): The raster points to save.
        LAS_NAME (str): The name of the .las file.
        out_name_full (str): The full name of the output file.
    """
    TIF_DIR = r"data/output/"
    TIF_NAME = LAS_NAME + "_" + out_name_full + ".tif"
    TIF_PATH = os.path.join(TIF_DIR, TIF_NAME)
    raster_points.rio.to_raster(TIF_PATH, recalc_transform=False)


def save_output(
    points, raster_points, waterdelen, las_x, LAS_NAME, output_file_name, create_tif
):
    """
    Saves the output to .csv and .tif files and creates a plot.

    Args:
        points (GeoDataFrame): The points dataframe.
        raster_points (GeoDataFrame): The raster points.
        waterdelen (GeoDataFrame): The waterdelen dataframe.
        lasX (array): The lasX array.
        LAS_NAME (str): The name of the .las file.
        output_file_name (List[str]): The name of the output file.
        create_tif (bool): Whether to create a .tif file.
    """
    out_name_full = "_".join(output_file_name)
    save_to_csv(points, LAS_NAME, out_name_full)
    if create_tif:
        create_plot(raster_points, waterdelen, LAS_NAME, las_x, out_name_full)
        save_tif(raster_points, LAS_NAME, out_name_full)


def main(
    LAS_NAME: str = "X126000Y500000",
    filter_geometries: bool = True,
    filter_minmax: bool = True,
    min_peil: int = -1,
    max_peil: int = 1,
    filter_centerline: bool = False,
    dist_centerline: int = 2,
    tif_averaging_mode: str = "mode",
    create_tif: bool = True,
    output_file_name: List[str] = [],
):
    """
    The main function that loads the data, applies filters, and saves the output.

    Args:
        LAS_NAME (str, optional): The name of the .las file. Defaults to "X126000Y500000".
        filter_geometries (bool, optional): Whether to filter geometries. Defaults to True.
        filter_minmax (bool, optional): Whether to filter minmax. Defaults to True.
        min_peil (int, optional): The minimum peil. Defaults to -1.
        max_peil (int, optional): The maximum peil. Defaults to 1.
        filter_centerline (bool, optional): Whether to filter the centerline. Defaults to False.
        dist_centerline (int, optional): The distance of the centerline. Defaults to 2.
        tif_averaging_mode (str, optional): The tif averaging mode. Defaults to "mode", can also be "mean" or "median".
        create_tif (bool, optional): Whether to create a .tif file. Defaults to True.
        output_file_name (List[str], optional): The name of the output file. Defaults to [].
    """
    points, waterdelen, las_x = load_data(LAS_NAME)

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

    raster_points = None
    if create_tif:
        raster_points = generate_tif(points, tif_averaging_mode)
        print("points are averaged based on their", tif_averaging_mode, "value")

    save_output(
        points, raster_points, waterdelen, las_x, LAS_NAME, output_file_name, create_tif
    )


if __name__ == "__main__":
    main()
