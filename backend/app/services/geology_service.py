from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from math import ceil, hypot
from pathlib import Path
from typing import Callable

from app.services.geotechnical_model import get_rock_class_factor, get_rock_constructability
from app.services.rock_class_estimator import estimate_rock_class, normalize_refrock_text

TARGET_CRS = "EPSG:5179"
ROCK_COL_CANDIDATES = ["refrock", "ROCK", "rock", "lithology", "LITHO", "lithoname"]
DEFAULT_SAMPLE_INTERVAL_M = 20.0
GEOLOGY_DATA_DIR_ENV = "GEOLOGY_DATA_DIR"


@dataclass(frozen=True)
class GeologyDatasets:
    litho_gdf: object | None
    fault_gdf: object | None
    boundary_gdf: object | None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _SamplePoint:
    x: float
    y: float


def find_geology_data_dir(project_root: str | Path | None = None) -> Path | None:
    """Find the directory containing the three 1:250K geology Shapefiles."""
    configured = os.getenv(GEOLOGY_DATA_DIR_ENV)
    if configured:
        candidate = Path(configured).expanduser()
        if (candidate / "Geology_250K_Litho.shp").exists():
            return candidate

    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[3]
    raw_dir = root / "data" / "raw"
    if not raw_dir.exists():
        return None
    lithology_path = next(raw_dir.rglob("Geology_250K_Litho.shp"), None)
    return lithology_path.parent if lithology_path is not None else None


def load_geology_datasets(base_dir: str | Path, target_crs: str = TARGET_CRS) -> GeologyDatasets:
    warnings: list[str] = []
    try:
        import geopandas as gpd
    except Exception as error:
        return GeologyDatasets(None, None, None, (f"geopandas_unavailable: {error}",))

    base = Path(base_dir)

    def _read(name: str):
        path = base / name
        if not path.exists():
            warnings.append(f"geology_file_missing: {name}")
            return None
        try:
            gdf = gpd.read_file(path)
            if gdf.crs is None:
                warnings.append(f"geology_crs_missing: {name}")
                return gdf.set_crs(target_crs, allow_override=True)
            return gdf.to_crs(target_crs)
        except Exception as error:
            warnings.append(f"geology_file_read_failed: {name}: {error}")
            return None

    return GeologyDatasets(
        litho_gdf=_read("Geology_250K_Litho.shp"),
        fault_gdf=_read("Geology_250K_Fault.shp"),
        boundary_gdf=_read("Geology_250K_Boudary.shp"),
        warnings=tuple(warnings),
    )


@lru_cache(maxsize=4)
def load_default_geology_datasets(
    project_root: str | Path | None = None,
    target_crs: str = TARGET_CRS,
) -> GeologyDatasets:
    base_dir = find_geology_data_dir(project_root)
    if base_dir is None:
        return GeologyDatasets(
            None,
            None,
            None,
            ("geology_data_directory_missing",),
        )
    return load_geology_datasets(base_dir, target_crs=target_crs)


def _nearest_row(gdf, point):
    if gdf is None or len(gdf) == 0:
        return None
    try:
        nearest = gdf.sindex.nearest(point, return_all=False)
        indices = nearest[1] if isinstance(nearest, tuple) else nearest
        index = int(indices[0] if getattr(indices, "ndim", 1) == 1 else indices[0][0])
        return gdf.iloc[index]
    except Exception:
        try:
            return gdf.iloc[gdf.geometry.distance(point).argmin()]
        except Exception:
            return None


def _line_dist_m(gdf, point) -> float | None:
    if gdf is None or len(gdf) == 0:
        return None
    try:
        row = _nearest_row(gdf, point)
        return float(row.geometry.distance(point)) if row is not None else None
    except Exception:
        return None


