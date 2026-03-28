import json
import logging
import time
from datetime import datetime, date
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional, Tuple, Union
from zipfile import ZipFile

import geopandas as gpd
import pandas as pd
import requests
from requests.structures import CaseInsensitiveDict

logger = logging.getLogger(__name__)

# Chunk size when streaming BGT ZIP to disk (avoids holding full response in RAM).
_ZIP_STREAM_CHUNK = 8 * 1024 * 1024

def get_waterdelen(
    bbox: Tuple[float, float, float, float], 
    crs: str = "EPSG:28992",
    reference_date: Optional[Union[str, datetime, date]] = None
) -> Optional[gpd.GeoDataFrame]:
    """
    Download waterdelen from BGT API based on a bounding box.
    
    Args:
        bbox (tuple): Bounding box coordinates (minx, miny, maxx, maxy)
        crs (str): Coordinate system of the bounding box. Defaults to Dutch RD New.
        reference_date (str, datetime, date, optional): Reference date to filter water bodies.
                                                        Only returns water bodies valid on this specific date.
                                                        Format: YYYY-MM-DD if string. Defaults to None (returns all).
    
    Returns:
        GeoDataFrame: Downloaded waterdelen data or None if download fails
    """
    try:
        # Configure API parameters
        base_url = "https://api.pdok.nl"
        featurelist = ["waterdeel"]
        fileformat = "citygml"
        
        # Convert bbox to polygon WKT string
        minx, miny, maxx, maxy = bbox
        area_km2 = max(0.0, (maxx - minx) * (maxy - miny)) / 1_000_000.0
        logger.info(
            f"PDOK BGT request bbox (RD, m): ({minx:.1f}, {miny:.1f}) – ({maxx:.1f}, {maxy:.1f}); "
            f"~{area_km2:.0f} km² extent"
        )
        geofilter = f'POLYGON(({minx} {miny},{maxx} {miny},{maxx} {maxy},{minx} {maxy},{minx} {miny}))'
        
        # Request download URL
        api_url = f"{base_url}/lv/bgt/download/v1_0/full/custom"
        headers = CaseInsensitiveDict({
            "accept": "application/json",
            "Content-Type": "application/json"
        })
        
        data = json.dumps({
            "featuretypes": featurelist,
            "format": fileformat,
            "geofilter": geofilter
        })
        
        # Get download URL
        response = requests.post(api_url, headers=headers, data=data)
        response.raise_for_status()
        download_url = response.json()['_links']['status']['href']
        
        # Poll until download is ready
        status_url = f"{base_url}{download_url}"
        while True:
            response = requests.get(status_url)
            response.raise_for_status()
            status = response.json()
            
            if status['status'] == 'COMPLETED':
                zip_url = status['_links']['download']['href']
                break
            elif status['status'] == 'FAILED':
                raise Exception("BGT download failed")
                
            logger.info(f"PDOK BGT export progress: {status.get('progress', '...')}%")
            time.sleep(1)
        
        # Download ZIP to disk (stream), then extract and read GML from a real path.
        # Loading the full ZIP into BytesIO and passing a zipfile handle into pyogrio/GDAL
        # has been associated with native crashes on large BGT exports (macOS).
        download_href = f"{base_url}{zip_url}"
        logger.info("PDOK BGT export ready; downloading ZIP (stream to disk)…")
        with TemporaryDirectory(prefix="heron_bgt_") as tmp:
            tmp_path = Path(tmp)
            zip_path = tmp_path / "bgt_waterdeel.zip"
            with requests.get(download_href, stream=True, timeout=600) as zip_response:
                zip_response.raise_for_status()
                with open(zip_path, "wb") as out_f:
                    for chunk in zip_response.iter_content(chunk_size=_ZIP_STREAM_CHUNK):
                        if chunk:
                            out_f.write(chunk)
            zip_bytes = zip_path.stat().st_size
            logger.info(f"PDOK BGT ZIP on disk ({zip_bytes // (1024 * 1024)} MiB); extracting…")

            with ZipFile(zip_path, "r") as zipfile:
                zipfile.extractall(tmp_path)

            gml_paths = sorted(tmp_path.rglob("*.gml"))
            if not gml_paths:
                raise ValueError("No .gml file found in BGT ZIP")
            gml_path = gml_paths[0]
            if len(gml_paths) > 1:
                logger.info(f"Using first GML in archive: {gml_path.name} ({len(gml_paths)} candidates)")
            logger.info(f"Reading waterdeel geometries with GeoPandas/pyogrio: {gml_path}")
            gdf = gpd.read_file(gml_path)
        
        # Check column names in case they're different in newer API versions
        reg_col = 'tijdstipRegistratie' if 'tijdstipRegistratie' in gdf.columns else 'beginRegistratie'
        end_col = 'eindRegistratie' if 'eindRegistratie' in gdf.columns else 'eindReg_date'
        
        # Convert date columns to datetime objects
        if reg_col in gdf.columns:
            gdf[reg_col] = pd.to_datetime(gdf[reg_col])
        if end_col in gdf.columns:
            gdf[end_col] = pd.to_datetime(gdf[end_col])
        
        # Filter by reference date if provided
        if reference_date is not None:
            # Store original count for logging
            original_count = len(gdf)
            
            # Convert reference_date to datetime object if it's a string or date
            if isinstance(reference_date, str):
                ref_date_obj = datetime.strptime(reference_date, "%Y-%m-%d")
            elif isinstance(reference_date, date):
                ref_date_obj = datetime.combine(reference_date, datetime.min.time())
            else:
                ref_date_obj = reference_date
            
            logger.info(f"Filtering waterdelen for reference date: {ref_date_obj.strftime('%Y-%m-%d')}")
            
            # Simplified filtering
            # 1. waterdelen that were registered before or on the reference date
            # 2. AND either have no end date or an end date after the reference date
            gdf = gdf[
                ((gdf[reg_col] <= ref_date_obj) & (gdf[end_col] > ref_date_obj)) | 
                ((gdf[reg_col] <= ref_date_obj) & gdf[end_col].isna())
            ]
            
            logger.info(f"Filtered from {original_count} to {len(gdf)} waterdelen valid on {ref_date_obj.strftime('%Y-%m-%d')}")
                
        return gdf

    except Exception as e:
        logger.error(f"Error downloading waterdelen: {str(e)}")
        return None

