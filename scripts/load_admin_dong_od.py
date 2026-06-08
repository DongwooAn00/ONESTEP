from __future__ import annotations

from pathlib import Path

from load_postgis import CONTAINER_CSV_DIR, CSV_DIR, run_psql, wait_for_database


TABLES = [
    ("admin_dongs", "admin_dongs.csv"),
    ("admin_dong_od_by_mode", "synthetic_admin_dong_od_by_mode.csv"),
]

TABLE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS admin_dongs (
    admin_dong_code text PRIMARY KEY,
    province_id integer NOT NULL,
    zone_id integer NOT NULL REFERENCES zones(zone_id),
    province_name text NOT NULL,
    district_name text NOT NULL,
    dong_name text NOT NULL,
    population integer NOT NULL,
    population_source text NOT NULL,
    origin_weight double precision NOT NULL,
    destination_weight double precision NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_dong_od_by_mode (
    origin_province_id integer NOT NULL,
    destination_province_id integer NOT NULL,
    origin_zone_id integer NOT NULL REFERENCES zones(zone_id),
    destination_zone_id integer NOT NULL REFERENCES zones(zone_id),
    origin_admin_dong_code text NOT NULL REFERENCES admin_dongs(admin_dong_code),
    destination_admin_dong_code text NOT NULL REFERENCES admin_dongs(admin_dong_code),
    passenger_car integer NOT NULL,
    bus integer NOT NULL,
    subway integer NOT NULL,
    rail integer NOT NULL,
    high_speed_rail integer NOT NULL,
    air integer NOT NULL,
    sea integer NOT NULL,
    total integer NOT NULL,
    data_source text NOT NULL,
    PRIMARY KEY (origin_admin_dong_code, destination_admin_dong_code)
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_admin_dongs_zone ON admin_dongs(zone_id);
CREATE INDEX IF NOT EXISTS idx_admin_dongs_province ON admin_dongs(province_id);
CREATE INDEX IF NOT EXISTS idx_admin_dong_od_origin ON admin_dong_od_by_mode(origin_admin_dong_code);
CREATE INDEX IF NOT EXISTS idx_admin_dong_od_destination ON admin_dong_od_by_mode(destination_admin_dong_code);
CREATE INDEX IF NOT EXISTS idx_admin_dong_od_origin_zone ON admin_dong_od_by_mode(origin_zone_id);
CREATE INDEX IF NOT EXISTS idx_admin_dong_od_destination_zone ON admin_dong_od_by_mode(destination_zone_id);
CREATE INDEX IF NOT EXISTS idx_admin_dong_od_data_source ON admin_dong_od_by_mode(data_source);
"""

DROP_INDEX_SQL = """
DROP INDEX IF EXISTS idx_admin_dongs_zone;
DROP INDEX IF EXISTS idx_admin_dongs_province;
DROP INDEX IF EXISTS idx_admin_dong_od_origin;
DROP INDEX IF EXISTS idx_admin_dong_od_destination;
DROP INDEX IF EXISTS idx_admin_dong_od_origin_zone;
DROP INDEX IF EXISTS idx_admin_dong_od_destination_zone;
DROP INDEX IF EXISTS idx_admin_dong_od_data_source;
"""


def assert_csv_files_exist() -> None:
    missing_files = [filename for _, filename in TABLES if not (CSV_DIR / filename).exists()]
    if missing_files:
        joined_files = ", ".join(missing_files)
        raise FileNotFoundError(f"CSV 파일이 없습니다: {joined_files}. processed CSV를 먼저 배치하세요.")


def main() -> None:
    assert_csv_files_exist()
    wait_for_database()
    run_psql(TABLE_SCHEMA_SQL)
    run_psql(DROP_INDEX_SQL)
    run_psql(
        """
        TRUNCATE
            admin_dong_od_by_mode,
            admin_dongs
        RESTART IDENTITY CASCADE;
        """
    )

    for table_name, filename in TABLES:
        csv_path = Path(CONTAINER_CSV_DIR / filename)
        run_psql(f"\\copy {table_name} FROM '{csv_path}' WITH (FORMAT csv, HEADER true)")

    run_psql(INDEX_SQL)


if __name__ == "__main__":
    main()
