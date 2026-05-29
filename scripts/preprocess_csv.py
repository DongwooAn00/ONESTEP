from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "processed" / "csv"

FREIGHT_ITEM_CODES = [
    ("item_01", 1, "농산물", "농수임산품"),
    ("item_02", 2, "임산물", "농수임산품"),
    ("item_03", 3, "수산물", "농수임산품"),
    ("item_04", 4, "축산물", "농수임산품"),
    ("item_05", 5, "석탄광물", "광산품"),
    ("item_06", 6, "석회석광물", "광산품"),
    ("item_07", 7, "원유 및 천연가스 채취물", "광산품"),
    ("item_08", 8, "금속광물", "광산품"),
    ("item_09", 9, "비금속광물", "광산품"),
    ("item_10", 10, "음식료품", "경공업품"),
    ("item_11", 11, "담배제품", "경공업품"),
    ("item_12", 12, "섬유제품", "경공업품"),
    ("item_13", 13, "의복 액세서리 및 모피제품", "경공업품"),
    ("item_14", 14, "가죽 가방 및 신발제품", "경공업품"),
    ("item_15", 15, "목재 및 나무제품", "잡공업품"),
    ("item_16", 16, "펄프 종이 및 종이제품", "잡공업품"),
    ("item_17", 17, "인쇄 및 기록매체", "잡공업품"),
    ("item_18", 18, "코크스 연탄 및 석유정제품", "화학공업품"),
    ("item_19", 19, "화합물 및 화학제품", "화학공업품"),
    ("item_20", 20, "고무제품 및 플라스틱제품", "화학공업품"),
    ("item_21", 21, "비금속 광물제품", "잡공업품"),
    ("item_22", 22, "제1차 금속제품", "금속기계공업품"),
    ("item_23", 23, "금속가공제품", "금속기계공업품"),
    ("item_24", 24, "기타기계 및 장비제조품", "금속기계공업품"),
    ("item_25", 25, "전자부품 컴퓨터 영상 음향 및 통신장비", "금속기계공업품"),
    ("item_26", 26, "전기장비제품", "금속기계공업품"),
    ("item_27", 27, "의료 정밀 광학기기 및 시계", "금속기계공업품"),
    ("item_28", 28, "자동차 및 트레일러", "금속기계공업품"),
    ("item_29", 29, "기타운송장비", "금속기계공업품"),
    ("item_30", 30, "가구 제품", "기타"),
    ("item_31", 31, "기타제품", "기타"),
    ("item_32", 32, "도매제품", "기타"),
    ("container", None, "컨테이너", "기타"),
]


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


def preprocess_freight_item_codes() -> None:
    write_rows(
        OUT_DIR / "freight_item_codes.csv",
        ["item_code", "source_item_number", "item_name", "major_category"],
        FREIGHT_ITEM_CODES,
    )


def main() -> None:
    preprocess_zones()
    preprocess_freight_item_codes()
    preprocess_mode_od()
    preprocess_purpose_od()
    preprocess_freight_vehicle_od()
    preprocess_freight_tonnage_od()


if __name__ == "__main__":
    main()
