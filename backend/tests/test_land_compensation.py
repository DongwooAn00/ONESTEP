from __future__ import annotations

import math

from app.schemas.od_candidates import CandidateEdge, CandidateNode
from app.services import land_compensation
from app.services.cost_grid import build_cost_grid
from app.services.land_compensation import (
    DEFAULT_PRICE_PER_M2,
    InMemoryParcelRepository,
    Parcel,
    classify_land_type,
    estimate_land_compensation,
    estimate_missing_land_price_knn,
    resolve_land_price,
)


class PointGeometry:
    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y

    @property
    def centroid(self):
        return self

    def distance(self, other: "PointGeometry") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


class ParcelGeometry(PointGeometry):
    def __init__(self, x: float, y: float, area: float) -> None:
        super().__init__(x, y)
        self.area = area

    def intersects(self, corridor) -> bool:
        return True

    def intersection(self, corridor):
        return self


class RouteGeometry:
    def buffer(self, distance: float):
        return {"buffer_distance": distance}


def _parcel(
    pnu: str,
    *,
    lawd_code: str = "1111010100",
    sigungu_code: str = "11110",
    land_type: str = "대",
    price: float | None = None,
    x: float = 0.0,
    y: float = 0.0,
    area: float = 10.0,
) -> Parcel:
    return Parcel(
        pnu=pnu,
        lawd_code=lawd_code,
        sigungu_code=sigungu_code,
        land_type=land_type,
        geometry=ParcelGeometry(x, y, area),
        official_price_per_m2=price,
    )


def test_resolve_land_price_uses_official_price_first() -> None:
    target = _parcel("target", price=85_000)
    references = [_parcel("reference", price=10_000)]

    assert resolve_land_price(target, references) == (85_000.0, "official")


def test_resolve_land_price_uses_lawd_land_type_median() -> None:
    target = _parcel("target", price=None)
    references = [
        _parcel("one", price=70_000),
        _parcel("two", price=90_000),
        _parcel("other-type", land_type="전", price=500_000),
    ]

    assert resolve_land_price(target, references) == (
        80_000.0,
        "lawd_land_type_median",
    )


def test_resolve_land_price_uses_knn_when_lawd_median_is_missing() -> None:
    target = _parcel("target", lawd_code="A", price=None, x=0)
    references = [
        _parcel("one", lawd_code="B", price=100_000, x=9),
        _parcel("two", lawd_code="C", price=200_000, x=19),
    ]

    price, source = resolve_land_price(target, references, k=2)

    assert source == "knn_fallback"
    assert round(price, 3) == 133_333.333


def test_resolve_land_price_uses_default_when_no_candidates_exist() -> None:
    target = _parcel("target", price=0)

    assert resolve_land_price(target, []) == (
        DEFAULT_PRICE_PER_M2,
        "default",
    )


def test_land_compensation_uses_area_price_and_factor() -> None:
    parcel = _parcel("target", land_type="도로", price=85_000, area=123.4)
    repository = InMemoryParcelRepository([parcel])

    result = estimate_land_compensation(
        RouteGeometry(),
        road_width_m=20,
        repository=repository,
    )

    assert result["parcel_count"] == 1
    assert result["official_count"] == 1
    assert result["items"][0]["area_m2"] == 123.4
    assert result["items"][0]["land_cost"] == 123.4 * 85_000 * 1.5
    assert result["total_land_compensation"] == 123.4 * 85_000 * 1.5


def test_land_category_multipliers_and_route_totals() -> None:
    parcels = [
        _parcel("forest", land_type="임야", price=100_000, area=10),
        _parcel("farm", land_type="전", price=100_000, area=10),
        _parcel("home", land_type="대", price=100_000, area=10),
        _parcel("factory", land_type="공장용지", price=100_000, area=10),
        _parcel("unknown", land_type="도로", price=100_000, area=10),
    ]

    result = estimate_land_compensation(
        RouteGeometry(),
        road_width_m=20,
        repository=InMemoryParcelRepository(parcels),
    )

    assert classify_land_type("임야") == "forest"
    assert classify_land_type("답") == "farmland"
    assert classify_land_type("대지") == "residential"
    assert classify_land_type("창고용지") == "commercial_industrial"
    assert classify_land_type("도로") == "unknown"
    expected = {
        "forest": 1_200_000.0,
        "farmland": 1_400_000.0,
        "residential": 1_800_000.0,
        "commercial_industrial": 2_000_000.0,
        "unknown": 1_500_000.0,
    }
    assert result["land_compensation_by_land_type"] == expected
    assert result["land_compensation_total"] == sum(expected.values())
    assert {
        item["pnu"]: item["compensation_multiplier"] for item in result["items"]
    } == {
        "forest": 1.2,
        "farm": 1.4,
        "home": 1.8,
        "factory": 2.0,
        "unknown": 1.5,
    }


def test_official_price_skips_reference_parcel_lookup() -> None:
    parcel = _parcel("target", price=85_000, area=10)

    class OfficialOnlyRepository(InMemoryParcelRepository):
        def get_reference_parcels(self, target_parcel):
            raise AssertionError("공식값이 있는데 참조 필지를 조회함")

    result = estimate_land_compensation(
        RouteGeometry(),
        road_width_m=20,
        repository=OfficialOnlyRepository([parcel]),
    )

    assert result["official_count"] == 1
    assert result["warnings"] == []


def test_knn_uses_only_same_land_type_when_enough_candidates_exist() -> None:
    target = _parcel("target", land_type="전", price=None, x=0)
    neighbors = [
        _parcel("same-one", land_type="전", price=100_000, x=9),
        _parcel("same-two", land_type="전", price=200_000, x=19),
        _parcel("closer-other", land_type="대", price=9_999_999, x=1),
    ]

    price, metadata = estimate_missing_land_price_knn(
        target,
        neighbors,
        k=2,
    )

    assert round(price or 0, 3) == 133_333.333
    assert metadata["neighbor_count"] == 2
    assert metadata["used_same_land_type"] is True
    assert metadata["source"] == "knn_fallback"


class FlatDemProvider:
    def elevations(self, points):
        return [100.0 for _ in points]


def test_cost_grid_does_not_call_land_price_lookup(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("A* 비용격자에서 토지가격 조회가 호출됨")

    monkeypatch.setattr(
        land_compensation,
        "get_intersected_parcels",
        fail_if_called,
    )
    nodes = [
        CandidateNode(
            node_id="N001",
            latitude=36.5,
            longitude=127.0,
            cluster_total_flow=100,
            included_od_count=1,
        ),
        CandidateNode(
            node_id="N002",
            latitude=36.51,
            longitude=127.01,
            cluster_total_flow=90,
            included_od_count=1,
        ),
    ]
    edge = CandidateEdge(
        edge_id="E001",
        from_node_id="N001",
        to_node_id="N002",
        straight_distance_km=2.0,
        estimated_flow=100,
        rank=1,
    )

    grid, _, _ = build_cost_grid(
        edge,
        nodes,
        dem_provider=FlatDemProvider(),
        apply_optional_layers=False,
    )

    assert grid.cells
