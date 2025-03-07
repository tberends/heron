# -*- coding: utf-8 -*-

import logging
import geopandas as gpd
from shapely.geometry import Point
import matplotlib.pyplot as plt
import contextily as ctx

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def plot_frequency(points: gpd.GeoDataFrame, coordinates: tuple, las_name: str) -> None:
    """
    Plots a frequency diagram and a buffer around the point.

    Parameters:
        points (gpd.GeoDataFrame): The points to plot.
        coordinates (tuple): The coordinates of the point to buffer.
        las_name (str): The name of the LAS file.
    """
    # create a buffer around the point
    point = Point(coordinates)
    point_buffer = point.buffer(1)
    point_buffer_gdf = gpd.GeoDataFrame(geometry=[point_buffer])
    point_buffer_gdf.crs = points.crs

    # plot the point_buffer_gdf and the points
    fig, ax = plt.subplots(figsize=(10, 10))
    points.plot(ax=ax, color="blue")
    point_buffer_gdf.plot(ax=ax, color="red")
    ctx.add_basemap(ax, crs=points.crs, source=ctx.providers.CartoDB.Voyager)
    plt.legend(["points", "point_buffer_gdf"])
    plt.savefig(f"data/output/{las_name}_buffer.png")
    plt.clf()

    if "index_right" in points.columns:
        # Drop the 'index_right' column
        points = points.drop(columns=["index_right"])

    points_in_buffer = gpd.sjoin(points, point_buffer_gdf, predicate="within")

    if len(points_in_buffer) == 0:
        logger.info("No points found in buffer for frequency diagram")
        return

    # Print info
    logger.info(f"Number of points in buffer: {len(points_in_buffer)}")
    logger.info(f"Most common Z-value: {points_in_buffer['Z'].mode()[0]}")

    # plot frequency diagram with Z values on y-axis and number of points on x-axis
    plt.rcParams["font.family"] = "Helvetica"
    plt.hist(
        points_in_buffer["Z"],
        bins=100,
        orientation="horizontal",
        color="darkblue",
    )
    plt.ylabel("Waterlevel (mNAP)")
    plt.xlabel("Number of points")
    plt.title(f"Most common Z-value: {round(points_in_buffer['Z'].mode()[0], 2)} mNAP")
    plt.savefig(f"data/output/{las_name}_frequencydiagram.png")
