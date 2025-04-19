import logging
import numpy as np
import geopandas as gpd
from xarray import DataArray
import rioxarray as rxr
from rasterio.transform import Affine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


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

    # INFO: this causes small shifts when visualizing rasters
    # because this acts as 'snap' to lower left corner
    # When rasterizing again, this lower left corner acts
    # as centerpoint of rastercell: there is your shift to correct!
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

    # To default rasterio structure where top left corner is used as origin
    # Therefore: flipping Y-axis to origin in the top left corner.
    da = da.reindex(
        {
            "X": np.arange(da.X.min(), da.X.max() + 1),
            "Y": np.arange(da.Y.max(), da.Y.min() - 1, -1),  # Reverse Y order
        }
    )

    # For correct processing of NoData values in ArcGIS Pro
    da = da.fillna(np.nan)

    # Set the spatial dimensions
    da.rio.set_spatial_dims(x_dim="X", y_dim="Y", inplace=True)
    logger.info(f"Resolution is {da.rio.resolution()}")

    # Apply shift of 0.5 times pixel size in both X and Y directions
    # to correct the spatial shift introduced by the original indexing
    x_shift = 0.5 * da.rio.resolution()[0]  # Pixel size in X direction
    y_shift = 0.5 * da.rio.resolution()[1]  # Pixel size in Y direction

    # Get the current transform
    current_transform = da.rio.transform()
   
    # Create the new transform with the applied shift
    new_transform = Affine(
        current_transform.a, current_transform.b, current_transform.c + x_shift,
        current_transform.d, current_transform.e, current_transform.f - y_shift
    )

    # Refresh the xarray coordinates based on the new transform
    x_coords = np.arange(
        new_transform.c,
        new_transform.c + new_transform.a * da.sizes["X"],
        new_transform.a
    )

    y_coords = np.arange(
        new_transform.f,
        new_transform.f + new_transform.e * da.sizes["Y"],
        new_transform.e
    )
   
    # Assign the new coordinates
    da = da.assign_coords({"X": x_coords, "Y": y_coords})

    # Set the spatial dimensions explicitly
    da.rio.set_spatial_dims(x_dim="X", y_dim="Y", inplace=True)

    # Set the CRS
    da.rio.write_crs("EPSG:28992", inplace=True)
  
    # Apply the new transform
    da.rio.write_transform(new_transform, inplace=True)

    return da
