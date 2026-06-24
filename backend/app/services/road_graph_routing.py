from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

from app.db import connect
from app.schemas.od_candidates import CandidateEdge, CandidateNode
from app.services import route_mvp_config as config
from app.services.road_network import RoadAccessPoint, nearest_road_node, to_coordinate, to_road_point


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
    existing_road_access_length_km: float
    existing_road_access_percent: float
    warnings: list[str]


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
) -> tuple[dict[str, RoadGraphNode], dict[str, list[RoadGraphEdge]]]:
    straight_distance_m = max(edge.straight_distance_km * 1000.0, _distance_m(
        RoadGraphNode(start.node_id, start.road_x, start.road_y),
        RoadGraphNode(end.node_id, end.road_x, end.road_y),
    ))
    buffer_m = max(straight_distance_m * buffer_multiplier, min_buffer_km * 1000.0)
    min_x = min(start.road_x, end.road_x) - buffer_m
    max_x = max(start.road_x, end.road_x) + buffer_m
    min_y = min(start.road_y, end.road_y) - buffer_m
    max_y = max(start.road_y, end.road_y) + buffer_m

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
    return nodes, adjacency


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


def _access_geometry(node: CandidateNode, access: RoadAccessPoint) -> list[dict[str, float]]:
    return [
        {"lat": node.latitude, "lon": node.longitude},
        {"lat": access.coordinate.lat, "lon": access.coordinate.lon},
    ]


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
        segment_type = "existing_tunnel" if edge.is_existing_tunnel else "existing_road"
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
    buffer_multiplier: float = 1.2,
    min_buffer_km: float = 8.0,
) -> RoadGraphRoute:
    from_node, to_node = _candidate_endpoints(edge, nodes)
    start_access = nearest_road_node(from_node.latitude, from_node.longitude)
    end_access = nearest_road_node(to_node.latitude, to_node.longitude)
    graph_nodes, adjacency = _query_corridor_edges(
        start_access,
        end_access,
        edge=edge,
        buffer_multiplier=buffer_multiplier,
        min_buffer_km=min_buffer_km,
    )
    road_path = _find_road_path(graph_nodes, adjacency, start_access.node_id, end_access.node_id)

    details: list[dict] = []
    start_access_geometry = _access_geometry(from_node, start_access)
    end_access_geometry = _access_geometry(to_node, end_access)
    _append_segment(details, route_id, "new_surface_road", start_access_geometry)
    _merge_existing_road_segments(route_id, road_path, details)
    _append_segment(details, route_id, "new_surface_road", list(reversed(end_access_geometry)))

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
    route_length_km = round(
        existing_road_length_km + existing_tunnel_length_km + new_surface_road_length_km,
        3,
    )
    existing_access_length = round(existing_road_length_km + existing_tunnel_length_km, 3)
    existing_access_percent = round(existing_access_length / route_length_km * 100.0, 1) if route_length_km else 0.0

    warnings = []
    access_distance_m = _access_distance_m(from_node, start_access) + _access_distance_m(to_node, end_access)
    if access_distance_m > config.MAX_TOTAL_ROAD_SNAP_DISTANCE_M:
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
        existing_road_access_length_km=existing_access_length,
        existing_road_access_percent=existing_access_percent,
        warnings=warnings,
    )
