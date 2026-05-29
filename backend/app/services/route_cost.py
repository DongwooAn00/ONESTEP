from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import ceil, hypot

from app.db import connect
from app.schemas.route_cost import (
    AccessPoint,
    Coordinate,
    EvaluateRouteRequest,
    EvaluateRouteResult,
    RouteCandidate,
    RouteCostRequest,
    RouteCostResult,
    RouteSegment,
)
from app.schemas.route_generation import RouteGenerationRequest
from app.services.route_generation import generate_route_candidates


DEM_PROJ4 = (
    "+proj=tmerc +lat_0=38 +lon_0=127 +k=1 "
    "+x_0=200000 +y_0=600000 +ellps=GRS80 "
    "+towgs84=0,0,0,0,0,0,0 +units=m +no_defs"
)
ROAD_PROJ4 = (
    "+proj=tmerc +lat_0=38 +lon_0=128 +k=0.9999 "
    "+x_0=400000 +y_0=600000 +ellps=GRS80 +units=m +no_defs"
)


@dataclass(frozen=True)
class ProjectedPoint:
    x: float
    y: float


@dataclass(frozen=True)
class SamplePoint:
    x: float
    y: float
    lon: float
    lat: float
    elevation_m: float


@dataclass(frozen=True)
class ClassifiedSegment:
    segment_type: str
    length_m: float
    slope_percent: float


@dataclass(frozen=True)
class RoadNode:
    node_id: str
    x: float
    y: float
    lon: float
    lat: float
    dem_x: float
    dem_y: float


def _import_osr():
    from osgeo import osr

    return osr


@lru_cache(maxsize=1)
def _spatial_refs():
    osr = _import_osr()
    dem_srs = osr.SpatialReference()
    dem_srs.ImportFromProj4(DEM_PROJ4)
    dem_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    wgs84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    road_srs = osr.SpatialReference()
    road_srs.ImportFromProj4(ROAD_PROJ4)
    road_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    return {
        "wgs84_to_dem": osr.CoordinateTransformation(wgs84, dem_srs),
        "dem_to_wgs84": osr.CoordinateTransformation(dem_srs, wgs84),
        "wgs84_to_road": osr.CoordinateTransformation(wgs84, road_srs),
        "road_to_wgs84": osr.CoordinateTransformation(road_srs, wgs84),
        "road_to_dem": osr.CoordinateTransformation(road_srs, dem_srs),
    }


def _transform(transform, x: float, y: float) -> ProjectedPoint:
    tx, ty, _ = transform.TransformPoint(x, y)
    return ProjectedPoint(tx, ty)


def _nearest_road_node(lat: float, lon: float) -> tuple[RoadNode, float]:
    transforms = _spatial_refs()
    road_point = _transform(transforms["wgs84_to_road"], lon, lat)

    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH input_point AS (
                    SELECT ST_SetSRID(ST_MakePoint(%s, %s), 100001) AS geom
                )
                SELECT
                    road_nodes.node_id,
                    road_nodes.x,
                    road_nodes.y,
                    ST_Distance(road_nodes.geom, input_point.geom) AS distance_m
                FROM road_nodes, input_point
                ORDER BY road_nodes.geom <-> input_point.geom
                LIMIT 1;
                """,
                (road_point.x, road_point.y),
            )
            row = cursor.fetchone()

    if row is None:
        raise RuntimeError("DB의 road_nodes 테이블에 도로 노드가 없습니다.")

    node_id, x, y, distance_m = row
    wgs84 = _transform(transforms["road_to_wgs84"], x, y)
    dem = _transform(transforms["road_to_dem"], x, y)
    return (
        RoadNode(
            node_id=str(node_id),
            x=float(x),
            y=float(y),
            lon=wgs84.x,
            lat=wgs84.y,
            dem_x=dem.x,
            dem_y=dem.y,
        ),
        float(distance_m),
    )


def _sample_elevation(dem_x: float, dem_y: float) -> float:
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH input_point AS (
                    SELECT ST_SetSRID(ST_MakePoint(%s, %s), 100002) AS geom
                )
                SELECT ST_Value(dem_elevation.rast, 1, input_point.geom) AS elevation_m
                FROM dem_elevation, input_point
                WHERE ST_Intersects(dem_elevation.rast, input_point.geom)
                LIMIT 1;
                """,
                (dem_x, dem_y),
            )
            row = cursor.fetchone()

    if row is None:
        raise ValueError("입력 좌표가 DEM 범위를 벗어났습니다.")

    value = row[0]
    if value is None or float(value) == -9999:
        raise ValueError("입력 좌표의 DEM 고도값이 비어 있습니다.")
    return float(value)


