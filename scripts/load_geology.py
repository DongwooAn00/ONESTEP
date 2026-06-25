from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GEOLOGY_DIR = ROOT / "data" / "raw" / "geology_250k"
GEOLOGY_SRID = 4326
DBF_ENCODING = os.environ.get("GEOLOGY_DBF_ENCODING", "UTF-8")

LAYERS = [
    ("Geology_250K_Litho.shp", "geology_litho"),
    ("Geology_250K_Fault.shp", "geology_faults"),
    ("Geology_250K_Boudary.shp", "geology_boundaries"),
    ("Geology_250K_Frame.shp", "geology_frames"),
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


def load_shapefile(shapefile_path: Path, table_name: str) -> None:
    shp2pgsql = subprocess.Popen(
        [
            "shp2pgsql",
            "-c",
            "-D",
            "-I",
            "-s",
            str(GEOLOGY_SRID),
            "-W",
            DBF_ENCODING,
            str(shapefile_path),
            table_name,
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        text=True,
    )
    psql = subprocess.Popen(
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
        ],
        cwd=ROOT,
        stdin=shp2pgsql.stdout,
        stdout=subprocess.DEVNULL,
        text=True,
    )

    if shp2pgsql.stdout is not None:
        shp2pgsql.stdout.close()

    psql_returncode = psql.wait()
    shp2pgsql_returncode = shp2pgsql.wait()

    if shp2pgsql_returncode != 0:
        raise subprocess.CalledProcessError(shp2pgsql_returncode, "shp2pgsql")
    if psql_returncode != 0:
        raise subprocess.CalledProcessError(psql_returncode, "psql")


def assert_shapefiles_exist() -> None:
    missing_files = [GEOLOGY_DIR / filename for filename, _ in LAYERS if not (GEOLOGY_DIR / filename).exists()]
    if missing_files:
        joined_files = ", ".join(str(path) for path in missing_files)
        raise FileNotFoundError(f"수치지질도 Shapefile이 없습니다: {joined_files}")


def main() -> None:
    assert_shapefiles_exist()
    wait_for_database()
    run_psql("CREATE EXTENSION IF NOT EXISTS postgis;")

    for filename, table_name in LAYERS:
        print(f"Loading {filename} -> {table_name}")
        run_psql(f"DROP TABLE IF EXISTS {table_name};")
        load_shapefile(GEOLOGY_DIR / filename, table_name)
        run_psql(f"ANALYZE {table_name};")


if __name__ == "__main__":
    main()
