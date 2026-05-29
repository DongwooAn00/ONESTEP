from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.db import connect
from app.schemas.route_cost import Coordinate


ROAD_PROJ4 = (
    "+proj=tmerc +lat_0=38 +lon_0=128 +k=0.9999 "
    "+x_0=400000 +y_0=600000 +ellps=GRS80 +units=m +no_defs"
)


@dataclass(frozen=True)
class ProjectedPoint:
    x: float
    y: float


@dataclass(frozen=True)
class RoadAccessPoint:
    node_id: str
    distance_m: float
    road_x: float
    road_y: float
    coordinate: Coordinate


@dataclass(frozen=True)
class RoadLink:
    link_id: str
    start_node_id: str | None
    end_node_id: str | None
    road_name: str | None
    road_rank: str | None
    length_m: float | None
    coordinates: list[Coordinate]


def _import_osr():
    from osgeo import osr

    return osr


@lru_cache(maxsize=1)
def _spatial_refs():
    osr = _import_osr()

    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    wgs84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    road_srs = osr.SpatialReference()
    road_srs.ImportFromProj4(ROAD_PROJ4)
    road_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    return {
        "wgs84_to_road": osr.CoordinateTransformation(wgs84, road_srs),
        "road_to_wgs84": osr.CoordinateTransformation(road_srs, wgs84),
    }


def _transform(transform, x: float, y: float) -> ProjectedPoint:
    tx, ty, _ = transform.TransformPoint(x, y)
    return ProjectedPoint(tx, ty)


def to_road_point(lat: float, lon: float) -> ProjectedPoint:
    return _transform(_spatial_refs()["wgs84_to_road"], lon, lat)


def to_coordinate(x: float, y: float) -> Coordinate:
    point = _transform(_spatial_refs()["road_to_wgs84"], x, y)
    return Coordinate(lat=point.y, lon=point.x)


def nearest_road_node(lat: float, lon: float) -> RoadAccessPoint:
    point = to_road_point(lat, lon)
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
                (point.x, point.y),
            )
            row = cursor.fetchone()

    if row is None:
        raise RuntimeError("DB의 road_nodes 테이블에 도로 노드가 없습니다.")

    node_id, x, y, distance_m = row
    return RoadAccessPoint(
        node_id=str(node_id),
        distance_m=float(distance_m),
        road_x=float(x),
        road_y=float(y),
        coordinate=to_coordinate(float(x), float(y)),
    )


def nearby_road_links(lat: float, lon: float, radius_m: float = 2000, limit: int = 100) -> list[RoadLink]:
    point = to_road_point(lat, lon)
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH input_point AS (
                    SELECT ST_SetSRID(ST_MakePoint(%s, %s), 100001) AS geom
                )
                SELECT
                    road_links.link_id,
                    road_links.start_node_id,
                    road_links.end_node_id,
                    road_links.road_name,
                    road_links.road_rank,
                    road_links.length_m,
                    ST_AsText(road_links.geom) AS geom_wkt
                FROM road_links, input_point
                WHERE ST_DWithin(road_links.geom, input_point.geom, %s)
                ORDER BY road_links.geom <-> input_point.geom
                LIMIT %s;
                """,
                (point.x, point.y, radius_m, limit),
            )
            rows = cursor.fetchall()

    return [_road_link_from_row(row) for row in rows]


def links_connected_to_node(node_id: str, limit: int = 100) -> list[RoadLink]:
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    link_id,
                    start_node_id,
                    end_node_id,
                    road_name,
                    road_rank,
                    length_m,
                    ST_AsText(geom) AS geom_wkt
                FROM road_links
                WHERE start_node_id = %s OR end_node_id = %s
                ORDER BY length_m NULLS LAST
                LIMIT %s;
                """,
                (node_id, node_id, limit),
            )
            rows = cursor.fetchall()

    return [_road_link_from_row(row) for row in rows]


def _road_link_from_row(row) -> RoadLink:
    link_id, start_node_id, end_node_id, road_name, road_rank, length_m, geom_wkt = row
    return RoadLink(
        link_id=str(link_id),
        start_node_id=str(start_node_id) if start_node_id is not None else None,
        end_node_id=str(end_node_id) if end_node_id is not None else None,
        road_name=road_name,
        road_rank=road_rank,
        length_m=float(length_m) if length_m is not None else None,
        coordinates=_coordinates_from_multilinestring_wkt(geom_wkt),
    )


def _coordinates_from_multilinestring_wkt(value: str) -> list[Coordinate]:
    raw = value.removeprefix("MULTILINESTRING").strip()
    raw = raw.removeprefix("(").removesuffix(")")
    first_line = raw.split("),(")[0].strip()
    first_line = first_line.removeprefix("(").removesuffix(")")

    coordinates = []
    for pair in first_line.split(","):
        x_text, y_text = pair.strip().split()[:2]
        coordinates.append(to_coordinate(float(x_text), float(y_text)))
    return coordinates
