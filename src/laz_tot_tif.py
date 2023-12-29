import os
import json
import numpy as np
import geopandas as gpd
import pandas as pd
from shapely.geometry import shape, Point, MultiPolygon, Polygon, box, MultiPoint
import matplotlib.pyplot as plt
import rioxarray as rxr
import contextily as ctx

   
def laz_to_tif(points, tif_averaging_mode):
    # create a raster of 1x1m grid cells by taking either the
    #   mean, modus or median value of all points in the grid cell

    # create a normal pandas dataframe
    if isinstance(points, gpd.GeoDataFrame):
        points = points.drop(columns='geometry')
    
    points["X"] = points["X"].astype(np.int32)
    points["Y"] = points["Y"].astype(np.int32)
    points["Z"] = points["Z"].astype(np.float32)

    # reset the index
    points = points.reset_index(drop=True)
    points = points[["X", "Y", "Z"]]
    da = points.set_index(["Y", "X"])

    if tif_averaging_mode == 'mean':
        # remove duplicate indices by keeping the the mean value
        da_mean = da.groupby(level=[0, 1]).agg(lambda x: x.mean())
        da = da[~da.index.duplicated(keep="first")]
        da = da_mean.to_xarray()["Z"]

    if tif_averaging_mode == 'modus':
        # remove duplicate indices by keeping the most frequent value
        da_modus = da.groupby(level=[0, 1]).agg(lambda x: x.value_counts().index[0])
        da = da[~da.index.duplicated(keep="first")]
        da = da_modus.to_xarray()["Z"]

    if tif_averaging_mode == 'median':
        # remove duplicate indices by keeping the the median value
        da_median = da.groupby(level=[0, 1]).agg(lambda x: x.median())
        da = da[~da.index.duplicated(keep="first")]
        da = da_median.to_xarray()['Z']


    da = da.reindex(
    {
        "X": np.arange(da.X.min(), da.X.max() + 1),
        "Y": np.arange(da.Y.min(), da.Y.max() + 1),
    }
    )
    
    # set the spatial dimensions
    da.rio.set_spatial_dims(x_dim="X", y_dim="Y", inplace=True)
    print('Resulution is' , da.rio.resolution())
    # set the crs
    da.rio.write_coordinate_system(inplace=True)
    da.rio.write_crs("EPSG:28992", inplace=True)

    # set the transform
    da.rio.write_transform(da.rio.transform(), inplace=True)

    return da
