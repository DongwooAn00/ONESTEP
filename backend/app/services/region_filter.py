"""선택 시도 bounding box와 경계 buffer를 공통 계산 단계에 제공한다."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from app.config.regions import (
    REGION_ALIASES,
    REGION_BOUNDS,
    REGION_CODE_PREFIXES,
    SUPPORTED_REGIONS,
)


@dataclass(frozen=True)
class RegionBounds:
    name: str
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    def contains(self, longitude: float, latitude: float) -> bool:
        """좌표가 이 bounding box 안에 있는지 반환한다."""
        return (
            self.min_lon <= longitude <= self.max_lon
            and self.min_lat <= latitude <= self.max_lat
        )


@dataclass(frozen=True)
class RegionContext:
    enabled: bool
    selected_regions: tuple[str, ...]
    buffer_km: float
    bounds: tuple[RegionBounds, ...]

    def contains_point(self, longitude: float, latitude: float) -> bool:
        """선택 구역 중 하나의 buffered bbox에 좌표가 포함되는지 확인한다."""
        return not self.enabled or any(
            bound.contains(longitude, latitude) for bound in self.bounds
        )

    def contains_code(self, region_code: object) -> bool:
        """행정구역 코드의 시도 prefix가 선택 구역과 일치하는지 확인한다."""
        if not self.enabled:
            return True
        code = str(region_code or "").strip()
        return any(
            code.startswith(prefix)
            for name in self.selected_regions
            for prefix in REGION_CODE_PREFIXES[name]
        )

    @property
    def envelope(self) -> RegionBounds | None:
        """여러 선택 구역 bbox의 전체 envelope를 반환한다."""
        if not self.bounds:
            return None
        return RegionBounds(
            name="selected_regions_union_envelope",
            min_lon=min(bound.min_lon for bound in self.bounds),
            min_lat=min(bound.min_lat for bound in self.bounds),
            max_lon=max(bound.max_lon for bound in self.bounds),
            max_lat=max(bound.max_lat for bound in self.bounds),
        )

    def summary(self, **metrics: int | float | None) -> dict:
        """API debug 응답용 요약을 생성한다."""
        return {
            "enabled": self.enabled,
            "selected_regions": list(self.selected_regions),
            "buffer_km": self.buffer_km,
            **metrics,
        }


def normalize_region_names(regions: Iterable[str] | None) -> tuple[str, ...]:
    """중복을 제거하고 과거 명칭을 현재 지원 명칭으로 정규화한다."""
    normalized: list[str] = []
    for raw_name in regions or ():
        name = REGION_ALIASES.get(str(raw_name).strip(), str(raw_name).strip())
        if not name:
            continue
        if name not in REGION_BOUNDS:
            supported = ", ".join(SUPPORTED_REGIONS)
            raise ValueError(
                f"지원하지 않는 행정구역입니다: {name}. 지원 목록: {supported}"
            )
        if name not in normalized:
            normalized.append(name)
    return tuple(normalized)


def _buffered_bounds(name: str, buffer_km: float) -> RegionBounds:
    raw = REGION_BOUNDS[name]
    middle_latitude = (raw["min_lat"] + raw["max_lat"]) / 2.0
    latitude_delta = buffer_km / 111.0
    longitude_delta = buffer_km / (
        111.0 * max(0.1, math.cos(math.radians(middle_latitude)))
    )
    return RegionBounds(
        name=name,
        min_lon=raw["min_lon"] - longitude_delta,
        min_lat=raw["min_lat"] - latitude_delta,
        max_lon=raw["max_lon"] + longitude_delta,
        max_lat=raw["max_lat"] + latitude_delta,
    )


def build_region_context(
    selected_regions: Iterable[str] | None = None,
    use_region_filter: bool = False,
    buffer_km: float = 10.0,
) -> RegionContext:
    """빈 선택 또는 비활성 요청은 기존 전체 계산 context로 변환한다."""
    if not math.isfinite(float(buffer_km)) or not 0 <= float(buffer_km) <= 100:
        raise ValueError("region_buffer_km는 0~100 범위여야 합니다.")
    normalized = normalize_region_names(selected_regions)
    enabled = bool(use_region_filter and normalized)
    bounds = (
        tuple(_buffered_bounds(name, float(buffer_km)) for name in normalized)
        if enabled
        else ()
    )
    return RegionContext(
        enabled=enabled,
        selected_regions=normalized if enabled else (),
        buffer_km=float(buffer_km),
        bounds=bounds,
    )
