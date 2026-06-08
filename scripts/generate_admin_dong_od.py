from __future__ import annotations

import argparse
import csv
import hashlib
import math
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "processed" / "csv"

XLSX_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
MODE_COLUMNS = [
    "passenger_car",
    "bus",
    "subway",
    "rail",
    "high_speed_rail",
    "air",
    "sea",
]
OUTPUT_HEADER = [
    "origin_province_id",
    "destination_province_id",
    "origin_zone_id",
    "destination_zone_id",
    "origin_admin_dong_code",
    "destination_admin_dong_code",
    *MODE_COLUMNS,
    "total",
    "data_source",
]


def normalize(value: str) -> str:
    return unicodedata.normalize("NFC", value or "").strip()


def compact(value: str) -> str:
    return "".join(char for char in normalize(value) if char.isalnum())


def find_raw_file(keyword: str, suffix: str) -> Path:
    normalized_keyword = compact(keyword)
    for path in RAW_DIR.glob(f"*{suffix}"):
        if normalized_keyword in compact(path.name):
            return path
    raise FileNotFoundError(f"{keyword} 파일을 찾을 수 없습니다.")


def to_int(value: str) -> int:
    cleaned = (value or "").replace(",", "").strip()
    return int(float(cleaned)) if cleaned else 0


def csv_rows(path: Path, encoding: str = "utf-8-sig") -> list[dict[str, str]]:
    with path.open("r", encoding=encoding, newline="") as file:
        return [{normalize(k): normalize(v) for k, v in row.items()} for row in csv.DictReader(file)]