def _rock_attrs(litho_gdf, point) -> dict:
    if litho_gdf is None or len(litho_gdf) == 0:
        return {}
    try:
        candidate_indices = list(litho_gdf.sindex.query(point, predicate="intersects"))
        matches = litho_gdf.iloc[candidate_indices] if candidate_indices else litho_gdf.iloc[0:0]
        if matches.empty:
            nearest = _nearest_row(litho_gdf, point)
            if nearest is None:
                return {}
            row = nearest
        else:
            row = matches.iloc[0]
    except Exception:
        return {}

    attrs = {}
    for column in ROCK_COL_CANDIDATES:
        if column in litho_gdf.columns:
            attrs[column] = normalize_refrock_text(row.get(column))
    refrock = next((attrs[column] for column in ROCK_COL_CANDIDATES if attrs.get(column)), None)
    attrs["refrock"] = refrock
    return attrs


def get_dem_elevation(x: float, y: float, provider=None) -> float | None:
    if provider is None:
        return None
    try:
        return provider.elevations([type("ProjectedPointLike", (), {"x": x, "y": y})()])[0]
    except Exception:
        return None


def get_slope_degree(x: float, y: float, slope_lookup: Callable[[float, float], float | None] | None = None) -> float | None:
    if slope_lookup is None:
        return None
    try:
        return slope_lookup(x, y)
    except Exception:
        return None


def _sample_polyline(points, sample_interval_m: float) -> list[tuple[float, _SamplePoint]]:
    if not points:
        return []
    if len(points) == 1:
        return [(0.0, _SamplePoint(float(points[0].x), float(points[0].y)))]

    cumulative = [0.0]
    for start, end in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + hypot(end.x - start.x, end.y - start.y))
    total_length = cumulative[-1]
    if total_length <= 0:
        return [(0.0, _SamplePoint(float(points[0].x), float(points[0].y)))]

    interval = max(float(sample_interval_m), 0.1)
    sample_count = max(1, ceil(total_length / interval))
    stations = [min(total_length, index * interval) for index in range(sample_count + 1)]
    if stations[-1] != total_length:
        stations.append(total_length)

    sampled: list[tuple[float, _SamplePoint]] = []
    segment_index = 0
    for station in stations:
        while segment_index < len(cumulative) - 2 and station > cumulative[segment_index + 1]:
            segment_index += 1
        start = points[segment_index]
        end = points[segment_index + 1]
        segment_length = cumulative[segment_index + 1] - cumulative[segment_index]
        progress = (station - cumulative[segment_index]) / segment_length if segment_length else 0.0
        sampled.append(
            (
                station,
                _SamplePoint(
                    float(start.x + progress * (end.x - start.x)),
                    float(start.y + progress * (end.y - start.y)),
                ),
            )
        )
    return sampled


