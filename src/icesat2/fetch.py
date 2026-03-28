from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Union

import numpy as np
from pyproj import Transformer

from src.import_data import get_waterdelen_for_points_gdf

from src.icesat2.config import Atl03Config, DEFAULT_ICESAT_BBOX_LONLAT
from src.icesat2.download import download_granules, list_hdf5_paths
from src.icesat2.geodataframe import photon_recarray_to_points_gdf
from src.icesat2.hdf5_atl03 import read_atl03_points_from_hdf5

ATL08_SHORT_NAME = "ATL08"


def fetch_icesat_points_gdf(
    temporal: tuple[str, str],
    logger: logging.Logger,
    bbox_lonlat: Optional[tuple[float, float, float, float]] = None,
    cache_dir: Union[str, Path] = "data/raw/icesat_hdf5",
    config: Optional[Atl03Config] = None,
    reference_date=None,
    crs_rd: str = "EPSG:28992",
) -> tuple:
    """
    Download ATL03 + ATL08, read ground-classified photons, return (points_gdf, waterdelen_gdf, x_array).

    ``x_array`` mirrors ``load_data`` third return (X coordinates as numpy array).
    """
    cfg = config or Atl03Config()
    bbox = bbox_lonlat if bbox_lonlat is not None else DEFAULT_ICESAT_BBOX_LONLAT
    cache = Path(cache_dir).expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)

    downloaded: list[Path] = []
    downloaded.extend(
        download_granules(
            logger=logger,
            out_dir=cache,
            bbox_lonlat=bbox,
            temporal=temporal,
            short_name=cfg.short_name,
            version=cfg.version,
        )
    )
    downloaded.extend(
        download_granules(
            logger=logger,
            out_dir=cache,
            bbox_lonlat=bbox,
            temporal=temporal,
            short_name=ATL08_SHORT_NAME,
            version=cfg.version,
        )
    )

    h5_files = list_hdf5_paths(downloaded)
    atl03_files = sorted({p for p in h5_files if p.name.startswith("ATL03_")})

    _empty_rec_dtype = [
        ("lon", "f8"),
        ("lat", "f8"),
        ("rd_x", "f8"),
        ("rd_y", "f8"),
        ("h_nap", "f8"),
        ("delta_time", "f8"),
        ("ph_class", "i4"),
        ("beam", "O"),
    ]

    if not atl03_files:
        logger.error("No ATL03 HDF5 files available after download.")
        empty = photon_recarray_to_points_gdf(np.recarray((0,), dtype=_empty_rec_dtype), crs_rd=crs_rd)
        wd = get_waterdelen_for_points_gdf(empty, crs=crs_rd, reference_date=reference_date)
        return empty, wd, np.array([], dtype=float)

    atl08_map = {p.name: p for p in cache.glob("ATL08_*.h5")}
    if not atl08_map:
        logger.warning(f"No ATL08 granules in {cache}; ground classification will be unavailable.")

    transformer_lonlat_to_rd = Transformer.from_crs("EPSG:4326", crs_rd, always_xy=True)

    all_points: list[np.ndarray] = []
    for i, fpath in enumerate(atl03_files, start=1):
        try:
            logger.info(f"[{i}/{len(atl03_files)}] Reading ATL03 {fpath.name}")
            atl08_name = fpath.name.replace("ATL03_", "ATL08_", 1)
            atl08_path = atl08_map.get(atl08_name)
            if atl08_path is None:
                logger.warning(f"{fpath.name}: no matching ATL08 ({atl08_name}) in {cache}.")
            pts = read_atl03_points_from_hdf5(
                h5_path=fpath,
                config=cfg,
                bbox_lonlat=bbox,
                transformer_lonlat_to_rd=transformer_lonlat_to_rd,
                logger=logger,
                atl08_path=atl08_path,
            )
            if pts.size > 0:
                all_points.append(pts)
        except Exception as e:
            logger.warning(f"Failed reading {fpath.name}: {e}")
            continue

    if not all_points:
        logger.error("No ATL03 photons extracted after filtering.")
        empty = photon_recarray_to_points_gdf(np.recarray((0,), dtype=_empty_rec_dtype), crs_rd=crs_rd)
        wd = get_waterdelen_for_points_gdf(empty, crs=crs_rd, reference_date=reference_date)
        return empty, wd, np.array([], dtype=float)

    combined = np.concatenate(all_points)
    logger.info(f"Total ICESat photons: {combined.size}")
    gdf = photon_recarray_to_points_gdf(combined, crs_rd=crs_rd)
    waterdelen = get_waterdelen_for_points_gdf(gdf, crs=crs_rd, reference_date=reference_date)
    x_arr = gdf["X"].to_numpy(dtype=float, copy=False)
    return gdf, waterdelen, x_arr
