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


def _import_pyproj():
    from pyproj import CRS, Transformer

    return CRS, Transformer


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


@lru_cache(maxsize=1)
def _pyproj_transformers():
    crs, transformer = _import_pyproj()
    wgs84 = crs.from_epsg(4326)
    road_srs = crs.from_proj4(ROAD_PROJ4)
    return {
        "wgs84_to_road": transformer.from_crs(wgs84, road_srs, always_xy=True),
        "road_to_wgs84": transformer.from_crs(road_srs, wgs84, always_xy=True),
    }


def _transform(transform, x: float, y: float) -> ProjectedPoint:
    tx, ty, _ = transform.TransformPoint(x, y)
    return ProjectedPoint(tx, ty)


def _transform_pyproj(transform, x: float, y: float) -> ProjectedPoint:
    tx, ty = transform.transform(x, y)
    return ProjectedPoint(tx, ty)


def to_road_point(lat: float, lon: float) -> ProjectedPoint:
    try:
        return _transform_pyproj(_pyproj_transformers()["wgs84_to_road"], lon, lat)
    except ImportError:
        return _transform(_spatial_refs()["wgs84_to_road"], lon, lat)


def to_coordinate(x: float, y: float) -> Coordinate:
    try:
        point = _transform_pyproj(_pyproj_transformers()["road_to_wgs84"], x, y)
    except ImportError:
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


def snap_geometry_to_road_centerline(
    geometry: list[dict[str, float]],
    *,
    max_distance_m: float,
) -> tuple[list[dict[str, float]], list[bool]]:
    """Snap WGS84 points to exact road centerlines in one spatial query."""
    if not geometry:
        return [], []
    projected = [
        to_road_point(
            float(point["lat"]),
            float(point.get("lon", point.get("lng", point.get("longitude")))),
        )
        for point in geometry
    ]
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH input_points AS (
                    SELECT
                        ordinality AS point_index,
                        ST_SetSRID(ST_MakePoint(x, y), 100001) AS geom
                    FROM unnest(
                        %s::double precision[],
                        %s::double precision[]
                    ) WITH ORDINALITY AS points(x, y, ordinality)
                )
                SELECT
                    input_points.point_index,
                    ST_X(nearest.snapped_point) AS snapped_x,
                    ST_Y(nearest.snapped_point) AS snapped_y
                FROM input_points
                LEFT JOIN LATERAL (
                    SELECT ST_ClosestPoint(road_links.geom, input_points.geom) AS snapped_point
                    FROM road_links
                    WHERE ST_DWithin(road_links.geom, input_points.geom, %s)
                    ORDER BY road_links.geom <-> input_points.geom
                    LIMIT 1
                ) AS nearest ON TRUE
                ORDER BY input_points.point_index;
                """,
                (
                    [point.x for point in projected],
                    [point.y for point in projected],
                    max_distance_m,
                ),
            )
            rows = cursor.fetchall()

    snapped_geometry: list[dict[str, float]] = []
    snap_mask: list[bool] = []
    for original, row in zip(geometry, rows):
        if row[1] is None or row[2] is None:
            snapped_geometry.append(dict(original))
            snap_mask.append(False)
            continue
        coordinate = to_coordinate(float(row[1]), float(row[2]))
        snapped_geometry.append({"lat": coordinate.lat, "lon": coordinate.lon})
        snap_mask.append(True)
    return snapped_geometry, snap_mask


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
