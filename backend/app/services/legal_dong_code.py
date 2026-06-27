from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
LEGAL_DONG_CODE_CSV = ROOT / "data" / "processed" / "csv" / "국토교통부_법정동코드_20250805.csv"


@lru_cache(maxsize=1)
def load_legal_dong_codes() -> tuple[dict[str, str], ...]:
    if not LEGAL_DONG_CODE_CSV.exists():
        raise FileNotFoundError(f"법정동코드 CSV 파일이 없습니다: {LEGAL_DONG_CODE_CSV}")

    rows = []
    for encoding in ("utf-8-sig", "cp949"):
        try:
            with LEGAL_DONG_CODE_CSV.open("r", encoding=encoding, newline="") as file:
                reader = csv.DictReader(file)
                rows = []
                for row in reader:
                    code = (row.get("법정동코드") or "").strip()
                    name = (row.get("법정동명") or "").strip()
                    status = (row.get("폐지여부") or "").strip()
                    if code and name and status == "존재":
                        rows.append({"legal_dong_code": code, "legal_dong_name": name})
            break
        except UnicodeDecodeError:
            continue

    return tuple(rows)


def list_legal_dong_codes(req_lvl: int, ld_code: str = "") -> list[dict[str, str]]:
    normalized_code = ld_code.strip()
    rows = load_legal_dong_codes()

    if req_lvl == 1:
        return [
            row
            for row in rows
            if row["legal_dong_code"].endswith("00000000")
        ]

    if req_lvl == 2:
        if not 2 <= len(normalized_code) <= 5:
            raise ValueError("reqLvl=2는 ldCode가 2~5자리여야 합니다.")
        return [
            row
            for row in rows
            if row["legal_dong_code"].startswith(normalized_code)
            and row["legal_dong_code"].endswith("00000")
            and not row["legal_dong_code"].endswith("00000000")
        ]

    if req_lvl == 3:
        if not 2 <= len(normalized_code) <= 10:
            raise ValueError("reqLvl=3은 ldCode가 2~10자리여야 합니다.")
        return [
            row
            for row in rows
            if row["legal_dong_code"].startswith(normalized_code)
            and not row["legal_dong_code"].endswith("00000")
        ]

    raise ValueError("reqLvl은 1, 2, 3 중 하나여야 합니다.")