def sample_route_geology(
    points,
    *,
    start_profile_elev_m: float,
    end_profile_elev_m: float,
    datasets: GeologyDatasets,
    dem_elevation_lookup: Callable[[float, float], float | None],
    slope_lookup: Callable[[float, float], float | None] | None = None,
    sample_interval_m: float = DEFAULT_SAMPLE_INTERVAL_M,
    source_crs: str = TARGET_CRS,
    target_crs: str = TARGET_CRS,
) -> list[dict]:
    try:
        from shapely.geometry import Point
    except Exception:
        return []

    sampled_points = _sample_polyline(points, sample_interval_m)
    if not sampled_points:
        return []
    total_length = sampled_points[-1][0]
    transformer = None
    if source_crs != target_crs:
        try:
            from pyproj import Transformer

            transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
        except Exception:
            transformer = None

    samples: list[dict] = []
    for station, point in sampled_points:
        progress = station / total_length if total_length else 0.0
        tunnel_elev = start_profile_elev_m + progress * (end_profile_elev_m - start_profile_elev_m)
        surface_elev = dem_elevation_lookup(point.x, point.y)
        overburden = surface_elev - tunnel_elev if surface_elev is not None else None
        slope_deg = get_slope_degree(point.x, point.y, slope_lookup)
        geology_x, geology_y = (
            transformer.transform(point.x, point.y) if transformer is not None else (point.x, point.y)
        )
        geometry = Point(geology_x, geology_y)
        attrs = _rock_attrs(datasets.litho_gdf, geometry)
        fault_dist = _line_dist_m(datasets.fault_gdf, geometry)
        boundary_dist = _line_dist_m(datasets.boundary_gdf, geometry)
        estimate = estimate_rock_class(
            refrock=attrs.get("refrock"),
            overburden_m=overburden,
            slope_deg=slope_deg,
            fault_dist_m=fault_dist,
            boundary_dist_m=boundary_dist,
        )
        has_lithology = datasets.litho_gdf is not None and bool(attrs.get("refrock"))
        estimated_rock_class = estimate.estimated_rock_class if has_lithology else "unknown"
        estimated_rock_class_num = estimate.estimated_rock_class_num if has_lithology else 0
        rock_ground_factor = (
            estimate.rock_ground_factor
            if has_lithology
            else get_rock_class_factor("unknown")
        )
        rock_constructability = (
            estimate.rock_constructability
            if has_lithology
            else get_rock_constructability("unknown")
        )
        risk_reasons = list(estimate.risk_reasons)
        if not has_lithology:
            risk_reasons = [
                reason
                for reason in risk_reasons
                if reason != "unknown_refrock_default_class_III"
            ]
            risk_reasons.append("geology_lithology_unavailable")
        samples.append(
            {
                "station_m": round(station, 1),
                "geometry": geometry,
                "surface_elev_m": surface_elev,
                "tunnel_elev_m": tunnel_elev,
                "overburden_m": overburden,
                "slope_deg": slope_deg,
                "refrock": attrs.get("refrock"),
                "lithoname": attrs.get("lithoname"),
                "fault_dist_m": fault_dist,
                "boundary_dist_m": boundary_dist,
                "estimated_rock_class": estimated_rock_class,
                "estimated_rock_class_num": estimated_rock_class_num,
                "rock_ground_factor": rock_ground_factor,
                "rock_constructability": rock_constructability,
                "risk_reasons": risk_reasons,
            }
        )
    return samples


def _candidate_tunnel_runs(cells) -> list[tuple[int, int]]:
    """Return inclusive cell-index ranges that merit geotechnical sampling."""
    candidate_edges: list[int] = []
    for index, (start, end) in enumerate(zip(cells, cells[1:])):
        length_m = hypot(end.x - start.x, end.y - start.y)
        grade = (
            abs(end.elevation_m - start.elevation_m) / length_m * 100.0
            if length_m > 0 and start.elevation_m is not None and end.elevation_m is not None
            else 0.0
        )
        nearby = cells[max(0, index - 3) : min(len(cells), index + 5)]
        elevations = [cell.elevation_m for cell in nearby if cell.elevation_m is not None]
        relief = max(elevations) - min(elevations) if elevations else 0.0
        if max(start.slope_degrees, end.slope_degrees) >= 25.0 or grade >= 8.0 or relief >= 80.0:
            candidate_edges.append(index)

    runs: list[tuple[int, int]] = []
    for edge_index in candidate_edges:
        if not runs or edge_index > runs[-1][1]:
            runs.append((edge_index, edge_index + 1))
        else:
            runs[-1] = (runs[-1][0], edge_index + 1)
    return runs


