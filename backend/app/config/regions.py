"""MVP 시도/광역시 필터에 사용하는 WGS84 bounding box 정의."""

from __future__ import annotations


REGION_BOUNDS: dict[str, dict[str, float]] = {
    "서울특별시": {"min_lon": 126.76, "min_lat": 37.41, "max_lon": 127.19, "max_lat": 37.72},
    "부산광역시": {"min_lon": 128.75, "min_lat": 34.87, "max_lon": 129.32, "max_lat": 35.40},
    "대구광역시": {"min_lon": 128.35, "min_lat": 35.59, "max_lon": 129.00, "max_lat": 36.02},
    "인천광역시": {"min_lon": 124.60, "min_lat": 37.00, "max_lon": 126.80, "max_lat": 37.98},
    "광주광역시": {"min_lon": 126.64, "min_lat": 35.02, "max_lon": 127.02, "max_lat": 35.26},
    "대전광역시": {"min_lon": 127.25, "min_lat": 36.18, "max_lon": 127.56, "max_lat": 36.50},
    "울산광역시": {"min_lon": 128.97, "min_lat": 35.28, "max_lon": 129.47, "max_lat": 35.73},
    "세종특별자치시": {"min_lon": 127.10, "min_lat": 36.40, "max_lon": 127.42, "max_lat": 36.73},
    "경기도": {"min_lon": 126.37, "min_lat": 36.89, "max_lon": 127.86, "max_lat": 38.30},
    "강원특별자치도": {"min_lon": 127.05, "min_lat": 37.02, "max_lon": 129.37, "max_lat": 38.62},
    "충청북도": {"min_lon": 127.27, "min_lat": 36.00, "max_lon": 128.66, "max_lat": 37.25},
    "충청남도": {"min_lon": 125.95, "min_lat": 35.95, "max_lon": 127.63, "max_lat": 37.06},
    "전북특별자치도": {"min_lon": 126.29, "min_lat": 35.30, "max_lon": 127.92, "max_lat": 36.16},
    "전라남도": {"min_lon": 125.05, "min_lat": 33.90, "max_lon": 127.85, "max_lat": 35.50},
    "경상북도": {"min_lon": 127.80, "min_lat": 35.55, "max_lon": 130.92, "max_lat": 37.55},
    "경상남도": {"min_lon": 127.58, "min_lat": 34.55, "max_lon": 129.22, "max_lat": 35.90},
    "제주특별자치도": {"min_lon": 126.08, "min_lat": 33.10, "max_lon": 126.97, "max_lat": 33.62},
}

REGION_CODE_PREFIXES: dict[str, tuple[str, ...]] = {
    "서울특별시": ("11",),
    "부산광역시": ("26",),
    "대구광역시": ("27",),
    "인천광역시": ("28",),
    "광주광역시": ("29",),
    "대전광역시": ("30",),
    "울산광역시": ("31",),
    "세종특별자치시": ("36",),
    "경기도": ("41",),
    "강원특별자치도": ("42", "51"),
    "충청북도": ("43",),
    "충청남도": ("44",),
    "전북특별자치도": ("45", "52"),
    "전라남도": ("46",),
    "경상북도": ("47",),
    "경상남도": ("48",),
    "제주특별자치도": ("50",),
}

REGION_ALIASES = {
    "강원도": "강원특별자치도",
    "전라북도": "전북특별자치도",
}

SUPPORTED_REGIONS = tuple(REGION_BOUNDS)
