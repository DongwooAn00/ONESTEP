from __future__ import annotations

import csv
import heapq
import json
import logging
import math
import os
import random
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO, Iterable

import numpy as np

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

from sklearn.cluster import KMeans
from sklearn.neighbors import NearestNeighbors

from app.schemas.od_candidates import CandidateEdge, CandidateNode, ODCandidateResult, ODCandidateStats
from app.services.region_filter import RegionContext, build_region_context

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OD_CSV = ROOT / "data" / "processed" / "synthetic_admin_dong_od_by_mode.csv"
DEFAULT_COORDINATE_CSV = ROOT / "data" / "processed" / "admin_dong_coordinates.csv"
OUTPUT_DIR = ROOT / "data" / "processed"
DEFAULT_K_VALUES = [10, 20, 30, 50]
MERGE_DISTANCE_KM = 3.0
DEFAULT_TOP_NODE_LIMIT = 100
DEFAULT_EDGE_LIMIT = 50
DEFAULT_LOW_IMPACT_PRUNE_PERCENT = 20
EDGE_BATCH_SIZE = 20_000
RANDOM_SEED = 42
STANDARD_OD_COLUMNS = [
    "origin_latitude",
    "origin_longitude",
    "destination_latitude",
    "destination_longitude",
    "total_flow",
]

FLOW_GROUPS = {
    "car_flow": {
        "weight": 1.0,
        "candidates": ["passenger_car", "car", "car_flow", "auto", "automobile", "passenger"],
    },
    "bus_flow": {
        "weight": 1.2,
        "candidates": ["bus", "bus_flow"],
    },
    "subway_flow": {
        "weight": 0.8,
        "candidates": ["subway", "metro", "urban_rail", "subway_flow"],
    },
    "rail_flow": {
        "weight": 1.0,
        "candidates": ["rail", "train", "rail_flow"],
    },
    "high_speed_rail_flow": {
        "weight": 1.0,
        "candidates": ["high_speed_rail", "hsr", "ktx", "high_speed_rail_flow"],
    },
    "air_flow": {
        "weight": 1.0,
        "candidates": ["air", "aviation", "air_flow"],
    },
    "sea_flow": {
        "weight": 1.0,
        "candidates": ["sea", "ship", "shipping", "marine", "sea_flow"],
    },
    "freight_flow": {
        "weight": 1.5,
        "candidates": ["freight", "cargo", "truck", "truck_flow", "freight_flow", "cargo_flow"],
    },
}

COLUMN_MAPPING = {
    "origin_latitude": [
        "origin_latitude",
        "origin_lat",
        "origin_y",
        "from_latitude",
        "from_lat",
        "start_latitude",
        "start_lat",
        "o_lat",
    ],
    "origin_longitude": [
        "origin_longitude",
        "origin_lon",
        "origin_lng",
        "origin_x",
        "from_longitude",
        "from_lon",
        "from_lng",
        "start_longitude",
        "start_lon",
        "start_lng",
        "o_lon",
        "o_lng",
    ],
    "destination_latitude": [
        "destination_latitude",
        "destination_lat",
        "destination_y",
        "dest_latitude",
        "dest_lat",
        "to_latitude",
        "to_lat",
        "end_latitude",
        "end_lat",
        "d_lat",
    ],
    "destination_longitude": [
        "destination_longitude",
        "destination_lon",
        "destination_lng",
        "destination_x",
        "dest_longitude",
        "dest_lon",
        "dest_lng",
        "to_longitude",
        "to_lon",
        "to_lng",
        "end_longitude",
        "end_lon",
        "end_lng",
        "d_lon",
        "d_lng",
    ],
}

CODE_COLUMN_MAPPING = {
    "origin_code": ["origin_admin_dong_code", "origin_code", "from_admin_dong_code", "start_admin_dong_code"],
    "destination_code": [
        "destination_admin_dong_code",
        "destination_code",
        "dest_admin_dong_code",
        "to_admin_dong_code",
        "end_admin_dong_code",
    ],
}


@dataclass(frozen=True)
class FlowColumn:
    column: str
    weight: float
    group: str


@dataclass(frozen=True)
class ODRecord:
    origin_latitude: float
    origin_longitude: float
    destination_latitude: float
    destination_longitude: float
    origin_x: float
    origin_y: float
    destination_x: float
    destination_y: float
    total_flow: float


@dataclass(frozen=True)
class RawClusterNode:
    x: float
    y: float
    latitude: float
    longitude: float
    cluster_total_flow: float
    included_od_count: int
    source_k: int


