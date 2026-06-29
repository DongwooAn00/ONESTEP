from __future__ import annotations

import heapq
import logging
import math
from dataclasses import dataclass

from app.db import connect
from app.schemas.od_candidates import CandidateEdge, CandidateNode
from app.services import route_mvp_config as config
from app.services.cost_grid import dem_to_lon_lat, lon_lat_to_dem
from app.services.region_filter import RegionContext
from app.services.road_network import RoadAccessPoint, nearest_road_node, to_coordinate, to_road_point

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoadGraphNode:
    node_id: str
    x: float
    y: float


@dataclass(frozen=True)
class RoadGraphEdge:
    link_id: str
    from_node_id: str
    to_node_id: str
    road_name: str | None
    road_rank: str | None
    link_category: int | None
    length_m: float
    geometry_xy: list[tuple[float, float]]

    @property
    def is_existing_tunnel(self) -> bool:
        text = f"{self.road_name or ''} {self.link_category or ''}".lower()
        return "tunnel" in text or "터널" in text


@dataclass(frozen=True)
class RoadGraphRoute:
    route_geometry: list[dict[str, float]]
    segment_details: list[dict]
    route_length_km: float
    existing_road_length_km: float
    existing_tunnel_length_km: float
    new_surface_road_length_km: float
    connector_length_km: float
    existing_road_access_length_km: float
    existing_road_access_percent: float
    warnings: list[str]
    road_nodes_before: int = 0
    road_nodes_after: int = 0
    road_edges_before: int = 0
    road_edges_after: int = 0
    origin_road_node_id: str | None = None
    destination_road_node_id: str | None = None
    origin_snap_distance_m: float = 0.0
    destination_snap_distance_m: float = 0.0


def _node_lookup(nodes: list[CandidateNode]) -> dict[str, CandidateNode]:
    return {node.node_id: node for node in nodes}


def _candidate_endpoints(edge: CandidateEdge, nodes: list[CandidateNode]) -> tuple[CandidateNode, CandidateNode]:
    by_id = _node_lookup(nodes)
    from_node = by_id.get(edge.from_node_id)
    to_node = by_id.get(edge.to_node_id)
    if from_node is None or to_node is None:
        raise ValueError(f"candidate node missing for {edge.edge_id}")
    return from_node, to_node


def _road_rank_cost_multiplier(road_rank: str | None) -> float:
    text = str(road_rank or "")
    if text in {"101", "102"}:
        return 0.55
    if text in {"103", "104"}:
        return 0.70
    if text in {"105", "106"}:
        return 0.85
    return 1.0


def _link_cost(edge: RoadGraphEdge) -> float:
    tunnel_factor = 0.9 if edge.is_existing_tunnel else 1.0
    return edge.length_m * _road_rank_cost_multiplier(edge.road_rank) * tunnel_factor


def _distance_m(a: RoadGraphNode, b: RoadGraphNode) -> float:
    return math.hypot(b.x - a.x, b.y - a.y)


def _access_distance_m(node: CandidateNode, access: RoadAccessPoint) -> float:
    point = to_road_point(node.latitude, node.longitude)
    return math.hypot(access.road_x - point.x, access.road_y - point.y)


