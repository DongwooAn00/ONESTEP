from __future__ import annotations

import argparse
import csv
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "processed" / "admin_dongs.csv"
DEFAULT_OUTPUT = ROOT / "data" / "processed" / "admin_dong_coordinates.csv"
KAKAO_ADDRESS_SEARCH_URL = "https://dapi.kakao.com/v2/local/search/address.json"


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "admin_dong_code",
                "latitude",
                "longitude",
                "query",
                "matched_address",
                "match_type",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def kakao_address_search(rest_api_key: str, query: str) -> dict | None:
    params = urllib.parse.urlencode({"query": query, "size": 1})
    request = urllib.request.Request(
        f"{KAKAO_ADDRESS_SEARCH_URL}?{params}",
        headers={"Authorization": f"KakaoAK {rest_api_key}"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    documents = payload.get("documents") or []
    return documents[0] if documents else None


def make_query(row: dict[str, str]) -> str:
    parts = [
        row.get("province_name", ""),
        row.get("district_name", ""),
        row.get("dong_name", ""),
    ]
    return " ".join(part.strip() for part in parts if part and part.strip())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build admin_dong_coordinates.csv from Kakao Local address search."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sleep", type=float, default=0.12, help="Delay between Kakao API calls in seconds.")
    parser.add_argument("--limit", type=int, default=None, help="Optional row limit for testing.")
    args = parser.parse_args()

    rest_api_key = os.environ.get("KAKAO_REST_API_KEY")
    if not rest_api_key:
        raise SystemExit("Set KAKAO_REST_API_KEY before running this script.")

    rows = read_rows(args.input)
    if args.limit:
        rows = rows[: args.limit]

    coordinates: list[dict[str, str]] = []
    missed = 0
    for index, row in enumerate(rows, start=1):
        query = make_query(row)
        if not query:
            missed += 1
            continue

        try:
            document = kakao_address_search(rest_api_key, query)
        except Exception as error:
            print(f"[{index}/{len(rows)}] failed: {query} ({error})")
            missed += 1
            time.sleep(args.sleep)
            continue

        if not document:
            print(f"[{index}/{len(rows)}] no match: {query}")
            missed += 1
            time.sleep(args.sleep)
            continue

        coordinates.append(
            {
                "admin_dong_code": row["admin_dong_code"],
                "latitude": document["y"],
                "longitude": document["x"],
                "query": query,
                "matched_address": document.get("address_name", ""),
                "match_type": document.get("address_type", ""),
            }
        )

        if index % 100 == 0:
            print(f"[{index}/{len(rows)}] matched={len(coordinates)} missed={missed}")
            write_rows(args.output, coordinates)

        time.sleep(args.sleep)

    write_rows(args.output, coordinates)
    print(f"wrote {len(coordinates)} rows to {args.output}")
    if missed:
        print(f"missed {missed} rows")


if __name__ == "__main__":
    main()
