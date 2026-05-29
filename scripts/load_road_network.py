from __future__ import annotations

import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHAPEFILE_DIR = ROOT / "data" / "processed" / "shapefiles"
NODES_SHP = SHAPEFILE_DIR / "nodes" / "ad0102_2023_GR.shp"
LINKS_SHP = SHAPEFILE_DIR / "links" / "ad0022_2023_GR.shp"
ROAD_SRID = 100001

ROAD_SRS_SQL = """
INSERT INTO spatial_ref_sys (srid, auth_name, auth_srid, srtext, proj4text)
VALUES (
    100001,
    'ONESTEP',
    100001,
    'PROJCS["Korea 2000 Katech(TM128)",GEOGCS["GCS_ITRF_2000",DATUM["D_ITRF_2000",SPHEROID["GRS_1980",6378137.0,298.257222101]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],PARAMETER["False_Easting",400000.0],PARAMETER["False_Northing",600000.0],PARAMETER["Central_Meridian",128.0],PARAMETER["Scale_Factor",0.9999],PARAMETER["Latitude_Of_Origin",38.0],UNIT["Meter",1.0]]',
    '+proj=tmerc +lat_0=38 +lon_0=128 +k=0.9999 +x_0=400000 +y_0=600000 +ellps=GRS80 +units=m +no_defs'
)
ON CONFLICT (srid) DO UPDATE
SET auth_name = EXCLUDED.auth_name,
    auth_srid = EXCLUDED.auth_srid,
    srtext = EXCLUDED.srtext,
    proj4text = EXCLUDED.proj4text;
"""


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


def run_sql_file(path: Path) -> None:
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
            "-f",
            "-",
        ],
        cwd=ROOT,
        input=path.read_text(encoding="utf-8"),
        text=True,
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
            str(ROAD_SRID),
            "-W",
            "CP949",
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
    missing_files = [path for path in [NODES_SHP, LINKS_SHP] if not path.exists()]
    if missing_files:
        joined_files = ", ".join(str(path) for path in missing_files)
        raise FileNotFoundError(
            f"Shapefile이 없습니다: {joined_files}. 먼저 `python3 scripts/extract_road_shapefiles.py`를 실행하세요."
        )


def recreate_road_tables() -> None:
    run_psql(
        f"""
        DROP TABLE IF EXISTS staging_road_links;
        DROP TABLE IF EXISTS staging_road_nodes;
        DROP TABLE IF EXISTS road_links;
        DROP TABLE IF EXISTS road_nodes;

        CREATE TABLE road_nodes (
            node_id text PRIMARY KEY,
            node_type text,
            node_name text,
            x double precision,
            y double precision,
            geom geometry(Point, {ROAD_SRID}) NOT NULL
        );

        CREATE TABLE road_links (
            link_id text PRIMARY KEY,
            start_node_id text REFERENCES road_nodes(node_id),
            end_node_id text REFERENCES road_nodes(node_id),
            road_name text,
            road_rank text,
            link_category bigint,
            oneway text,
            lanes integer,
            length_m double precision,
            geom geometry(MultiLineString, {ROAD_SRID}) NOT NULL
        );
        """
    )


def normalize_road_network() -> None:
    run_psql(
        """
        INSERT INTO road_nodes (node_id, node_type, node_name, x, y, geom)
        SELECT
            node_id,
            node_type,
            node_name,
            x,
            y,
            geom
        FROM staging_road_nodes
        WHERE node_id IS NOT NULL
        ON CONFLICT (node_id) DO UPDATE
        SET node_type = EXCLUDED.node_type,
            node_name = EXCLUDED.node_name,
            x = EXCLUDED.x,
            y = EXCLUDED.y,
            geom = EXCLUDED.geom;

        INSERT INTO road_links (
            link_id,
            start_node_id,
            end_node_id,
            road_name,
            road_rank,
            link_category,
            oneway,
            lanes,
            length_m,
            geom
        )
        SELECT
            links.link_id,
            start_nodes.node_id,
            end_nodes.node_id,
            links.road_name,
            links.road_rank,
            links.link_cate::bigint,
            links.oneway,
            links.lanes,
            links.length * 1000.0,
            links.geom
        FROM staging_road_links AS links
        LEFT JOIN road_nodes AS start_nodes
            ON start_nodes.node_id = NULLIF(links.up_from_no, '')
        LEFT JOIN road_nodes AS end_nodes
            ON end_nodes.node_id = NULLIF(links.up_to_node, '')
        WHERE links.link_id IS NOT NULL
        ON CONFLICT (link_id) DO UPDATE
        SET start_node_id = EXCLUDED.start_node_id,
            end_node_id = EXCLUDED.end_node_id,
            road_name = EXCLUDED.road_name,
            road_rank = EXCLUDED.road_rank,
            link_category = EXCLUDED.link_category,
            oneway = EXCLUDED.oneway,
            lanes = EXCLUDED.lanes,
            length_m = EXCLUDED.length_m,
            geom = EXCLUDED.geom;

        CREATE INDEX IF NOT EXISTS idx_road_nodes_geom ON road_nodes USING gist(geom);
        CREATE INDEX IF NOT EXISTS idx_road_links_geom ON road_links USING gist(geom);
        CREATE INDEX IF NOT EXISTS idx_road_links_start_node ON road_links(start_node_id);
        CREATE INDEX IF NOT EXISTS idx_road_links_end_node ON road_links(end_node_id);
        CREATE INDEX IF NOT EXISTS idx_road_links_road_rank ON road_links(road_rank);

        ANALYZE road_nodes;
        ANALYZE road_links;
        """
    )


def main() -> None:
    assert_shapefiles_exist()
    wait_for_database()
    run_psql(ROAD_SRS_SQL)
    run_sql_file(ROOT / "db" / "init" / "002_schema.sql")
    recreate_road_tables()
    load_shapefile(NODES_SHP, "staging_road_nodes")
    load_shapefile(LINKS_SHP, "staging_road_links")
    normalize_road_network()


if __name__ == "__main__":
    main()
