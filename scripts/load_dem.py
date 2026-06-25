from __future__ import annotations

import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEM_SRID = 100002

DEM_SRS_SQL = """
CREATE EXTENSION IF NOT EXISTS postgis_raster;

INSERT INTO spatial_ref_sys (srid, auth_name, auth_srid, srtext, proj4text)
VALUES (
    100002,
    'ONESTEP',
    100002,
    'PROJCS["ONESTEP DEM TM",GEOGCS["GRS80 ELLIPSOID",DATUM["GRS80 ELLIPSOID",SPHEROID["GRS 1980",6378137,298.257222101004]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",38],PARAMETER["central_meridian",127],PARAMETER["scale_factor",1],PARAMETER["false_easting",200000],PARAMETER["false_northing",600000],UNIT["metre",1]]',
    '+proj=tmerc +lat_0=38 +lon_0=127 +k=1 +x_0=200000 +y_0=600000 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs'
)
ON CONFLICT (srid) DO UPDATE
SET auth_name = EXCLUDED.auth_name,
    auth_srid = EXCLUDED.auth_srid,
    srtext = EXCLUDED.srtext,
    proj4text = EXCLUDED.proj4text;
"""


def dem_path() -> Path:
    ascii_path = ROOT / "data" / "raw" / "dem.img"
    if ascii_path.exists():
        return ascii_path

    matches = list((ROOT / "data" / "raw").glob("*GRS80.img"))
    if len(matches) != 1:
        joined = ", ".join(str(path) for path in matches) or "없음"
        raise FileNotFoundError(f"DEM 파일 후보가 1개여야 합니다: {joined}")
    return matches[0]


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


def load_dem() -> None:
    path = dem_path()
    raster2pgsql = subprocess.Popen(
        [
            "raster2pgsql",
            "-d",
            "-I",
            "-C",
            "-s",
            str(DEM_SRID),
            "-t",
            "256x256",
            str(path),
            "dem_elevation",
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
        stdin=raster2pgsql.stdout,
        stdout=subprocess.DEVNULL,
        text=True,
    )

    if raster2pgsql.stdout is not None:
        raster2pgsql.stdout.close()

    psql_returncode = psql.wait()
    raster_returncode = raster2pgsql.wait()

    if raster_returncode != 0:
        raise subprocess.CalledProcessError(raster_returncode, "raster2pgsql")
    if psql_returncode != 0:
        raise subprocess.CalledProcessError(psql_returncode, "psql")


def assert_dem_exists() -> None:
    dem_path()


def main() -> None:
    assert_dem_exists()
    wait_for_database()
    run_psql(DEM_SRS_SQL)
    load_dem()


if __name__ == "__main__":
    main()