@contextmanager
def _open_text(source: str | Path | BinaryIO):
    if isinstance(source, (str, Path)):
        with Path(source).open("r", encoding="utf-8-sig", newline="") as file:
            yield file
        return

    source.seek(0)
    yield source


def _normalize_header(value: str) -> str:
    return "".join(ch for ch in value.strip().lower() if ch.isalnum())


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    cleaned = str(value).replace(",", "").strip()
    if not cleaned:
        return None
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _valid_lat_lon(latitude: float | None, longitude: float | None) -> bool:
    return (
        latitude is not None
        and longitude is not None
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    )


@lru_cache(maxsize=1)
def _transformers():
    try:
        from pyproj import Transformer
    except ImportError:
        return None
    return (
        Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True),
        Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True),
    )


def _project(lon: float, lat: float) -> tuple[float, float]:
    transformers = _transformers()
    if transformers is not None:
        return transformers[0].transform(lon, lat)
    reference_latitude = 36.5
    return (
        lon * 111_320.0 * math.cos(math.radians(reference_latitude)),
        lat * 111_320.0,
    )


def _unproject(x: float, y: float) -> tuple[float, float]:
    transformers = _transformers()
    if transformers is not None:
        return transformers[1].transform(x, y)
    reference_latitude = 36.5
    return (
        x / (111_320.0 * math.cos(math.radians(reference_latitude))),
        y / 111_320.0,
    )


def _distance_km_xy(a_x: float, a_y: float, b_x: float, b_y: float) -> float:
    return math.hypot(a_x - b_x, a_y - b_y) / 1000.0


def _find_column(headers: list[str], candidates: Iterable[str]) -> str | None:
    by_normalized = {_normalize_header(header): header for header in headers}
    for candidate in candidates:
        match = by_normalized.get(_normalize_header(candidate))
        if match:
            return match
    return None


def _detect_flow_columns(headers: list[str]) -> list[FlowColumn]:
    flow_columns: list[FlowColumn] = []
    for group, config in FLOW_GROUPS.items():
        column = _find_column(headers, config["candidates"])
        if column:
            flow_columns.append(FlowColumn(column=column, weight=float(config["weight"]), group=group))

    if flow_columns:
        return flow_columns

    fallback = _find_column(headers, ["total_flow", "weighted_total_flow", "total", "flow", "traffic", "volume", "trips"])
    return [FlowColumn(column=fallback, weight=1.0, group="total_flow")] if fallback else []


def _detect_coordinate_columns(headers: list[str]) -> dict[str, str]:
    return {
        key: column
        for key, candidates in COLUMN_MAPPING.items()
        if (column := _find_column(headers, candidates))
    }


def _detect_code_columns(headers: list[str]) -> dict[str, str]:
    return {
        key: column
        for key, candidates in CODE_COLUMN_MAPPING.items()
        if (column := _find_column(headers, candidates))
    }


def _load_coordinate_lookup(
    path: Path = DEFAULT_COORDINATE_CSV,
    region_context: RegionContext | None = None,
) -> dict[str, tuple[float, float]]:
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        headers = reader.fieldnames or []
        code_column = _find_column(headers, ["admin_dong_code", "code", "dong_code"])
        latitude_column = _find_column(headers, ["latitude", "lat", "y"])
        longitude_column = _find_column(headers, ["longitude", "lon", "lng", "x"])
        if not code_column or not latitude_column or not longitude_column:
            return {}

        lookup = {}
        for row in reader:
            latitude = _to_float(row.get(latitude_column))
            longitude = _to_float(row.get(longitude_column))
            if (
                _valid_lat_lon(latitude, longitude)
                and (
                    region_context is None
                    or not region_context.enabled
                    or region_context.contains_point(float(longitude), float(latitude))
                )
            ):
                lookup[str(row.get(code_column, "")).strip()] = (latitude, longitude)
        return lookup


def _record_in_region(
    record: ODRecord,
    row: dict[str, str],
    code_columns: dict[str, str],
    region_context: RegionContext | None,
) -> bool:
    """OD 양 끝점이 선택 구역 또는 경계 buffer 안에 있는지 확인한다."""
    if region_context is None or not region_context.enabled:
        return True

    origin_code = str(row.get(code_columns.get("origin_code", ""), "")).strip()
    destination_code = str(
        row.get(code_columns.get("destination_code", ""), "")
    ).strip()
    origin_matches = (
        bool(origin_code) and region_context.contains_code(origin_code)
    ) or region_context.contains_point(
        record.origin_longitude,
        record.origin_latitude,
    )
    destination_matches = (
        bool(destination_code) and region_context.contains_code(destination_code)
    ) or region_context.contains_point(
        record.destination_longitude,
        record.destination_latitude,
    )
    return origin_matches and destination_matches


