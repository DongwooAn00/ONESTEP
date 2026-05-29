from app.services.route_cost import SamplePoint, classify_profile


def test_classify_profile_promotes_long_steep_run_to_tunnel():
    samples = [
        SamplePoint(x=0, y=0, lon=0, lat=0, elevation_m=0),
        SamplePoint(x=100, y=0, lon=0, lat=0, elevation_m=20),
        SamplePoint(x=200, y=0, lon=0, lat=0, elevation_m=40),
        SamplePoint(x=300, y=0, lon=0, lat=0, elevation_m=60),
        SamplePoint(x=400, y=0, lon=0, lat=0, elevation_m=80),
    ]

    segments = classify_profile(samples)

    assert {segment.segment_type for segment in segments} == {"tunnel"}


def test_classify_profile_downgrades_short_steep_run_to_steep_road():
    samples = [
        SamplePoint(x=0, y=0, lon=0, lat=0, elevation_m=0),
        SamplePoint(x=100, y=0, lon=0, lat=0, elevation_m=20),
        SamplePoint(x=200, y=0, lon=0, lat=0, elevation_m=40),
    ]

    segments = classify_profile(samples)

    assert {segment.segment_type for segment in segments} == {"steep_road"}
