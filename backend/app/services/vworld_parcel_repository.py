from __future__ import annotations

import json
import math
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache

from pyproj import CRS, Transformer
from shapely.geometry import box, shape
from shapely.ops import transform

from app.services.land_compensation import Parcel, ParcelLike
from app.services.route_cost import DEM_PROJ4
from app.services.vworld_land_price import VWorldConfigError, VWorldRequestError


VWORLD_WFS_URL = "https://api.vworld.kr/req/wfs"
VWORLD_PARCEL_LAYERS = "lp_pa_cbnd_bonbun,lp_pa_cbnd_bubun"
DEFAULT_TILE_SIZE_M = 2_000.0
DEFAULT_MAX_FEATURES = 1_000
DEFAULT_MAX_PAGES = 20
DEFAULT_MAX_TILES = 120


@lru_cache(maxsize=1)
def _transformers() -> tuple[Transformer, Transformer]:
    wgs84 = CRS.from_epsg(4326)
    dem = CRS.from_proj4(DEM_PROJ4)
    return (
        Transformer.from_crs(wgs84, dem, always_xy=True),
        Transformer.from_crs(dem, wgs84, always_xy=True),
    )


def _credential(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise VWorldConfigError(f"{name} is required.")
    return value


def _to_float(value) -> float | None:
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _extract_land_category(properties: dict) -> str:
    for key in (
        "land_category",
        "lndcgrCodeNm",
        "jimok",
        "지목",
        "land_use",
        "use_region",
    ):
        value = properties.get(key)
        if value not in (None, ""):
            return str(value).strip()
    jibun = str(properties.get("jibun") or "").strip()
    # VWorld examples: "73 대", "78대", "19도", "12-3 임야".
    category = re.sub(r"^산?\s*\d+(?:-\d+)?\s*", "", jibun).strip()
    return category


class VWorldParcelRepository:
    """Parcel polygons and official prices backed by VWorld cadastral WFS."""

    warning = None

    def __init__(
        self,
        *,
        api_key: str | None = None,
        domain: str | None = None,
        tile_size_m: float = DEFAULT_TILE_SIZE_M,
        timeout: float = 20.0,
        max_tiles: int = DEFAULT_MAX_TILES,
    ) -> None:
        self.api_key = api_key or _credential("VWORLD_API_KEY")
        self.domain = domain or _credential("VWORLD_DOMAIN")
        self.tile_size_m = float(tile_size_m)
        self.timeout = float(timeout)
        self.max_tiles = int(max_tiles)
        self._tile_cache: dict[tuple[int, int], list[Parcel]] = {}
        self._parcel_cache: dict[str, Parcel] = {}
        self._lock = threading.RLock()

    def _tile_bounds_wgs84(self, tile_x: int, tile_y: int) -> tuple[float, float, float, float]:
        min_x = tile_x * self.tile_size_m
        min_y = tile_y * self.tile_size_m
        max_x = min_x + self.tile_size_m
        max_y = min_y + self.tile_size_m
        _, dem_to_wgs84 = _transformers()
        corners = [
            dem_to_wgs84.transform(x, y)
            for x, y in (
                (min_x, min_y),
                (min_x, max_y),
                (max_x, min_y),
                (max_x, max_y),
            )
        ]
        return (
            min(point[0] for point in corners),
            min(point[1] for point in corners),
            max(point[0] for point in corners),
            max(point[1] for point in corners),
        )

    def _request_page(
        self,
        bbox_wgs84: tuple[float, float, float, float],
        *,
        start_index: int,
    ) -> dict:
        params = {
            "service": "WFS",
            "request": "GetFeature",
            "version": "1.1.0",
            "typeName": VWORLD_PARCEL_LAYERS,
            "bbox": ",".join(f"{value:.8f}" for value in bbox_wgs84),
            "output": "application/json",
            "srsName": "EPSG:4326",
            "maxFeatures": str(DEFAULT_MAX_FEATURES),
            "startIndex": str(start_index),
            "key": self.api_key,
            "domain": self.domain,
        }
        request = urllib.request.Request(
            f"{VWORLD_WFS_URL}?{urllib.parse.urlencode(params)}",
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            raise VWorldRequestError(f"VWorld parcel WFS HTTP error: {error.code}") from error
        except urllib.error.URLError as error:
            raise VWorldRequestError(f"VWorld parcel WFS request failed: {error.reason}") from error
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise VWorldRequestError("VWorld parcel WFS JSON response could not be parsed.") from error

    def _fetch_tile(self, tile_x: int, tile_y: int) -> list[Parcel]:
        key = (tile_x, tile_y)
        with self._lock:
            cached = self._tile_cache.get(key)
            if cached is not None:
                return cached

        bbox_wgs84 = self._tile_bounds_wgs84(tile_x, tile_y)
        features: list[dict] = []
        start_index = 0
        for _ in range(DEFAULT_MAX_PAGES):
            data = self._request_page(bbox_wgs84, start_index=start_index)
            page = [
                feature
                for feature in data.get("features", [])
                if isinstance(feature, dict)
            ]
            features.extend(page)
            total = int(data.get("totalFeatures") or len(features))
            if not page or len(features) >= total:
                break
            start_index += len(page)
        else:
            raise VWorldRequestError(
                f"VWorld parcel WFS pagination exceeded {DEFAULT_MAX_PAGES} pages."
            )

        wgs84_to_dem, _ = _transformers()
        parcels_by_pnu: dict[str, Parcel] = {}
        for feature in features:
            properties = feature.get("properties") or {}
            geometry_json = feature.get("geometry")
            pnu = str(properties.get("pnu") or "").strip()
            if not pnu or not geometry_json:
                continue
            try:
                source_geometry = shape(geometry_json)
                min_lon, min_lat, max_lon, max_lat = source_geometry.bounds
                if max_lon < 90 and min_lat > 90:
                    source_geometry = transform(
                        lambda x, y, z=None: (y, x),
                        source_geometry,
                    )
                geometry = transform(
                    wgs84_to_dem.transform,
                    source_geometry,
                )
                if geometry.is_empty:
                    continue
                if not geometry.is_valid:
                    geometry = geometry.buffer(0)
            except Exception:
                continue
            land_category_raw = _extract_land_category(properties)
            parcel = Parcel(
                pnu=pnu,
                lawd_code=pnu[:10],
                sigungu_code=pnu[:5],
                land_type=land_category_raw,
                land_category_raw=land_category_raw,
                geometry=geometry,
                official_price_per_m2=_to_float(properties.get("jiga")),
            )
            parcels_by_pnu[pnu] = parcel

        parcels = list(parcels_by_pnu.values())
        with self._lock:
            self._tile_cache[key] = parcels
            self._parcel_cache.update(parcels_by_pnu)
        return parcels

    def get_intersected_parcels(
        self,
        route_geom,
        road_width_m: float,
    ) -> list[ParcelLike]:
        corridor = route_geom.buffer(road_width_m / 2.0)
        min_x, min_y, max_x, max_y = corridor.bounds
        min_tile_x = math.floor(min_x / self.tile_size_m)
        max_tile_x = math.floor(max_x / self.tile_size_m)
        min_tile_y = math.floor(min_y / self.tile_size_m)
        max_tile_y = math.floor(max_y / self.tile_size_m)
        tiles = [
            (tile_x, tile_y)
            for tile_x in range(min_tile_x, max_tile_x + 1)
            for tile_y in range(min_tile_y, max_tile_y + 1)
            if box(
                tile_x * self.tile_size_m,
                tile_y * self.tile_size_m,
                (tile_x + 1) * self.tile_size_m,
                (tile_y + 1) * self.tile_size_m,
            ).intersects(corridor)
        ]
        if len(tiles) > self.max_tiles:
            raise VWorldRequestError(
                f"Parcel corridor requires {len(tiles)} WFS tiles; limit is {self.max_tiles}."
            )

        parcels: dict[str, Parcel] = {}
        for tile_x, tile_y in tiles:
            for parcel in self._fetch_tile(tile_x, tile_y):
                if parcel.geometry.intersects(corridor):
                    parcels[parcel.pnu] = parcel
        return list(parcels.values())

    def get_reference_parcels(self, target_parcel: ParcelLike) -> list[ParcelLike]:
        lawd_code = str(
            target_parcel.get("lawd_code")
            if isinstance(target_parcel, dict)
            else target_parcel.lawd_code
        )
        with self._lock:
            return [
                parcel
                for parcel in self._parcel_cache.values()
                if parcel.lawd_code == lawd_code
            ]

    def get_reference_parcels_around_route(
        self,
        route_geom,
        search_radius_m: float,
    ) -> list[ParcelLike]:
        search_area = route_geom.buffer(search_radius_m)
        min_x, min_y, max_x, max_y = search_area.bounds
        min_tile_x = math.floor(min_x / self.tile_size_m)
        max_tile_x = math.floor(max_x / self.tile_size_m)
        min_tile_y = math.floor(min_y / self.tile_size_m)
        max_tile_y = math.floor(max_y / self.tile_size_m)
        tiles = [
            (tile_x, tile_y)
            for tile_x in range(min_tile_x, max_tile_x + 1)
            for tile_y in range(min_tile_y, max_tile_y + 1)
            if box(
                tile_x * self.tile_size_m,
                tile_y * self.tile_size_m,
                (tile_x + 1) * self.tile_size_m,
                (tile_y + 1) * self.tile_size_m,
            ).intersects(search_area)
        ]
        if len(tiles) > self.max_tiles:
            raise VWorldRequestError(
                f"Parcel KNN search requires {len(tiles)} WFS tiles; limit is {self.max_tiles}."
            )

        parcels: dict[str, Parcel] = {}
        for tile_x, tile_y in tiles:
            for parcel in self._fetch_tile(tile_x, tile_y):
                if parcel.official_price_per_m2 is not None and parcel.geometry.intersects(search_area):
                    parcels[parcel.pnu] = parcel
        return list(parcels.values())


@lru_cache(maxsize=1)
def get_default_parcel_repository() -> VWorldParcelRepository:
    return VWorldParcelRepository()
