from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.services.rock_class_estimator import estimate_rock_class

TARGET_CRS = "EPSG:5179"
ROCK_COL_CANDIDATES = ["refrock", "ROCK", "rock", "lithology", "LITHO", "lithoname"]
DEFAULT_SAMPLE_INTERVAL_M = 20.0


@dataclass(frozen=True)
class GeologyDatasets:
    litho_gdf: object | None
    fault_gdf: object | None
    boundary_gdf: object | None
    warnings: tuple[str, ...] = ()


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


def _line_dist_m(gdf, point) -> float | None:
    if gdf is None or len(gdf) == 0:
        return None
    try:
        return float(gdf.geometry.distance(point).min())
    except Exception:
        return None


def _rock_attrs(litho_gdf, point) -> dict:
    if litho_gdf is None or len(litho_gdf) == 0:
        return {}
    try:
        matches = litho_gdf[litho_gdf.geometry.contains(point)]
        if matches.empty:
            matches = litho_gdf.iloc[[litho_gdf.geometry.distance(point).idxmin()]]
        row = matches.iloc[0]
    except Exception:
        return {}

    attrs = {}
    for column in ROCK_COL_CANDIDATES:
        if column in litho_gdf.columns:
            attrs[column] = row.get(column)
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


def sample_route_geology(
    points,
    *,
    start_profile_elev_m: float,
    end_profile_elev_m: float,
    datasets: GeologyDatasets,
    dem_elevation_lookup: Callable[[float, float], float | None],
    slope_lookup: Callable[[float, float], float | None] | None = None,
) -> list[dict]:
    try:
        from shapely.geometry import Point
    except Exception:
        return []

    if not points:
        return []
    total_length = sum(
        ((end.x - start.x) ** 2 + (end.y - start.y) ** 2) ** 0.5
        for start, end in zip(points, points[1:])
    )
    station = 0.0
    samples: list[dict] = []
    for index, point in enumerate(points):
        if index > 0:
            prev = points[index - 1]
            station += ((point.x - prev.x) ** 2 + (point.y - prev.y) ** 2) ** 0.5
        progress = station / total_length if total_length else 0.0
        tunnel_elev = start_profile_elev_m + progress * (end_profile_elev_m - start_profile_elev_m)
        surface_elev = dem_elevation_lookup(point.x, point.y)
        overburden = surface_elev - tunnel_elev if surface_elev is not None else None
        slope_deg = get_slope_degree(point.x, point.y, slope_lookup)
        geometry = Point(point.x, point.y)
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
                "estimated_rock_class": estimate.estimated_rock_class,
                "estimated_rock_class_num": estimate.estimated_rock_class_num,
                "rock_ground_factor": estimate.rock_ground_factor,
                "rock_constructability": estimate.rock_constructability,
                "risk_reasons": estimate.risk_reasons,
            }
        )
    return samples
