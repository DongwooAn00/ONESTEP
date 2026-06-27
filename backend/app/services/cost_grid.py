from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from app.db import connect
from app.schemas.od_candidates import CandidateEdge, CandidateNode
from app.services import route_mvp_config as config
from app.services.road_network import ROAD_PROJ4
from app.services.route_cost import DEM_PROJ4


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
        return _transform(_spatial_refs()["wgs84_to_dem"], lon, lat)
    except ImportError:
        try:
            return _transform_pyproj(_pyproj_transformers()["wgs84_to_dem"], lon, lat)
        except ImportError:
            return _fallback_project(lon, lat)


def dem_to_lon_lat(x: float, y: float) -> tuple[float, float]:
    try:
        point = _transform(_spatial_refs()["dem_to_wgs84"], x, y)
        return point.x, point.y
    except ImportError:
        try:
            point = _transform_pyproj(_pyproj_transformers()["dem_to_wgs84"], x, y)
            return point.x, point.y
        except ImportError:
            return _fallback_unproject(x, y)


def dem_to_road(x: float, y: float) -> ProjectedPoint:
    try:
        return _transform(_spatial_refs()["dem_to_road"], x, y)
    except ImportError:
        try:
            return _transform_pyproj(_pyproj_transformers()["dem_to_road"], x, y)
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
    def resolution_m(self) -> float | None:
        try:
            with connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT ABS(ST_ScaleX(rast)), ABS(ST_ScaleY(rast))
                        FROM dem_elevation
                        LIMIT 1;
                        """
                    )
                    row = cursor.fetchone()
            if row is None or row[0] is None or row[1] is None:
                return None
            return max(float(row[0]), float(row[1]))
        except Exception:
            return None

    def elevations(self, points: list[ProjectedPoint]) -> list[float | None]:
        values: list[float | None] = []
        with connect() as connection:
            with connection.cursor() as cursor:
                for point in points:
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
                        (point.x, point.y),
                    )
                    row = cursor.fetchone()
                    if row is None or row[0] is None or float(row[0]) == -9999:
                        values.append(None)
                    else:
                        values.append(float(row[0]))
        return values


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
        grid.warnings.append("하천/수계 레이어가 없어 교량 구간과 하천 회피 비용을 반영하지 못했습니다.")
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
                            SELECT COALESCE(river_rank, rank, type, name, '') AS river_rank
                            FROM {table}, input_point
                            WHERE ST_DWithin({table}.geom, input_point.geom, %s)
                            LIMIT 1;
                            """,
                            (cell.x, cell.y, grid.cell_size_m * 0.7),
                        )
                        result = cursor.fetchone()
                        if result:
                            rank = _normalize_river_rank(result[0])
                            cell.river_rank = rank
                            cell.cost *= config.RIVER_MULTIPLIERS.get(rank, 10.0)
    except Exception as error:
        grid.warnings.append(f"하천 데이터 반영을 건너뜁니다: {error}")


def _apply_optional_roads(grid: CostGrid) -> None:
    if not _table_exists("road_links"):
        grid.warnings.append("기존 도로망 데이터가 없어 도로 접근 비용 보정을 적용하지 않았습니다.")
        return

    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                for row_cells in grid.cells:
                    for cell in row_cells:
                        road_point = dem_to_road(cell.x, cell.y)
                        cursor.execute(
                            """
                            WITH input_point AS (
                                SELECT ST_SetSRID(ST_MakePoint(%s, %s), 100001) AS geom
                            )
                            SELECT road_rank
                            FROM road_links, input_point
                            WHERE ST_DWithin(road_links.geom, input_point.geom, %s)
                            ORDER BY road_links.geom <-> input_point.geom
                            LIMIT 1;
                            """,
                            (road_point.x, road_point.y, config.ROAD_ACCESS_BUFFER_M),
                        )
                        result = cursor.fetchone()
                        if result:
                            multiplier, rank = _road_multiplier(result[0])
                            cell.cost *= multiplier
                            cell.road_rank = rank
    except Exception as error:
        grid.warnings.append(f"기존 도로망 비용 보정을 건너뜁니다: {error}")


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


def _apply_optional_protected_areas(grid: CostGrid) -> None:
    protected_table = _find_existing_table(["protected_areas"])
    building_table = _find_existing_table(["building_footprints"])
    builtup_table = _find_existing_table(["builtup_areas", "urban_areas"])

    if protected_table is None and building_table is None and builtup_table is None:
        grid.warnings.append("건물/시가지 레이어가 없어 건물 및 시가지 회피 비용을 반영하지 못했습니다.")
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


def build_cost_grid(
    edge: CandidateEdge,
    nodes: list[CandidateNode],
    *,
    buffer_multiplier: float = 0.3,
    min_buffer_km: float = 5.0,
    cell_size_m: float = config.DEFAULT_GRID_CELL_SIZE_M,
    dem_provider: DemProvider | None = None,
    apply_optional_layers: bool = True,
) -> tuple[CostGrid, ProjectedPoint, ProjectedPoint]:
    start, end = _edge_points(edge, nodes)
    straight_distance_m = max(edge.straight_distance_km * 1000.0, math.hypot(end.x - start.x, end.y - start.y))
    buffer_m = max(straight_distance_m * buffer_multiplier, min_buffer_km * 1000.0)
    min_x = min(start.x, end.x) - buffer_m
    max_x = max(start.x, end.x) + buffer_m
    min_y = min(start.y, end.y) - buffer_m
    max_y = max(start.y, end.y) + buffer_m
    active_cell_size = _adaptive_cell_size(max_x - min_x, max_y - min_y, cell_size_m)
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
        _apply_optional_roads(grid)
        _apply_optional_protected_areas(grid)
    return grid, start, end
