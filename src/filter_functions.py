
import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from shapely.geometry import shape, Point, MultiPolygon, Polygon, box
from shapely.strtree import STRtree


def filter_minmax(points, min_peil , max_peil):
    points = points.loc[(points['Z'] > min_peil)
                        & (points['Z'] < max_peil)
                        ]

    return points

def filter_hartlijn(points, hartlijn, buffer_size):
    hartlijn_buffered = hartlijn['geometry'].buffer(buffer_size, cap_style='flat') 
    hartlijn_buffered = gpd.GeoDataFrame(geometry=hartlijn_buffered)

    if 'index_right' in points.columns:
    # Drop the 'index_right' column
        points = points.drop(columns=['index_right'])

    points_in_buffer =  gpd.sjoin(points, hartlijn_buffered, predicate="within")
    # TODO add unique? only neccesarry when dataframe is not filtered initially
    print('filtered around a hartlijn')
    return points_in_buffer