def _query_corridor_edges(
    start: RoadAccessPoint,
    end: RoadAccessPoint,
    *,
    edge: CandidateEdge,
    buffer_multiplier: float,
    min_buffer_km: float,
    region_context: RegionContext | None = None,
) -> tuple[
    dict[str, RoadGraphNode],
    dict[str, list[RoadGraphEdge]],
    dict[str, int],
]:
    straight_distance_m = max(edge.straight_distance_km * 1000.0, _distance_m(
        RoadGraphNode(start.node_id, start.road_x, start.road_y),
        RoadGraphNode(end.node_id, end.road_x, end.road_y),
    ))
    buffer_m = max(straight_distance_m * buffer_multiplier, min_buffer_km * 1000.0)
    min_x = min(start.road_x, end.road_x) - buffer_m
    max_x = max(start.road_x, end.road_x) + buffer_m
    min_y = min(start.road_y, end.road_y) - buffer_m
    max_y = max(start.road_y, end.road_y) + buffer_m
    if region_context is not None and region_context.enabled and region_context.envelope is not None:
        envelope = region_context.envelope
        region_points = [
            to_road_point(lat, lon)
            for lon, lat in (
                (envelope.min_lon, envelope.min_lat),
                (envelope.min_lon, envelope.max_lat),
                (envelope.max_lon, envelope.min_lat),
                (envelope.max_lon, envelope.max_lat),
            )
        ]
        min_x = max(min_x, min(point.x for point in region_points))
        max_x = min(max_x, max(point.x for point in region_points))
        min_y = max(min_y, min(point.y for point in region_points))
        max_y = min(max_y, max(point.y for point in region_points))
        if min_x >= max_x or min_y >= max_y:
            raise ValueError("기존도로 검색 corridor가 선택 계산 구역과 겹치지 않습니다.")

    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH bbox AS (
                    SELECT ST_MakeEnvelope(%s, %s, %s, %s, 100001) AS geom
                )
                SELECT
                    links.link_id,
                    links.start_node_id,
                    start_nodes.x,
                    start_nodes.y,
                    links.end_node_id,
                    end_nodes.x,
                    end_nodes.y,
                    links.road_name,
                    links.road_rank,
                    links.link_category,
                    links.oneway,
                    COALESCE(links.length_m, ST_Length(links.geom)) AS length_m,
                    ST_AsText(links.geom) AS geom_wkt
                FROM road_links AS links
                JOIN road_nodes AS start_nodes ON start_nodes.node_id = links.start_node_id
                JOIN road_nodes AS end_nodes ON end_nodes.node_id = links.end_node_id
                JOIN bbox ON ST_Intersects(links.geom, bbox.geom)
                WHERE links.start_node_id IS NOT NULL
                  AND links.end_node_id IS NOT NULL
                  AND COALESCE(links.length_m, ST_Length(links.geom)) > 0;
                """,
                (min_x, min_y, max_x, max_y),
            )
            rows = cursor.fetchall()

    road_edges_before = len(rows)
    road_node_ids_before = {
        str(node_id)
        for row in rows
        for node_id in (row[1], row[4])
    }
    if (
        region_context is not None
        and region_context.enabled
        and len(region_context.bounds) > 1
    ):
        filtered_rows = []
        for row in rows:
            start_coordinate = to_coordinate(float(row[2]), float(row[3]))
            end_coordinate = to_coordinate(float(row[5]), float(row[6]))
            if (
                region_context.contains_point(
                    start_coordinate.lon,
                    start_coordinate.lat,
                )
                or region_context.contains_point(
                    end_coordinate.lon,
                    end_coordinate.lat,
                )
            ):
                filtered_rows.append(row)
        rows = filtered_rows

    nodes: dict[str, RoadGraphNode] = {}
    adjacency: dict[str, list[RoadGraphEdge]] = {}
    for row in rows:
        (
            link_id,
            start_node_id,
            start_x,
            start_y,
            end_node_id,
            end_x,
            end_y,
            road_name,
            road_rank,
            link_category,
            oneway,
            length_m,
            geom_wkt,
        ) = row
        start_id = str(start_node_id)
        end_id = str(end_node_id)
        nodes[start_id] = RoadGraphNode(start_id, float(start_x), float(start_y))
        nodes[end_id] = RoadGraphNode(end_id, float(end_x), float(end_y))
        geometry_xy = _coordinates_from_multilinestring_wkt(geom_wkt)
        forward = RoadGraphEdge(
            link_id=str(link_id),
            from_node_id=start_id,
            to_node_id=end_id,
            road_name=road_name,
            road_rank=str(road_rank) if road_rank is not None else None,
            link_category=int(link_category) if link_category is not None else None,
            length_m=float(length_m),
            geometry_xy=geometry_xy,
        )
        adjacency.setdefault(start_id, []).append(forward)
        if str(oneway or "0") != "1":
            adjacency.setdefault(end_id, []).append(
                RoadGraphEdge(
                    link_id=str(link_id),
                    from_node_id=end_id,
                    to_node_id=start_id,
                    road_name=road_name,
                    road_rank=str(road_rank) if road_rank is not None else None,
                    link_category=int(link_category) if link_category is not None else None,
                    length_m=float(length_m),
                    geometry_xy=list(reversed(geometry_xy)),
                )
            )
    road_edges_after = len(rows)
    return nodes, adjacency, {
        "road_nodes_before": len(road_node_ids_before),
        "road_nodes_after": len(nodes),
        "road_edges_before": road_edges_before,
        "road_edges_after": road_edges_after,
    }


def _coordinates_from_multilinestring_wkt(value: str) -> list[tuple[float, float]]:
    raw = value.removeprefix("MULTILINESTRING").strip()
    raw = raw.removeprefix("(").removesuffix(")")
    first_line = raw.split("),(")[0].strip()
    first_line = first_line.removeprefix("(").removesuffix(")")
    coordinates = []
    for pair in first_line.split(","):
        x_text, y_text = pair.strip().split()[:2]
        coordinates.append((float(x_text), float(y_text)))
    return coordinates


def _heuristic(node: RoadGraphNode, goal: RoadGraphNode) -> float:
    return _distance_m(node, goal) * 0.55


def _find_road_path(
    nodes: dict[str, RoadGraphNode],
    adjacency: dict[str, list[RoadGraphEdge]],
    start_node_id: str,
    end_node_id: str,
) -> list[RoadGraphEdge]:
    if start_node_id not in nodes or end_node_id not in nodes:
        raise ValueError("도로망 검색 영역에 출발 또는 도착 도로 노드가 없습니다.")

    goal = nodes[end_node_id]
    frontier: list[tuple[float, int, str]] = [(0.0, 0, start_node_id)]
    came_from: dict[str, tuple[str, RoadGraphEdge] | None] = {start_node_id: None}
    cost_so_far: dict[str, float] = {start_node_id: 0.0}
    sequence = 1

    while frontier:
        _, _, current = heapq.heappop(frontier)
        if current == end_node_id:
            return _reconstruct_path(came_from, current)

        for road_edge in adjacency.get(current, []):
            next_id = road_edge.to_node_id
            new_cost = cost_so_far[current] + _link_cost(road_edge)
            if next_id not in cost_so_far or new_cost < cost_so_far[next_id]:
                cost_so_far[next_id] = new_cost
                priority = new_cost + _heuristic(nodes[next_id], goal)
                heapq.heappush(frontier, (priority, sequence, next_id))
                sequence += 1
                came_from[next_id] = (current, road_edge)

    raise ValueError("도로망 그래프에서 출발점과 도착점을 연결하는 경로를 찾지 못했습니다.")


def _reconstruct_path(
    came_from: dict[str, tuple[str, RoadGraphEdge] | None],
    current: str,
) -> list[RoadGraphEdge]:
    path: list[RoadGraphEdge] = []
    while came_from[current] is not None:
        previous, edge = came_from[current]
        path.append(edge)
        current = previous
    path.reverse()
    return path


def _geometry_to_lat_lon(points: list[tuple[float, float]]) -> list[dict[str, float]]:
    return [{"lat": to_coordinate(x, y).lat, "lon": to_coordinate(x, y).lon} for x, y in points]


def _access_geometry(
    node: CandidateNode,
    access: RoadAccessPoint,
    *,
    road_target: dict[str, float] | None = None,
) -> list[dict[str, float]]:
    direct_geometry = [
        {"lat": node.latitude, "lon": node.longitude},
        road_target
        or {"lat": access.coordinate.lat, "lon": access.coordinate.lon},
    ]
    return _detour_access_geometry_around_buildings(direct_geometry)


def _table_exists(table_name: str) -> bool:
    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass(%s);", (table_name,))
                row = cursor.fetchone()
                return bool(row and row[0])
    except Exception:
        return False


def _point_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _corner_walk(corners: list[tuple[float, float]], start: tuple[float, float], end: tuple[float, float]) -> list[tuple[float, float]]:
    start_index = min(range(len(corners)), key=lambda index: _point_distance(start, corners[index]))
    end_index = min(range(len(corners)), key=lambda index: _point_distance(end, corners[index]))

    def walk(step: int) -> list[tuple[float, float]]:
        indexes = [start_index]
        current = start_index
        while current != end_index:
            current = (current + step) % len(corners)
            indexes.append(current)
            if len(indexes) > len(corners) + 1:
                break
        if start_index == end_index:
            indexes = [start_index, (start_index + step) % len(corners), (start_index + step * 2) % len(corners)]
        return [corners[index] for index in indexes]

    candidates = [walk(1), walk(-1)]
    return min(
        candidates,
        key=lambda path: (
            _point_distance(start, path[0])
            + sum(_point_distance(a, b) for a, b in zip(path, path[1:]))
            + _point_distance(path[-1], end)
        ),
    )


def _detour_access_geometry_around_buildings(geometry: list[dict[str, float]]) -> list[dict[str, float]]:
    if len(geometry) < 2 or not _table_exists("building_footprints"):
        return geometry

    start_dem = lon_lat_to_dem(geometry[0]["lon"], geometry[0]["lat"])
    end_dem = lon_lat_to_dem(geometry[-1]["lon"], geometry[-1]["lat"])
    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    WITH access_line AS (
                        SELECT ST_SetSRID(ST_MakeLine(
                            ST_MakePoint(%s, %s),
                            ST_MakePoint(%s, %s)
                        ), 100002) AS geom
                    ),
                    hit_buildings AS (
                        SELECT ST_Union(building_footprints.geom) AS geom
                        FROM building_footprints, access_line
                        WHERE ST_Intersects(building_footprints.geom, access_line.geom)
                    ),
                    detour_box AS (
                        SELECT ST_Expand(ST_Envelope(geom), %s) AS geom
                        FROM hit_buildings
                        WHERE geom IS NOT NULL
                    )
                    SELECT
                        ST_XMin(geom),
                        ST_YMin(geom),
                        ST_XMax(geom),
                        ST_YMax(geom)
                    FROM detour_box;
                    """,
                    (start_dem.x, start_dem.y, end_dem.x, end_dem.y, config.BUILDING_BUFFER_M),
                )
                row = cursor.fetchone()
    except Exception:
        return geometry

    if not row:
        return geometry

    min_x, min_y, max_x, max_y = (float(value) for value in row)
    corners = [
        (min_x, min_y),
        (min_x, max_y),
        (max_x, max_y),
        (max_x, min_y),
    ]
    detour_points = _corner_walk(corners, (start_dem.x, start_dem.y), (end_dem.x, end_dem.y))
    detour_geometry = [geometry[0]]
    for x, y in detour_points:
        lon, lat = dem_to_lon_lat(x, y)
        detour_geometry.append({"lat": lat, "lon": lon})
    detour_geometry.append(geometry[-1])
    return detour_geometry


