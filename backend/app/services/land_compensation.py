"""후보 노선 생성 이후 필지별 토지보상비를 계산한다."""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median
from typing import Any, Mapping, Protocol, Sequence


DEFAULT_PRICE_PER_M2 = 100_000.0
LAND_COMPENSATION_FACTOR = 1.5
DEFAULT_K = 5
DEFAULT_MAX_DISTANCE_M = 1_000.0
LAND_COMPENSATION_MULTIPLIERS = {
    "forest": 1.2,
    "farmland": 1.4,
    "residential": 1.8,
    "commercial_industrial": 2.0,
    "unknown": 1.5,
}
LAND_CATEGORY_MAPPING = {
    "임야": "forest",
    "전": "farmland",
    "답": "farmland",
    "과수원": "farmland",
    "대": "residential",
    "대지": "residential",
    "공장용지": "commercial_industrial",
    "창고용지": "commercial_industrial",
    "주차장": "commercial_industrial",
    "주유소용지": "commercial_industrial",
}


@dataclass
class Parcel:
    """토지보상비 계산에 필요한 최소 필지 정보."""

    pnu: str
    lawd_code: str
    sigungu_code: str
    land_type: str
    geometry: Any
    official_price_per_m2: float | None = None
    land_category_raw: str | None = None


ParcelLike = Parcel | Mapping[str, Any]


class ParcelRepository(Protocol):
    """실제 필지 DB/API 또는 테스트 저장소가 구현할 조회 계약."""

    def get_intersected_parcels(
        self,
        route_geom: Any,
        road_width_m: float,
    ) -> list[ParcelLike]:
        """노선 도로부지와 교차하는 필지를 반환한다."""

    def get_reference_parcels(self, target_parcel: ParcelLike) -> list[ParcelLike]:
        """중앙값 및 KNN 계산에 사용할 공식가격 보유 후보 필지를 반환한다."""


class NullParcelRepository:
    """실제 필지 경계 저장소가 연결되기 전 사용하는 안전한 저장소."""

    warning = "필지 경계/공시지가 저장소가 연결되지 않아 토지보상비를 0원으로 처리했습니다."

    def get_intersected_parcels(
        self,
        route_geom: Any,
        road_width_m: float,
    ) -> list[ParcelLike]:
        """연결 전에는 빈 필지 목록을 반환한다."""
        return []

    def get_reference_parcels(self, target_parcel: ParcelLike) -> list[ParcelLike]:
        """연결 전에는 가격 참조 필지를 반환하지 않는다."""
        return []


class InMemoryParcelRepository:
    """단위 테스트와 MVP mock 데이터에 사용하는 메모리 저장소."""

    def __init__(
        self,
        parcels: Sequence[ParcelLike],
        *,
        reference_parcels: Sequence[ParcelLike] | None = None,
    ) -> None:
        self.parcels = list(parcels)
        self.reference_parcels = (
            list(reference_parcels)
            if reference_parcels is not None
            else list(parcels)
        )

    def get_intersected_parcels(
        self,
        route_geom: Any,
        road_width_m: float,
    ) -> list[ParcelLike]:
        """도로 중심선을 전체 폭의 절반만큼 버퍼해 교차 필지를 찾는다."""
        corridor = _buffer_route(route_geom, road_width_m)
        return [
            parcel
            for parcel in self.parcels
            if _geometry(parcel).intersects(corridor)
        ]

    def get_reference_parcels(self, target_parcel: ParcelLike) -> list[ParcelLike]:
        """등록된 가격 참조 필지 전체를 반환한다."""
        return list(self.reference_parcels)


def _value(parcel: ParcelLike, field: str, default: Any = None) -> Any:
    if isinstance(parcel, Mapping):
        return parcel.get(field, default)
    return getattr(parcel, field, default)


def _geometry(parcel: ParcelLike) -> Any:
    geometry = _value(parcel, "geometry")
    if geometry is None:
        raise ValueError("parcel.geometry가 필요합니다.")
    return geometry


def _valid_price(value: Any) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(price) or price <= 0:
        return None
    return price