def _row_total_flow(row: dict[str, str], flow_columns: list[FlowColumn]) -> float:
    return sum((_to_float(row.get(item.column)) or 0.0) * item.weight for item in flow_columns)


def _row_to_record(
    row: dict[str, str],
    flow_columns: list[FlowColumn],
    coordinate_columns: dict[str, str],
    coordinate_lookup: dict[str, tuple[float, float]],
    code_columns: dict[str, str],
) -> tuple[ODRecord | None, bool, bool]:
    total_flow = _row_total_flow(row, flow_columns)
    if total_flow <= 0:
        return None, False, True

    origin_latitude = _to_float(row.get(coordinate_columns.get("origin_latitude", "")))
    origin_longitude = _to_float(row.get(coordinate_columns.get("origin_longitude", "")))
    destination_latitude = _to_float(row.get(coordinate_columns.get("destination_latitude", "")))
    destination_longitude = _to_float(row.get(coordinate_columns.get("destination_longitude", "")))

    if coordinate_lookup and code_columns:
        if not _valid_lat_lon(origin_latitude, origin_longitude):
            origin_code = str(row.get(code_columns.get("origin_code", ""), "")).strip()
            if origin_code in coordinate_lookup:
                origin_latitude, origin_longitude = coordinate_lookup[origin_code]
        if not _valid_lat_lon(destination_latitude, destination_longitude):
            destination_code = str(row.get(code_columns.get("destination_code", ""), "")).strip()
            if destination_code in coordinate_lookup:
                destination_latitude, destination_longitude = coordinate_lookup[destination_code]

    if not (
        _valid_lat_lon(origin_latitude, origin_longitude)
        and _valid_lat_lon(destination_latitude, destination_longitude)
    ):
        return None, True, False

    assert origin_latitude is not None
    assert origin_longitude is not None
    assert destination_latitude is not None
    assert destination_longitude is not None
    origin_x, origin_y = _project(origin_longitude, origin_latitude)
    destination_x, destination_y = _project(destination_longitude, destination_latitude)
    return (
        ODRecord(
            origin_latitude=origin_latitude,
            origin_longitude=origin_longitude,
            destination_latitude=destination_latitude,
            destination_longitude=destination_longitude,
            origin_x=origin_x,
            origin_y=origin_y,
            destination_x=destination_x,
            destination_y=destination_y,
            total_flow=total_flow,
        ),
        False,
        False,
    )


def load_od_data(source: str | Path | BinaryIO) -> tuple[int, list[str], list[FlowColumn], dict[str, str], dict[str, str]]:
    with _open_text(source) as file:
        reader = csv.DictReader(file)
        headers = reader.fieldnames or []
        total_rows = sum(1 for _ in reader)
    flow_columns = _detect_flow_columns(headers)
    coordinate_columns = _detect_coordinate_columns(headers)
    code_columns = _detect_code_columns(headers)
    return total_rows, headers, flow_columns, coordinate_columns, code_columns


def _reservoir_add(records: list[ODRecord], record: ODRecord, sample_size: int, seen: int) -> None:
    if len(records) < sample_size:
        records.append(record)
        return
    index = random.randint(0, seen - 1)
    if index < sample_size:
        records[index] = record