def write_csv(path: Path, header: list[str], rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        writer.writerows(rows)


def xlsx_column_index(cell_ref: str) -> int:
    index = 0
    for char in "".join(ch for ch in cell_ref if ch.isalpha()):
        index = index * 26 + ord(char.upper()) - 64
    return index - 1


def read_xlsx_rows(path: Path):
    with zipfile.ZipFile(path) as workbook:
        shared_strings = []
        shared_root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
        for item in shared_root.findall("x:si", XLSX_NS):
            shared_strings.append("".join(node.text or "" for node in item.iterfind(".//x:t", XLSX_NS)))

        with workbook.open("xl/worksheets/sheet1.xml") as sheet_file:
            for _, row_elem in ET.iterparse(sheet_file, events=("end",)):
                if not row_elem.tag.endswith("row"):
                    continue
                values: list[str] = []
                for cell in row_elem.findall("x:c", XLSX_NS):
                    index = xlsx_column_index(cell.attrib.get("r", "A1"))
                    while len(values) <= index:
                        values.append("")
                    value_elem = cell.find("x:v", XLSX_NS)
                    if value_elem is None:
                        value = ""
                    elif cell.attrib.get("t") == "s":
                        value = shared_strings[int(value_elem.text or "0")]
                    else:
                        value = value_elem.text or ""
                    values[index] = normalize(value)
                yield values
                row_elem.clear()


def canonical_province_name(name: str) -> str:
    return {
        "강원특별자치도": "강원도",
        "전북특별자치도": "전라북도",
    }.get(name, name)


def canonical_district_name(province_name: str, district_name: str) -> str:
    if province_name == "세종특별자치시" and not district_name:
        return "세종시"
    if province_name == "경기도" and district_name.startswith("부천시 "):
        return "부천시"
    if province_name == "경기도" and district_name.startswith("화성시 "):
        return "화성시"
    return district_name


def deterministic_unit(*parts: str) -> float:
    key = "|".join(parts).encode("utf-8")
    digest = hashlib.blake2b(key, digest_size=8).digest()
    value = int.from_bytes(digest, "big") / ((1 << 64) - 1)
    return max(value, 1e-9)


def dong_activity_weight(code: str, direction: str) -> float:
    # 인구 자료가 없는 행정동에만 쓰는 결정론적 fallback이다.
    return 0.65 + 1.35 * deterministic_unit(code, direction)


def load_population_by_admin_dong() -> dict[str, int]:
    path = find_raw_file("연령별인구현황월간", ".csv")
    rows = csv_rows(path, encoding="cp949")
    population_by_code = {}

    for row in rows:
        match = re.search(r"\((\d{10})\)", row["행정구역"])
        if not match:
            continue
        code = match.group(1)
        population_by_code[code] = to_int(row["2026년05월_계_총인구수"])

    return population_by_code


def load_zones() -> tuple[dict[tuple[str, str], dict[str, str]], dict[str, dict[str, str]]]:
    zones = csv_rows(OUT_DIR / "zones.csv")
    by_name = {(row["province_name"], row["district_name"]): row for row in zones}
    by_id = {row["zone_id"]: row for row in zones}
    return by_name, by_id


def load_admin_dongs(
    zones_by_name: dict[tuple[str, str], dict[str, str]],
    population_by_code: dict[str, int],
) -> list[dict[str, str]]:
    path = find_raw_file("행정동20260325", ".xlsx")
    rows = read_xlsx_rows(path)
    header = next(rows)
    dongs = []

    for raw_row in rows:
        row = dict(zip(header, raw_row))
        if not row.get("읍면동명") or row.get("말소일자"):
            continue

        raw_province = row["시도명"]
        province_name = canonical_province_name(raw_province)
        district_name = canonical_district_name(province_name, row.get("시군구명", ""))
        zone = zones_by_name.get((province_name, district_name))
        if not zone:
            raise KeyError(f"시군구 존 매핑 실패: {province_name} {district_name} {row['읍면동명']}")

        population = population_by_code.get(row["행정동코드"], 0)
        if population > 0:
            origin_weight = destination_weight = float(population)
        else:
            origin_weight = dong_activity_weight(row["행정동코드"], "origin")
            destination_weight = dong_activity_weight(row["행정동코드"], "destination")

        dongs.append(
            {
                "admin_dong_code": row["행정동코드"],
                "province_id": zone["province_id"],
                "zone_id": zone["zone_id"],
                "province_name": province_name,
                "district_name": district_name,
                "dong_name": row["읍면동명"],
                "population": str(population),
                "population_source": "actual" if population > 0 else "fallback_zone_average",
                "origin_weight": str(origin_weight),
                "destination_weight": str(destination_weight),
            }
        )

    population_by_zone: dict[str, list[int]] = defaultdict(list)
    for dong in dongs:
        population = int(dong["population"])
        if population > 0:
            population_by_zone[dong["zone_id"]].append(population)

    all_populations = [population for populations in population_by_zone.values() for population in populations]
    global_average = round(sum(all_populations) / len(all_populations))
    for dong in dongs:
        if int(dong["population"]) > 0:
            continue
        zone_populations = population_by_zone.get(dong["zone_id"], [])
        fallback_population = round(sum(zone_populations) / len(zone_populations)) if zone_populations else global_average
        dong["population"] = str(fallback_population)
        dong["origin_weight"] = str(float(fallback_population))
        dong["destination_weight"] = str(float(fallback_population))

    return dongs


def load_seoul_tpss_to_standard_code(dongs: list[dict[str, str]]) -> dict[str, str]:
    seoul_master_path = find_raw_file("서울시행정동마스터정보", ".csv")
    standard_by_name = {
        (row["district_name"], row["dong_name"]): row["admin_dong_code"]
        for row in dongs
        if row["province_name"] == "서울특별시"
    }
    mapping = {}

    for row in csv_rows(seoul_master_path, encoding="cp949"):
        tpss_id = row["행정동_ID"]
        if len(tpss_id) != 8:
            continue
        standard_code = standard_by_name.get((row["자치구_명칭"], row["행정동_명칭"]))
        if standard_code:
            mapping[tpss_id] = standard_code

    return mapping


def load_seoul_actual_rows(tpss_to_standard: dict[str, str], dongs_by_code: dict[str, dict[str, str]]):
    path = find_raw_file("TPSS행정동OD수단", ".csv")
    aggregated: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])

    for row in csv_rows(path):
        origin = tpss_to_standard.get(row["시작행정동ID"])
        destination = tpss_to_standard.get(row["종료행정동ID"])
        if not origin or not destination:
            continue
        values = aggregated[(origin, destination)]
        values[0] += to_int(row["전체승객수"])
        values[1] += to_int(row["버스승객수"])
        values[2] += to_int(row["지하철승객수"])

    for (origin, destination), (_, bus, subway) in aggregated.items():
        origin_dong = dongs_by_code[origin]
        destination_dong = dongs_by_code[destination]
        total = bus + subway
        yield [
            origin_dong["province_id"],
            destination_dong["province_id"],
            origin_dong["zone_id"],
            destination_dong["zone_id"],
            origin,
            destination,
            0,
            bus,
            subway,
            0,
            0,
            0,
            0,
            total,
            "actual_tpss_seoul",
        ]