def _interpolate_polyline(points: list[ProjectedPoint], interval_m: float) -> list[ProjectedPoint]:
    output = [points[0]]
    for start, end in zip(points, points[1:]):
        dx = end.x - start.x
        dy = end.y - start.y
        length = hypot(dx, dy)
        steps = max(1, ceil(length / interval_m))
        for index in range(1, steps + 1):
            ratio = index / steps
            output.append(ProjectedPoint(start.x + dx * ratio, start.y + dy * ratio))
    return output


def _sample_line(points: list[ProjectedPoint], interval_m: float) -> list[SamplePoint]:
    transforms = _spatial_refs()
    samples = []
    for point in _interpolate_polyline(points, interval_m):
        wgs84 = _transform(transforms["dem_to_wgs84"], point.x, point.y)
        samples.append(
            SamplePoint(
                x=point.x,
                y=point.y,
                lon=wgs84.x,
                lat=wgs84.y,
                elevation_m=_sample_elevation(point.x, point.y),
            )
        )
    return samples


def _coordinates_to_dem_points(coordinates: list[Coordinate]) -> list[ProjectedPoint]:
    transforms = _spatial_refs()
    return [_transform(transforms["wgs84_to_dem"], coordinate.lon, coordinate.lat) for coordinate in coordinates]


def _dem_points_to_coordinates(points: list[ProjectedPoint]) -> list[Coordinate]:
    transforms = _spatial_refs()
    coordinates = []
    for point in points:
        wgs84 = _transform(transforms["dem_to_wgs84"], point.x, point.y)
        coordinates.append(Coordinate(lat=wgs84.y, lon=wgs84.x))
    return coordinates


def classify_profile(
    samples: list[SamplePoint],
    tunnel_slope_percent: float = 15,
    steep_slope_percent: float = 8,
    min_tunnel_run_m: float = 300,
    merge_gap_m: float = 100,
) -> list[ClassifiedSegment]:
    segments = []
    for start, end in zip(samples, samples[1:]):
        length = hypot(end.x - start.x, end.y - start.y)
        slope = abs(end.elevation_m - start.elevation_m) / length * 100 if length else 0
        if slope >= tunnel_slope_percent:
            segment_type = "tunnel"
        elif slope >= steep_slope_percent:
            segment_type = "steep_road"
        else:
            segment_type = "road"
        segments.append(ClassifiedSegment(segment_type, length, slope))

    segments = _downgrade_short_tunnels(segments, min_tunnel_run_m)
    return _merge_tunnel_gaps(segments, merge_gap_m)


def _downgrade_short_tunnels(
    segments: list[ClassifiedSegment], min_tunnel_run_m: float
) -> list[ClassifiedSegment]:
    result = list(segments)
    index = 0
    while index < len(result):
        if result[index].segment_type != "tunnel":
            index += 1
            continue
        end = index
        length = 0.0
        while end < len(result) and result[end].segment_type == "tunnel":
            length += result[end].length_m
            end += 1
        if length < min_tunnel_run_m:
            for cursor in range(index, end):
                result[cursor] = ClassifiedSegment("steep_road", result[cursor].length_m, result[cursor].slope_percent)
        index = end
    return result


def _merge_tunnel_gaps(segments: list[ClassifiedSegment], merge_gap_m: float) -> list[ClassifiedSegment]:
    result = list(segments)
    index = 1
    while index < len(result) - 1:
        if result[index].segment_type == "tunnel":
            index += 1
            continue
        gap_start = index
        gap_length = 0.0
        while index < len(result) and result[index].segment_type != "tunnel":
            gap_length += result[index].length_m
            index += 1
        has_tunnel_before = gap_start > 0 and result[gap_start - 1].segment_type == "tunnel"
        has_tunnel_after = index < len(result) and result[index].segment_type == "tunnel"
        if has_tunnel_before and has_tunnel_after and gap_length <= merge_gap_m:
            for cursor in range(gap_start, index):
                result[cursor] = ClassifiedSegment("tunnel", result[cursor].length_m, result[cursor].slope_percent)
    return result


def _summarize_segments(segments: list[ClassifiedSegment]) -> list[RouteSegment]:
    if not segments:
        return []

    summarized: list[RouteSegment] = []
    current_type = segments[0].segment_type
    current: list[ClassifiedSegment] = []

    for segment in segments:
        if segment.segment_type != current_type:
            summarized.append(_to_route_segment(current_type, current))
            current = []
            current_type = segment.segment_type
        current.append(segment)
    summarized.append(_to_route_segment(current_type, current))
    return summarized


def _to_route_segment(segment_type: str, segments: list[ClassifiedSegment]) -> RouteSegment:
    length = sum(segment.length_m for segment in segments)
    weighted_slope = sum(segment.slope_percent * segment.length_m for segment in segments) / length if length else 0
    max_slope = max((segment.slope_percent for segment in segments), default=0)
    return RouteSegment(
        segment_type=segment_type,
        length_m=round(length, 1),
        average_slope_percent=round(weighted_slope, 2),
        max_slope_percent=round(max_slope, 2),
    )


