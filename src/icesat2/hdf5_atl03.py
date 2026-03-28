from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Optional

import numpy as np


def require_h5py():
    try:
        import h5py  # noqa: F401
    except Exception as exc:
        raise RuntimeError("Missing dependency: h5py. Install with: pip install h5py") from exc


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


def _strong_beams_from_sc_orient(sc_orient: int) -> list[str]:
    if sc_orient == 1:
        return ["gt1r", "gt2r", "gt3r"]
    if sc_orient == 0:
        return ["gt1l", "gt2l", "gt3l"]
    return ["gt1l", "gt1r", "gt2l", "gt2r", "gt3l", "gt3r"]


def _infer_ground_value_from_classed_pc_flag(ds, logger: logging.Logger) -> int:
    values = None
    for attr_name in ("flag_values", "values", "flag_value"):
        if attr_name in ds.attrs:
            try:
                values = np.array(ds.attrs[attr_name]).astype(int).tolist()
                break
            except Exception:
                values = None

    meanings = None
    for attr_name in ("flag_meanings", "flag_meaning", "meanings"):
        if attr_name in ds.attrs:
            meanings_raw = ds.attrs[attr_name]
            if isinstance(meanings_raw, (bytes, str)):
                meanings = str(meanings_raw).replace("\x00", "").strip().split()
            else:
                try:
                    meanings = [str(x) for x in meanings_raw]
                except Exception:
                    meanings = None
            break

    if meanings:
        meanings_lower = [m.lower() for m in meanings]
        for idx, m in enumerate(meanings_lower):
            if m == "ground" or "ground" in m:
                if values is not None and idx < len(values):
                    return int(values[idx])
                return 1

    logger.warning("Could not infer ATL08 ground value from classed_pc_flag; assuming 1.")
    return 1


def _build_ground_mask_from_atl08(
    f_atl03,
    f_atl08,
    beam: str,
    n_photons: int,
    logger: logging.Logger,
) -> Optional[np.ndarray]:
    path_flag = f"{beam}/signal_photons/classed_pc_flag"
    path_indx = f"{beam}/signal_photons/classed_pc_indx"
    path_seg = f"{beam}/signal_photons/ph_segment_id"
    if path_flag not in f_atl08 or path_indx not in f_atl08 or path_seg not in f_atl08:
        logger.warning(
            f"{beam}: ATL08 missing one of classed_pc_flag/classed_pc_indx/ph_segment_id; skipping beam."
        )
        return None

    ds_flag = f_atl08[path_flag]
    ground_val = _infer_ground_value_from_classed_pc_flag(ds_flag, logger)

    class_flag = np.asarray(ds_flag[:]).reshape(-1).astype(int, copy=False)
    class_indx = np.asarray(f_atl08[path_indx][:]).reshape(-1).astype(int, copy=False)
    ph_seg_id = np.asarray(f_atl08[path_seg][:]).reshape(-1).astype(int, copy=False)

    keep = class_flag == int(ground_val)
    if not np.any(keep):
        return np.zeros((n_photons,), dtype=bool)

    class_indx = class_indx[keep]
    ph_seg_id = ph_seg_id[keep]

    path_seg_atl03 = f"{beam}/geolocation/segment_id"
    path_beg = f"{beam}/geolocation/ph_index_beg"
    if path_seg_atl03 not in f_atl03 or path_beg not in f_atl03:
        logger.warning(f"{beam}: ATL03 missing geolocation/segment_id or ph_index_beg; cannot couple ATL08->ATL03.")
        return None

    seg_ids = np.asarray(f_atl03[path_seg_atl03][:]).reshape(-1).astype(int, copy=False)
    ph_index_beg = np.asarray(f_atl03[path_beg][:]).reshape(-1).astype(int, copy=False)

    seg_pos = np.searchsorted(seg_ids, ph_seg_id)
    n_seg = seg_ids.size
    in_bounds = seg_pos < n_seg
    # Must not index seg_ids[seg_pos] where seg_pos == n_seg (searchsorted can return len(seg_ids)).
    seg_match = np.zeros(ph_seg_id.shape, dtype=bool)
    seg_match[in_bounds] = seg_ids[seg_pos[in_bounds]] == ph_seg_id[in_bounds]
    valid = in_bounds & seg_match
    if not np.any(valid):
        logger.warning(f"{beam}: No matching segment_id between ATL08 and ATL03 for this granule.")
        return np.zeros((n_photons,), dtype=bool)

    seg_pos = seg_pos[valid]
    class_indx = class_indx[valid]

    ph0 = ph_index_beg[seg_pos] - 1
    idx0 = class_indx - 1
    photon_idx0 = ph0 + idx0

    in_range = (photon_idx0 >= 0) & (photon_idx0 < int(n_photons))
    photon_idx0 = photon_idx0[in_range]
    if photon_idx0.size == 0:
        return np.zeros((n_photons,), dtype=bool)

    mask = np.zeros((n_photons,), dtype=bool)
    mask[np.asarray(photon_idx0, dtype=int)] = True
    return mask


