from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence


def download_granules(
    logger: logging.Logger,
    out_dir: Path,
    bbox_lonlat: tuple[float, float, float, float],
    temporal: tuple[str, str],
    short_name: str,
    version: str,
) -> list[Path]:
    import earthaccess

    out_dir.mkdir(parents=True, exist_ok=True)
    earthaccess.login(strategy="environment")

    kwargs = dict(
        short_name=short_name,
        version=version,
        bounding_box=bbox_lonlat,
        temporal=temporal,
    )
    results = earthaccess.search_data(**kwargs)
    logger.info(f"Earthaccess: found {len(results)} granules for {short_name} v{version}.")
    if len(results) == 0:
        return []

    files = earthaccess.download(results, str(out_dir))
    logger.info(f"Earthaccess: downloaded {len(files)} files into {out_dir}.")
    return [Path(f) for f in files]


def list_hdf5_paths(paths: Sequence[Path]) -> list[Path]:
    return [p for p in paths if p.suffix.lower() in {".h5", ".hdf5", ".hdf"}]
