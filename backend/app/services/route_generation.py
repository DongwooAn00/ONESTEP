from __future__ import annotations

from math import cos, hypot, radians

from app.schemas.route_cost import Coordinate
from app.schemas.route_generation import (
    GeneratedRouteCandidate,
    RouteGenerationRequest,
    RouteGenerationResult,
)


def _lon_lat_to_local_meters(lon: float, lat: float, ref_lat: float) -> tuple[float, float]:
    meters_per_degree_lat = 111_320.0
    meters_per_degree_lon = 111_320.0 * cos(radians(ref_lat))
    return lon * meters_per_degree_lon, lat * meters_per_degree_lat


def _local_meters_to_lon_lat(x: float, y: float, ref_lat: float) -> tuple[float, float]:
    meters_per_degree_lat = 111_320.0
    meters_per_degree_lon = 111_320.0 * cos(radians(ref_lat))
    return x / meters_per_degree_lon, y / meters_per_degree_lat


def _candidate_lines(
    start_lon: float,
    start_lat: float,
    end_lon: float,
    end_lat: float,
) -> list[tuple[str, list[tuple[float, float]]]]:
    ref_lat = (start_lat + end_lat) / 2
    start_x, start_y = _lon_lat_to_local_meters(start_lon, start_lat, ref_lat)
    end_x, end_y = _lon_lat_to_local_meters(end_lon, end_lat, ref_lat)
    dx = end_x - start_x
    dy = end_y - start_y
    distance = hypot(dx, dy)
    if distance == 0:
        raise ValueError("출발지와 도착지가 너무 가깝습니다.")

    normal_x = -dy / distance
    normal_y = dx / distance
    offset = min(max(distance * 0.2, 500), 3000)
    mid_x = (start_x + end_x) / 2
    mid_y = (start_y + end_y) / 2

    def to_coordinate(x: float, y: float) -> tuple[float, float]:
        lon, lat = _local_meters_to_lon_lat(x, y, ref_lat)
        return lon, lat

    return [
        ("straight", [to_coordinate(start_x, start_y), to_coordinate(end_x, end_y)]),
        (
            "left_bypass",
            [
                to_coordinate(start_x, start_y),
                to_coordinate(mid_x + normal_x * offset, mid_y + normal_y * offset),
                to_coordinate(end_x, end_y),
            ],
        ),
        (
            "right_bypass",
            [
                to_coordinate(start_x, start_y),
                to_coordinate(mid_x - normal_x * offset, mid_y - normal_y * offset),
                to_coordinate(end_x, end_y),
            ],
        ),
    ]


def generate_route_candidates(payload: RouteGenerationRequest) -> RouteGenerationResult:
    # MVP 기본값. 이후 알고리즘 팀원이 이 함수의 내부 생성 방식을 교체하면 된다.
    candidates: list[GeneratedRouteCandidate] = []
    for name, points in _candidate_lines(
        payload.start_lon,
        payload.start_lat,
        payload.end_lon,
        payload.end_lat,
    )[
        : payload.candidate_count
    ]:
        candidates.append(
            GeneratedRouteCandidate(
                name=name,
                coordinates=[Coordinate(lat=lat, lon=lon) for lon, lat in points],
            )
        )

    return RouteGenerationResult(candidates=candidates)