def _read_candidate_records(
    source: str | Path | BinaryIO,
    flow_columns: list[FlowColumn],
    coordinate_columns: dict[str, str],
    coordinate_lookup: dict[str, tuple[float, float]],
    code_columns: dict[str, str],
    *,
    total_rows: int,
    flow_filter_percent: int | None,
    sample_size: int | None,
    region_context: RegionContext | None = None,
) -> tuple[list[ODRecord], int, int, int, int]:
    coordinate_excluded = 0
    non_positive_excluded = 0
    valid_seen = 0
    region_excluded = 0
    heap: list[tuple[float, int, ODRecord]] = []
    records: list[ODRecord] = []
    top_count = max(1, math.ceil(total_rows * flow_filter_percent / 100)) if flow_filter_percent else None

    random.seed(RANDOM_SEED)
    with _open_text(source) as file:
        reader = csv.DictReader(file)
        for row_index, row in enumerate(reader):
            record, missing_coordinates, non_positive_flow = _row_to_record(
                row,
                flow_columns,
                coordinate_columns,
                coordinate_lookup,
                code_columns,
            )
            coordinate_excluded += int(missing_coordinates)
            non_positive_excluded += int(non_positive_flow)
            if record is None:
                continue
            if not _record_in_region(record, row, code_columns, region_context):
                region_excluded += 1
                continue

            valid_seen += 1
            if top_count is not None:
                item = (record.total_flow, row_index, record)
                if len(heap) < top_count:
                    heapq.heappush(heap, item)
                else:
                    heapq.heappushpop(heap, item)
                continue

            if sample_size:
                _reservoir_add(records, record, sample_size, valid_seen)
            else:
                records.append(record)

    if top_count is not None:
        records = [record for _, _, record in sorted(heap, key=lambda item: item[0], reverse=True)]
        if sample_size and len(records) > sample_size:
            records = random.sample(records, sample_size)

    return records, coordinate_excluded, non_positive_excluded, valid_seen, region_excluded


def _records_to_points(records: list[ODRecord]) -> tuple[np.ndarray, np.ndarray]:
    points = np.empty((len(records) * 2, 2), dtype=np.float64)
    weights = np.empty(len(records) * 2, dtype=np.float64)
    for index, record in enumerate(records):
        point_index = index * 2
        points[point_index] = [record.origin_x, record.origin_y]
        points[point_index + 1] = [record.destination_x, record.destination_y]
        weights[point_index] = record.total_flow
        weights[point_index + 1] = record.total_flow
    return points, weights


def _weighted_kmeans_nodes(records: list[ODRecord], k_values: list[int]) -> list[RawClusterNode]:
    if not records:
        raise ValueError("No OD rows with valid coordinates and positive total_flow are available.")

    points, weights = _records_to_points(records)
    unique_point_count = len({(round(x, 3), round(y, 3)) for x, y in points})
    if unique_point_count < 2:
        raise ValueError("At least two distinct coordinate points are required for clustering.")

    raw_nodes: list[RawClusterNode] = []
    for requested_k in k_values:
        active_k = min(requested_k, unique_point_count, len(points))
        if active_k < 2:
            continue

        kmeans = KMeans(n_clusters=active_k, random_state=RANDOM_SEED, n_init="auto")
        labels = kmeans.fit_predict(points, sample_weight=weights)
        flow_by_cluster = np.bincount(labels, weights=weights, minlength=active_k)
        count_by_cluster = np.bincount(labels, minlength=active_k)

        for cluster_index, center in enumerate(kmeans.cluster_centers_):
            cluster_flow = float(flow_by_cluster[cluster_index])
            if cluster_flow <= 0:
                continue
            lon, lat = _unproject(float(center[0]), float(center[1]))
            raw_nodes.append(
                RawClusterNode(
                    x=float(center[0]),
                    y=float(center[1]),
                    latitude=lat,
                    longitude=lon,
                    cluster_total_flow=cluster_flow,
                    included_od_count=int(count_by_cluster[cluster_index]),
                    source_k=requested_k,
                )
            )

    if not raw_nodes:
        raise ValueError("Weighted K-Means did not produce candidate centers.")
    return raw_nodes


def _merge_nearby_nodes(nodes: list[RawClusterNode], merge_distance_km: float) -> list[CandidateNode]:
    groups: list[dict] = []
    for node in sorted(nodes, key=lambda item: item.cluster_total_flow, reverse=True):
        matched_group = None
        for group in groups:
            if _distance_km_xy(node.x, node.y, group["x"], group["y"]) <= merge_distance_km:
                matched_group = group
                break

        if matched_group is None:
            groups.append(
                {
                    "x": node.x,
                    "y": node.y,
                    "cluster_total_flow": node.cluster_total_flow,
                    "included_od_count": node.included_od_count,
                    "source_k_values": {node.source_k},
                    "merged_count": 1,
                }
            )
            continue

        previous_flow = matched_group["cluster_total_flow"]
        next_flow = previous_flow + node.cluster_total_flow
        matched_group["x"] = (matched_group["x"] * previous_flow + node.x * node.cluster_total_flow) / next_flow
        matched_group["y"] = (matched_group["y"] * previous_flow + node.y * node.cluster_total_flow) / next_flow
        matched_group["cluster_total_flow"] = next_flow
        matched_group["included_od_count"] += node.included_od_count
        matched_group["source_k_values"].add(node.source_k)
        matched_group["merged_count"] += 1

    groups.sort(key=lambda item: item["cluster_total_flow"], reverse=True)
    merged_nodes: list[CandidateNode] = []
    for index, group in enumerate(groups, start=1):
        lon, lat = _unproject(group["x"], group["y"])
        merged_nodes.append(
            CandidateNode(
                node_id=f"N{index:03d}",
                latitude=round(lat, 6),
                longitude=round(lon, 6),
                x=round(group["x"], 3),
                y=round(group["y"], 3),
                cluster_total_flow=round(group["cluster_total_flow"], 3),
                included_od_count=int(group["included_od_count"]),
                source_k_values=sorted(group["source_k_values"]),
                merged_count=int(group["merged_count"]),
            )
        )
    return merged_nodes