def classify_land_type(value: Any) -> str:
    raw = str(value or "").strip()
    if raw in LAND_COMPENSATION_MULTIPLIERS:
        return raw
    if raw in LAND_CATEGORY_MAPPING:
        return LAND_CATEGORY_MAPPING[raw]
    normalized = raw.replace(" ", "")
    if normalized in LAND_CATEGORY_MAPPING:
        return LAND_CATEGORY_MAPPING[normalized]
    if "임야" in normalized or "산림" in normalized:
        return "forest"
    if normalized in {"전", "답", "과수원"} or "농지" in normalized:
        return "farmland"
    if normalized in {"대", "대지"} or "주거" in normalized:
        return "residential"
    if any(
        token in normalized
        for token in ("상업", "공업", "공장", "창고", "주차장", "주유소")
    ):
        return "commercial_industrial"
    return "unknown"


def _land_category_raw(parcel: ParcelLike) -> str:
    for field in (
        "land_category_raw",
        "land_category",
        "지목",
        "land_use",
        "use_region",
        "land_type",
    ):
        value = _value(parcel, field)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _same_parcel(left: ParcelLike, right: ParcelLike) -> bool:
    if left is right:
        return True
    left_pnu = str(_value(left, "pnu") or "")
    right_pnu = str(_value(right, "pnu") or "")
    return bool(left_pnu and left_pnu == right_pnu)


def _centroid_distance_m(left: ParcelLike, right: ParcelLike) -> float | None:
    try:
        distance = float(_geometry(left).centroid.distance(_geometry(right).centroid))
    except (AttributeError, TypeError, ValueError):
        return None
    if not math.isfinite(distance) or distance < 0:
        return None
    return distance


def _official_median(
    parcels: Sequence[ParcelLike],
    *,
    code_field: str,
    code_value: str,
    land_type: str,
) -> float | None:
    prices = [
        price
        for parcel in parcels
        if str(_value(parcel, code_field) or "") == code_value
        and str(_value(parcel, "land_type") or "") == land_type
        and (price := _valid_price(_value(parcel, "official_price_per_m2")))
        is not None
    ]
    return float(median(prices)) if prices else None


def estimate_missing_land_price_knn(
    target_parcel: ParcelLike,
    nearby_parcels: Sequence[ParcelLike],
    k: int = DEFAULT_K,
    max_distance_m: float = DEFAULT_MAX_DISTANCE_M,
) -> tuple[float | None, dict[str, Any]]:
    """공식가격이 없는 필지만 거리 가중 KNN으로 가격을 추정한다."""
    if k < 1:
        raise ValueError("k는 1 이상이어야 합니다.")
    if max_distance_m <= 0:
        raise ValueError("max_distance_m은 0보다 커야 합니다.")

    target_land_type = str(_value(target_parcel, "land_type") or "")
    candidates: list[tuple[float, float, bool]] = []
    for neighbor in nearby_parcels:
        if _same_parcel(target_parcel, neighbor):
            continue
        price = _valid_price(_value(neighbor, "official_price_per_m2"))
        if price is None:
            continue
        distance = _centroid_distance_m(target_parcel, neighbor)
        if distance is None or distance > max_distance_m:
            continue
        candidates.append(
            (
                distance,
                price,
                str(_value(neighbor, "land_type") or "") == target_land_type,
            )
        )

    same_type = [candidate for candidate in candidates if candidate[2]]
    used_same_land_type = len(same_type) >= k
    active_candidates = same_type if used_same_land_type else candidates
    selected = sorted(active_candidates, key=lambda item: item[0])[:k]
    metadata = {
        "neighbor_count": len(selected),
        "max_distance_m": float(max_distance_m),
        "used_same_land_type": used_same_land_type,
        "mean_distance_m": (
            round(sum(item[0] for item in selected) / len(selected), 3)
            if selected
            else None
        ),
        "source": "knn_fallback",
    }
    if not selected:
        return None, metadata

    weighted_sum = sum(price / (distance + 1.0) for distance, price, _ in selected)
    weight_sum = sum(1.0 / (distance + 1.0) for distance, _, _ in selected)
    return weighted_sum / weight_sum, metadata


