"""CRS policy (ARCHITECTURE §6, D-006).

- Interchange: OGC:CRS84 / EPSG:4326, longitude, latitude order.
- Simulation: one local projected metric CRS per pilot (West Bengal: EPSG:32645,
  UTM zone 45N).
- Fail fast on missing/implausible CRS or coordinates; no silent guessing.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyproj import CRS, Transformer

# Interchange CRS (web map / API): longitude, latitude (EPSG:4326 axis order lon,lat)
INTERCHANGE_CRS = "OGC:CRS84"

# Projected CRS for the West Bengal pilot zone (UTM 45N, metres)
WB_PROJECTED_CRS = "EPSG:32645"


@dataclass(frozen=True)
class LonLat:
    """Explicit longitude/latitude value object — prevents axis-order confusion."""

    lon: float
    lat: float

    def __post_init__(self) -> None:
        if not (-180.0 <= self.lon <= 180.0):
            raise ValueError(f"longitude out of range: {self.lon}")
        if not (-90.0 <= self.lat <= 90.0):
            raise ValueError(f"latitude out of range: {self.lat}")


def require_projected_metric(crs_id: str) -> CRS:
    """Reject angular CRS for simulation use (silent degrees-as-metres is a bug)."""
    crs = CRS.from_user_input(crs_id)
    if crs.is_geographic:
        raise ValueError(f"{crs_id} is geographic; simulation requires a projected metric CRS")
    return crs


def to_projected(lon: float, lat: float, src: str = INTERCHANGE_CRS, dst: str = WB_PROJECTED_CRS) -> tuple[float, float]:
    """Transform (lon, lat) -> projected (x, y). Always lon,lat order here."""
    pt = LonLat(lon, lat)
    tf = Transformer.from_crs(CRS.from_user_input(src), CRS.from_user_input(dst), always_xy=True)
    x, y = tf.transform(pt.lon, pt.lat)
    return float(x), float(y)


def to_lonlat(x: float, y: float, src: str = WB_PROJECTED_CRS, dst: str = INTERCHANGE_CRS) -> LonLat:
    tf = Transformer.from_crs(CRS.from_user_input(src), CRS.from_user_input(dst), always_xy=True)
    lon, lat = tf.transform(x, y)
    return LonLat(float(lon), float(lat))


def roundtrip_error(lon: float, lat: float) -> float:
    """Metres of closure error for a projected round trip — an axis-order smoke test."""
    x, y = to_projected(lon, lat)
    back = to_lonlat(x, y)
    from pyproj import Geod

    geod = Geod(ellps="WGS84")
    _, _, dist = geod.inv(lon, lat, back.lon, back.lat)
    return float(dist)