def _segment_length_km_from_geometry(points: list[dict[str, float]]) -> float:
    if len(points) < 2:
        return 0.0
    total = 0.0
    road_points = [to_road_point(point["lat"], point["lon"]) for point in points]
    for start, end in zip(road_points, road_points[1:]):
        total += math.hypot(end.x - start.x, end.y - start.y)
    return total / 1000.0


def _append_segment(
    details: list[dict],
    route_id: str,
    segment_type: str,
    geometry: list[dict[str, float]],
) -> None:
    length_km = _segment_length_km_from_geometry(geometry)
    if length_km <= 0:
        return
    details.append(
        {
            "route_id": route_id,
            "segment_id": f"{route_id}-S{len(details) + 1:03d}",
            "segment_type": segment_type,
            "segment_length_km": round(length_km, 3),
            "segment_geometry": geometry,
            "average_slope": 0.0,
            "max_slope": 0.0,
        }
    )


def _merge_existing_road_segments(
    route_id: str,
    road_path: list[RoadGraphEdge],
    details: list[dict],
) -> None:
    current_type = None
    current_geometry: list[dict[str, float]] = []
    for edge in road_path:
        # Existing tunnels are part of the baseline road asset. The MVP segment
        # contract intentionally exposes only existing_road for existing assets.
        segment_type = "existing_road"
        geometry = _geometry_to_lat_lon(edge.geometry_xy)
        if len(geometry) < 2:
            continue
        if current_type != segment_type:
            if current_type and current_geometry:
                _append_segment(details, route_id, current_type, current_geometry)
            current_type = segment_type
            current_geometry = geometry
            continue
        current_geometry.extend(geometry[1:])

    if current_type and current_geometry:
        _append_segment(details, route_id, current_type, current_geometry)


