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
import numpy as np
import pandas as pd
import laspy
from shapely.geometry import shape, Point, MultiPolygon, Polygon, box, MultiPoint
import geopandas as gpd
from src.filter_within_geometries import filter_within_geometries
from src.laz_tot_tif import laz_to_tif
from src.filter_functions import *
import rioxarray as rxr
import contextily as ctx
import matplotlib.pyplot as plt

""" Step 1: Load input & create a geopandas dataframe from the relevant columns """
DATA_DIR = r"data/raw/"
LAS_NAME = "X126000Y500000"  # change the name of the .las file in the raw directory
IN_EXTENSION = ".laz"
LAS_LOC = LAS_NAME + IN_EXTENSION
LAZ_FILE = os.path.join(DATA_DIR, LAS_LOC)
las = laspy.read(LAZ_FILE)
crs = "EPSG:28992"

lasX = np.array(las.X / 1000)
lasY = np.array(las.Y / 1000)
lasZ = np.array(las.Z / 1000)

# additional data can be addes to the dataframe here
data_coord = pd.DataFrame({"X": lasX, "Y": lasY, "Z": lasZ})

points = gpd.GeoDataFrame(
    data_coord, geometry=gpd.points_from_xy(data_coord.X, data_coord.Y), crs=crs
)
print("Total points: ", len(lasX))

# load shapefiles geometries
waterdelen = gpd.read_file("data/external/bgt_waterdeel.shp")

# User can add more parts so they can join with additional information from polygon to points
waterdelen = gpd.GeoDataFrame(waterdelen["geometry"], geometry=waterdelen["geometry"])


""" 
Step 2: define filter actions  
Choose which filter options the user wants to use for processing the .las files

"""

filter_geometries = (
    True  # option to filter .las points within shapefiles (e.g. waterdelen)
)
filter_minmax = False  # option for filtering between mean and mad value
min_peil = -1  # lower Z value for which points are filtered out
max_peil = 1  # upper Z value for which points are filtered out
filter_hartlijn = False  # filter around hartlijn of e.g. waterbody (to decrease for isntance the effect of vegetation)
dist_hartlijn = 2  # size of buffer from hartlijn (m)
tif_averaging_mode = (
    "median"  # option for chosing value used for tif mean, mode, median
)
create_tif = True  # average the values based on option above and create a 1x1m grid
output_file_name = []  # list of options set to true used to adjust name of output file


"""
Step 3: execute functions
"""
if filter_geometries == True:
    points = filter_within_geometries(points, waterdelen)
    print("files are filtered within geometries")
    output_file_name.append("fwg")


if filter_minmax == True:
    points = filter_minmax(points, min_peil, max_peil)
    print("points are filtered between a predefined minimum and maximum mNAP")
    output_file_name.append("minmax")


if filter_hartlijn == True:
    hartlijn = gpd.read_file("data/external/hartlijn_test.shp")
    output_file_name.append("hartlijn")
    print("points are filtered around a distance of " + str(dist_hartlijn) + "m")


if create_tif == True:
    # does not change the output point cloud.
    raster_points = laz_to_tif(points, tif_averaging_mode)
    print("points are averaged based on their", tif_averaging_mode, "value")


"""
Step 4: write outpout to file(s)
Create file extensions based on functions executed in the scripts. 
For every functions a abbreviation is added. 
"""

out_name_full = "_".join(output_file_name)
WRITE_DIR = r"data/output/"  # back to /processed
WRITE_NAME = LAS_NAME + "_" + out_name_full + ".csv"
WRITE_PATH = os.path.join(WRITE_DIR, WRITE_NAME)
points.to_csv(WRITE_PATH, index=False)

if create_tif == True:
    fig, ax = plt.subplots(figsize=(10, 10))
    ctx.add_basemap(ax, crs=raster_points.rio.crs, source=ctx.providers.CartoDB.Voyager)
    raster_points.plot(ax=ax, cmap="terrain")
    waterdelen.plot(ax=ax, facecolor="none", edgecolor="blue")

    TIF_DIR = r"data/tifs/"
    TIF_NAME = LAS_NAME + "_" + out_name_full + ".tif"
    TIF_PATH = os.path.join(TIF_DIR, TIF_NAME)
    raster_points.rio.to_raster(TIF_PATH, recalc_transform=False)
