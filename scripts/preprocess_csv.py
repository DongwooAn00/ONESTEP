from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "processed" / "csv"


def normalize_name(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def compact(value: str) -> str:
    return re.sub(r"\s+", "", normalize_name(value))


def read_rows(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return [[cell.strip() for cell in row] for row in csv.reader(file)]


def write_rows(path: Path, header: list[str], rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        writer.writerows(rows)


def to_int(value: str) -> int:
    cleaned = value.replace(",", "").strip()
    return int(float(cleaned)) if cleaned else 0


def to_float(value: str) -> float:
    cleaned = value.replace(",", "").strip()
    return float(cleaned) if cleaned else 0.0


def split_admin_name(value: str) -> tuple[str, str]:
    if "_" not in value:
        return value, ""
    province_name, district_name = value.split("_", 1)
    return province_name, district_name


def find_raw_csv(keyword: str) -> Path:
    for path in RAW_DIR.glob("*.csv"):
        if keyword in compact(path.name):
            return path
    raise FileNotFoundError(f"{keyword} CSV 파일을 찾을 수 없습니다.")


def preprocess_zones() -> None:
    path = find_raw_csv("존체계")
    rows = read_rows(path)
    output = []

    for row in rows[1:]:
        if not row or not row[0]:
            continue
        province_name, district_name = split_admin_name(row[2])
        output.append(
            [
                to_int(row[0]),
                to_int(row[1]),
                row[2],
                province_name,
                district_name,
            ]
        )

    write_rows(
        OUT_DIR / "zones.csv",
        ["zone_id", "province_id", "admin_name", "province_name", "district_name"],
        output,
    )


def preprocess_mode_od() -> None:
    path = find_raw_csv("수단별OD")
    rows = read_rows(path)
    output = []

    for row in rows[1:]:
        if not row or not row[0]:
            continue
        row = row[:12]
        output.append(
            [
                to_int(row[0]),
                to_int(row[1]),
                to_int(row[2]),
                to_int(row[3]),
                to_int(row[4]),
                to_int(row[5]),
                to_int(row[6]),
                to_int(row[7]),
                to_int(row[8]),
                to_int(row[9]),
                to_int(row[10]),
                to_int(row[11]),
            ]
        )

    write_rows(
        OUT_DIR / "od_by_mode.csv",
        [
            "origin_province_id",
            "destination_province_id",
            "origin_zone_id",
            "destination_zone_id",
            "passenger_car",
            "bus",
            "subway",
            "rail",
            "high_speed_rail",
            "air",
            "sea",
            "total",
        ],
        output,
    )


def preprocess_purpose_od() -> None:
    path = find_raw_csv("목적별OD")
    rows = read_rows(path)
    output = []

    for row in rows[1:]:
        if not row or not row[0]:
            continue
        row = row[:10]
        output.append(
            [
                to_int(row[0]),
                to_int(row[1]),
                to_int(row[2]),
                to_int(row[3]),
                to_int(row[4]),
                to_int(row[5]),
                to_int(row[6]),
                to_int(row[7]),
                to_int(row[8]),
                to_int(row[9]),
            ]
        )

    write_rows(
        OUT_DIR / "od_by_purpose.csv",
        [
            "origin_province_id",
            "destination_province_id",
            "origin_zone_id",
            "destination_zone_id",
            "commute",
            "school",
            "business",
            "return_home",
            "other",
            "total",
        ],
        output,
    )


def preprocess_freight_vehicle_od() -> None:
    path = find_raw_csv("화물자동차OD")
    rows = read_rows(path)
    output = []

    for row in rows[2:]:
        if not row or not row[0]:
            continue
        output.append(
            [
                to_int(row[0]),
                to_int(row[1]),
                to_int(row[2]),
                to_int(row[3]),
                to_float(row[4]),
                to_float(row[5]),
                to_float(row[6]),
                to_float(row[7]),
            ]
        )

    write_rows(
        OUT_DIR / "freight_vehicle_od.csv",
        [
            "origin_zone_id",
            "origin_province_id",
            "destination_zone_id",
            "destination_province_id",
            "small_truck",
            "medium_truck",
            "large_truck",
            "total",
        ],
        output,
    )


def item_column_name(raw_name: str) -> str:
    if raw_name == "컨테이너":
        return "container"
    if raw_name == "전체":
        return "total"
    match = re.fullmatch(r"품목(\d+)", raw_name)
    if match:
        return f"item_{int(match.group(1)):02d}"
    return raw_name


def preprocess_freight_tonnage_od() -> None:
    path = find_raw_csv("화물물동량OD")
    rows = read_rows(path)
    raw_header = rows[1]
    item_headers = [item_column_name(name) for name in raw_header[4:]]

    wide_output = []
    long_output = []

    for row in rows[2:]:
        if not row or not row[0]:
            continue
        base = [
            to_int(row[0]),
            to_int(row[1]),
            to_int(row[2]),
            to_int(row[3]),
        ]
        values = [to_float(value) for value in row[4 : 4 + len(item_headers)]]
        wide_output.append(base + values)

        for item_code, tonnage in zip(item_headers, values):
            if item_code == "total":
                continue
            long_output.append(base + [item_code, tonnage])

    write_rows(
        OUT_DIR / "freight_tonnage_od.csv",
        [
            "origin_zone_id",
            "destination_zone_id",
            "origin_province_id",
            "destination_province_id",
            *item_headers,
        ],
        wide_output,
    )
    write_rows(
        OUT_DIR / "freight_tonnage_od_long.csv",
        [
            "origin_zone_id",
            "destination_zone_id",
            "origin_province_id",
            "destination_province_id",
            "item_code",
            "tonnage_per_year",
        ],
        long_output,
    )


def main() -> None:
    preprocess_zones()
    preprocess_mode_od()
    preprocess_purpose_od()
    preprocess_freight_vehicle_od()
    preprocess_freight_tonnage_od()


if __name__ == "__main__":
    main()
