from __future__ import annotations

import json
import math
import os
import re
import threading
import time
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
VWORLD_PARCEL_LAYER = "lp_pa_cbnd_bubun"
DEFAULT_TILE_SIZE_M = 2_000.0
DEFAULT_MAX_FEATURES = 1_000
DEFAULT_MAX_TILES = 120
DEFAULT_MAX_SPLIT_DEPTH = 8
DEFAULT_MAX_REQUESTS_PER_TILE = 512
DEFAULT_MAX_RETRIES = 2


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


def _to_nonnegative_int(value, default: int = 0) -> int:
    try:
        number = int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


def _publication_key(properties: dict) -> tuple[int, int, int]:
    year = _to_nonnegative_int(properties.get("gosi_year"), -1)
    month = _to_nonnegative_int(properties.get("gosi_month"), -1)
    has_price = int(_to_float(properties.get("jiga")) is not None)
    return year, month, has_price


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
        max_features: int = DEFAULT_MAX_FEATURES,
        max_split_depth: int = DEFAULT_MAX_SPLIT_DEPTH,
        max_requests_per_tile: int = DEFAULT_MAX_REQUESTS_PER_TILE,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self.api_key = api_key or _credential("VWORLD_API_KEY")
        self.domain = domain or _credential("VWORLD_DOMAIN")
        self.tile_size_m = float(tile_size_m)
        self.timeout = float(timeout)
        self.max_tiles = int(max_tiles)
        self.max_features = int(max_features)
        self.max_split_depth = int(max_split_depth)
        self.max_requests_per_tile = int(max_requests_per_tile)
        self.max_retries = int(max_retries)
        if self.max_features < 1:
            raise ValueError("max_features must be greater than 0.")
        if self.max_split_depth < 0:
            raise ValueError("max_split_depth must be non-negative.")
        if self.max_requests_per_tile < 1:
            raise ValueError("max_requests_per_tile must be greater than 0.")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative.")
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

    def _request_bbox(
        self,
        bbox_wgs84: tuple[float, float, float, float],
    ) -> dict:
        params = {
            "service": "WFS",
            "request": "GetFeature",
            "version": "1.1.0",
            "typeName": VWORLD_PARCEL_LAYER,
            "bbox": ",".join(f"{value:.8f}" for value in bbox_wgs84),
            "output": "application/json",
            "srsName": "EPSG:4326",
            "maxFeatures": str(self.max_features),
            "key": self.api_key,
            "domain": self.domain,
        }
        request = urllib.request.Request(
            f"{VWORLD_WFS_URL}?{urllib.parse.urlencode(params)}",
            method="GET",
        )
        last_error: VWorldRequestError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                    headers = getattr(response, "headers", None)
                    content_type = headers.get("Content-Type", "") if headers is not None else ""
            except urllib.error.HTTPError as error:
                retryable = error.code == 429 or error.code >= 500
                last_error = VWorldRequestError(
                    f"VWorld parcel WFS HTTP error: {error.code}"
                )
                if not retryable or attempt >= self.max_retries:
                    raise last_error from error
            except urllib.error.URLError as error:
                last_error = VWorldRequestError(
                    f"VWorld parcel WFS request failed: {error.reason}"
                )
                if attempt >= self.max_retries:
                    raise last_error from error
            else:
                try:
                    data = json.loads(raw.decode("utf-8"))
                    if not isinstance(data, dict):
                        raise ValueError("top-level JSON value is not an object")
                    return data
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                    preview = " ".join(
                        raw[:300].decode("utf-8", errors="replace").split()
                    )
                    last_error = VWorldRequestError(
                        "VWorld parcel WFS returned a non-JSON response "
                        f"(content-type={content_type or 'unknown'}, body={preview!r})."
                    )
                    if attempt >= self.max_retries:
                        raise last_error from error

            time.sleep(0.25 * (2**attempt))

        if last_error is not None:
            raise last_error
        raise VWorldRequestError("VWorld parcel WFS request failed.")

    @staticmethod
    def _split_bbox(
        bbox_wgs84: tuple[float, float, float, float],
    ) -> tuple[tuple[float, float, float, float], ...]:
        min_lon, min_lat, max_lon, max_lat = bbox_wgs84
        mid_lon = (min_lon + max_lon) / 2.0
        mid_lat = (min_lat + max_lat) / 2.0
        return (
            (min_lon, min_lat, mid_lon, mid_lat),
            (mid_lon, min_lat, max_lon, mid_lat),
            (min_lon, mid_lat, mid_lon, max_lat),
            (mid_lon, mid_lat, max_lon, max_lat),
        )

    def _fetch_bbox_features(
        self,
        bbox_wgs84: tuple[float, float, float, float],
        *,
        depth: int,
        request_count: list[int],
    ) -> list[dict]:
        request_count[0] += 1
        if request_count[0] > self.max_requests_per_tile:
            raise VWorldRequestError(
                "VWorld parcel WFS spatial subdivision exceeded "
                f"{self.max_requests_per_tile} requests for one tile."
            )

        data = self._request_bbox(bbox_wgs84)
        raw_features = data.get("features", [])
        if not isinstance(raw_features, list):
            raise VWorldRequestError("VWorld parcel WFS features must be a list.")
        features = [feature for feature in raw_features if isinstance(feature, dict)]
        total_value = data.get("totalFeatures")
        total = _to_nonnegative_int(total_value, len(features))
        is_truncated = total > len(features) or (
            total_value in (None, "") and len(features) >= self.max_features
        )
        if not is_truncated:
            return features
        if depth >= self.max_split_depth:
            raise VWorldRequestError(
                "VWorld parcel WFS still exceeds the feature limit after "
                f"{self.max_split_depth} spatial subdivisions."
            )

        split_features: list[dict] = []
        for child_bbox in self._split_bbox(bbox_wgs84):
            split_features.extend(
                self._fetch_bbox_features(
                    child_bbox,
                    depth=depth + 1,
                    request_count=request_count,
                )
            )
        return split_features

    def _fetch_tile(self, tile_x: int, tile_y: int) -> list[Parcel]:
        key = (tile_x, tile_y)
        with self._lock:
            cached = self._tile_cache.get(key)
            if cached is not None:
                return cached

        bbox_wgs84 = self._tile_bounds_wgs84(tile_x, tile_y)
        features = self._fetch_bbox_features(
            bbox_wgs84,
            depth=0,
            request_count=[0],
        )

        wgs84_to_dem, _ = _transformers()
        parcels_by_pnu: dict[str, Parcel] = {}
        publication_by_pnu: dict[str, tuple[int, int, int]] = {}
        for feature in features:
            properties = feature.get("properties") or {}
            geometry_json = feature.get("geometry")
            pnu = str(properties.get("pnu") or "").strip()
            if not pnu or not geometry_json:
                continue
            publication_key = _publication_key(properties)
            existing_key = publication_by_pnu.get(pnu)
            if existing_key is not None and publication_key <= existing_key:
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
            publication_by_pnu[pnu] = publication_key

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