def _prune_nodes(
    nodes: list[CandidateNode],
    low_impact_prune_percent: int | None,
    top_node_limit: int,
) -> tuple[list[CandidateNode], int]:
    active_nodes = sorted(nodes, key=lambda item: item.cluster_total_flow, reverse=True)
    before_count = len(active_nodes)
    if low_impact_prune_percent:
        keep_count = max(2, math.ceil(len(active_nodes) * (100 - low_impact_prune_percent) / 100))
        active_nodes = active_nodes[:keep_count]
    if top_node_limit:
        active_nodes = active_nodes[:top_node_limit]

    renumbered = [
        node.model_copy(update={"node_id": f"N{index:03d}"})
        for index, node in enumerate(active_nodes, start=1)
    ]
    return renumbered, before_count - len(renumbered)


def _flush_edge_batch(
    nearest: NearestNeighbors,
    node_ids: list[str],
    origins: list[list[float]],
    destinations: list[list[float]],
    flows: list[float],
    accumulator: dict[tuple[int, int], dict[str, float]],
) -> None:
    if not origins:
        return
    origin_indexes = nearest.kneighbors(np.asarray(origins), return_distance=False).ravel()
    destination_indexes = nearest.kneighbors(np.asarray(destinations), return_distance=False).ravel()
    for origin_index, destination_index, flow in zip(origin_indexes, destination_indexes, flows):
        if origin_index == destination_index:
            continue
        pair = tuple(sorted((int(origin_index), int(destination_index))))
        bucket = accumulator.setdefault(pair, {"flow": 0.0, "od_count": 0.0})
        bucket["flow"] += flow
        bucket["od_count"] += 1


def _generate_candidate_edges(
    source: str | Path | BinaryIO,
    flow_columns: list[FlowColumn],
    coordinate_columns: dict[str, str],
    coordinate_lookup: dict[str, tuple[float, float]],
    code_columns: dict[str, str],
    nodes: list[CandidateNode],
    *,
    edge_limit: int,
    min_estimated_flow: float | None,
    sample_size: int | None,
    region_context: RegionContext | None = None,
) -> list[CandidateEdge]:
    node_points = np.asarray([[node.x, node.y] for node in nodes], dtype=np.float64)
    nearest = NearestNeighbors(n_neighbors=1)
    nearest.fit(node_points)
    node_ids = [node.node_id for node in nodes]
    accumulator: dict[tuple[int, int], dict[str, float]] = {}
    origins: list[list[float]] = []
    destinations: list[list[float]] = []
    flows: list[float] = []
    processed = 0

    with _open_text(source) as file:
        reader = csv.DictReader(file)
        for row in reader:
            record, _, _ = _row_to_record(row, flow_columns, coordinate_columns, coordinate_lookup, code_columns)
            if record is None:
                continue
            if not _record_in_region(record, row, code_columns, region_context):
                continue
            processed += 1
            if sample_size and processed > sample_size:
                break

            origins.append([record.origin_x, record.origin_y])
            destinations.append([record.destination_x, record.destination_y])
            flows.append(record.total_flow)
            if len(origins) >= EDGE_BATCH_SIZE:
                _flush_edge_batch(nearest, node_ids, origins, destinations, flows, accumulator)
                origins.clear()
                destinations.clear()
                flows.clear()

    _flush_edge_batch(nearest, node_ids, origins, destinations, flows, accumulator)

    candidates = []
    for (from_index, to_index), values in accumulator.items():
        from_node = nodes[from_index]
        to_node = nodes[to_index]
        assert from_node.x is not None
        assert from_node.y is not None
        assert to_node.x is not None
        assert to_node.y is not None
        distance_km = _distance_km_xy(from_node.x, from_node.y, to_node.x, to_node.y)
        estimated_flow = values["flow"]
        if distance_km < 5 or distance_km > 100:
            continue
        if min_estimated_flow is not None and estimated_flow < min_estimated_flow:
            continue
        candidates.append((estimated_flow, from_index, to_index, distance_km, int(values["od_count"])))

    candidates.sort(key=lambda row: row[0], reverse=True)
    return [
        CandidateEdge(
            edge_id=f"E{rank:03d}",
            from_node_id=node_ids[from_index],
            to_node_id=node_ids[to_index],
            straight_distance_km=round(distance_km, 3),
            estimated_flow=round(estimated_flow, 3),
            rank=rank,
            od_count=od_count,
            source=(
                "region_filtered_od_weighted_kmeans"
                if region_context and region_context.enabled
                else "all_od_weighted_kmeans"
            ),
        )
        for rank, (estimated_flow, from_index, to_index, distance_km, od_count) in enumerate(
            candidates[:edge_limit],
            start=1,
        )
    ]


