#!/usr/bin/env python3
"""
Download ICESat-2 ATL08 (v007) with earthaccess, extract `h_te_best_fit`,
filter strong beams and quality/surface flags, transform to RD New (EPSG:28992),
bin to 1 km cells, compute per-cell statistics, optionally interpolate gaps,
export GeoTIFF, and plot.

Notes
-----
- ATL08 structure can vary slightly across product versions. This script searches
  for expected HDF5 dataset paths and fails gracefully when a dataset is missing.
- Downloading 2020-2026 can be large.
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import sys
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Optional

import numpy as np

from dotenv import load_dotenv

if TYPE_CHECKING:
    import xarray as xr


def _require_import(module_name: str, pip_hint: str) -> None:
    raise RuntimeError(
        f"Missing dependency: {module_name}. "
        f"Install it first (example): {pip_hint}"
    )


def _import_optional(module_name: str):
    try:
        return __import__(module_name)
    except Exception:
        return None


@dataclass(frozen=True)
class Atl08Config:
    short_name: str = "ATL08"
    version: str = "007"
    # Default includes all beams; actual selection is done per granule via sc_orient.
    beams: tuple[str, ...] = ("gt1l", "gt1r", "gt2l", "gt2r", "gt3l", "gt3r")
    auto_select_beams: bool = True
    quality_flag_value: int = 0
    # If not provided, we attempt to infer the land code from HDF5 flag attributes.
    surface_type_land_code: Optional[int] = None
    # ATL08 uses 1D photon-level arrays under <beam>/heights/
    h_te_best_fit_candidates: tuple[str, ...] = ("h_te_best_fit",)
    lat_candidates: tuple[str, ...] = ("lat_ph", "latitude")
    lon_candidates: tuple[str, ...] = ("lon_ph", "longitude")
    delta_time_candidates: tuple[str, ...] = ("delta_time",)
    quality_candidates: tuple[str, ...] = ("quality_flag", "quality_ph", "quality_photons")
    surface_type_candidates: tuple[str, ...] = ("surface_type", "surface_type_flag", "surface_type_ph")


def _strong_beams_from_sc_orient(sc_orient: int) -> list[str]:
    """Map sc_orient (0=backward, 1=forward) to beam sides."""
    # Forward: gt1r, gt2r, gt3r; Backward: gt1l, gt2l, gt3l.
    if sc_orient == 1:
        return ["gt1r", "gt2r", "gt3r"]
    if sc_orient == 0:
        return ["gt1l", "gt2l", "gt3l"]
    # Transitional/unknown: fall back to all beams.
    return ["gt1l", "gt1r", "gt2l", "gt2r", "gt3l", "gt3r"]


def build_logger(out_dir: Path, verbose: bool) -> logging.Logger:
    out_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("atl08")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.DEBUG if verbose else logging.INFO)
    sh.setFormatter(fmt)

    fh = logging.FileHandler(out_dir / "atl08_pipeline.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    if not logger.handlers:
        logger.addHandler(sh)
        logger.addHandler(fh)
    return logger


def parse_args() -> argparse.Namespace:
    default_bbox = (4.45, 52.14, 5.44, 53.20)  # lon_min, lat_min, lon_max, lat_max
    parser = argparse.ArgumentParser(description="Download and grid ICESat-2 ATL08 (v007) for Noord-Holland.")
    parser.add_argument("--bbox", nargs=4, type=float, default=default_bbox, metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"))
    parser.add_argument("--temporal", nargs=2, type=str, default=("2025-01-01", "2025-12-31"), metavar=("START", "END"))
    parser.add_argument("--out-dir", type=str, default="atl08_output")
    parser.add_argument("--out-prefix", type=str, default="atl08_nh_rdnew_1km")

    parser.add_argument("--stat", choices=("median", "mean"), default="median", help="Per-cell height statistic.")

    parser.add_argument("--cell-size-m", type=int, default=100, help="Grid cell size in meters (RD New).")

    parser.add_argument("--use-icepyx-subset", action="store_true",
                        help="Optional: use icepyx for subsetting/download (best-effort).")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def _first_existing_key(h5_group, candidates: Iterable[str]) -> Optional[str]:
    for k in candidates:
        if k in h5_group:
            return k
    return None


def _find_dataset_path(f, beam: str, heights_group: str, candidates: Iterable[str]) -> Optional[str]:
    # Common ATL06/ATL08 pattern: /<beam>/heights/<dataset>
    grp = f[f"{beam}/{heights_group}"]
    key = _first_existing_key(grp, candidates)
    if key is None:
        return None
    return f"{beam}/{heights_group}/{key}"


def _infer_land_code_from_attrs(ds) -> Optional[int]:
    # Try common HDF5 attributes for flag values/meanings.
    for attr_name in ("flag_values", "values", "flag_value"):
        if attr_name in ds.attrs:
            try:
                values = np.array(ds.attrs[attr_name]).astype(int).tolist()
            except Exception:
                continue
            # meanings might be in another attribute
            break
    else:
        values = None

    meanings = None
    for attr_name in ("flag_meanings", "flag_meaning", "meanings"):
        if attr_name in ds.attrs:
            meanings_raw = ds.attrs[attr_name]
            # Often a bytes string with spaces: b"ocean inland_water land"
            if isinstance(meanings_raw, (bytes, str)):
                meanings = str(meanings_raw).replace("\x00", "").strip().split()
            else:
                try:
                    meanings = [str(x) for x in meanings_raw]
                except Exception:
                    meanings = None
            break

    if values is None or meanings is None:
        return None

    # Attempt to map "land" (case-insensitive).
    meanings_lower = [m.lower() for m in meanings]
    for idx, m in enumerate(meanings_lower):
        if m == "land" or "land" in m:
            if idx < len(values):
                return int(values[idx])

    return None


def read_atl08_points_from_hdf5(
    h5_path: Path,
    config: Atl08Config,
    bbox_lonlat: tuple[float, float, float, float],
    quality_flag_value: int,
    transformer_lonlat_to_rd,
    logger: logging.Logger,
) -> np.ndarray:
    """Lees ATL08 punten uit één HDF5-granule.

    Returns een numpy structured array met columns:
    lon, lat, rd_x, rd_y, h, delta_time, quality_flag, surface_type_land, beam
    """
    try:
        import h5py
    except Exception:
        _require_import("h5py", "pip install h5py")

    lon_min, lat_min, lon_max, lat_max = bbox_lonlat

    # 3D transform: WGS84 ellipsoidal height -> RD New + NAP height.
    # Note: Vertical component may be unavailable if the needed PROJ geoid grids
    # are not present in the environment; we log a warning in that case.
    try:
        from pyproj import Transformer

        transformer_llh_to_rdnap = Transformer.from_crs(
            "EPSG:4979",  # WGS84 3D (lon/lat/h_ellipsoid)
            "EPSG:7415",  # Amersfoort / RD New + NAP height
            always_xy=True,
        )
    except Exception as e:
        logger.warning(f"Kon 3D LLH->RD+NAP transformer niet maken; fallback naar 2D. Details: {e}")
        transformer_llh_to_rdnap = None

    with h5py.File(h5_path, "r") as f:
        points_list: list[np.recarray] = []

        selected_beams = list(config.beams)
        if config.auto_select_beams:
            try:
                sc_orient_arr = f["/orbit_info/sc_orient"][()]
                sc_orient = int(np.atleast_1d(sc_orient_arr)[0])
                selected_beams = [
                    b for b in _strong_beams_from_sc_orient(sc_orient) if b in set(config.beams)
                ]
                logger.info(f"{h5_path.name}: sc_orient={sc_orient} -> beams={selected_beams}")
            except Exception as e:
                logger.warning(
                    f"{h5_path.name}: could not read /orbit_info/sc_orient; using config.beams. Details: {e}"
                )

        # Determine which column in surf_type corresponds to "land".
        # In v007 ATL08: surf_type has shape (N, 5) and ds_surf_type is a dimension scale with
        # flag_values = [1..5] and flag_meanings = ["land","ocean","seaice","landice","inland_water"].
        land_col_idx = 0
        if "ds_surf_type" in f:
            ds_surf = f["ds_surf_type"]
            land_code = config.surface_type_land_code
            if land_code is None:
                land_code = _infer_land_code_from_attrs(ds_surf)
            ds_vals = np.asarray(ds_surf[:]).astype(int).reshape(-1)
            matches = np.where(ds_vals == int(land_code) if land_code is not None else ds_vals[0])[0]
            if matches.size:
                land_col_idx = int(matches[0])
        else:
            logger.warning(f"{h5_path.name}: ds_surf_type ontbreekt; neem land_col_idx=0.")

        for beam in selected_beams:
            if beam not in f:
                continue

            try:
                lat = f[f"{beam}/land_segments/latitude"][:]
                lon = f[f"{beam}/land_segments/longitude"][:]
                dt = f[f"{beam}/land_segments/delta_time"][:]
                h = f[f"{beam}/land_segments/terrain/h_te_best_fit"][:]
                quality = f[f"{beam}/land_segments/terrain_flg"][:]
                surf_type = f[f"{beam}/land_segments/surf_type"][:]  # shape (N, 5)
            except KeyError as e:
                logger.warning(f"{h5_path.name}: beam={beam} ontbrekende datasets ({e}). Skipping beam.")
                continue

            lat = np.asarray(lat).reshape(-1)
            lon = np.asarray(lon).reshape(-1)
            dt = np.asarray(dt).reshape(-1)
            h = np.asarray(h).reshape(-1)
            quality = np.asarray(quality).reshape(-1)
            surf_type = np.asarray(surf_type)

            if not (lat.size == lon.size == dt.size == h.size == quality.size):
                logger.warning(f"{h5_path.name}: beam={beam} size mismatch lat/lon/dt/h/quality. Skipping.")
                continue
            if surf_type.ndim != 2 or surf_type.shape[0] != lat.size:
                logger.warning(f"{h5_path.name}: beam={beam} unexpected surf_type shape {surf_type.shape}. Skipping.")
                continue

            mask_bbox = (lon >= lon_min) & (lon <= lon_max) & (lat >= lat_min) & (lat <= lat_max)
            if not np.any(mask_bbox):
                continue

            quality = quality.astype(int, copy=False)
            mask_quality = quality == int(quality_flag_value)
            mask_land = surf_type[:, land_col_idx].astype(int, copy=False) == 1

            # Extra kwaliteitsfilters (best-effort mapping naar datasetnamen in ATL08 v007).
            # - h_te_sigma_sh komt in v007 niet altijd voor; we gebruiken dan h_te_std.
            # - "signal_photons" komt niet als eenvoudige 1D dataset onder land_segments; we gebruiken n_te_photons.
            h_sigma = None
            for cand in (
                f"{beam}/land_segments/terrain/h_te_sigma_sh",
                f"{beam}/land_segments/terrain/h_te_sigma_sh_20m",
                f"{beam}/land_segments/terrain/h_te_std",
                f"{beam}/land_segments/terrain/h_te_uncertainty",
            ):
                if cand in f:
                    h_sigma = np.asarray(f[cand][:]).reshape(-1)
                    break
            if h_sigma is None or h_sigma.size != h.size:
                logger.warning(
                    f"{h5_path.name}: beam={beam} kon geen passende h_te sigma dataset vinden; skip sigma-filter."
                )
                mask_sigma = np.ones_like(h, dtype=bool)
            else:
                mask_sigma = np.isfinite(h_sigma) & (h_sigma < 2.0)

            signal_ph = None
            for cand in (
                f"{beam}/land_segments/signal_photons",
                f"{beam}/land_segments/terrain/n_te_photons",
                f"{beam}/land_segments/terrain/photon_rate_te",
            ):
                if cand in f:
                    signal_ph = np.asarray(f[cand][:]).reshape(-1)
                    break
            if signal_ph is None or signal_ph.size != h.size:
                logger.warning(
                    f"{h5_path.name}: beam={beam} kon geen passende photon-signal dataset vinden; skip signal-filter."
                )
                mask_signal = np.ones_like(h, dtype=bool)
            else:
                mask_signal = np.isfinite(signal_ph) & (signal_ph > 20)

            mask = mask_bbox & mask_quality & mask_land & mask_sigma & mask_signal & np.isfinite(h)
            if not np.any(mask):
                continue

            lon_sel = lon[mask]
            lat_sel = lat[mask]
            h_sel = h[mask]
            dt_sel = dt[mask]
            quality_sel = quality[mask]
            surface_land_sel = surf_type[:, land_col_idx].astype(int, copy=False)[mask]

            # 3D transform (vertical component naar NAP) indien beschikbaar.
            if transformer_llh_to_rdnap is not None:
                try:
                    rd_x, rd_y, h_nap = transformer_llh_to_rdnap.transform(lon_sel, lat_sel, h_sel)
                    # Detecteer snelle "identity" transformatie (vertical component ontbreekt).
                    if np.all(np.isfinite(h_nap)) and np.nanmax(np.abs((h_nap - h_sel))) < 1e-6:
                        logger.warning(
                            f"{h5_path.name}: beam={beam} verticale component lijkt niet toegepast; "
                            f"h blijft ellipsoïdaal (NAP-conversie ontbreekt in PROJ)."
                        )
                except Exception as e:
                    logger.warning(
                        f"{h5_path.name}: beam={beam} 3D transformatie faalde; fallback naar 2D. Details: {e}"
                    )
                    rd_x, rd_y = transformer_lonlat_to_rd.transform(lon_sel, lat_sel)
                    h_nap = h_sel
            else:
                rd_x, rd_y = transformer_lonlat_to_rd.transform(lon_sel, lat_sel)
                h_nap = h_sel

            beam_arr = np.array([beam] * h_sel.size, dtype=object)
            rec = np.rec.fromarrays(
                [lon_sel, lat_sel, rd_x, rd_y, h_nap, dt_sel, quality_sel, surface_land_sel, beam_arr],
                names=["lon", "lat", "rd_x", "rd_y", "h", "delta_time", "quality_flag", "surface_type_land", "beam"],
            )
            points_list.append(rec)

        if not points_list:
            return np.recarray(
                (0,),
                dtype=[
                    ("lon", "f8"),
                    ("lat", "f8"),
                    ("rd_x", "f8"),
                    ("rd_y", "f8"),
                    ("h", "f8"),
                    ("delta_time", "f8"),
                    ("quality_flag", "i4"),
                    ("surface_type_land", "i4"),
                    ("beam", "O"),
                ],
            )

        return np.concatenate(points_list)


def download_with_earthaccess(
    logger: logging.Logger,
    out_dir: Path,
    bbox_lonlat: tuple[float, float, float, float],
    temporal: tuple[str, str],
    short_name: str,
    version: str,
) -> list[Path]:
    import earthaccess

    earthaccess.login(strategy="environment")

    kwargs = dict(short_name=short_name, version=version, bounding_box=bbox_lonlat, temporal=temporal)

    results = earthaccess.search_data(**kwargs)
    logger.info(f"Earthaccess: found {len(results)} granules for {short_name} v{version}.")
    if len(results) == 0:
        return []

    files = earthaccess.download(results, out_dir)
    logger.info(f"Earthaccess: downloaded {len(files)} files into {out_dir}.")
    return [Path(f) for f in files]


def download_with_icepyx_best_effort(
    logger: logging.Logger,
    out_dir: Path,
    bbox_lonlat: tuple[float, float, float, float],
    temporal: tuple[str, str],
    version: str,
    short_name: str,
) -> list[Path]:
    """
    Best-effort integration.
    icepyx order/download can output files in formats that may not match earthaccess' naming.
    If icepyx is unavailable or download fails, we return an empty list.
    """
    ipx = _import_optional("icepyx")
    if ipx is None:
        logger.warning("icepyx is not installed. Skipping icepyx subset/download.")
        return []

    # icepyx Query expects spatial_extent = [lon_min, lat_min, lon_max, lat_max]
    spatial_extent = [bbox_lonlat[0], bbox_lonlat[1], bbox_lonlat[2], bbox_lonlat[3]]
    date_range = [temporal[0], temporal[1]]

    try:
        query = ipx.Query(short_name, spatial_extent, date_range)
        # Subset=True activates harmony-based spatial/temporal subsetting.
        order = query.order_granules(subset=True)
        logger.info(f"icepyx: order placed (best-effort).")
        # Download to path; icepyx handles the wait until ready if needed.
        query.download_granules(out_dir, overwrite=True)
    except Exception as e:
        logger.warning(f"icepyx download failed: {e}")
        return []

    # Collect likely output files.
    candidates = list(out_dir.glob("**/*.h5")) + list(out_dir.glob("**/*.nc")) + list(out_dir.glob("**/*.hdf5"))
    return sorted({p.resolve() for p in candidates})


def grid_points_to_cells(
    lonlat_points: np.recarray,
    cell_size_m: int,
    stat: str,
    logger: logging.Logger,
) -> tuple[xr.DataArray, xr.DataArray, xr.DataArray, np.ndarray, np.ndarray]:
    """
    Returns:
    - height_stat (2D DataArray)
    - std_stat (2D DataArray)
    - count_stat (2D DataArray)
    - x_centers (1D)
    - y_centers (1D, increasing)
    """
    import pandas as pd
    import xarray as xr

    if lonlat_points.size == 0:
        raise ValueError("No points to grid.")

    # lonlat_points is een numpy structured array; dot-notation is niet betrouwbaar.
    x = np.asarray(lonlat_points["rd_x"], dtype=float)
    y = np.asarray(lonlat_points["rd_y"], dtype=float)
    h = np.asarray(lonlat_points["h"], dtype=float)

    # Align grid edges to cell size.
    x_min = float(np.nanmin(x))
    x_max = float(np.nanmax(x))
    y_min = float(np.nanmin(y))
    y_max = float(np.nanmax(y))

    x0 = math.floor(x_min / cell_size_m) * cell_size_m
    x1 = math.ceil(x_max / cell_size_m) * cell_size_m
    y0 = math.floor(y_min / cell_size_m) * cell_size_m
    y1 = math.ceil(y_max / cell_size_m) * cell_size_m

    x_edges = np.arange(x0, x1 + cell_size_m, cell_size_m)
    y_edges = np.arange(y0, y1 + cell_size_m, cell_size_m)
    x_centers = x_edges[:-1] + cell_size_m / 2.0
    y_centers = y_edges[:-1] + cell_size_m / 2.0  # increasing

    x_idx = np.searchsorted(x_edges, x, side="right") - 1
    y_idx = np.searchsorted(y_edges, y, side="right") - 1

    valid = (x_idx >= 0) & (x_idx < x_centers.size) & (y_idx >= 0) & (y_idx < y_centers.size) & np.isfinite(h)
    if not np.any(valid):
        raise ValueError("All points fell outside computed grid bins (unexpected).")

    df = pd.DataFrame({"x_idx": x_idx[valid].astype(int), "y_idx": y_idx[valid].astype(int), "h": h[valid]})

    # Aggregate per cell
    gb = df.groupby(["y_idx", "x_idx"], sort=False)["h"]
    if stat == "median":
        height = gb.median()
    else:
        height = gb.mean()
    std = gb.std(ddof=0)
    count = gb.count()

    ny = y_centers.size
    nx = x_centers.size

    height_grid = np.full((ny, nx), np.nan, dtype=float)
    std_grid = np.full((ny, nx), np.nan, dtype=float)
    count_grid = np.zeros((ny, nx), dtype=int)

    # Map group results into arrays.
    for (y_i, x_i), v in height.items():
        height_grid[int(y_i), int(x_i)] = float(v)
    for (y_i, x_i), v in std.items():
        std_grid[int(y_i), int(x_i)] = float(v) if v is not None else np.nan
    for (y_i, x_i), v in count.items():
        count_grid[int(y_i), int(x_i)] = int(v)

    height_da = xr.DataArray(height_grid, coords={"y": y_centers, "x": x_centers}, dims=("y", "x"), name="height")
    std_da = xr.DataArray(std_grid, coords={"y": y_centers, "x": x_centers}, dims=("y", "x"), name="height_std")
    count_da = xr.DataArray(count_grid, coords={"y": y_centers, "x": x_centers}, dims=("y", "x"), name="n_samples")

    logger.info(f"Binned into grid {nx} x {ny} cells.")
    return height_da, std_da, count_da, x_centers, y_centers


def export_geotiff(
    height_da,
    std_da,
    out_path_height: Path,
    out_path_std: Path,
    logger: logging.Logger,
):
    try:
        import rioxarray
        import xarray as xr
    except Exception:
        logger.error("rioxarray/xarray missing. Cannot export GeoTIFF.")
        return

    # Write in EPSG:28992
    height_out = height_da.sortby("y", ascending=False)
    std_out = std_da.sortby("y", ascending=False)
    height_out = height_out.rio.write_crs("EPSG:28992", inplace=False)
    std_out = std_out.rio.write_crs("EPSG:28992", inplace=False)

    height_out = height_out.rio.write_nodata(np.nan, inplace=False)
    std_out = std_out.rio.write_nodata(np.nan, inplace=False)

    height_out.name = "h_te_best_fit"
    std_out.name = "h_te_best_fit_std"

    height_out.rio.to_raster(out_path_height)
    std_out.rio.to_raster(out_path_std)
    logger.info(f"Exported GeoTIFF: {out_path_height.name} and {out_path_std.name}")


def plot_results(
    height_da,
    std_da,
    out_dir: Path,
    out_prefix: str,
):
    try:
        import matplotlib.pyplot as plt
    except Exception as e:
        logging.getLogger("atl08").warning(f"matplotlib niet beschikbaar; kan plots niet maken. Details: {e}")
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    height_sorted = height_da.sortby("y", ascending=False)
    std_sorted = std_da.sortby("y", ascending=False)

    x = height_sorted["x"].values
    y = height_sorted["y"].values
    h = np.asarray(height_sorted.values)
    s = np.asarray(std_sorted.values)

    fig = plt.figure(figsize=(12, 10))
    ax = plt.axes()
    im = ax.pcolormesh(x, y, h, shading="auto")
    cbar = plt.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label("Height (h_te_best_fit, m)")
    ax.set_xlabel("RD New X (m)")
    ax.set_ylabel("RD New Y (m)")
    ax.set_title("ICESat-2 ATL08 v007 - Gridded height (1 km, RD New)")
    fig.savefig(out_dir / f"{out_prefix}_height_rdnew.png", dpi=160, bbox_inches="tight")
    plt.close(fig)

    fig = plt.figure(figsize=(12, 10))
    ax = plt.axes()
    im = ax.pcolormesh(x, y, s, shading="auto")
    cbar = plt.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label("Std per grid cell (m)")
    ax.set_xlabel("RD New X (m)")
    ax.set_ylabel("RD New Y (m)")
    ax.set_title("ICESat-2 ATL08 v007 - Height uncertainty (std, per bin)")
    fig.savefig(out_dir / f"{out_prefix}_std_rdnew.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir).expanduser().resolve()

    logger = build_logger(out_dir, verbose=bool(args.verbose))
    logger.info("Starting ATL08 pipeline.")
    load_dotenv()

    # Dependency checks for required modules.
    try:
        import earthaccess  # noqa: F401
        import h5py  # noqa: F401
        from pyproj import Transformer  # noqa: F401
        import xarray as xr  # noqa: F401
        import rioxarray  # noqa: F401
    except Exception as e:
        logger.error(f"Some required dependencies are missing: {e}")
        logger.error("Install (example): pip install earthaccess h5py pyproj xarray rioxarray matplotlib")
        return 2

    temporal = (args.temporal[0], args.temporal[1])

    bbox_lonlat = tuple(args.bbox)  # lon_min, lat_min, lon_max, lat_max

    config = Atl08Config(
        surface_type_land_code=None,  # inferred
    )

    out_raw = out_dir / "raw_hdf5"
    out_raw.mkdir(parents=True, exist_ok=True)

    files = download_with_earthaccess(
        logger=logger,
        out_dir=out_raw,
        bbox_lonlat=bbox_lonlat,
        temporal=temporal,
        short_name=config.short_name,
        version=config.version,
    )

    if args.use_icepyx_subset:
        logger.info("Attempting icepyx subset/download (best-effort).")
        out_ipx = out_dir / "icepyx_subset"
        ipx_files = download_with_icepyx_best_effort(
            logger=logger,
            out_dir=out_ipx,
            bbox_lonlat=bbox_lonlat,
            temporal=temporal,
            version=config.version,
            short_name=config.short_name,
        )
        # Prefer HDF5 inputs if any were produced.
        if ipx_files:
            files = sorted(set(files).union(set(ipx_files)))

    # Filter to local h5/hdf5 files (ATL08 should be HDF5).
    h5_files = [p for p in files if p.suffix.lower() in {".h5", ".hdf5", ".hdf"}]
    if not h5_files:
        logger.error("No HDF5 files available to read ATL08 points.")
        return 3
    logger.info(f"Reading ATL08 points from {len(h5_files)} file(s).")

    from pyproj import Transformer

    transformer_lonlat_to_rd = Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True)

    all_points = []
    for i, fpath in enumerate(h5_files, start=1):
        try:
            logger.info(f"[{i}/{len(h5_files)}] Reading {fpath.name}")
            pts = read_atl08_points_from_hdf5(
                h5_path=fpath,
                config=config,
                bbox_lonlat=bbox_lonlat,
                quality_flag_value=config.quality_flag_value,
                transformer_lonlat_to_rd=transformer_lonlat_to_rd,
                logger=logger,
            )
            if pts.size > 0:
                all_points.append(pts)
        except Exception as e:
            logger.warning(f"Failed reading {fpath.name}: {e}")
            continue

    if not all_points:
        logger.error("No ATL08 points extracted after filtering.")
        return 4

    import xarray as xr  # noqa: F401

    lonlat_points = np.concatenate(all_points)
    logger.info(f"Total extracted points: {lonlat_points.size}")

    # Build grid
    height_da, std_da, count_da, x_centers, y_centers = grid_points_to_cells(
        lonlat_points=lonlat_points,
        cell_size_m=args.cell_size_m,
        stat=args.stat,
        logger=logger,
    )

    # Export GeoTIFF
    out_tif_height = out_dir / f"{args.out_prefix}_height_{args.stat}_{args.cell_size_m}m.tif"
    out_tif_std = out_dir / f"{args.out_prefix}_std_{args.cell_size_m}m.tif"
    export_geotiff(height_da, std_da, out_tif_height, out_tif_std, logger=logger)

    # Plots
    plot_results(
        height_da=height_da,
        std_da=std_da,
        out_dir=out_dir,
        out_prefix=args.out_prefix,
    )

    # Quick summary stats.
    finite_h = np.isfinite(height_da.values)
    if np.any(finite_h):
        h_mean = float(np.nanmean(height_da.values))
        h_std = float(np.nanstd(height_da.values))
        logger.info(f"Final grid: mean={h_mean:.3f} m, std={h_std:.3f} m (finite cells only).")

    logger.info("Done.")
    return 0


if __name__ == "__main__":
    # Keep warnings quiet by default; the logger still captures details.
    warnings.filterwarnings("ignore", category=UserWarning)
    raise SystemExit(main())

