

"""
Filters laz points within geometries 
"""



import numpy as np
import pandas as pd
from shapely.geometry import shape, Point, MultiPolygon, Polygon, box, MultiPoint
import geopandas as gpd

def filter_within_geometries(points, geometries):    
    # join the dataframes based on points that lie within the waterbodies GeoDataFram
    lasInWaterdeel = gpd.sjoin(points, geometries, predicate="within")

    # filter out unique combinations of X,Y coördinates (dependent on precision of data)
    lasIW_unique = ~lasInWaterdeel.duplicated(subset=['X', 'Y']) #, keep=False
    las_gdf_unique = lasInWaterdeel[lasIW_unique]

    return las_gdf_unique