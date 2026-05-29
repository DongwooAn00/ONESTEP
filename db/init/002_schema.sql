CREATE TABLE IF NOT EXISTS zones (
    zone_id integer PRIMARY KEY,
    province_id integer NOT NULL,
    admin_name text NOT NULL,
    province_name text NOT NULL,
    district_name text NOT NULL
);

CREATE TABLE IF NOT EXISTS freight_item_codes (
    item_code text PRIMARY KEY,
    source_item_number integer,
    item_name text NOT NULL,
    major_category text NOT NULL
);

CREATE TABLE IF NOT EXISTS od_by_mode (
    origin_province_id integer NOT NULL,
    destination_province_id integer NOT NULL,
    origin_zone_id integer NOT NULL REFERENCES zones(zone_id),
    destination_zone_id integer NOT NULL REFERENCES zones(zone_id),
    passenger_car integer NOT NULL,
    bus integer NOT NULL,
    subway integer NOT NULL,
    rail integer NOT NULL,
    high_speed_rail integer NOT NULL,
    air integer NOT NULL,
    sea integer NOT NULL,
    total integer NOT NULL,
    PRIMARY KEY (origin_zone_id, destination_zone_id)
);

CREATE TABLE IF NOT EXISTS od_by_purpose (
    origin_province_id integer NOT NULL,
    destination_province_id integer NOT NULL,
    origin_zone_id integer NOT NULL REFERENCES zones(zone_id),
    destination_zone_id integer NOT NULL REFERENCES zones(zone_id),
    commute integer NOT NULL,
    school integer NOT NULL,
    business integer NOT NULL,
    return_home integer NOT NULL,
    other integer NOT NULL,
    total integer NOT NULL,
    PRIMARY KEY (origin_zone_id, destination_zone_id)
);

CREATE TABLE IF NOT EXISTS freight_vehicle_od (
    origin_zone_id integer NOT NULL REFERENCES zones(zone_id),
    origin_province_id integer NOT NULL,
    destination_zone_id integer NOT NULL REFERENCES zones(zone_id),
    destination_province_id integer NOT NULL,
    small_truck double precision NOT NULL,
    medium_truck double precision NOT NULL,
    large_truck double precision NOT NULL,
    total double precision NOT NULL,
    PRIMARY KEY (origin_zone_id, destination_zone_id)
);

CREATE TABLE IF NOT EXISTS freight_tonnage_od (
    origin_zone_id integer NOT NULL REFERENCES zones(zone_id),
    destination_zone_id integer NOT NULL REFERENCES zones(zone_id),
    origin_province_id integer NOT NULL,
    destination_province_id integer NOT NULL,
    item_01 double precision NOT NULL,
    item_02 double precision NOT NULL,
    item_03 double precision NOT NULL,
    item_04 double precision NOT NULL,
    item_05 double precision NOT NULL,
    item_06 double precision NOT NULL,
    item_09 double precision NOT NULL,
    item_10 double precision NOT NULL,
    item_11 double precision NOT NULL,
    item_12 double precision NOT NULL,
    item_13 double precision NOT NULL,
    item_14 double precision NOT NULL,
    item_15 double precision NOT NULL,
    item_16 double precision NOT NULL,
    item_17 double precision NOT NULL,
    item_18 double precision NOT NULL,
    item_19 double precision NOT NULL,
    item_20 double precision NOT NULL,
    item_21 double precision NOT NULL,
    item_22 double precision NOT NULL,
    item_23 double precision NOT NULL,
    item_24 double precision NOT NULL,
    item_25 double precision NOT NULL,
    item_26 double precision NOT NULL,
    item_27 double precision NOT NULL,
    item_28 double precision NOT NULL,
    item_29 double precision NOT NULL,
    item_30 double precision NOT NULL,
    item_31 double precision NOT NULL,
    item_32 double precision NOT NULL,
    container double precision NOT NULL,
    total double precision NOT NULL,
    PRIMARY KEY (origin_zone_id, destination_zone_id)
);

CREATE TABLE IF NOT EXISTS freight_tonnage_od_long (
    origin_zone_id integer NOT NULL REFERENCES zones(zone_id),
    destination_zone_id integer NOT NULL REFERENCES zones(zone_id),
    origin_province_id integer NOT NULL,
    destination_province_id integer NOT NULL,
    item_code text NOT NULL REFERENCES freight_item_codes(item_code),
    tonnage_per_year double precision NOT NULL,
    PRIMARY KEY (origin_zone_id, destination_zone_id, item_code)
);

CREATE TABLE IF NOT EXISTS road_nodes (
    node_id text PRIMARY KEY,
    geom geometry(Point, 5179) NOT NULL
);

CREATE TABLE IF NOT EXISTS road_links (
    link_id text PRIMARY KEY,
    start_node_id text REFERENCES road_nodes(node_id),
    end_node_id text REFERENCES road_nodes(node_id),
    road_name text,
    road_rank text,
    length_m double precision,
    geom geometry(LineString, 5179) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_od_by_mode_origin_zone ON od_by_mode(origin_zone_id);
CREATE INDEX IF NOT EXISTS idx_od_by_mode_destination_zone ON od_by_mode(destination_zone_id);
CREATE INDEX IF NOT EXISTS idx_od_by_purpose_origin_zone ON od_by_purpose(origin_zone_id);
CREATE INDEX IF NOT EXISTS idx_od_by_purpose_destination_zone ON od_by_purpose(destination_zone_id);
CREATE INDEX IF NOT EXISTS idx_freight_vehicle_origin_zone ON freight_vehicle_od(origin_zone_id);
CREATE INDEX IF NOT EXISTS idx_freight_vehicle_destination_zone ON freight_vehicle_od(destination_zone_id);
CREATE INDEX IF NOT EXISTS idx_freight_tonnage_origin_zone ON freight_tonnage_od(origin_zone_id);
CREATE INDEX IF NOT EXISTS idx_freight_tonnage_destination_zone ON freight_tonnage_od(destination_zone_id);
CREATE INDEX IF NOT EXISTS idx_freight_tonnage_long_origin_zone ON freight_tonnage_od_long(origin_zone_id);
CREATE INDEX IF NOT EXISTS idx_freight_tonnage_long_destination_zone ON freight_tonnage_od_long(destination_zone_id);
CREATE INDEX IF NOT EXISTS idx_freight_tonnage_long_item_code ON freight_tonnage_od_long(item_code);
CREATE INDEX IF NOT EXISTS idx_freight_item_codes_major_category ON freight_item_codes(major_category);
CREATE INDEX IF NOT EXISTS idx_road_nodes_geom ON road_nodes USING gist(geom);
CREATE INDEX IF NOT EXISTS idx_road_links_geom ON road_links USING gist(geom);