def _flatten_geometry(details: list[dict]) -> list[dict[str, float]]:
    geometry: list[dict[str, float]] = []
    for detail in details:
        segment_geometry = detail["segment_geometry"]
        if not geometry:
            geometry.extend(segment_geometry)
        else:
            geometry.extend(segment_geometry[1:])
    return geometry


def build_road_graph_route(
    edge: CandidateEdge,
    nodes: list[CandidateNode],
    *,
    route_id: str,
    buffer_multiplier: float = 0.25,
    min_buffer_km: float = 8.0,
    region_context: RegionContext | None = None,
) -> RoadGraphRoute:
    from_node, to_node = _candidate_endpoints(edge, nodes)
    start_access = nearest_road_node(from_node.latitude, from_node.longitude)
    end_access = nearest_road_node(to_node.latitude, to_node.longitude)
    start_snap_distance_m = _access_distance_m(from_node, start_access)
    end_snap_distance_m = _access_distance_m(to_node, end_access)
    for candidate_node, access, distance_m in (
        (from_node, start_access, start_snap_distance_m),
        (to_node, end_access, end_snap_distance_m),
    ):
        logger.info(
            "[RoadSnap] candidate_id=%s candidate_node=%s nearest_road_node=%s distance_m=%.1f",
            route_id,
            candidate_node.node_id,
            access.node_id,
            distance_m,
        )
    attempts = list(dict.fromkeys((buffer_multiplier, max(0.5, buffer_multiplier), 1.0)))
    last_error: ValueError | None = None
    for active_buffer in attempts:
        graph_nodes, adjacency, graph_stats = _query_corridor_edges(
            start_access,
            end_access,
            edge=edge,
            buffer_multiplier=active_buffer,
            min_buffer_km=min_buffer_km,
            region_context=region_context,
        )
        try:
            road_path = _find_road_path(
                graph_nodes,
                adjacency,
                start_access.node_id,
                end_access.node_id,
            )
            if active_buffer != attempts[0]:
                logger.info(
                    "[RoadGraph] candidate_id=%s corridor_retry_multiplier=%.2f",
                    route_id,
                    active_buffer,
                )
            break
        except ValueError as error:
            last_error = error
    else:
        raise last_error or ValueError("기존도로 경로를 찾지 못했습니다.")

    details: list[dict] = []
    road_start_geometry = (
        _geometry_to_lat_lon([road_path[0].geometry_xy[0]])
        if road_path and road_path[0].geometry_xy
        else []
    )
    road_end_geometry = (
        _geometry_to_lat_lon([road_path[-1].geometry_xy[-1]])
        if road_path and road_path[-1].geometry_xy
        else []
    )
    start_access_geometry = _access_geometry(
        from_node,
        start_access,
        road_target=road_start_geometry[0] if road_start_geometry else None,
    )
    end_access_geometry = _access_geometry(
        to_node,
        end_access,
        road_target=road_end_geometry[0] if road_end_geometry else None,
    )
    _append_segment(details, route_id, "connector", start_access_geometry)
    _merge_existing_road_segments(route_id, road_path, details)
    _append_segment(details, route_id, "connector", list(reversed(end_access_geometry)))

    existing_road_length_km = round(
        sum(item["segment_length_km"] for item in details if item["segment_type"] == "existing_road"),
        3,
    )
    existing_tunnel_length_km = round(
        sum(item["segment_length_km"] for item in details if item["segment_type"] == "existing_tunnel"),
        3,
    )
    new_surface_road_length_km = round(
        sum(item["segment_length_km"] for item in details if item["segment_type"] == "new_surface_road"),
        3,
    )
    connector_length_km = round(
        sum(item["segment_length_km"] for item in details if item["segment_type"] == "connector"),
        3,
    )
    route_length_km = round(
        existing_road_length_km
        + existing_tunnel_length_km
        + new_surface_road_length_km
        + connector_length_km,
        3,
    )
    existing_access_length = round(existing_road_length_km + existing_tunnel_length_km, 3)
    existing_access_percent = round(existing_access_length / route_length_km * 100.0, 1) if route_length_km else 0.0

    warnings = []
    for candidate_node, access, distance_m in (
        (from_node, start_access, start_snap_distance_m),
        (to_node, end_access, end_snap_distance_m),
    ):
        if distance_m > config.MAX_ROAD_SNAP_DISTANCE_M:
            warning = (
                f"{route_id}: 후보 정점 {candidate_node.node_id}의 최근접 도로 노드 "
                f"{access.node_id}까지 스냅 거리가 {distance_m / 1000.0:.2f} km로 "
                f"허용거리 {config.MAX_ROAD_SNAP_DISTANCE_M / 1000.0:.2f} km를 초과합니다."
            )
            warnings.append(warning)
            logger.warning("[RoadSnap] %s", warning)
    access_distance_m = _access_distance_m(from_node, start_access) + _access_distance_m(to_node, end_access)
    if access_distance_m > config.MAX_ROAD_SNAP_DISTANCE_M * 2:
        warnings.append(
            f"{route_id}: 후보 정점과 기존 도로망 접속 거리 합계가 {access_distance_m / 1000.0:.2f} km입니다."
        )

    return RoadGraphRoute(
        route_geometry=_flatten_geometry(details),
        segment_details=details,
        route_length_km=route_length_km,
        existing_road_length_km=existing_road_length_km,
        existing_tunnel_length_km=existing_tunnel_length_km,
        new_surface_road_length_km=new_surface_road_length_km,
        connector_length_km=connector_length_km,
        existing_road_access_length_km=existing_access_length,
        existing_road_access_percent=existing_access_percent,
        warnings=warnings,
        origin_road_node_id=start_access.node_id,
        destination_road_node_id=end_access.node_id,
        origin_snap_distance_m=round(start_snap_distance_m, 1),
        destination_snap_distance_m=round(end_snap_distance_m, 1),
        **graph_stats,
    )
