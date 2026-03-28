from __future__ import annotations

from dataclasses import dataclass

# lon_min, lat_min, lon_max, lat_max — Beemster for Noord-Holland use (4.45, 52.14, 5.44, 53.20)
DEFAULT_ICESAT_BBOX_LONLAT: tuple[float, float, float, float] = (4.7923, 52.4824, 5.0422, 52.6409)

@dataclass(frozen=True)
class Atl03Config:
    short_name: str = "ATL03"
    version: str = "007"
    beams: tuple[str, ...] = ("gt1l", "gt1r", "gt2l", "gt2r", "gt3l", "gt3r")
    auto_select_beams: bool = False

    conf_surface_idx: int = 0
    signal_conf_min: int = 0
    quality_ph_min: int = 2
    ground_ph_class_values: tuple[int, int] = (3, 4)
    ground_signal_class_values: tuple[int, int] = (4, 5)

    lat_candidates: tuple[str, ...] = ("lat_ph", "latitude")
    lon_candidates: tuple[str, ...] = ("lon_ph", "longitude")
    h_candidates: tuple[str, ...] = ("h_ph", "height_ph")
    delta_time_candidates: tuple[str, ...] = ("delta_time",)
    ph_classification_candidates: tuple[str, ...] = ("ph_classification",)
    quality_candidates: tuple[str, ...] = ("quality_ph", "quality_photons")
    signal_conf_candidates: tuple[str, ...] = ("signal_conf_ph",)
    signal_photons_candidates: tuple[str, ...] = ("signal_photons",)
