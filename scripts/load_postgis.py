from __future__ import annotations

import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSV_DIR = ROOT / "data" / "processed" / "csv"
CONTAINER_CSV_DIR = Path("/workspace/data/processed/csv")

TABLES = [
    ("zones", "zones.csv"),
    ("freight_item_codes", "freight_item_codes.csv"),
    ("od_by_mode", "od_by_mode.csv"),
    ("od_by_purpose", "od_by_purpose.csv"),
    ("freight_vehicle_od", "freight_vehicle_od.csv"),
    ("freight_tonnage_od", "freight_tonnage_od.csv"),
    ("freight_tonnage_od_long", "freight_tonnage_od_long.csv"),
]


def wait_for_database() -> None:
    for _ in range(30):
        result = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "db",
                "pg_isready",
                "-U",
                "onestep",
                "-d",
                "onestep",
            ],
            cwd=ROOT,
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(1)

    raise TimeoutError("PostgreSQL이 준비되지 않았습니다. `docker compose up -d` 상태를 확인하세요.")


def run_psql(sql: str) -> None:
    subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "onestep",
            "-d",
            "onestep",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        ],
        cwd=ROOT,
        check=True,
    )


def assert_csv_files_exist() -> None:
    missing_files = [filename for _, filename in TABLES if not (CSV_DIR / filename).exists()]
    if missing_files:
        joined_files = ", ".join(missing_files)
        raise FileNotFoundError(
            f"CSV 파일이 없습니다: {joined_files}. 먼저 `python3 scripts/preprocess_csv.py`를 실행하세요."
        )


def main() -> None:
    assert_csv_files_exist()
    wait_for_database()
    run_psql(
        """
        TRUNCATE
            freight_tonnage_od_long,
            freight_tonnage_od,
            freight_vehicle_od,
            od_by_purpose,
            od_by_mode,
            freight_item_codes,
            zones
        RESTART IDENTITY CASCADE;
        """
    )

    for table_name, filename in TABLES:
        csv_path = CONTAINER_CSV_DIR / filename
        run_psql(f"\\copy {table_name} FROM '{csv_path}' WITH (FORMAT csv, HEADER true)")


if __name__ == "__main__":
    main()
