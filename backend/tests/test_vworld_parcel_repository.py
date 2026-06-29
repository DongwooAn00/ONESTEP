from shapely.geometry import LineString

from app.services.vworld_parcel_repository import (
    VWORLD_PARCEL_LAYER,
    VWorldParcelRepository,
    _transformers,
)


def _feature(
    pnu: str,
    *,
    price: str,
    year: str = "2025",
    month: str = "01",
    min_lon: float = 127.7290,
    min_lat: float = 37.8810,
):
    return {
        "type": "Feature",
        "properties": {
            "pnu": pnu,
            "jibun": "73 대",
            "jiga": price,
            "gosi_year": year,
            "gosi_month": month,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [min_lon, min_lat],
                [min_lon + 0.001, min_lat],
                [min_lon + 0.001, min_lat + 0.001],
                [min_lon, min_lat + 0.001],
                [min_lon, min_lat],
            ]],
        },
    }


def _route():
    wgs84_to_dem, _ = _transformers()
    start = wgs84_to_dem.transform(127.7292, 37.8814)
    end = wgs84_to_dem.transform(127.7298, 37.8816)
    return LineString([start, end])


def test_vworld_repository_maps_wfs_geometry_pnu_category_and_price(monkeypatch):
    repository = VWorldParcelRepository(
        api_key="test-key",
        domain="http://localhost:5173",
        tile_size_m=2_000,
    )
    calls = []

    def fake_request(bbox):
        calls.append(bbox)
        return {
            "type": "FeatureCollection",
            "totalFeatures": 1,
            "features": [_feature("5111010400100730000", price="2624000")],
        }

    monkeypatch.setattr(repository, "_request_bbox", fake_request)

    parcels = repository.get_intersected_parcels(_route(), 20)
    first_call_count = len(calls)
    cached = repository.get_intersected_parcels(_route(), 20)

    assert len(parcels) == 1
    assert cached[0].pnu == "5111010400100730000"
    assert parcels[0].land_category_raw == "대"
    assert parcels[0].official_price_per_m2 == 2_624_000.0
    assert first_call_count >= 1
    assert len(calls) == first_call_count


def test_vworld_repository_uses_price_layer_only():
    assert VWORLD_PARCEL_LAYER == "lp_pa_cbnd_bubun"


def test_vworld_repository_spatially_subdivides_and_keeps_latest_price(monkeypatch):
    repository = VWorldParcelRepository(
        api_key="test-key",
        domain="http://localhost:5173",
        tile_size_m=2_000,
        max_features=2,
        max_split_depth=2,
    )
    calls = []
    old = _feature("5111010400100730000", price="1000000", year="2024")
    latest = _feature("5111010400100730000", price="2624000", year="2025")

    def fake_request(bbox):
        calls.append(bbox)
        if len(calls) == 1:
            return {
                "type": "FeatureCollection",
                "totalFeatures": 3,
                "features": [old, _feature("5111010400100740000", price="500000")],
            }
        return {
            "type": "FeatureCollection",
            "totalFeatures": 1 if len(calls) in (2, 3) else 0,
            "features": [latest] if len(calls) == 2 else (
                [old] if len(calls) == 3 else []
            ),
        }

    monkeypatch.setattr(repository, "_request_bbox", fake_request)

    parcels = repository.get_intersected_parcels(_route(), 20)

    assert len(calls) == 5
    assert len(parcels) == 1
    assert parcels[0].pnu == "5111010400100730000"
    assert parcels[0].official_price_per_m2 == 2_624_000.0
