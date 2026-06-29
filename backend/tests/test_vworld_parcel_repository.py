from shapely.geometry import LineString

from app.services.vworld_parcel_repository import VWorldParcelRepository, _transformers


def test_vworld_repository_maps_wfs_geometry_pnu_category_and_price(monkeypatch):
    repository = VWorldParcelRepository(
        api_key="test-key",
        domain="http://localhost:5173",
        tile_size_m=2_000,
    )
    calls = []

    def fake_request(bbox, *, start_index):
        calls.append((bbox, start_index))
        return {
            "type": "FeatureCollection",
            "totalFeatures": 1,
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "pnu": "5111010400100730000",
                        "jibun": "73 대",
                        "jiga": "2624000",
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [127.7290, 37.8810],
                            [127.7300, 37.8810],
                            [127.7300, 37.8820],
                            [127.7290, 37.8820],
                            [127.7290, 37.8810],
                        ]],
                    },
                }
            ],
        }

    monkeypatch.setattr(repository, "_request_page", fake_request)
    wgs84_to_dem, _ = _transformers()
    start = wgs84_to_dem.transform(127.7292, 37.8814)
    end = wgs84_to_dem.transform(127.7298, 37.8816)
    route = LineString([start, end])

    parcels = repository.get_intersected_parcels(route, 20)
    first_call_count = len(calls)
    cached = repository.get_intersected_parcels(route, 20)

    assert len(parcels) == 1
    assert cached[0].pnu == "5111010400100730000"
    assert parcels[0].land_category_raw == "대"
    assert parcels[0].official_price_per_m2 == 2_624_000.0
    assert first_call_count >= 1
    assert len(calls) == first_call_count