def _estimate_cost(
    segments: list[ClassifiedSegment],
    road_unit_cost: float,
    tunnel_unit_cost: float,
    steep_road_factor: float,
    rock_factor: float,
) -> float:
    road_m = sum(segment.length_m for segment in segments if segment.segment_type == "road")
    steep_m = sum(segment.length_m for segment in segments if segment.segment_type == "steep_road")
    tunnel_m = sum(segment.length_m for segment in segments if segment.segment_type == "tunnel")
    cost = (
        road_m / 1000 * road_unit_cost
        + steep_m / 1000 * road_unit_cost * steep_road_factor
        + tunnel_m / 1000 * tunnel_unit_cost * rock_factor
    )
    return round(cost, 3)


def evaluate_route_candidate(
    name: str,
    coordinates: list[Coordinate],
    sample_interval_m: float,
    road_unit_cost: float,
    tunnel_unit_cost: float,
    steep_road_factor: float,
    rock_factor: float,
) -> RouteCandidate:
    control_points = _coordinates_to_dem_points(coordinates)
    samples = _sample_line(control_points, sample_interval_m)
    classified = classify_profile(samples)
    total_length = sum(segment.length_m for segment in classified)
    road_length = sum(segment.length_m for segment in classified if segment.segment_type == "road")
    steep_length = sum(segment.length_m for segment in classified if segment.segment_type == "steep_road")
    tunnel_length = sum(segment.length_m for segment in classified if segment.segment_type == "tunnel")

    return RouteCandidate(
        name=name,
        total_length_m=round(total_length, 1),
        road_length_m=round(road_length, 1),
        steep_road_length_m=round(steep_length, 1),
        tunnel_length_m=round(tunnel_length, 1),
        max_slope_percent=round(max((segment.slope_percent for segment in classified), default=0), 2),
        min_elevation_m=round(min(sample.elevation_m for sample in samples), 2),
        max_elevation_m=round(max(sample.elevation_m for sample in samples), 2),
        estimated_cost_billion_krw=_estimate_cost(
            classified,
            road_unit_cost,
            tunnel_unit_cost,
            steep_road_factor,
            rock_factor,
        ),
        segments=_summarize_segments(classified),
        coordinates=[Coordinate(lat=sample.lat, lon=sample.lon) for sample in samples],
    )


def evaluate_route(payload: EvaluateRouteRequest) -> EvaluateRouteResult:
    return EvaluateRouteResult(
        candidate=evaluate_route_candidate(
            name=payload.name,
            coordinates=payload.coordinates,
            sample_interval_m=payload.sample_interval_m,
            road_unit_cost=payload.road_unit_cost_billion_krw_per_km,
            tunnel_unit_cost=payload.tunnel_unit_cost_billion_krw_per_km,
            steep_road_factor=payload.steep_road_factor,
            rock_factor=payload.rock_factor,
        )
    )


def analyze_route_cost(payload: RouteCostRequest) -> RouteCostResult:
    start_node, start_distance = _nearest_road_node(payload.start_lat, payload.start_lon)
    end_node, end_distance = _nearest_road_node(payload.end_lat, payload.end_lon)

    candidates: list[RouteCandidate] = []
    generation_result = generate_route_candidates(
        payload=RouteGenerationRequest(
            start_lat=payload.start_lat,
            start_lon=payload.start_lon,
            end_lat=payload.end_lat,
            end_lon=payload.end_lon,
            rock_factor=payload.rock_factor,
            sample_interval_m=payload.sample_interval_m,
            road_unit_cost_billion_krw_per_km=payload.road_unit_cost_billion_krw_per_km,
            tunnel_unit_cost_billion_krw_per_km=payload.tunnel_unit_cost_billion_krw_per_km,
            steep_road_factor=payload.steep_road_factor,
        )
    )
    for generated in generation_result.candidates:
        candidates.append(
            evaluate_route_candidate(
                name=generated.name,
                coordinates=generated.coordinates,
                sample_interval_m=payload.sample_interval_m,
                road_unit_cost=payload.road_unit_cost_billion_krw_per_km,
                tunnel_unit_cost=payload.tunnel_unit_cost_billion_krw_per_km,
                steep_road_factor=payload.steep_road_factor,
                rock_factor=payload.rock_factor,
            )
        )

    recommended = min(candidates, key=lambda candidate: candidate.estimated_cost_billion_krw)

    return RouteCostResult(
        start_access=AccessPoint(
            node_id=start_node.node_id,
            distance_m=round(start_distance, 1),
            coordinate=Coordinate(lat=start_node.lat, lon=start_node.lon),
        ),
        end_access=AccessPoint(
            node_id=end_node.node_id,
            distance_m=round(end_distance, 1),
            coordinate=Coordinate(lat=end_node.lat, lon=end_node.lon),
        ),
        recommended_candidate=recommended.name,
        candidates=candidates,
    )
