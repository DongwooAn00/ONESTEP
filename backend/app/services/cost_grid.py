from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from app.db import connect
from app.schemas.od_candidates import CandidateEdge, CandidateNode
from app.services import route_mvp_config as config
from app.services.rock_class_estimator import estimate_rock_class
from app.services.road_network import ROAD_PROJ4
from app.services.route_cost import DEM_PROJ4
from app.services.region_filter import RegionContext


@dataclass(frozen=True)
class ProjectedPoint:
    x: float
    y: float


@dataclass
class CostCell:
    row: int
    col: int
    x: float
    y: float
    lon: float
    lat: float
    elevation_m: float | None
    slope_degrees: float = 0.0
    cost: float = 1.0
    river_rank: str | None = None
    road_rank: str | None = None
    road_distance_m: float | None = None
    protected: bool = False
    building: bool = False
    builtup_area: bool = False
    overburden_m: float | None = None
    estimated_rock_class: str | None = None
    rock_class: str | None = None
    local_relief_m: float | None = None
    fault_dist_m: float | None = None
    boundary_dist_m: float | None = None
    rock_ground_factor: float | None = None
    rock_constructability: str | None = None
    risk_reasons: list[str] | None = None

    @property
    def is_river(self) -> bool:
        return self.river_rank is not None


@dataclass
class CostGrid:
    cells: list[list[CostCell]]
    cell_size_m: float
    origin_x: float
    origin_y: float
    warnings: list[str]

    @property
    def height(self) -> int:
        return len(self.cells)

    @property
    def width(self) -> int:
        return len(self.cells[0]) if self.cells else 0

    def cell(self, row: int, col: int) -> CostCell:
        return self.cells[row][col]

    def in_bounds(self, row: int, col: int) -> bool:
        return 0 <= row < self.height and 0 <= col < self.width

    def nearest_index(self, point: ProjectedPoint) -> tuple[int, int]:
        col = round((point.x - self.origin_x) / self.cell_size_m)
        row = round((point.y - self.origin_y) / self.cell_size_m)
        return max(0, min(self.height - 1, row)), max(0, min(self.width - 1, col))


class DemProvider(Protocol):
    def elevations(self, points: list[ProjectedPoint]) -> list[float | None]:
        ...


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

    dem_srs = osr.SpatialReference()
    dem_srs.ImportFromProj4(DEM_PROJ4)
    dem_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    road_srs = osr.SpatialReference()
    road_srs.ImportFromProj4(ROAD_PROJ4)
    road_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    return {
        "wgs84_to_dem": osr.CoordinateTransformation(wgs84, dem_srs),
        "dem_to_wgs84": osr.CoordinateTransformation(dem_srs, wgs84),
        "dem_to_road": osr.CoordinateTransformation(dem_srs, road_srs),
    }


@lru_cache(maxsize=1)
def _pyproj_transformers():
    crs, transformer = _import_pyproj()
    wgs84 = crs.from_epsg(4326)
    dem_srs = crs.from_proj4(DEM_PROJ4)
    road_srs = crs.from_proj4(ROAD_PROJ4)

    return {
        "wgs84_to_dem": transformer.from_crs(wgs84, dem_srs, always_xy=True),
        "dem_to_wgs84": transformer.from_crs(dem_srs, wgs84, always_xy=True),
        "dem_to_road": transformer.from_crs(dem_srs, road_srs, always_xy=True),
    }


def _transform(transform, x: float, y: float) -> ProjectedPoint:
    tx, ty, _ = transform.TransformPoint(x, y)
    return ProjectedPoint(tx, ty)


def _transform_pyproj(transform, x: float, y: float) -> ProjectedPoint:
    tx, ty = transform.transform(x, y)
    return ProjectedPoint(tx, ty)


def lon_lat_to_dem(lon: float, lat: float) -> ProjectedPoint:
    try:
        return _transform_pyproj(_pyproj_transformers()["wgs84_to_dem"], lon, lat)
    except ImportError:
        try:
            return _transform(_spatial_refs()["wgs84_to_dem"], lon, lat)
        except ImportError:
            return _fallback_project(lon, lat)


def dem_to_lon_lat(x: float, y: float) -> tuple[float, float]:
    try:
        point = _transform_pyproj(_pyproj_transformers()["dem_to_wgs84"], x, y)
        return point.x, point.y
    except ImportError:
        try:
            point = _transform(_spatial_refs()["dem_to_wgs84"], x, y)
            return point.x, point.y
        except ImportError:
            return _fallback_unproject(x, y)


def dem_to_road(x: float, y: float) -> ProjectedPoint:
    try:
        return _transform_pyproj(_pyproj_transformers()["dem_to_road"], x, y)
    except ImportError:
        try:
            return _transform(_spatial_refs()["dem_to_road"], x, y)
        except ImportError:
            return ProjectedPoint(x, y)


