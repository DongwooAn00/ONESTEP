from __future__ import annotations

import math
from dataclasses import dataclass

from app.services import route_mvp_config as config
from app.services.cost_grid import CostCell


@dataclass
class RouteSegmentDetail:
    segment_id: str
    segment_type: str
    segment_length_km: float
    segment_geometry: list[dict[str, float]]
    average_slope: float
    max_slope: float


@dataclass(frozen=True)
class _AtomicSegment:
    segment_type: str
    start: CostCell
    end: CostCell
    length_km: float
    average_slope: float
    max_slope: float
    river_rank: str | None = None


def _distance_km(start: CostCell, end: CostCell) -> float:
    return math.hypot(end.x - start.x, end.y - start.y) / 1000.0


def _local_relief_m(cells: list[CostCell], index: int, window: int = 3) -> float:
    start = max(0, index - window)
    end = min(len(cells), index + window + 1)
    elevations = [cell.elevation_m for cell in cells[start:end] if cell.elevation_m is not None]
    return max(elevations) - min(elevations) if elevations else 0.0


def _initial_type(cells: list[CostCell], index: int, start: CostCell, end: CostCell) -> tuple[str, str | None]:
    river_rank = start.river_rank or end.river_rank
    if river_rank:
        return "bridge", river_rank

    max_slope = max(start.slope_degrees, end.slope_degrees)
    high_relief = _local_relief_m(cells, index) >= 80 and max(start.cost, end.cost) >= 5.0
    if max_slope >= 25 or max_slope >= 20 or high_relief:
        return "tunnel", None
    return "surface_road", None


def _atomic_segments(cells: list[CostCell]) -> list[_AtomicSegment]:
    atoms = []
    for index, (start, end) in enumerate(zip(cells, cells[1:])):
        length_km = _distance_km(start, end)
        if length_km <= 0:
            continue
        segment_type, river_rank = _initial_type(cells, index, start, end)
        average_slope = (start.slope_degrees + end.slope_degrees) / 2.0
        atoms.append(
            _AtomicSegment(
                segment_type=segment_type,
                start=start,
                end=end,
                length_km=length_km,
                average_slope=average_slope,
                max_slope=max(start.slope_degrees, end.slope_degrees),
                river_rank=river_rank,
            )
        )
    return atoms


def _downgrade_short_tunnels(atoms: list[_AtomicSegment]) -> list[_AtomicSegment]:
    result = list(atoms)
    index = 0
    while index < len(result):
        if result[index].segment_type != "tunnel":
            index += 1
            continue
        end = index
        length_km = 0.0
        while end < len(result) and result[end].segment_type == "tunnel":
            length_km += result[end].length_km
            end += 1
        if length_km < 0.3:
            for cursor in range(index, end):
                atom = result[cursor]
                result[cursor] = _AtomicSegment(
                    "surface_road",
                    atom.start,
                    atom.end,
                    atom.length_km,
                    atom.average_slope,
                    atom.max_slope,
                    atom.river_rank,
                )
        index = end
    return result


def _merge_tunnel_gaps(atoms: list[_AtomicSegment]) -> list[_AtomicSegment]:
    result = list(atoms)
    index = 1
    while index < len(result) - 1:
        if result[index].segment_type == "tunnel":
            index += 1
            continue
        gap_start = index
        gap_length_km = 0.0
        while index < len(result) and result[index].segment_type not in {"tunnel", "bridge"}:
            gap_length_km += result[index].length_km
            index += 1
        has_tunnel_before = gap_start > 0 and result[gap_start - 1].segment_type == "tunnel"
        has_tunnel_after = index < len(result) and result[index].segment_type == "tunnel"
        if has_tunnel_before and has_tunnel_after and gap_length_km < 0.2:
            for cursor in range(gap_start, index):
                atom = result[cursor]
                result[cursor] = _AtomicSegment(
                    "tunnel",
                    atom.start,
                    atom.end,
                    atom.length_km,
                    atom.average_slope,
                    atom.max_slope,
                    atom.river_rank,
                )
    return result


def _bridge_min_length_km(rank: str | None) -> float:
    return config.BRIDGE_MIN_LENGTH_KM.get(rank or "unknown", config.BRIDGE_MIN_LENGTH_KM["unknown"])


def classify_route_segments(route_id: str, cells: list[CostCell]) -> dict:
    atoms = _merge_tunnel_gaps(_downgrade_short_tunnels(_atomic_segments(cells)))
    if not atoms:
        return {
            "surface_road_length_km": 0.0,
            "tunnel_length_km": 0.0,
            "bridge_length_km": 0.0,
            "tunnel_segment_count": 0,
            "bridge_segment_count": 0,
            "segment_details": [],
        }

    grouped: list[list[_AtomicSegment]] = []
    for atom in atoms:
        if not grouped or grouped[-1][-1].segment_type != atom.segment_type:
            grouped.append([atom])
        else:
            grouped[-1].append(atom)

    details: list[RouteSegmentDetail] = []
    for index, group in enumerate(grouped, start=1):
        segment_type = group[0].segment_type
        raw_length_km = sum(atom.length_km for atom in group)
        length_km = raw_length_km
        if segment_type == "bridge":
            length_km = max(raw_length_km, _bridge_min_length_km(group[0].river_rank))
        weighted_slope = (
            sum(atom.average_slope * atom.length_km for atom in group) / raw_length_km if raw_length_km else 0.0
        )
        geometry = [{"lat": group[0].start.lat, "lon": group[0].start.lon}]
        geometry.extend({"lat": atom.end.lat, "lon": atom.end.lon} for atom in group)
        details.append(
            RouteSegmentDetail(
                segment_id=f"{route_id}-S{index:03d}",
                segment_type=segment_type,
                segment_length_km=round(length_km, 3),
                segment_geometry=geometry,
                average_slope=round(weighted_slope, 2),
                max_slope=round(max(atom.max_slope for atom in group), 2),
            )
        )

    return {
        "surface_road_length_km": round(sum(item.segment_length_km for item in details if item.segment_type == "surface_road"), 3),
        "tunnel_length_km": round(sum(item.segment_length_km for item in details if item.segment_type == "tunnel"), 3),
        "bridge_length_km": round(sum(item.segment_length_km for item in details if item.segment_type == "bridge"), 3),
        "tunnel_segment_count": sum(1 for item in details if item.segment_type == "tunnel"),
        "bridge_segment_count": sum(1 for item in details if item.segment_type == "bridge"),
        "segment_details": details,
    }