def read_atl03_points_from_hdf5(
    h5_path: Path,
    config,
    bbox_lonlat: tuple[float, float, float, float],
    transformer_lonlat_to_rd,
    logger: logging.Logger,
    atl08_path: Optional[Path] = None,
) -> np.ndarray:
    """Return structured array: lon, lat, rd_x, rd_y, h_nap, delta_time, ph_class, beam."""
    require_h5py()
    import h5py

    lon_min, lat_min, lon_max, lat_max = bbox_lonlat

    try:
        from pyproj import Transformer

        transformer_llh_to_rdnap = Transformer.from_crs(
            "EPSG:4979",
            "EPSG:7415",
            always_xy=True,
        )
    except Exception as e:
        logger.warning(f"Could not build 3D LLH->RD+NAP transformer; using 2D fallback. Details: {e}")
        transformer_llh_to_rdnap = None

    empty_dtype = [
        ("lon", "f8"),
        ("lat", "f8"),
        ("rd_x", "f8"),
        ("rd_y", "f8"),
        ("h_nap", "f8"),
        ("delta_time", "f8"),
        ("ph_class", "i4"),
        ("beam", "O"),
    ]

    with h5py.File(h5_path, "r") as f:
        points_list: list[np.recarray] = []

        selected_beams = list(config.beams)
        if config.auto_select_beams:
            try:
                sc_orient_arr = f["/orbit_info/sc_orient"][()]
                sc_orient = int(np.atleast_1d(sc_orient_arr)[0])
                selected_beams = [b for b in _strong_beams_from_sc_orient(sc_orient) if b in set(config.beams)]
                logger.info(f"{h5_path.name}: sc_orient={sc_orient} -> beams={selected_beams}")
            except Exception as e:
                logger.warning(
                    f"{h5_path.name}: could not read /orbit_info/sc_orient; using config.beams. Details: {e}"
                )

        f_atl08 = None
        if atl08_path is not None and atl08_path.exists():
            try:
                f_atl08 = h5py.File(atl08_path, "r")
            except Exception as e:
                logger.warning(f"{h5_path.name}: could not open ATL08 companion {atl08_path.name}: {e}")
                f_atl08 = None
        elif atl08_path is not None:
            logger.warning(f"{h5_path.name}: ATL08 companion not found at {atl08_path}.")

        for beam in selected_beams:
            if beam not in f:
                continue
            if "heights" not in f[beam]:
                logger.warning(f"{h5_path.name}: beam={beam} has no /heights group; skipping.")
                continue

            grp = f[f"{beam}/heights"]

            try:
                lat = _read_atl03_dataset_1d(grp, config.lat_candidates, "lat_ph")
                lon = _read_atl03_dataset_1d(grp, config.lon_candidates, "lon_ph")
                h_ellip = _read_atl03_dataset_1d(grp, config.h_candidates, "h_ph")
                dt = _read_atl03_dataset_1d(grp, config.delta_time_candidates, "delta_time")
            except KeyError as e:
                logger.warning(f"{h5_path.name}: beam={beam} missing dataset ({e}). Skipping beam.")
                continue
            except Exception as e:
                logger.warning(f"{h5_path.name}: beam={beam} could not parse datasets ({e}). Skipping beam.")
                continue

            if not (lat.size == lon.size == h_ellip.size == dt.size):
                logger.warning(f"{h5_path.name}: beam={beam} size mismatch; skipping beam.")
                continue

            mask_bbox = (lon >= lon_min) & (lon <= lon_max) & (lat >= lat_min) & (lat <= lat_max)
            if not np.any(mask_bbox):
                continue

            mask_height = np.isfinite(h_ellip)

            if f_atl08 is None:
                logger.warning(f"{h5_path.name}: no ATL08 companion open; cannot apply classed_pc_flag ground filter.")
                continue

            mask_ground = _build_ground_mask_from_atl08(
                f_atl03=f,
                f_atl08=f_atl08,
                beam=beam,
                n_photons=int(h_ellip.size),
                logger=logger,
            )
            if mask_ground is None:
                continue

            mask = mask_bbox & mask_ground & mask_height
            if not np.any(mask):
                continue

            lon_sel = lon[mask]
            lat_sel = lat[mask]
            h_sel = h_ellip[mask]
            dt_sel = dt[mask]
            ph_class_sel = np.ones_like(dt_sel, dtype=int)

            if transformer_llh_to_rdnap is not None:
                try:
                    rd_x, rd_y, h_nap = transformer_llh_to_rdnap.transform(lon_sel, lat_sel, h_sel)
                    if np.all(np.isfinite(h_nap)) and np.nanmax(np.abs((h_nap - h_sel))) < 1e-6:
                        logger.warning(
                            f"{h5_path.name}: beam={beam} vertical component may be unchanged (ellipsoidal h); "
                            "check PROJ NAP support."
                        )
                except Exception as e:
                    logger.warning(
                        f"{h5_path.name}: beam={beam} 3D transform failed; 2D fallback. Details: {e}"
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

        if f_atl08 is not None:
            try:
                f_atl08.close()
            except Exception:
                pass

        if not points_list:
            return np.recarray((0,), dtype=empty_dtype)

        return np.concatenate(points_list)