def _fallback_project(lon: float, lat: float) -> ProjectedPoint:
    ref_lat = 36.5
    return ProjectedPoint(
        lon * 111_320.0 * math.cos(math.radians(ref_lat)),
        lat * 111_320.0,
    )


def _fallback_unproject(x: float, y: float) -> tuple[float, float]:
    ref_lat = 36.5
    return x / (111_320.0 * math.cos(math.radians(ref_lat))), y / 111_320.0


class PostgisDemProvider:
    def __init__(self) -> None:
        self._metadata: tuple[float, float, float, float] | None = None
        self._elevation_cache: dict[tuple[int, int], float | None] = {}

    def _grid_metadata(self) -> tuple[float, float, float, float] | None:
        if self._metadata is not None:
            return self._metadata
        try:
            with connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT
                            ABS(ST_ScaleX(rast)),
                            ABS(ST_ScaleY(rast)),
                            ST_UpperLeftX(rast),
                            ST_UpperLeftY(rast)
                        FROM dem_elevation
                        LIMIT 1;
                        """
                    )
                    row = cursor.fetchone()
            if row is None or any(value is None for value in row):
                return None
            self._metadata = tuple(float(value) for value in row)
            return self._metadata
        except Exception:
            return None

    def resolution_m(self) -> float | None:
        metadata = self._grid_metadata()
        return max(metadata[0], metadata[1]) if metadata is not None else None

    def elevations(self, points: list[ProjectedPoint]) -> list[float | None]:
        if not points:
            return []
        metadata = self._grid_metadata()
        if metadata is None:
            keys = [(round(point.x), round(point.y)) for point in points]
        else:
            scale_x, scale_y, origin_x, origin_y = metadata
            keys = [
                (
                    math.floor((point.x - origin_x) / scale_x),
                    math.floor((origin_y - point.y) / scale_y),
                )
                for point in points
            ]
        missing_by_key: dict[tuple[int, int], ProjectedPoint] = {}
        for key, point in zip(keys, points):
            if key not in self._elevation_cache:
                missing_by_key.setdefault(key, point)
        if missing_by_key:
            missing_keys = list(missing_by_key)
            missing_points = [missing_by_key[key] for key in missing_keys]
            fetched = self._fetch_elevations(missing_points)
            self._elevation_cache.update(zip(missing_keys, fetched))
        return [self._elevation_cache[key] for key in keys]

    @staticmethod
    def _fetch_elevations(points: list[ProjectedPoint]) -> list[float | None]:
        xs = [point.x for point in points]
        ys = [point.y for point in points]
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    WITH input_points AS (
                        SELECT
                            ordinality AS point_index,
                            ST_SetSRID(ST_MakePoint(x, y), 100002) AS geom
                        FROM unnest(
                            %s::double precision[],
                            %s::double precision[]
                        ) WITH ORDINALITY AS points(x, y, ordinality)
                    )
                    SELECT (
                        SELECT ST_Value(dem_elevation.rast, 1, input_points.geom)
                        FROM dem_elevation
                        WHERE ST_Intersects(dem_elevation.rast, input_points.geom)
                        LIMIT 1
                    ) AS elevation_m
                    FROM input_points
                    ORDER BY point_index;
                    """,
                    (xs, ys),
                )
                rows = cursor.fetchall()
        return [
            None
            if row is None or row[0] is None or float(row[0]) == -9999
            else float(row[0])
            for row in rows
        ]


def _table_exists(table_name: str) -> bool:
    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass(%s);", (table_name,))
                row = cursor.fetchone()
                return bool(row and row[0])
    except Exception:
        return False


def _find_existing_table(names: list[str]) -> str | None:
    for name in names:
        if _table_exists(name):
            return name
    return None