def enrich_candidate_tunnel_cells(
    cells,
    *,
    dem_provider,
    datasets: GeologyDatasets | None = None,
    sample_interval_m: float = DEFAULT_SAMPLE_INTERVAL_M,
    source_crs: str,
) -> list[str]:
    """Populate path cells from 20 m DEM/geology samples for tunnel decisions.

    The planned elevation is a straight profile between each potential tunnel
    run's endpoints. Negative cover is preserved and reported; it is never
    clamped to zero.
    """
    if len(cells) < 2:
        return []
    active_datasets = datasets or load_default_geology_datasets()
    warnings = list(active_datasets.warnings)

    for run_start, run_end in _candidate_tunnel_runs(cells):
        run_cells = cells[run_start : run_end + 1]
        start_elevation = run_cells[0].elevation_m
        end_elevation = run_cells[-1].elevation_m
        if start_elevation is None or end_elevation is None:
            warnings.append("tunnel_profile_endpoint_elevation_missing")
            continue

        preview_samples = _sample_polyline(run_cells, sample_interval_m)
        preview_points = [point for _, point in preview_samples]
        preview_elevations = dem_provider.elevations(preview_points)
        elevation_cache: dict[tuple[float, float], float | None] = {
            (round(point.x, 3), round(point.y, 3)): elevation
            for point, elevation in zip(preview_points, preview_elevations)
        }

        def elevation_lookup(x: float, y: float) -> float | None:
            key = (round(x, 3), round(y, 3))
            if key not in elevation_cache:
                elevation_cache[key] = dem_provider.elevations([_SamplePoint(x, y)])[0]
            return elevation_cache[key]

        def slope_lookup(x: float, y: float) -> float | None:
            nearest = min(run_cells, key=lambda cell: (cell.x - x) ** 2 + (cell.y - y) ** 2)
            return nearest.slope_degrees

        samples = sample_route_geology(
            run_cells,
            start_profile_elev_m=float(start_elevation),
            end_profile_elev_m=float(end_elevation),
            datasets=active_datasets,
            dem_elevation_lookup=elevation_lookup,
            slope_lookup=slope_lookup,
            sample_interval_m=sample_interval_m,
            source_crs=source_crs,
            target_crs=TARGET_CRS,
        )
        if not samples:
            warnings.append("tunnel_geology_sampling_returned_no_points")
            continue

        cell_stations = [0.0]
        for start, end in zip(run_cells, run_cells[1:]):
            cell_stations.append(cell_stations[-1] + hypot(end.x - start.x, end.y - start.y))

        for cell_index, cell in enumerate(run_cells):
            lower = 0.0 if cell_index == 0 else (cell_stations[cell_index - 1] + cell_stations[cell_index]) / 2.0
            upper = (
                cell_stations[-1]
                if cell_index == len(run_cells) - 1
                else (cell_stations[cell_index] + cell_stations[cell_index + 1]) / 2.0
            )
            nearby_samples = [
                sample
                for sample in samples
                if lower <= float(sample["station_m"]) <= upper
            ]
            if not nearby_samples:
                nearby_samples = [
                    min(samples, key=lambda sample: abs(float(sample["station_m"]) - cell_stations[cell_index]))
                ]

            overburdens = [
                float(sample["overburden_m"])
                for sample in nearby_samples
                if sample.get("overburden_m") is not None
            ]
            if overburdens:
                cell.overburden_m = (
                    min(overburdens)
                    if any(value < 0 for value in overburdens)
                    else sum(overburdens) / len(overburdens)
                )
            worst_sample = max(
                nearby_samples,
                key=lambda sample: int(sample.get("estimated_rock_class_num") or 3),
            )
            cell.estimated_rock_class = worst_sample.get("estimated_rock_class")
            cell.rock_class = worst_sample.get("estimated_rock_class")
            cell.rock_ground_factor = worst_sample.get("rock_ground_factor")
            cell.rock_constructability = worst_sample.get("rock_constructability")
            fault_distances = [
                float(sample["fault_dist_m"])
                for sample in nearby_samples
                if sample.get("fault_dist_m") is not None
            ]
            boundary_distances = [
                float(sample["boundary_dist_m"])
                for sample in nearby_samples
                if sample.get("boundary_dist_m") is not None
            ]
            cell.fault_dist_m = min(fault_distances) if fault_distances else cell.fault_dist_m
            cell.boundary_dist_m = min(boundary_distances) if boundary_distances else cell.boundary_dist_m
            reasons = list(cell.risk_reasons or [])
            for sample in nearby_samples:
                reasons.extend(sample.get("risk_reasons") or [])
            cell.risk_reasons = list(dict.fromkeys(reasons))
    return list(dict.fromkeys(warnings))
