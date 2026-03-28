#!/usr/bin/env python3
"""
Download ICESat-2 ATL03 (v007) with earthaccess, extract photon heights (h_ph),
filter strong/ground photons, transform to RD New + NAP (EPSG:28992+7415),
bin to 1 km cells, compute per-cell statistics, export GeoTIFF, and plot.

Notes
-----
- ATL03 is photon-level (much denser than ATL08 segments). After filtering, this
  should yield better 1 km grid coverage in flat NL terrain.
- Dataset paths and shapes can vary slightly across ATL03 versions; this script
  searches for expected dataset keys under each beam's `heights` group.
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Optional

import numpy as np
from dotenv import load_dotenv

if TYPE_CHECKING:
    import xarray as xr


def _require_import(module_name: str, pip_hint: str) -> None:
    raise RuntimeError(
        f"Missing dependency: {module_name}. Install it first (example): {pip_hint}"
    )


def _import_optional(module_name: str):
    try:
        return __import__(module_name)
    except Exception:
        return None


@dataclass(frozen=True)
class Atl03Config:
    short_name: str = "ATL03"
    version: str = "007"
    # Default includes all beams; actual selection is done per granule via sc_orient.
    beams: tuple[str, ...] = ("gt1l", "gt1r", "gt2l", "gt2r", "gt3l", "gt3r")
    auto_select_beams: bool = True

    # Photon filtering
    conf_surface_idx: int = 0
    signal_conf_min: int = 0
    quality_ph_min: int = 2
    ground_ph_class_values: tuple[int, int] = (3, 4)
    # ATL03 L1B (v007) in this dataset set does not contain `ph_classification`.
    # Instead we fall back to `signal_class_ph` which uses different flag meanings:
    # - 4=primary_signal
    # - 5=fitted_signal
    ground_signal_class_values: tuple[int, int] = (4, 5)

    # ATL03 uses photon-level arrays under `<beam>/heights/`
    lat_candidates: tuple[str, ...] = ("lat_ph", "latitude")
    lon_candidates: tuple[str, ...] = ("lon_ph", "longitude")
    h_candidates: tuple[str, ...] = ("h_ph", "height_ph")
    delta_time_candidates: tuple[str, ...] = ("delta_time",)
    ph_classification_candidates: tuple[str, ...] = ("ph_classification",)
    quality_candidates: tuple[str, ...] = ("quality_ph", "quality_photons")

    # Confidence candidates (prefer signal_conf_ph)
    signal_conf_candidates: tuple[str, ...] = ("signal_conf_ph",)
    signal_photons_candidates: tuple[str, ...] = ("signal_photons",)


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
    logger = logging.getLogger("atl03")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.DEBUG if verbose else logging.INFO)
    sh.setFormatter(fmt)

    fh = logging.FileHandler(out_dir / "atl03_pipeline.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    if not logger.handlers:
        logger.addHandler(sh)
        logger.addHandler(fh)
    return logger


def parse_args() -> argparse.Namespace:
    default_bbox = (4.45, 52.14, 5.44, 53.20)  # lon_min, lat_min, lon_max, lat_max
    parser = argparse.ArgumentParser(description="Download and grid ICESat-2 ATL03 (v007) for Noord-Holland.")
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        default=default_bbox,
        metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"),
    )
    parser.add_argument("--temporal", nargs=2, type=str, default=("2025-01-01", "2025-12-31"), metavar=("START", "END"))
    parser.add_argument("--out-dir", type=str, default="atl03_output")
    parser.add_argument("--out-prefix", type=str, default="atl03_nh_rdnew_1km")

    parser.add_argument("--stat", choices=("median", "mean"), default="median", help="Per-cell height statistic.")
    parser.add_argument("--cell-size-m", type=int, default=100, help="Grid cell size in meters (RD New).")

    parser.add_argument("--signal-confidence-surface-idx", type=int, default=0, help="Column in signal_conf_ph for land.")
    parser.add_argument("--signal-confidence-min", type=int, default=0, help="Minimum signal confidence (>=).")
    parser.add_argument(
        "--quality-ph-min",
        type=int,
        default=2,
        help="Keep photons with quality_ph <= QUALITY_PH_MIN (dataset uses 0=nominal; larger values indicate saturation/noise flags).",
    )
    parser.add_argument("--use-icepyx-subset", action="store_true", help="Best-effort icepyx subset/download (optional).")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def _first_existing_key(h5_group, candidates: Iterable[str]) -> Optional[str]:
    for k in candidates:
        if k in h5_group:
            return k
    return None


def _read_atl03_dataset_1d(grp, candidates: Iterable[str], ds_label: str) -> np.ndarray:
    key = _first_existing_key(grp, candidates)
    if key is None:
        raise KeyError(f"Missing dataset for {ds_label}; searched candidates={list(candidates)}")
    return np.asarray(grp[key][:]).reshape(-1)


def _read_atl03_dataset_signal(grp, candidates_conf: Iterable[str], candidates_ph: Iterable[str], conf_surface_idx: int) -> tuple[Optional[np.ndarray], str]:
    key_conf = _first_existing_key(grp, candidates_conf)
    if key_conf is not None:
        sc = np.asarray(grp[key_conf][:])
        if sc.ndim != 2 or sc.shape[1] <= conf_surface_idx:
            raise ValueError(f"Unexpected shape for {key_conf}: {sc.shape}, conf_surface_idx={conf_surface_idx}")
        return sc[:, conf_surface_idx].reshape(-1), f"{key_conf}[:, {conf_surface_idx}]"

    key_ph = _first_existing_key(grp, candidates_ph)
    if key_ph is not None:
        return np.asarray(grp[key_ph][:]).reshape(-1), key_ph

    return None, "missing"


def read_atl03_points_from_hdf5(
    h5_path: Path,
    config: Atl03Config,
    bbox_lonlat: tuple[float, float, float, float],
    transformer_lonlat_to_rd,
    logger: logging.Logger,
) -> np.ndarray:
    """Read ATL03 photon points from one HDF5 granule.

    Returns a numpy structured array with columns:
    lon, lat, rd_x, rd_y, h_nap, delta_time, ph_class, beam
    """
    try:
        import h5py
    except Exception:
        _require_import("h5py", "pip install h5py")

    lon_min, lat_min, lon_max, lat_max = bbox_lonlat

    # 3D transform: WGS84 ellipsoidal height -> RD New + NAP height.
    try:
        from pyproj import Transformer

        # Use `EPSG:7415` (not `EPSG:28992+7415`) because the latter can fail with some PROJ builds.
        transformer_llh_to_rdnap = Transformer.from_crs(
            "EPSG:4979",  # WGS84 3D (lon,lat,h_ellip)
            "EPSG:7415",  # Amersfoort / RD New + NAP height (returns X/Y + NAP z)
            always_xy=True,
        )
    except Exception as e:
        logger.warning(f"Kon 3D LLH->RD+NAP transformer niet maken; fallback naar 2D. Details: {e}")
        transformer_llh_to_rdnap = None

    ph_classification_fallback_logged = False

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

        for beam in selected_beams:
            if beam not in f:
                continue
            if "heights" not in f[beam]:
                logger.warning(f"{h5_path.name}: beam={beam} heeft geen /heights groep; skipping.")
                continue

            grp = f[f"{beam}/heights"]

            try:
                lat = _read_atl03_dataset_1d(grp, config.lat_candidates, "lat_ph")
                lon = _read_atl03_dataset_1d(grp, config.lon_candidates, "lon_ph")
                h_ellip = _read_atl03_dataset_1d(grp, config.h_candidates, "h_ph")
                dt = _read_atl03_dataset_1d(grp, config.delta_time_candidates, "delta_time")
                quality_ph = _read_atl03_dataset_1d(grp, config.quality_candidates, "quality_ph")
                signal_arr, signal_src = _read_atl03_dataset_signal(
                    grp,
                    candidates_conf=config.signal_conf_candidates,
                    candidates_ph=config.signal_photons_candidates,
                    conf_surface_idx=config.conf_surface_idx,
                )
                # Ground/surface filtering:
                # - Prefer `ph_classification` when available.
                # - Fall back to `signal_class_ph` for this particular ATL03 dataset layout.
                try:
                    ph_class = _read_atl03_dataset_1d(grp, config.ph_classification_candidates, "ph_classification")
                    ph_class_source = "ph_classification"
                except KeyError:
                    ph_class = _read_atl03_dataset_1d(grp, ("signal_class_ph",), "signal_class_ph")
                    ph_class_source = "signal_class_ph"
            except KeyError as e:
                logger.warning(f"{h5_path.name}: beam={beam} missing dataset ({e}). Skipping beam.")
                continue
            except Exception as e:
                logger.warning(f"{h5_path.name}: beam={beam} could not parse datasets ({e}). Skipping beam.")
                continue

            if not (lat.size == lon.size == h_ellip.size == dt.size == ph_class.size == quality_ph.size):
                logger.warning(f"{h5_path.name}: beam={beam} size mismatch; skipping beam.")
                continue

            mask_bbox = (lon >= lon_min) & (lon <= lon_max) & (lat >= lat_min) & (lat <= lat_max)
            if not np.any(mask_bbox):
                continue

            # Core NL-ground photon filtering.
            if ph_class_source == "ph_classification":
                mask_ground = (ph_class == int(config.ground_ph_class_values[0])) | (
                    ph_class == int(config.ground_ph_class_values[1])
                )
            else:
                if not ph_classification_fallback_logged:
                    logger.warning(
                        f"{h5_path.name}: ph_classification ontbreekt; fallback gebruikt signal_class_ph "
                        f"(ground_signal_class_values={config.ground_signal_class_values})."
                    )
                    ph_classification_fallback_logged = True
                mask_ground = (ph_class == int(config.ground_signal_class_values[0])) | (
                    ph_class == int(config.ground_signal_class_values[1])
                )
            # quality_ph is a flag where 0=nominal; larger values indicate special conditions (noise, saturation, etc.).
            # For NL grid coverage we keep nominal and exclude the clearly flagged photons.
            mask_quality = quality_ph <= int(config.quality_ph_min)
            mask_height = np.isfinite(h_ellip)

            if signal_arr is None:
                logger.warning(f"{h5_path.name}: beam={beam} no signal confidence dataset found; skipping signal filter.")
                mask_signal = np.ones_like(h_ellip, dtype=bool)
            else:
                mask_signal = signal_arr >= int(config.signal_conf_min)

            mask = mask_bbox & mask_ground & mask_quality & mask_signal & mask_height
            if not np.any(mask):
                continue

            lon_sel = lon[mask]
            lat_sel = lat[mask]
            h_sel = h_ellip[mask]
            dt_sel = dt[mask]
            ph_class_sel = ph_class[mask]

            # 3D transform (vertical component naar NAP) indien beschikbaar.
            if transformer_llh_to_rdnap is not None:
                try:
                    rd_x, rd_y, h_nap = transformer_llh_to_rdnap.transform(lon_sel, lat_sel, h_sel)
                    if np.all(np.isfinite(h_nap)) and np.nanmax(np.abs((h_nap - h_sel))) < 1e-6:
                        logger.warning(
                            f"{h5_path.name}: beam={beam} verticale component lijkt niet toegepast; "
                            f"h blijft ellipsoidaal (NAP-conversie ontbreekt in PROJ)."
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

            beam_arr = np.array([beam] * h_nap.size, dtype=object)
            rec = np.rec.fromarrays(
                [lon_sel, lat_sel, rd_x, rd_y, h_nap, dt_sel, ph_class_sel, beam_arr],
                names=["lon", "lat", "rd_x", "rd_y", "h_nap", "delta_time", "ph_class", "beam"],
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
                    ("h_nap", "f8"),
                    ("delta_time", "f8"),
                    ("ph_class", "i4"),
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

    spatial_extent = [bbox_lonlat[0], bbox_lonlat[1], bbox_lonlat[2], bbox_lonlat[3]]
    date_range = [temporal[0], temporal[1]]

    try:
        query = ipx.Query(short_name, spatial_extent, date_range)
        order = query.order_granules(subset=True)
        logger.info("icepyx: order placed (best-effort).")
        query.download_granules(out_dir, overwrite=True)
    except Exception as e:
        logger.warning(f"icepyx download failed: {e}")
        return []

    candidates = list(out_dir.glob("**/*.h5")) + list(out_dir.glob("**/*.nc")) + list(out_dir.glob("**/*.hdf5"))
    return sorted({p.resolve() for p in candidates})


def grid_points_to_cells(
    lonlat_points: np.recarray,
    cell_size_m: int,
    stat: str,
    logger: logging.Logger,
) -> tuple[xr.DataArray, xr.DataArray, xr.DataArray, np.ndarray, np.ndarray]:
    import pandas as pd
    import xarray as xr

    if lonlat_points.size == 0:
        raise ValueError("No points to grid.")

    # Field names are written explicitly for ATL03 photons.
    x = np.asarray(lonlat_points["rd_x"], dtype=float)
    y = np.asarray(lonlat_points["rd_y"], dtype=float)
    h = np.asarray(lonlat_points["h_nap"], dtype=float)

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
    y_centers = y_edges[:-1] + cell_size_m / 2.0

    x_idx = np.searchsorted(x_edges, x, side="right") - 1
    y_idx = np.searchsorted(y_edges, y, side="right") - 1

    valid = (
        (x_idx >= 0)
        & (x_idx < x_centers.size)
        & (y_idx >= 0)
        & (y_idx < y_centers.size)
        & np.isfinite(h)
    )
    if not np.any(valid):
        raise ValueError("All points fell outside computed grid bins (unexpected).")

    df = pd.DataFrame({"x_idx": x_idx[valid].astype(int), "y_idx": y_idx[valid].astype(int), "h_nap": h[valid]})

    gb = df.groupby(["y_idx", "x_idx"], sort=False)["h_nap"]
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

    for (y_i, x_i), v in height.items():
        height_grid[int(y_i), int(x_i)] = float(v)
    for (y_i, x_i), v in std.items():
        std_grid[int(y_i), int(x_i)] = float(v) if v is not None else np.nan
    for (y_i, x_i), v in count.items():
        count_grid[int(y_i), int(x_i)] = int(v)

    height_da = xr.DataArray(height_grid, coords={"y": y_centers, "x": x_centers}, dims=("y", "x"), name="h_nap")
    std_da = xr.DataArray(std_grid, coords={"y": y_centers, "x": x_centers}, dims=("y", "x"), name="h_nap_std")
    count_da = xr.DataArray(count_grid, coords={"y": y_centers, "x": x_centers}, dims=("y", "x"), name="n_samples")

    logger.info(f"Binned into grid {nx} x {ny} cells.")
    return height_da, std_da, count_da, x_centers, y_centers


def export_geotiff(
    height_da,
    std_da,
    out_path_height: Path,
    out_path_std: Path,
    logger: logging.Logger,
) -> None:
    try:
        import rioxarray
        import xarray as xr  # noqa: F401
    except Exception:
        logger.error("rioxarray/xarray missing. Cannot export GeoTIFF.")
        return

    height_out = height_da.sortby("y", ascending=False)
    std_out = std_da.sortby("y", ascending=False)
    height_out = height_out.rio.write_crs("EPSG:28992", inplace=False)
    std_out = std_out.rio.write_crs("EPSG:28992", inplace=False)

    height_out = height_out.rio.write_nodata(np.nan, inplace=False)
    std_out = std_out.rio.write_nodata(np.nan, inplace=False)

    height_out.name = "h_nap"
    std_out.name = "h_nap_std"

    height_out.rio.to_raster(out_path_height)
    std_out.rio.to_raster(out_path_std)
    logger.info(f"Exported GeoTIFF: {out_path_height.name} and {out_path_std.name}")


def plot_results(
    height_da,
    std_da,
    out_dir: Path,
    out_prefix: str,
) -> None:
    try:
        import matplotlib.pyplot as plt
    except Exception as e:
        logging.getLogger("atl03").warning(f"matplotlib niet beschikbaar; kan plots niet maken. Details: {e}")
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
    cbar.set_label("NAP height (h_nap, m)")
    ax.set_xlabel("RD New X (m)")
    ax.set_ylabel("RD New Y (m)")
    ax.set_title("ICESat-2 ATL03 v007 - Gridded NAP height (1 km, RD New)")
    fig.savefig(out_dir / f"{out_prefix}_height_rdnew.png", dpi=160, bbox_inches="tight")
    plt.close(fig)

    fig = plt.figure(figsize=(12, 10))
    ax = plt.axes()
    im = ax.pcolormesh(x, y, s, shading="auto")
    cbar = plt.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label("Std per grid cell (m)")
    ax.set_xlabel("RD New X (m)")
    ax.set_ylabel("RD New Y (m)")
    ax.set_title("ICESat-2 ATL03 v007 - Height uncertainty (std, per bin)")
    fig.savefig(out_dir / f"{out_prefix}_std_rdnew.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir).expanduser().resolve()

    logger = build_logger(out_dir, verbose=bool(args.verbose))
    logger.info("Starting ATL03 pipeline.")
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

    config = Atl03Config(
        conf_surface_idx=int(args.signal_confidence_surface_idx),
        signal_conf_min=int(args.signal_confidence_min),
        quality_ph_min=int(args.quality_ph_min),
        # ground_ph_class_values fixed as (3,4) by ATL03 spec for ground/ground_top
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
        if ipx_files:
            files = sorted(set(files).union(set(ipx_files)))

    h5_files = [p for p in files if p.suffix.lower() in {".h5", ".hdf5", ".hdf"}]

    if not h5_files:
        logger.error("No HDF5 files available to read ATL03 points.")
        return 3

    logger.info(f"Reading ATL03 points from {len(h5_files)} file(s).")

    from pyproj import Transformer

    transformer_lonlat_to_rd = Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True)

    all_points: list[np.recarray] = []
    for i, fpath in enumerate(h5_files, start=1):
        try:
            logger.info(f"[{i}/{len(h5_files)}] Reading {fpath.name}")
            pts = read_atl03_points_from_hdf5(
                h5_path=fpath,
                config=config,
                bbox_lonlat=bbox_lonlat,
                transformer_lonlat_to_rd=transformer_lonlat_to_rd,
                logger=logger,
            )
            if pts.size > 0:
                all_points.append(pts)
        except Exception as e:
            logger.warning(f"Failed reading {fpath.name}: {e}")
            continue

    if not all_points:
        logger.error("No ATL03 points extracted after filtering.")
        return 4

    lonlat_points = np.concatenate(all_points)
    logger.info(f"Total extracted points: {lonlat_points.size}")

    height_da, std_da, count_da, x_centers, y_centers = grid_points_to_cells(
        lonlat_points=lonlat_points,
        cell_size_m=args.cell_size_m,
        stat=args.stat,
        logger=logger,
    )

    out_tif_height = out_dir / f"{args.out_prefix}_height_{args.stat}_{args.cell_size_m}m.tif"
    out_tif_std = out_dir / f"{args.out_prefix}_std_{args.cell_size_m}m.tif"
    export_geotiff(height_da, std_da, out_tif_height, out_tif_std, logger=logger)

    plot_results(height_da=height_da, std_da=std_da, out_dir=out_dir, out_prefix=args.out_prefix)

    finite_h = np.isfinite(height_da.values)
    if np.any(finite_h):
        h_mean = float(np.nanmean(height_da.values))
        h_std = float(np.nanstd(height_da.values))
        logger.info(f"Final grid: mean={h_mean:.3f} m, std={h_std:.3f} m (finite cells only).")

    logger.info("Done.")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=UserWarning)
    raise SystemExit(main())