@lru_cache(maxsize=16)
def _table_columns(table_name: str) -> frozenset[str]:
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = %s;
                """,
                (table_name,),
            )
            return frozenset(str(row[0]) for row in cursor.fetchall())


def _layer_text_expression(table_name: str) -> str:
    available = _table_columns(table_name)
    columns = [
        f"{table_name}.{column}"
        for column in ("area_type", "type", "name")
        if column in available
    ]
    return f"COALESCE({', '.join(columns)}, '')" if columns else "''"


def _quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _geology_refrock_expression(table_name: str) -> str:
    available = _table_columns(table_name)
    columns = [
        column
        for column in ("refrock", "ROCK", "rock", "lithology", "LITHO", "lithoname")
        if column in available
    ]
    if not columns:
        return "NULL"
    table = _quote_ident(table_name)
    return "COALESCE(" + ", ".join(
        f"NULLIF({table}.{_quote_ident(column)}::text, '')" for column in columns
    ) + ")"


def _normalize_river_rank(value: object) -> str:
    text = str(value or "").lower()
    if any(token in text for token in ("national", "major", "large", "국가", "대하천", "큰")):
        return "large"
    if any(token in text for token in ("small", "minor", "local", "소하천")):
        return "small"
    return "unknown" if not text else "normal"


def _road_multiplier(rank: object) -> tuple[float, str | None]:
    text = str(rank or "").lower()
    if any(token in text for token in ("express", "national", "highway", "고속", "국도")):
        return config.HIGHWAY_ROAD_MULTIPLIER, "highway_or_national"
    if any(token in text for token in ("local", "province", "지방")):
        return config.LOCAL_ROAD_MULTIPLIER, "local"
    return config.GENERAL_ROAD_MULTIPLIER, "road"


def _slope_cost(slope_degrees: float) -> float:
    for upper, cost in config.SLOPE_COST_BREAKS:
        if slope_degrees < upper:
            return cost
    return 12.0


def _adaptive_cell_size(width_m: float, height_m: float, requested_cell_size_m: float) -> float:
    cell_size = requested_cell_size_m
    while math.ceil(width_m / cell_size) * math.ceil(height_m / cell_size) > config.MAX_GRID_CELLS:
        cell_size *= 1.35
    return cell_size


def _node_lookup(nodes: list[CandidateNode]) -> dict[str, CandidateNode]:
    return {node.node_id: node for node in nodes}


def _edge_points(edge: CandidateEdge, nodes: list[CandidateNode]) -> tuple[ProjectedPoint, ProjectedPoint]:
    by_id = _node_lookup(nodes)
    from_node = by_id.get(edge.from_node_id)
    to_node = by_id.get(edge.to_node_id)
    if from_node is None or to_node is None:
        raise ValueError(f"candidate node missing for {edge.edge_id}")
    return (
        lon_lat_to_dem(from_node.longitude, from_node.latitude),
        lon_lat_to_dem(to_node.longitude, to_node.latitude),
    )


def _calculate_slopes(cells: list[list[CostCell]], cell_size_m: float) -> None:
    height = len(cells)
    width = len(cells[0]) if cells else 0
    for row in range(height):
        for col in range(width):
            cell = cells[row][col]
            if cell.elevation_m is None:
                cell.cost = float("inf")
                continue

            neighbor_slopes = []
            for drow, dcol in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nrow = row + drow
                ncol = col + dcol
                if 0 <= nrow < height and 0 <= ncol < width:
                    neighbor = cells[nrow][ncol]
                    if neighbor.elevation_m is not None:
                        dz = abs(neighbor.elevation_m - cell.elevation_m)
                        neighbor_slopes.append(math.degrees(math.atan(dz / cell_size_m)))
            cell.slope_degrees = max(neighbor_slopes, default=0.0)
            cell.cost = _slope_cost(cell.slope_degrees)


def _apply_optional_rivers(grid: CostGrid) -> None:
    table = _find_existing_table(["rivers", "river_lines", "waterways", "streams"])
    if table is None:
        grid.warnings.append("하천/수계 레이어가 없어 하천·계곡 회피 위험 패널티를 반영하지 못했습니다.")
        return

    try:
        cells = [cell for row_cells in grid.cells for cell in row_cells]
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    WITH input_points AS (
                        SELECT
                            ordinality AS point_index,
                            ST_SetSRID(ST_MakePoint(x, y), 100002) AS geom
                        FROM unnest(
                            %s::double precision[],
                            %s::double precision[]
                        ) WITH ORDINALITY AS points(x, y, ordinality)
                    )
                    SELECT input_points.point_index, nearest.river_rank
                    FROM input_points
                    LEFT JOIN LATERAL (
                        SELECT COALESCE(river_rank, rank, type, name, '') AS river_rank
                        FROM {table}
                        WHERE ST_DWithin({table}.geom, input_points.geom, %s)
                        ORDER BY {table}.geom <-> input_points.geom
                        LIMIT 1
                    ) AS nearest ON TRUE
                    ORDER BY input_points.point_index;
                    """,
                    (
                        [cell.x for cell in cells],
                        [cell.y for cell in cells],
                        grid.cell_size_m * 0.7,
                    ),
                )
                results = cursor.fetchall()
        for cell, result in zip(cells, results):
            if result[1] is not None:
                rank = _normalize_river_rank(result[1])
                cell.river_rank = rank
                cell.cost *= config.RIVER_MULTIPLIERS.get(rank, 10.0)
    except Exception as error:
        grid.warnings.append(f"하천 데이터 반영을 건너뜁니다: {error}")


