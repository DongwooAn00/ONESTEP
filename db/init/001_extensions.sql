CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_raster;

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
