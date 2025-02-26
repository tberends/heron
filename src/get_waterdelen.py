import requests
from requests.structures import CaseInsensitiveDict
import json
import time
from zipfile import ZipFile
from io import BytesIO
import geopandas as gpd
from typing import Tuple, Optional

def get_waterdelen(bbox: Tuple[float, float, float, float], crs: str = "EPSG:28992") -> Optional[gpd.GeoDataFrame]:
    """
    Download waterdelen from BGT API based on a bounding box.
    
    Args:
        bbox (tuple): Bounding box coordinates (minx, miny, maxx, maxy)
        crs (str): Coordinate system of the bounding box. Defaults to Dutch RD New.
    
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
                
            print(f"Download progress: {status.get('progress', '...')}%")
            time.sleep(1)
        
        # Download and process ZIP
        zip_response = requests.get(f"{base_url}{zip_url}")
        zip_response.raise_for_status()
        
        with ZipFile(BytesIO(zip_response.content)) as zipfile:
            # Read first GML file in ZIP
            first_file = zipfile.namelist()[0]
            with zipfile.open(first_file) as gml_file:
                gdf = gpd.read_file(gml_file)
                
        return gdf

    except Exception as e:
        print(f"Error downloading waterdelen: {str(e)}")
        return None