def _apply_optional_roads(grid: CostGrid) -> None:
    if not _table_exists("road_links"):
        grid.warnings.append("기존 도로망 데이터가 없어 도로 접근 비용 보정을 적용하지 않았습니다.")
        return

    try:
        cells = [cell for row_cells in grid.cells for cell in row_cells]
        road_points = [dem_to_road(cell.x, cell.y) for cell in cells]
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
                        nearest.road_rank,
                        nearest.distance_m
                    FROM input_points
                    LEFT JOIN LATERAL (
                        SELECT
                            road_links.road_rank,
                            ST_Distance(road_links.geom, input_points.geom) AS distance_m
                        FROM road_links
                        WHERE ST_DWithin(road_links.geom, input_points.geom, %s)
                        ORDER BY road_links.geom <-> input_points.geom
                        LIMIT 1
                    ) AS nearest ON TRUE
                    ORDER BY input_points.point_index;
                    """,
                    (
                        [point.x for point in road_points],
                        [point.y for point in road_points],
                        config.ROAD_ACCESS_BUFFER_M,
                    ),
                )
                results = cursor.fetchall()
        for cell, result in zip(cells, results):
            if result[1] is not None:
                multiplier, rank = _road_multiplier(result[1])
                cell.cost *= multiplier
                cell.road_rank = rank
                cell.road_distance_m = float(result[2])
    except Exception as error:
        grid.warnings.append(f"기존 도로망 비용 보정을 건너뜁니다: {error}")


def _apply_optional_geology(grid: CostGrid) -> None:
    litho_table = _find_existing_table(["geology_litho"])
    fault_table = _find_existing_table(["geology_faults"])
    boundary_table = _find_existing_table(["geology_boundaries"])
    if litho_table is None and fault_table is None and boundary_table is None:
        grid.warnings.append("수치지질도 레이어가 없어 암반등급·단층거리·지질경계거리를 반영하지 못했습니다.")
        return

    cells = [cell for row_cells in grid.cells for cell in row_cells]
    refrock_expression = _geology_refrock_expression(litho_table) if litho_table is not None else "NULL"
    litho_join = (
        f"""
        LEFT JOIN LATERAL (
            SELECT {refrock_expression} AS refrock
            FROM {_quote_ident(litho_table)}
            ORDER BY
                {_quote_ident(litho_table)}.geom <-> input_points.geom,
                ST_Area({_quote_ident(litho_table)}.geom) ASC
            LIMIT 1
        ) AS litho ON TRUE
        """
        if litho_table is not None
        else "LEFT JOIN LATERAL (SELECT NULL::text AS refrock) AS litho ON TRUE"
    )
    fault_join = (
        f"""
        LEFT JOIN LATERAL (
            SELECT ST_Distance({_quote_ident(fault_table)}.geom::geography, input_points.geom::geography) AS fault_dist_m
            FROM {_quote_ident(fault_table)}
            ORDER BY {_quote_ident(fault_table)}.geom <-> input_points.geom
            LIMIT 1
        ) AS fault ON TRUE
        """
        if fault_table is not None
        else "LEFT JOIN LATERAL (SELECT NULL::double precision AS fault_dist_m) AS fault ON TRUE"
    )
    boundary_join = (
        f"""
        LEFT JOIN LATERAL (
            SELECT ST_Distance({_quote_ident(boundary_table)}.geom::geography, input_points.geom::geography) AS boundary_dist_m
            FROM {_quote_ident(boundary_table)}
            ORDER BY {_quote_ident(boundary_table)}.geom <-> input_points.geom
            LIMIT 1
        ) AS boundary ON TRUE
        """
        if boundary_table is not None
        else "LEFT JOIN LATERAL (SELECT NULL::double precision AS boundary_dist_m) AS boundary ON TRUE"
    )
    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    WITH input_points AS (
                        SELECT
                            ordinality AS point_index,
                            ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS geom
                        FROM unnest(
                            %s::double precision[],
                            %s::double precision[]
                        ) WITH ORDINALITY AS points(lon, lat, ordinality)
                    )
                    SELECT
                        input_points.point_index,
                        litho.refrock,
                        fault.fault_dist_m,
                        boundary.boundary_dist_m
                    FROM input_points
                    {litho_join}
                    {fault_join}
                    {boundary_join}
                    ORDER BY input_points.point_index;
                    """,
                    (
                        [cell.lon for cell in cells],
                        [cell.lat for cell in cells],
                    ),
                )
                results = cursor.fetchall()
    except Exception as error:
        grid.warnings.append(f"수치지질도 반영을 건너뜁니다: {error}")
        return

    for cell, result in zip(cells, results):
        _, refrock, fault_dist_m, boundary_dist_m = result
        fault = float(fault_dist_m) if fault_dist_m is not None else None
        boundary = float(boundary_dist_m) if boundary_dist_m is not None else None
        estimate = estimate_rock_class(
            refrock=refrock,
            overburden_m=None,
            slope_deg=cell.slope_degrees,
            fault_dist_m=fault,
            boundary_dist_m=boundary,
        )
        cell.estimated_rock_class = estimate.estimated_rock_class
        cell.rock_class = estimate.estimated_rock_class
        cell.fault_dist_m = fault
        cell.boundary_dist_m = boundary
        cell.rock_ground_factor = estimate.rock_ground_factor
        cell.rock_constructability = estimate.rock_constructability
        cell.risk_reasons = list(estimate.risk_reasons)


