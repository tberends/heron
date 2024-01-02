import numpy as np
import geopandas as gpd
from xarray import DataArray
import rioxarray as rxr


def generate_raster(points: gpd.GeoDataFrame, raster_averaging_mode: str) -> DataArray:
    """
    Generates a TIF file from a GeoPandas DataFrame.
    Creates a raster of 1x1m grid cells by taking either the mean, mode or median value of all points in the grid cell.

    Parameters:
    points (Union[gpd.GeoDataFrame, pd.DataFrame]): A DataFrame containing the points to be rasterized.
    tif_averaging_mode (str): The method of averaging to use. Can be 'mean', 'mode', or 'median'.

    Returns:
    rxr.DataArray: A DataArray containing the rasterized points.
    """
    # Ensure points is a normal pandas dataframe
    if isinstance(points, gpd.GeoDataFrame):
        points = points.drop(columns="geometry")

    points["X"] = points["X"].astype(np.int32)
    points["Y"] = points["Y"].astype(np.int32)
    points["Z"] = points["Z"].astype(np.float32)

    # Reset the index
    points = points.reset_index(drop=True)
    points = points[["X", "Y", "Z"]]
    da = points.set_index(["Y", "X"])

    # Remove duplicate indices by keeping the mean, mode, or median value
    if raster_averaging_mode == "mean":
        da = da.groupby(level=[0, 1]).mean().to_xarray()["Z"]
    elif raster_averaging_mode == "mode":
        da = (
            da.groupby(level=[0, 1])
            .agg(lambda x: x.value_counts().index[0])
            .to_xarray()["Z"]
        )
    elif raster_averaging_mode == "median":
        da = da.groupby(level=[0, 1]).median().to_xarray()["Z"]

    da = da.reindex(
        {
            "X": np.arange(da.X.min(), da.X.max() + 1),
            "Y": np.arange(da.Y.min(), da.Y.max() + 1),
        }
    )

    # Set the spatial dimensions
    da.rio.set_spatial_dims(x_dim="X", y_dim="Y", inplace=True)
    print("Resolution is", da.rio.resolution())

    # Set the CRS
    da.rio.write_crs("EPSG:28992", inplace=True)

    # Set the transform
    da.rio.write_transform(da.rio.transform(), inplace=True)

    return da
