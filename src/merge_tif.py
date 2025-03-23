import logging
import os
import rioxarray as rxr
import xarray as xr

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def merge_tif_files(output_dir='data/output/', output_filename='merged_output.tif', merge_dim='band'):
    """
    Merge all .tif files in the specified directory into a single .tif file.

    Args:
        output_dir (str): The directory containing .tif files to merge.
        output_filename (str): The name of the output merged .tif file.
        merge_dim (str): Dimension to merge along. Options:
            - 'band': Stack files as different bands (default)
            - 'x': Merge files horizontally
            - 'y': Merge files vertically
            - 'time': Merge as temporal sequence
    """
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Get a list of all the .tif files in the specified directory
    tif_files = [os.path.join(output_dir, f) for f in os.listdir(output_dir) if f.endswith('.tif')]
    
    if not tif_files:
        logger.error("No .tif files found in the specified directory.")
        return
    
    # Open all the .tif files using xarray
    rasters = [rxr.open_rasterio(f) for f in tif_files]

    # Merge the rasters along the specified dimension
    mosaic = xr.concat(rasters, dim='band').mean(dim='band')

    logger.info(f"Final mosaic shape: {mosaic.shape}")

    # Create full output path
    output_path = os.path.join(output_dir, output_filename)
    
    # Write the merged raster
    save_tif(mosaic, output_path)

def save_tif(raster_points, out_name_full):
    """
    Saves the raster points to a .tif file.

    Args:
        raster_points (DataArray): The raster points to save.
        out_name_full (str): The full path of the output file.
    """
    if raster_points is None:
        return

    raster_points.rio.to_raster(out_name_full, recalc_transform=False)
    logger.info(f"TIF file saved to: {out_name_full}")

# Add main function
if __name__ == "__main__":
    merge_tif_files()