def _apply_optional_protected_areas_legacy(grid: CostGrid) -> None:
    table = _find_existing_table(["protected_areas", "urban_areas", "builtup_areas"])
    if table is None:
        return

    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                for row_cells in grid.cells:
                    for cell in row_cells:
                        cursor.execute(
                            f"""
                            WITH input_point AS (
                                SELECT ST_SetSRID(ST_MakePoint(%s, %s), 100002) AS geom
                            )
                            SELECT COALESCE(area_type, type, name, '') AS area_type
                            FROM {table}, input_point
                            WHERE ST_Intersects({table}.geom, input_point.geom)
                            LIMIT 1;
                            """,
                            (cell.x, cell.y),
                        )
                        result = cursor.fetchone()
                        if not result:
                            continue
                        area_type = str(result[0] or "").lower()
                        if "protect" in area_type or "보호" in area_type:
                            cell.cost = 1_000_000.0
                            cell.protected = True
                        else:
                            cell.cost *= 3.0
    except Exception as error:
        grid.warnings.append(f"보호구역/시가지 비용 보정을 건너뜁니다: {error}")


@lru_cache(maxsize=1)
def _population_urban_index() -> tuple[dict[tuple[int, int], list[tuple[float, float, int]]], float]:
    """Build a coarse spatial index from administrative population centers."""
    radius = config.URBAN_POPULATION_RADIUS_M
    buckets: dict[tuple[int, int], list[tuple[float, float, int]]] = {}
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT representative_lon, representative_lat, population
                FROM admin_dongs
                WHERE representative_lon IS NOT NULL
                  AND representative_lat IS NOT NULL
                  AND population > 0;
                """
            )
            rows = cursor.fetchall()
    for longitude, latitude, population in rows:
        point = lon_lat_to_dem(float(longitude), float(latitude))
        key = (math.floor(point.x / radius), math.floor(point.y / radius))
        buckets.setdefault(key, []).append((point.x, point.y, int(population)))
    return buckets, radius


def _apply_population_urban_penalty(grid: CostGrid) -> bool:
    """Penalize populated urban areas when polygon/building layers are absent."""
    try:
        buckets, radius = _population_urban_index()
    except Exception as error:
        grid.warnings.append(f"행정동 인구 기반 시가지 회피 비용을 반영하지 못했습니다: {error}")
        return False
    if not buckets:
        return False

    radius_squared = radius * radius
    for row_cells in grid.cells:
        for cell in row_cells:
            bucket_x = math.floor(cell.x / radius)
            bucket_y = math.floor(cell.y / radius)
            nearby_population = 0
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for x, y, population in buckets.get((bucket_x + dx, bucket_y + dy), ()):
                        if (x - cell.x) ** 2 + (y - cell.y) ** 2 <= radius_squared:
                            nearby_population += population

            if nearby_population >= config.URBAN_POPULATION_HIGH:
                cell.cost *= config.URBAN_POPULATION_HIGH_MULTIPLIER
                cell.builtup_area = True
            elif nearby_population >= config.URBAN_POPULATION_MEDIUM:
                cell.cost *= config.URBAN_POPULATION_MEDIUM_MULTIPLIER
                cell.builtup_area = True
            elif nearby_population >= config.URBAN_POPULATION_LOW:
                cell.cost *= config.URBAN_POPULATION_LOW_MULTIPLIER
                cell.builtup_area = True
    grid.warnings.append(
        "시가지 폴리곤이 없어 행정동 인구 밀도 기반 회피 패널티를 적용했습니다."
    )
    return True


def _apply_optional_protected_areas(grid: CostGrid) -> None:
    protected_table = _find_existing_table(["protected_areas"])
    building_table = _find_existing_table(["building_footprints"])
    builtup_table = _find_existing_table(["builtup_areas", "urban_areas"])

    if protected_table is None and building_table is None and builtup_table is None:
        if not _apply_population_urban_penalty(grid):
            grid.warnings.append("건물/시가지 레이어가 없어 시가지 회피 비용을 반영하지 못했습니다.")
        return

    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                for row_cells in grid.cells:
                    for cell in row_cells:
                        if protected_table is not None:
                            cursor.execute(
                                f"""
                                WITH input_point AS (
                                    SELECT ST_SetSRID(ST_MakePoint(%s, %s), 100002) AS geom
                                )
                                SELECT COALESCE(area_type, type, name, '') AS area_type
                                FROM {protected_table}, input_point
                                WHERE ST_Intersects({protected_table}.geom, input_point.geom)
                                LIMIT 1;
                                """,
                                (cell.x, cell.y),
                            )
                            result = cursor.fetchone()
                            area_type = str(result[0] or "").lower() if result else ""
                            if result and ("protect" in area_type or "보호" in area_type):
                                cell.cost = config.PROTECTED_AREA_BLOCK_COST
                                cell.protected = True
                                continue

                        if building_table is not None:
                            cursor.execute(
                                f"""
                                WITH input_point AS (
                                    SELECT ST_SetSRID(ST_MakePoint(%s, %s), 100002) AS geom
                                )
                                SELECT 1
                                FROM {building_table}, input_point
                                WHERE ST_Intersects({building_table}.geom, input_point.geom)
                                LIMIT 1;
                                """,
                                (cell.x, cell.y),
                            )
                            if cursor.fetchone():
                                cell.cost = config.BUILDING_BLOCK_COST
                                cell.protected = True
                                cell.building = True
                                continue

                            cursor.execute(
                                f"""
                                WITH input_point AS (
                                    SELECT ST_SetSRID(ST_MakePoint(%s, %s), 100002) AS geom
                                )
                                SELECT 1
                                FROM {building_table}, input_point
                                WHERE ST_DWithin({building_table}.geom, input_point.geom, %s)
                                LIMIT 1;
                                """,
                                (cell.x, cell.y, config.BUILDING_BUFFER_M),
                            )
                            if cursor.fetchone():
                                cell.cost *= config.BUILDING_BUFFER_MULTIPLIER
                                cell.builtup_area = True
                                continue

                        if builtup_table is not None:
                            cursor.execute(
                                f"""
                                WITH input_point AS (
                                    SELECT ST_SetSRID(ST_MakePoint(%s, %s), 100002) AS geom
                                )
                                SELECT COALESCE(area_type, type, name, '') AS area_type
                                FROM {builtup_table}, input_point
                                WHERE ST_Intersects({builtup_table}.geom, input_point.geom)
                                LIMIT 1;
                                """,
                                (cell.x, cell.y),
                            )
                            result = cursor.fetchone()
                            if not result:
                                continue
                            area_type = str(result[0] or "").lower()
                            if "protect" in area_type or "보호" in area_type:
                                cell.cost = config.PROTECTED_AREA_BLOCK_COST
                                cell.protected = True
                            elif "building" in area_type or "건물" in area_type:
                                cell.cost *= config.BUILTUP_AREA_MULTIPLIER
                                cell.builtup_area = True
                            else:
                                cell.cost *= config.URBAN_AREA_MULTIPLIER
                                cell.builtup_area = True
    except Exception as error:
        grid.warnings.append(f"건물/시가지 비용 보정을 건너뜁니다: {error}")


def _apply_optional_protected_areas_batched(grid: CostGrid) -> None:
    """Apply polygon avoidance layers with a bounded number of SQL queries."""
    protected_table = _find_existing_table(["protected_areas"])
    building_table = _find_existing_table(["building_footprints"])
    builtup_table = _find_existing_table(["builtup_areas", "urban_areas"])
    if protected_table is None and building_table is None and builtup_table is None:
        if not _apply_population_urban_penalty(grid):
            grid.warnings.append("건물/시가지 레이어가 없어 시가지 회피 비용을 반영하지 못했습니다.")
        return

    cells = [cell for row_cells in grid.cells for cell in row_cells]
    xs = [cell.x for cell in cells]
    ys = [cell.y for cell in cells]
    protected_types: list[str | None] = [None] * len(cells)
    building_flags: list[tuple[bool, bool]] = [(False, False)] * len(cells)
    builtup_types: list[str | None] = [None] * len(cells)
    try:
        protected_text = (
            _layer_text_expression(protected_table)
            if protected_table is not None
            else "''"
        )
        builtup_text = (
            _layer_text_expression(builtup_table)
            if builtup_table is not None
            else "''"
        )
        with connect() as connection:
            with connection.cursor() as cursor:
                if protected_table is not None:
                    cursor.execute(
                        f"""
                        WITH input_points AS (
                            SELECT ordinality AS point_index,
                                   ST_SetSRID(ST_MakePoint(x, y), 100002) AS geom
                            FROM unnest(%s::double precision[], %s::double precision[])
                                 WITH ORDINALITY AS points(x, y, ordinality)
                        )
                        SELECT input_points.point_index, layer.area_type
                        FROM input_points
                        LEFT JOIN LATERAL (
                            SELECT {protected_text} AS area_type
                            FROM {protected_table}
                            WHERE ST_Intersects({protected_table}.geom, input_points.geom)
                            LIMIT 1
                        ) AS layer ON TRUE
                        ORDER BY input_points.point_index;
                        """,
                        (xs, ys),
                    )
                    protected_types = [
                        str(row[1]).lower() if row[1] is not None else None
                        for row in cursor.fetchall()
                    ]

                if building_table is not None:
                    cursor.execute(
                        f"""
                        WITH input_points AS (
                            SELECT ordinality AS point_index,
                                   ST_SetSRID(ST_MakePoint(x, y), 100002) AS geom
                            FROM unnest(%s::double precision[], %s::double precision[])
                                 WITH ORDINALITY AS points(x, y, ordinality)
                        )
                        SELECT input_points.point_index,
                               EXISTS (
                                   SELECT 1 FROM {building_table}
                                   WHERE ST_Intersects({building_table}.geom, input_points.geom)
                               ) AS intersects_building,
                               EXISTS (
                                   SELECT 1 FROM {building_table}
                                   WHERE ST_DWithin({building_table}.geom, input_points.geom, %s)
                               ) AS near_building
                        FROM input_points
                        ORDER BY input_points.point_index;
                        """,
                        (xs, ys, config.BUILDING_BUFFER_M),
                    )
                    building_flags = [
                        (bool(row[1]), bool(row[2])) for row in cursor.fetchall()
                    ]

                if builtup_table is not None:
                    cursor.execute(
                        f"""
                        WITH input_points AS (
                            SELECT ordinality AS point_index,
                                   ST_SetSRID(ST_MakePoint(x, y), 100002) AS geom
                            FROM unnest(%s::double precision[], %s::double precision[])
                                 WITH ORDINALITY AS points(x, y, ordinality)
                        )
                        SELECT input_points.point_index, layer.area_type
                        FROM input_points
                        LEFT JOIN LATERAL (
                            SELECT {builtup_text} AS area_type
                            FROM {builtup_table}
                            WHERE ST_Intersects({builtup_table}.geom, input_points.geom)
                            LIMIT 1
                        ) AS layer ON TRUE
                        ORDER BY input_points.point_index;
                        """,
                        (xs, ys),
                    )
                    builtup_types = [
                        str(row[1]).lower() if row[1] is not None else None
                        for row in cursor.fetchall()
                    ]
    except Exception as error:
        grid.warnings.append(f"건물/시가지 일괄 비용 보정을 건너뜁니다: {error}")
        return

    for cell, protected_type, building_flag, builtup_type in zip(
        cells, protected_types, building_flags, builtup_types
    ):
        if protected_type and ("protect" in protected_type or "보호" in protected_type):
            cell.cost = config.PROTECTED_AREA_BLOCK_COST
            cell.protected = True
            continue
        intersects_building, near_building = building_flag
        if intersects_building:
            cell.cost = config.BUILDING_BLOCK_COST
            cell.protected = True
            cell.building = True
            continue
        if near_building:
            cell.cost *= config.BUILDING_BUFFER_MULTIPLIER
            cell.builtup_area = True
            continue
        if not builtup_type:
            continue
        if "protect" in builtup_type or "보호" in builtup_type:
            cell.cost = config.PROTECTED_AREA_BLOCK_COST
            cell.protected = True
        elif "building" in builtup_type or "건물" in builtup_type:
            cell.cost *= config.BUILTUP_AREA_MULTIPLIER
            cell.builtup_area = True
        else:
            cell.cost *= config.URBAN_AREA_MULTIPLIER
            cell.builtup_area = True


def build_cost_grid(
    edge: CandidateEdge,
    nodes: list[CandidateNode],
    *,
    buffer_multiplier: float = 0.3,
    min_buffer_km: float = 5.0,
    cell_size_m: float = config.DEFAULT_GRID_CELL_SIZE_M,
    dem_provider: DemProvider | None = None,
    apply_optional_layers: bool = True,
    apply_existing_road_bias: bool = False,
    region_context: RegionContext | None = None,
) -> tuple[CostGrid, ProjectedPoint, ProjectedPoint]:
    start, end = _edge_points(edge, nodes)
    straight_distance_m = max(edge.straight_distance_km * 1000.0, math.hypot(end.x - start.x, end.y - start.y))
    buffer_m = max(straight_distance_m * buffer_multiplier, min_buffer_km * 1000.0)
    min_x = min(start.x, end.x) - buffer_m
    max_x = max(start.x, end.x) + buffer_m
    min_y = min(start.y, end.y) - buffer_m
    max_y = max(start.y, end.y) + buffer_m
    if region_context is not None and region_context.enabled:
        envelope = region_context.envelope
        if envelope is not None:
            region_corners = [
                lon_lat_to_dem(lon, lat)
                for lon, lat in (
                    (envelope.min_lon, envelope.min_lat),
                    (envelope.min_lon, envelope.max_lat),
                    (envelope.max_lon, envelope.min_lat),
                    (envelope.max_lon, envelope.max_lat),
                )
            ]
            min_x = max(min_x, min(point.x for point in region_corners))
            max_x = min(max_x, max(point.x for point in region_corners))
            min_y = max(min_y, min(point.y for point in region_corners))
            max_y = min(max_y, max(point.y for point in region_corners))
            if min_x >= max_x or min_y >= max_y:
                raise ValueError(
                    "후보 연결쌍이 선택 행정구역의 경계 여유 범위 밖에 있습니다."
                )
    active_cell_size = _adaptive_cell_size(
        max_x - min_x,
        max_y - min_y,
        cell_size_m,
    )
    active_provider = dem_provider or PostgisDemProvider()
    dem_resolution_m = active_provider.resolution_m() if hasattr(active_provider, "resolution_m") else None
    if dem_resolution_m:
        active_cell_size = max(active_cell_size, dem_resolution_m)
    width = max(2, math.ceil((max_x - min_x) / active_cell_size) + 1)
    height = max(2, math.ceil((max_y - min_y) / active_cell_size) + 1)

    points = [
        ProjectedPoint(min_x + col * active_cell_size, min_y + row * active_cell_size)
        for row in range(height)
        for col in range(width)
    ]
    elevations = active_provider.elevations(points)
    if len(elevations) != len(points):
        raise ValueError("DEM provider returned an unexpected number of elevation samples.")

    cells: list[list[CostCell]] = []
    iterator = iter(zip(points, elevations))
    for row in range(height):
        row_cells = []
        for col in range(width):
            point, elevation = next(iterator)
            lon, lat = dem_to_lon_lat(point.x, point.y)
            row_cells.append(
                CostCell(row=row, col=col, x=point.x, y=point.y, lon=lon, lat=lat, elevation_m=elevation)
            )
        cells.append(row_cells)

    grid = CostGrid(cells=cells, cell_size_m=active_cell_size, origin_x=min_x, origin_y=min_y, warnings=[])
    _calculate_slopes(grid.cells, grid.cell_size_m)
    if grid.cell(*grid.nearest_index(start)).elevation_m is None or grid.cell(*grid.nearest_index(end)).elevation_m is None:
        raise ValueError("시작점 또는 종료점이 DEM 유효 영역 밖에 있습니다.")

    if apply_optional_layers:
        _apply_optional_rivers(grid)
        if apply_existing_road_bias:
            _apply_optional_roads(grid)
        _apply_optional_geology(grid)
        _apply_optional_protected_areas_batched(grid)
    return grid, start, end


def generate_dem_route_grid(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    *,
    candidate_id: str = "DEM",
    buffer_multiplier: float = 0.3,
    min_buffer_km: float = 5.0,
    cell_size_m: float = config.DEFAULT_GRID_CELL_SIZE_M,
    dem_provider: DemProvider | None = None,
    apply_optional_layers: bool = True,
    region_context: RegionContext | None = None,
) -> tuple[CostGrid, ProjectedPoint, ProjectedPoint]:
    """Build an independent DEM grid for a new link between arbitrary points.

    Existing-road and road-buffer cells receive a lower traversal cost. This
    lets the DEM route stay on the current network and leave it only where a
    terrain-aware new link is worthwhile.
    """
    start_node = CandidateNode(
        node_id=f"{candidate_id}-START",
        latitude=start_lat,
        longitude=start_lon,
        cluster_total_flow=0,
        included_od_count=0,
    )
    end_node = CandidateNode(
        node_id=f"{candidate_id}-END",
        latitude=end_lat,
        longitude=end_lon,
        cluster_total_flow=0,
        included_od_count=0,
    )
    projected_start = lon_lat_to_dem(start_lon, start_lat)
    projected_end = lon_lat_to_dem(end_lon, end_lat)
    straight_distance_km = math.hypot(
        projected_end.x - projected_start.x,
        projected_end.y - projected_start.y,
    ) / 1000.0
    edge = CandidateEdge(
        edge_id=candidate_id,
        from_node_id=start_node.node_id,
        to_node_id=end_node.node_id,
        straight_distance_km=straight_distance_km,
        estimated_flow=0,
        rank=1,
    )
    return build_cost_grid(
        edge,
        [start_node, end_node],
        buffer_multiplier=buffer_multiplier,
        min_buffer_km=min_buffer_km,
        cell_size_m=cell_size_m,
        dem_provider=dem_provider,
        apply_optional_layers=apply_optional_layers,
        apply_existing_road_bias=True,
        region_context=region_context,
    )
