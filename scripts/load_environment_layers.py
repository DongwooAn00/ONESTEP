from __future__ import annotations

import argparse
from pathlib import Path

from load_postgis import ROOT, run_psql, wait_for_database


WATER_SHP = ROOT / "data" / "raw" / "water" / "N3L_E0020000.shp"
BUILDING_SHP = ROOT / "data" / "raw" / "building" / "CH_D010_00_20260624.shp"

DEM_SRID = 100002
WATER_SOURCE_SRID = 5179
BUILDING_SOURCE_SRID = 5186
BATCH_SIZE = 10_000

DEM_SRS_SQL = """
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


def _import_shapefile():
    try:
        import shapefile
    except ImportError as error:
        raise RuntimeError(
            "`pyshp`가 필요합니다. `cd backend && python -m venv .venv && "
            ".\\.venv\\Scripts\\python -m pip install -r requirements.txt`를 먼저 실행하세요."
        ) from error
    return shapefile


def _import_psycopg():
    try:
        import psycopg
    except ImportError as error:
        raise RuntimeError(
            "`psycopg`가 필요합니다. `cd backend && .\\.venv\\Scripts\\python -m pip install -r requirements.txt`를 실행하세요."
        ) from error
    return psycopg


def _database_url() -> str:
    return "postgresql://onestep:onestep@localhost:5432/onestep"


def _assert_shapefile(path: Path) -> None:
    missing = [path.with_suffix(suffix) for suffix in (".shp", ".shx", ".dbf", ".prj") if not path.with_suffix(suffix).exists()]
    if missing:
        raise FileNotFoundError("Missing shapefile components: " + ", ".join(str(item) for item in missing))


def _escape(value: object) -> str:
    text = str(value)
    return '"' + text.replace('"', '""') + '"'


def _ring_wkt(points: list[tuple[float, float]]) -> str:
    if not points:
        return ""
    if points[0] != points[-1]:
        points = [*points, points[0]]
    return "(" + ",".join(f"{x} {y}" for x, y in points) + ")"


def _parts(shape) -> list[list[tuple[float, float]]]:
    starts = list(shape.parts) + [len(shape.points)]
    return [
        [(float(x), float(y)) for x, y in shape.points[starts[index] : starts[index + 1]]]
        for index in range(len(starts) - 1)
    ]


def _multiline_wkt(shape) -> str:
    lines = []
    for points in _parts(shape):
        if len(points) >= 2:
            lines.append("(" + ",".join(f"{x} {y}" for x, y in points) + ")")
    return "MULTILINESTRING(" + ",".join(lines) + ")" if lines else ""


def _multipolygon_wkt(shape) -> str:
    rings = [_ring_wkt(points) for points in _parts(shape) if len(points) >= 3]
    return "MULTIPOLYGON(" + ",".join(f"({ring})" for ring in rings if ring) + ")" if rings else ""


def _field_names(reader) -> list[str]:
    return [field[0].lower() for field in reader.fields[1:]]


def _record_dict(field_names: list[str], record) -> dict[str, object]:
    return dict(zip(field_names, list(record)))


def _copy_water() -> None:
    shapefile = _import_shapefile()
    psycopg = _import_psycopg()
    with shapefile.Reader(str(WATER_SHP), encoding="cp949") as reader:
        fields = _field_names(reader)
        with psycopg.connect(_database_url()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DROP TABLE IF EXISTS staging_rivers_raw;
                    CREATE TABLE staging_rivers_raw (
                        source_id text,
                        name text,
                        type text,
                        river_rank text,
                        source_wkt text
                    );
                    """
                )
                with cursor.copy(
                    "COPY staging_rivers_raw (source_id, name, type, river_rank, source_wkt) FROM STDIN"
                ) as copy:
                    for shape_record in reader.iterShapeRecords():
                        row = _record_dict(fields, shape_record.record)
                        wkt = _multiline_wkt(shape_record.shape)
                        if not wkt:
                            continue
                        copy.write_row(
                            [
                                row.get("ufid"),
                                row.get("name"),
                                row.get("type"),
                                row.get("scls"),
                                wkt,
                            ]
                        )
            connection.commit()


def _copy_buildings() -> None:
    shapefile = _import_shapefile()
    psycopg = _import_psycopg()
    with shapefile.Reader(str(BUILDING_SHP), encoding="cp949") as reader:
        fields = _field_names(reader)
        with psycopg.connect(_database_url()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DROP TABLE IF EXISTS staging_buildings_raw;
                    CREATE TABLE staging_buildings_raw (
                        source_id text,
                        name text,
                        area_type text,
                        source_wkt text
                    );
                    """
                )
                with cursor.copy(
                    "COPY staging_buildings_raw (source_id, name, area_type, source_wkt) FROM STDIN"
                ) as copy:
                    for shape_record in reader.iterShapeRecords():
                        row = _record_dict(fields, shape_record.record)
                        wkt = _multipolygon_wkt(shape_record.shape)
                        if not wkt:
                            continue
                        copy.write_row([row.get("a0"), row.get("a4"), "building", wkt])
            connection.commit()


def _normalize_water_layer() -> None:
    run_psql(
        f"""
        DROP TABLE IF EXISTS rivers;
        CREATE TABLE rivers AS
        SELECT
            source_id,
            NULLIF(name, '') AS name,
            NULLIF(type, '') AS type,
            NULLIF(river_rank, '') AS river_rank,
            ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromText(source_wkt), {WATER_SOURCE_SRID}), {DEM_SRID}))
                ::geometry(MultiLineString, {DEM_SRID}) AS geom
        FROM staging_rivers_raw
        WHERE source_wkt IS NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_rivers_geom ON rivers USING gist(geom);
        CREATE INDEX IF NOT EXISTS idx_rivers_type ON rivers(type);

        ANALYZE rivers;
        """
    )


def _normalize_building_layers() -> None:
    run_psql(
        f"""
        DROP TABLE IF EXISTS building_footprints;
        CREATE TABLE building_footprints AS
        SELECT
            source_id,
            NULLIF(name, '') AS name,
            area_type,
            ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromText(source_wkt), {BUILDING_SOURCE_SRID}), {DEM_SRID}))
                ::geometry(MultiPolygon, {DEM_SRID}) AS geom
        FROM staging_buildings_raw
        WHERE source_wkt IS NOT NULL;

        DROP TABLE IF EXISTS builtup_areas;
        CREATE TABLE builtup_areas AS
        SELECT source_id, name, area_type, geom
        FROM building_footprints;

        CREATE INDEX IF NOT EXISTS idx_building_footprints_geom ON building_footprints USING gist(geom);
        CREATE INDEX IF NOT EXISTS idx_builtup_areas_geom ON builtup_areas USING gist(geom);

        ANALYZE building_footprints;
        ANALYZE builtup_areas;
        """
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Load environmental GIS layers into PostGIS.")
    parser.add_argument(
        "--include-water",
        action="store_true",
        help="Also load the full waterway layer. This can be slow because the raw water file has millions of records.",
    )
    args = parser.parse_args()

    _assert_shapefile(BUILDING_SHP)
    if args.include_water:
        _assert_shapefile(WATER_SHP)

    wait_for_database()
    run_psql(DEM_SRS_SQL)
    if args.include_water:
        _copy_water()
    _copy_buildings()
    if args.include_water:
        _normalize_water_layer()
    _normalize_building_layers()


if __name__ == "__main__":
    main()