def _resolve_land_price_with_metadata(
    parcel: ParcelLike,
    reference_parcels: Sequence[ParcelLike],
    *,
    k: int,
    max_distance_m: float,
    default_price_per_m2: float,
) -> tuple[float, str, dict[str, Any]]:
    official_price = _valid_price(_value(parcel, "official_price_per_m2"))
    if official_price is not None:
        return official_price, "official", {"source": "official"}

    lawd_code = str(_value(parcel, "lawd_code") or "")
    sigungu_code = str(_value(parcel, "sigungu_code") or "")
    land_type = str(_value(parcel, "land_type") or "")

    lawd_median = _official_median(
        reference_parcels,
        code_field="lawd_code",
        code_value=lawd_code,
        land_type=land_type,
    )
    if lawd_median is not None:
        return (
            lawd_median,
            "lawd_land_type_median",
            {"source": "lawd_land_type_median"},
        )

    knn_price, knn_metadata = estimate_missing_land_price_knn(
        parcel,
        reference_parcels,
        k=k,
        max_distance_m=max_distance_m,
    )
    if knn_price is not None:
        return knn_price, "knn_fallback", knn_metadata

    sigungu_median = _official_median(
        reference_parcels,
        code_field="sigungu_code",
        code_value=sigungu_code,
        land_type=land_type,
    )
    if sigungu_median is not None:
        return (
            sigungu_median,
            "sigungu_land_type_median",
            {"source": "sigungu_land_type_median"},
        )

    default_price = _valid_price(default_price_per_m2)
    if default_price is None:
        default_price = DEFAULT_PRICE_PER_M2
    return default_price, "default", {"source": "default"}


def resolve_land_price(
    parcel: ParcelLike,
    reference_parcels: Sequence[ParcelLike] = (),
    *,
    k: int = DEFAULT_K,
    max_distance_m: float = DEFAULT_MAX_DISTANCE_M,
    default_price_per_m2: float = DEFAULT_PRICE_PER_M2,
) -> tuple[float, str]:
    """공식값, 법정동 중앙값, KNN, 시군구 중앙값, 기본값 순으로 가격을 결정한다."""
    price, source, _ = _resolve_land_price_with_metadata(
        parcel,
        reference_parcels,
        k=k,
        max_distance_m=max_distance_m,
        default_price_per_m2=default_price_per_m2,
    )
    return price, source


def _buffer_route(route_geom: Any, road_width_m: float) -> Any:
    if road_width_m <= 0:
        raise ValueError("road_width_m은 0보다 커야 합니다.")
    try:
        return route_geom.buffer(road_width_m / 2.0)
    except AttributeError as error:
        raise ValueError("route_geom은 meter 단위 CRS의 buffer 지원 geometry여야 합니다.") from error


def get_intersected_parcels(
    route_geom: Any,
    road_width_m: float,
    repository: ParcelRepository | None = None,
) -> list[ParcelLike]:
    """저장소를 통해 도로부지와 교차하는 필지를 조회한다."""
    active_repository = repository or NullParcelRepository()
    return active_repository.get_intersected_parcels(route_geom, road_width_m)


def _empty_result(
    *,
    factor: float,
    road_width_m: float,
    warning: str | None = None,
) -> dict[str, Any]:
    return {
        "total_land_compensation": 0.0,
        "factor": factor,
        "road_width_m": road_width_m,
        "parcel_count": 0,
        "official_count": 0,
        "estimated_count": 0,
        "source_counts": {},
        "land_compensation_total": 0.0,
        "land_compensation_by_land_type": {
            land_type: 0.0 for land_type in LAND_COMPENSATION_MULTIPLIERS
        },
        "items": [],
        "warnings": [warning] if warning else [],
    }