def _write_json(filename: str, payload: list[dict]) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / filename
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _append_standard_records(
    source: str | Path | BinaryIO | None,
    writer: csv.DictWriter,
) -> tuple[int, int, int, int]:
    active_source = source or DEFAULT_OD_CSV
    total_rows, _, flow_columns, coordinate_columns, code_columns = load_od_data(active_source)
    coordinate_lookup = _load_coordinate_lookup()

    written_rows = 0
    coordinate_excluded = 0
    non_positive_excluded = 0
    with _open_text(active_source) as file:
        reader = csv.DictReader(file)
        for row in reader:
            record, missing_coordinates, non_positive_flow = _row_to_record(
                row,
                flow_columns,
                coordinate_columns,
                coordinate_lookup,
                code_columns,
            )
            coordinate_excluded += int(missing_coordinates)
            non_positive_excluded += int(non_positive_flow)
            if record is None:
                continue

            writer.writerow(
                {
                    "origin_latitude": record.origin_latitude,
                    "origin_longitude": record.origin_longitude,
                    "destination_latitude": record.destination_latitude,
                    "destination_longitude": record.destination_longitude,
                    "total_flow": record.total_flow,
                }
            )
            written_rows += 1

    return total_rows, written_rows, coordinate_excluded, non_positive_excluded