def allocate_integer(total: int, weighted_items: list[tuple[float, tuple[str, str]]]) -> list[tuple[tuple[str, str], int]]:
    if total <= 0 or not weighted_items:
        return []

    weight_sum = sum(weight for weight, _ in weighted_items)
    floors = []
    assigned = 0
    for weight, item in weighted_items:
        exact = total * weight / weight_sum
        value = math.floor(exact)
        if value > 0:
            floors.append((item, value, exact - value))
        else:
            floors.append((item, 0, exact))
        assigned += value

    remainder = total - assigned
    floors.sort(key=lambda row: row[2], reverse=True)
    for index in range(remainder):
        item, value, fraction = floors[index]
        floors[index] = (item, value + 1, fraction)

    return [(item, value) for item, value, _ in floors if value > 0]


def split_modes(total: int, district_row: dict[str, str]) -> list[int]:
    district_mode_total = sum(to_int(district_row[column]) for column in MODE_COLUMNS)
    if total <= 0:
        return [0] * len(MODE_COLUMNS)
    if district_mode_total <= 0:
        return [total, 0, 0, 0, 0, 0, 0]

    exact_values = []
    assigned = 0
    for column in MODE_COLUMNS:
        exact = total * to_int(district_row[column]) / district_mode_total
        value = math.floor(exact)
        exact_values.append([value, exact - value])
        assigned += value

    for value in sorted(range(len(exact_values)), key=lambda i: exact_values[i][1], reverse=True)[: total - assigned]:
        exact_values[value][0] += 1

    return [value for value, _ in exact_values]


def pair_weight(origin: dict[str, str], destination: dict[str, str]) -> float:
    weight = float(origin["origin_weight"]) * float(destination["destination_weight"])
    if origin["zone_id"] == destination["zone_id"]:
        weight *= 1.35
        if origin["admin_dong_code"] == destination["admin_dong_code"]:
            weight *= 2.25
    return weight


def load_district_mode_rows() -> list[dict[str, str]]:
    return csv_rows(OUT_DIR / "od_by_mode.csv")


def generate_synthetic_rows(
    district_rows: list[dict[str, str]],
    dongs_by_zone: dict[str, list[dict[str, str]]],
):
    for district_row in district_rows:
        origin_zone = district_row["origin_zone_id"]
        destination_zone = district_row["destination_zone_id"]
        if int(origin_zone) <= 25 and int(destination_zone) <= 25:
            continue

        origins = dongs_by_zone[origin_zone]
        destinations = dongs_by_zone[destination_zone]
        weighted_pairs = [
            (pair_weight(origin, destination), (origin["admin_dong_code"], destination["admin_dong_code"]))
            for origin in origins
            for destination in destinations
        ]

        for (origin_code, destination_code), total in allocate_integer(to_int(district_row["total"]), weighted_pairs):
            modes = split_modes(total, district_row)
            yield [
                district_row["origin_province_id"],
                district_row["destination_province_id"],
                origin_zone,
                destination_zone,
                origin_code,
                destination_code,
                *modes,
                total,
                "synthetic_from_sigungu_od",
            ]


def main() -> None:
    parser = argparse.ArgumentParser(description="전국 행정동 단위 가상 수단별 OD CSV를 생성합니다.")
    parser.add_argument("--skip-od", action="store_true", help="admin_dongs.csv만 생성합니다.")
    args = parser.parse_args()

    zones_by_name, _ = load_zones()
    population_by_code = load_population_by_admin_dong()
    dongs = load_admin_dongs(zones_by_name, population_by_code)
    dongs_by_code = {row["admin_dong_code"]: row for row in dongs}
    dongs_by_zone: dict[str, list[dict[str, str]]] = defaultdict(list)
    for dong in dongs:
        dongs_by_zone[dong["zone_id"]].append(dong)

    write_csv(
        OUT_DIR / "admin_dongs.csv",
        [
            "admin_dong_code",
            "province_id",
            "zone_id",
            "province_name",
            "district_name",
            "dong_name",
            "population",
            "population_source",
            "origin_weight",
            "destination_weight",
        ],
        ([row[column] for column in [
            "admin_dong_code",
            "province_id",
            "zone_id",
            "province_name",
            "district_name",
            "dong_name",
            "population",
            "population_source",
            "origin_weight",
            "destination_weight",
        ]] for row in dongs),
    )

    if args.skip_od:
        return

    tpss_to_standard = load_seoul_tpss_to_standard_code(dongs)
    district_rows = load_district_mode_rows()
    output_path = OUT_DIR / "synthetic_admin_dong_od_by_mode.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(OUTPUT_HEADER)
        writer.writerows(load_seoul_actual_rows(tpss_to_standard, dongs_by_code))
        writer.writerows(generate_synthetic_rows(district_rows, dongs_by_zone))


if __name__ == "__main__":
    main()