def estimate_land_compensation(
    route_geom: Any,
    road_width_m: float,
    repository: ParcelRepository | None = None,
    *,
    factor: float = LAND_COMPENSATION_FACTOR,
    k: int = DEFAULT_K,
    max_distance_m: float = DEFAULT_MAX_DISTANCE_M,
    default_price_per_m2: float = DEFAULT_PRICE_PER_M2,
) -> dict[str, Any]:
    """편입면적 × 결정 공시지가 × 보정계수로 후보 노선의 토지보상비를 계산한다."""
    active_repository = repository or NullParcelRepository()
    if factor <= 0:
        raise ValueError("factor는 0보다 커야 합니다.")
    if road_width_m <= 0:
        raise ValueError("road_width_m은 0보다 커야 합니다.")

    try:
        parcels = get_intersected_parcels(
            route_geom,
            road_width_m,
            active_repository,
        )
    except Exception as error:
        return _empty_result(
            factor=factor,
            road_width_m=road_width_m,
            warning=f"편입 필지 조회 실패로 토지보상비를 0원으로 처리했습니다: {error}",
        )

    if not parcels:
        warning = getattr(active_repository, "warning", None)
        return _empty_result(
            factor=factor,
            road_width_m=road_width_m,
            warning=warning,
        )

    try:
        corridor = _buffer_route(route_geom, road_width_m)
    except Exception as error:
        return _empty_result(
            factor=factor,
            road_width_m=road_width_m,
            warning=f"노선 버퍼 생성 실패로 토지보상비를 0원으로 처리했습니다: {error}",
        )

    items: list[dict[str, Any]] = []
    warnings: list[str] = []
    source_counts: dict[str, int] = {}
    compensation_by_land_type = {
        land_type: 0.0 for land_type in LAND_COMPENSATION_MULTIPLIERS
    }
    for parcel in parcels:
        pnu = str(_value(parcel, "pnu") or "")
        try:
            intersection = _geometry(parcel).intersection(corridor)
            area_m2 = float(intersection.area)
            if not math.isfinite(area_m2) or area_m2 <= 0:
                continue
        except Exception as error:
            warnings.append(f"{pnu or 'PNU 미상'}: 편입면적 계산 실패 ({error})")
            continue

        official_price = _valid_price(_value(parcel, "official_price_per_m2"))
        if official_price is not None:
            price = official_price
            source = "official"
            metadata = {"source": "official"}
        else:
            try:
                reference_parcels = active_repository.get_reference_parcels(parcel)
            except Exception as error:
                reference_parcels = []
                warnings.append(f"{pnu or 'PNU 미상'}: 참조 필지 조회 실패 ({error})")

            try:
                price, source, metadata = _resolve_land_price_with_metadata(
                    parcel,
                    reference_parcels,
                    k=k,
                    max_distance_m=max_distance_m,
                    default_price_per_m2=default_price_per_m2,
                )
            except Exception as error:
                price = _valid_price(default_price_per_m2) or DEFAULT_PRICE_PER_M2
                source = "default"
                metadata = {"source": "default"}
                warnings.append(f"{pnu or 'PNU 미상'}: 가격 결정 실패 ({error})")

        land_category_raw = _land_category_raw(parcel)
        land_type = classify_land_type(land_category_raw)
        compensation_multiplier = (
            LAND_COMPENSATION_MULTIPLIERS[land_type]
            if land_type != "unknown"
            else factor
        )
        land_cost = area_m2 * price * compensation_multiplier
        source_counts[source] = source_counts.get(source, 0) + 1
        compensation_by_land_type[land_type] += land_cost
        item = {
            "pnu": pnu,
            "land_category_raw": land_category_raw,
            "land_type": land_type,
            "acquired_area_m2": round(area_m2, 3),
            "estimated_land_price": round(price, 3),
            "compensation_multiplier": compensation_multiplier,
            "estimated_compensation": round(land_cost, 3),
            "area_m2": round(area_m2, 3),
            "price_per_m2": round(price, 3),
            "price_source": source,
            "land_cost": round(land_cost, 3),
        }
        if source == "knn_fallback":
            item["price_metadata"] = metadata
        items.append(item)

    total = sum(float(item["land_cost"]) for item in items)
    official_count = source_counts.get("official", 0)
    return {
        "total_land_compensation": round(total, 3),
        "factor": factor,
        "road_width_m": road_width_m,
        "parcel_count": len(items),
        "official_count": official_count,
        "estimated_count": len(items) - official_count,
        "source_counts": source_counts,
        "land_compensation_total": round(total, 3),
        "land_compensation_by_land_type": {
            land_type: round(value, 3)
            for land_type, value in compensation_by_land_type.items()
        },
        "items": items,
        "warnings": warnings,
    }


# TODO: PostGIS 필지 경계 테이블이 확정되면 ParcelRepository 구현을 추가한다.
# TODO: official_price_per_m2가 DB에 없을 때 PNU 단위 VWorld 조회/캐시 저장소를 연결한다.