def build_od_candidates_with_supplemental(
    source: str | Path | BinaryIO | None,
    supplemental_source: str | Path | BinaryIO,
    source_name: str,
    *,
    include_base_od: bool = True,
    flow_filter_percent: int | None = None,
    top_percent: int | None = None,
    k_values: list[int] | None = None,
    merge_distance_km: float = MERGE_DISTANCE_KM,
    top_node_limit: int = DEFAULT_TOP_NODE_LIMIT,
    low_impact_prune_percent: int | None = DEFAULT_LOW_IMPACT_PRUNE_PERCENT,
    edge_limit: int = DEFAULT_EDGE_LIMIT,
    min_estimated_flow: float | None = None,
    sample_size: int | None = None,
    persist_files: bool = True,
    selected_regions: list[str] | None = None,
    use_region_filter: bool = False,
    region_buffer_km: float = 10.0,
) -> ODCandidateResult:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".csv", delete=False) as file:
            temporary_path = Path(file.name)
            writer = csv.DictWriter(file, fieldnames=STANDARD_OD_COLUMNS)
            writer.writeheader()
            if include_base_od:
                base_total, base_written, base_coordinate_excluded, base_non_positive = _append_standard_records(source, writer)
            else:
                base_total = base_written = base_coordinate_excluded = base_non_positive = 0
            supplemental_total, supplemental_written, supplemental_coordinate_excluded, supplemental_non_positive = (
                _append_standard_records(supplemental_source, writer)
            )

        result = build_od_candidates(
            temporary_path,
            source_name,
            flow_filter_percent=flow_filter_percent,
            top_percent=top_percent,
            k_values=k_values,
            merge_distance_km=merge_distance_km,
            top_node_limit=top_node_limit,
            low_impact_prune_percent=low_impact_prune_percent,
            edge_limit=edge_limit,
            min_estimated_flow=min_estimated_flow,
            sample_size=sample_size,
            persist_files=persist_files,
            selected_regions=selected_regions,
            use_region_filter=use_region_filter,
            region_buffer_km=region_buffer_km,
        )
        result.stats.total_od_rows = base_total + supplemental_total
        result.stats.coordinate_excluded_rows = base_coordinate_excluded + supplemental_coordinate_excluded
        result.stats.non_positive_flow_excluded_rows = base_non_positive + supplemental_non_positive
        result.stats.region_filter_summary["od_rows_before"] = (
            base_total + supplemental_total
        )
        result.stats.warnings.append(
            f"Scenario OD merge is active: {supplemental_written} supplemental rows were added to "
            f"{base_written} base OD rows before candidate generation."
        )
        if supplemental_coordinate_excluded:
            result.stats.warnings.append(
                f"{supplemental_coordinate_excluded} supplemental rows without valid coordinates were excluded."
            )
        if supplemental_non_positive:
            result.stats.warnings.append(
                f"{supplemental_non_positive} supplemental rows with non-positive total_flow were excluded."
            )
        return result
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def build_od_candidates(
    source: str | Path | BinaryIO | None,
    source_name: str,
    *,
    flow_filter_percent: int | None = None,
    top_percent: int | None = None,
    k_values: list[int] | None = None,
    merge_distance_km: float = MERGE_DISTANCE_KM,
    top_node_limit: int = DEFAULT_TOP_NODE_LIMIT,
    low_impact_prune_percent: int | None = DEFAULT_LOW_IMPACT_PRUNE_PERCENT,
    edge_limit: int = DEFAULT_EDGE_LIMIT,
    min_estimated_flow: float | None = None,
    sample_size: int | None = None,
    persist_files: bool = True,
    selected_regions: list[str] | None = None,
    use_region_filter: bool = False,
    region_buffer_km: float = 10.0,
) -> ODCandidateResult:
    started_at = time.perf_counter()
    region_context = build_region_context(
        selected_regions,
        use_region_filter,
        region_buffer_km,
    )
    logger.info(
        "[RegionFilter] enabled=%s regions=%s buffer_km=%s",
        region_context.enabled,
        list(region_context.selected_regions),
        region_context.buffer_km,
    )
    active_source = source or DEFAULT_OD_CSV
    active_filter_percent = flow_filter_percent if flow_filter_percent is not None else top_percent
    active_k_values = k_values or DEFAULT_K_VALUES
    total_rows, _, flow_columns, coordinate_columns, code_columns = load_od_data(active_source)
    coordinate_lookup = _load_coordinate_lookup(
        region_context=region_context,
    )
    coordinate_lookup_used = bool(coordinate_lookup) and set(code_columns) == {"origin_code", "destination_code"}
    warnings: list[str] = []

    if total_rows <= 0:
        raise ValueError("OD CSV has no data rows.")
    if not flow_columns:
        raise ValueError("No flow columns found. Add total_flow or supported mode-specific flow columns.")

    required_coordinate_keys = {
        "origin_latitude",
        "origin_longitude",
        "destination_latitude",
        "destination_longitude",
    }
    has_coordinate_columns = set(coordinate_columns) == required_coordinate_keys
    if not has_coordinate_columns and not coordinate_lookup_used:
        missing = sorted(required_coordinate_keys - set(coordinate_columns))
        raise ValueError(
            "Origin/destination coordinate columns were not found and "
            f"{DEFAULT_COORDINATE_CSV.name} is missing or incomplete. "
            f"Missing columns: {', '.join(missing)}. "
            "For synthetic_admin_dong_od_by_mode.csv, create data/processed/admin_dong_coordinates.csv "
            "with admin_dong_code, latitude, longitude."
        )

    (
        records,
        coordinate_excluded_rows,
        non_positive_rows,
        valid_rows,
        region_excluded_rows,
    ) = _read_candidate_records(
        active_source,
        flow_columns,
        coordinate_columns,
        coordinate_lookup,
        code_columns,
        total_rows=total_rows,
        flow_filter_percent=active_filter_percent,
        sample_size=sample_size,
        region_context=region_context,
    )
    logger.info(
        "[RegionFilter] OD rows: %s -> %s",
        total_rows,
        valid_rows,
    )
    if sample_size:
        warnings.append(f"Sampling is active: clustering uses up to {sample_size} valid OD rows.")
    if active_filter_percent:
        warnings.append(f"OD flow filtering is active: top {active_filter_percent}% rows are used for clustering.")
    if not records and coordinate_excluded_rows:
        raise ValueError(
            "Origin/destination coordinate columns were not found and "
            f"{DEFAULT_COORDINATE_CSV.name} did not contain matching coordinates for the OD codes. "
            "Add origin/destination coordinate columns to the OD CSV or ensure "
            "admin_dong_code values match data/processed/admin_dong_coordinates.csv."
        )
    if region_context.enabled and len(records) < 2:
        raise ValueError(
            "선택 구역 내 유효 OD 데이터가 부족합니다. 구역을 추가하거나 "
            "region_buffer_km를 늘려주세요."
        )

    raw_nodes = _weighted_kmeans_nodes(records, active_k_values)
    merged_nodes = _merge_nearby_nodes(raw_nodes, merge_distance_km)
    if region_context.enabled:
        merged_nodes = [
            node
            for node in merged_nodes
            if region_context.contains_point(node.longitude, node.latitude)
        ]
        if len(merged_nodes) < 2:
            raise ValueError(
                "선택 구역 내 후보 노드가 2개 미만입니다. 구역을 추가하거나 "
                "region_buffer_km를 늘려주세요."
            )
    retained_nodes, pruned_node_count = _prune_nodes(merged_nodes, low_impact_prune_percent, top_node_limit)
    edges = _generate_candidate_edges(
        active_source,
        flow_columns,
        coordinate_columns,
        coordinate_lookup,
        code_columns,
        retained_nodes,
        edge_limit=edge_limit,
        min_estimated_flow=min_estimated_flow,
        sample_size=sample_size,
        region_context=region_context,
    )

    if coordinate_excluded_rows:
        warnings.append(f"{coordinate_excluded_rows} rows without valid coordinates were excluded.")
    if non_positive_rows:
        warnings.append(f"{non_positive_rows} rows with non-positive total_flow were excluded.")
    if not edges:
        warnings.append("No candidate edge satisfied the distance and estimated_flow filters.")
    if region_context.enabled:
        warnings.append(
            f"행정구역 필터 적용: {', '.join(region_context.selected_regions)} "
            f"(경계 여유 {region_context.buffer_km:g}km)"
        )

    result_files = {}
    if persist_files:
        result_files = {
            "candidate_nodes.json": _write_json("candidate_nodes.json", [node.model_dump() for node in retained_nodes]),
            "candidate_edges.json": _write_json("candidate_edges.json", [edge.model_dump() for edge in edges]),
        }

    elapsed_seconds = round(time.perf_counter() - started_at, 3)
    region_summary = region_context.summary(
        od_rows_before=total_rows,
        od_rows_after=valid_rows,
        candidate_coordinates_before=(valid_rows + region_excluded_rows) * 2,
        candidate_coordinates_after=valid_rows * 2,
        candidate_nodes_after=len(retained_nodes),
        candidate_edges_after=len(edges),
    )
    logger.info(
        "[RegionFilter] candidate coordinates: %s -> %s",
        region_summary["candidate_coordinates_before"],
        region_summary["candidate_coordinates_after"],
    )
    logger.info("[Pipeline] od_candidates elapsed_seconds=%s", elapsed_seconds)

    stats = ODCandidateStats(
        source_name=source_name,
        total_od_rows=total_rows,
        selected_top_percent=active_filter_percent,
        selected_top_rows=len(records),
        coordinate_excluded_rows=coordinate_excluded_rows,
        non_positive_flow_excluded_rows=non_positive_rows,
        clustered_od_rows=len(records),
        cluster_count_requested=max(active_k_values),
        cluster_count_used=len(retained_nodes),
        iterative_cluster_counts=active_k_values,
        pre_merge_node_count=len(raw_nodes),
        merged_node_count=len(merged_nodes),
        retained_node_count=len(retained_nodes),
        pruned_node_count=pruned_node_count,
        low_impact_prune_percent=low_impact_prune_percent,
        merge_distance_km=merge_distance_km,
        top_node_limit=top_node_limit,
        edge_limit=edge_limit,
        min_estimated_flow=min_estimated_flow,
        sample_size=sample_size,
        flow_columns=[item.column for item in flow_columns],
        flow_weights={item.column: item.weight for item in flow_columns},
        coordinate_columns=coordinate_columns,
        coordinate_lookup_used=coordinate_lookup_used,
        region_excluded_rows=region_excluded_rows,
        region_filter_summary=region_summary,
        elapsed_seconds=elapsed_seconds,
        result_files=result_files,
        warnings=warnings,
    )
    return ODCandidateResult(nodes=retained_nodes, edges=edges, stats=stats)
