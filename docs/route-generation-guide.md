# 후보 도로 생성 개발 가이드

이 문서는 사용자가 입력한 출발/도착 지점으로부터 후보 도로를 산출하는 파트를 구현하기 위한 안내서다.

## 담당 범위

팀원이 주로 수정할 파일은 다음이다.

```text
backend/app/services/route_generation.py
```

핵심 함수는 다음이다.

```python
def generate_route_candidates(payload: RouteGenerationRequest) -> RouteGenerationResult:
```

이 함수는 출발/도착 좌표를 받아 후보 노선 좌표 배열을 반환한다. 후보 평가, DEM 고도 조회, 경사도 계산, 공사비 산정은 이 함수 밖에서 처리한다.

## 전체 흐름

```text
프론트엔드 지점 입력
→ POST /api/generate-route
→ backend/app/api/routes.py
→ backend/app/services/route_generation.py
→ 후보 좌표 배열 반환
```

`POST /api/route-cost`도 내부에서 같은 후보 생성 함수를 호출한다.

```text
POST /api/route-cost
→ generate_route_candidates()
→ evaluate_route_candidate()
→ DEM 고도, 경사도, 터널 구간, 비용 계산
```

따라서 `generate_route_candidates()`를 개선하면 `generate-route`와 `route-cost` 양쪽에 반영된다.

## 입출력 규약

입력 타입은 `RouteGenerationRequest`다.

```python
payload.start_lat
payload.start_lon
payload.end_lat
payload.end_lon
payload.candidate_count
```

반환 타입은 `RouteGenerationResult`다.

```python
return RouteGenerationResult(
    candidates=[
        GeneratedRouteCandidate(
            name="candidate_1",
            coordinates=[
                Coordinate(lat=37.1, lon=127.1),
                Coordinate(lat=37.2, lon=127.2),
            ],
        )
    ]
)
```

규칙:

- 좌표는 WGS84 위도/경도다.
- `lat`는 위도, `lon`은 경도다.
- 후보는 최소 2개 이상의 좌표를 가져야 한다.
- `candidate_count`보다 많은 후보를 반환하지 않는 것을 권장한다.
- 후보 이름은 서로 구분 가능해야 한다.

## 도로망 DB 헬퍼

도로망 조회 코드는 다음 파일에 분리되어 있다.

```text
backend/app/services/road_network.py
```

후보 생성 로직에서는 SQL을 직접 작성하기보다 이 헬퍼를 먼저 사용한다.

### 가까운 도로 노드 찾기

```python
from app.services.road_network import nearest_road_node

start_access = nearest_road_node(payload.start_lat, payload.start_lon)
end_access = nearest_road_node(payload.end_lat, payload.end_lon)
```

반환값:

```python
start_access.node_id
start_access.distance_m
start_access.coordinate.lat
start_access.coordinate.lon
```

### 주변 도로 링크 찾기

```python
from app.services.road_network import nearby_road_links

links = nearby_road_links(payload.start_lat, payload.start_lon, radius_m=2000, limit=100)
```

반환되는 각 링크:

```python
link.link_id
link.start_node_id
link.end_node_id
link.road_name
link.road_rank
link.length_m
link.coordinates
```

`link.coordinates`는 WGS84 좌표 배열이다.

### 특정 노드에 연결된 링크 찾기

```python
from app.services.road_network import links_connected_to_node

links = links_connected_to_node(start_access.node_id, limit=100)
```

## 현재 구현 상태

현재 `route_generation.py`는 임시 MVP 로직이다.

```text
1. 입력 좌표에서 가장 가까운 도로 노드를 찾는다.
2. 시작/끝 도로 접속점을 기준으로 후보를 만든다.
3. straight, left_bypass, right_bypass 3개를 반환한다.
```

즉 현재는 실제 도로망 최단경로나 우회 경로를 탐색하지 않는다. 팀원은 이 임시 로직을 교체하면 된다.

## 추천 구현 방향

1차 목표는 너무 복잡하게 가지 말고 다음 순서를 권장한다.

1. `nearest_road_node()`로 출발/도착 접속 노드를 찾는다.
2. `links_connected_to_node()`로 접속 노드 주변 링크를 확인한다.
3. `road_links`의 `start_node_id`, `end_node_id`, `length_m`를 그래프로 본다.
4. Dijkstra 또는 A*로 기존 도로망 상의 경로를 1개 찾는다.
5. 그 경로 좌표를 `GeneratedRouteCandidate`로 반환한다.
6. 이후 조건을 달리해서 2~3개 후보를 만든다.

후보를 여러 개 만드는 방법 예시:

- 최단 거리 후보
- 간선 일부를 제외한 우회 후보
- `road_rank`가 높은 도로를 선호하는 후보
- 터널/급경사 평가 결과를 보고 비용이 큰 후보를 제외한 재탐색

## 주의할 점

- `route_generation.py`에서는 비용 계산을 하지 않는다.
- DEM 고도 조회도 직접 하지 않는 것을 권장한다.
- 후보 생성 함수는 좌표 배열만 반환한다.
- 반환 좌표가 너무 촘촘하면 응답이 커지고 평가 시간이 늘어난다.
- 반환 좌표가 너무 성기면 경로 형태가 부정확해진다.
- 도로망 좌표계는 DB 내부에서 처리하고, 서비스 반환값은 항상 WGS84로 유지한다.

## 로컬 실행 전제

DB가 먼저 준비되어 있어야 한다.

```bash
docker compose up -d
python3 scripts/load_postgis.py
python3 scripts/load_road_network.py
python3 scripts/load_dem.py
```

백엔드는 다음 DB를 사용한다.

```bash
DATABASE_URL=postgresql://onestep:onestep@localhost:5432/onestep
```

## 빠른 동작 확인

후보 생성 함수를 직접 호출한다.

```bash
PYTHONPATH=backend backend/.venv/bin/python - <<'PY'
from app.schemas.route_generation import RouteGenerationRequest
from app.services.route_generation import generate_route_candidates

result = generate_route_candidates(
    RouteGenerationRequest(
        start_lat=37.5665,
        start_lon=126.9780,
        end_lat=37.5796,
        end_lon=126.9770,
    )
)

for candidate in result.candidates:
    print(candidate.name, len(candidate.coordinates))
PY
```

API로 확인한다.

```bash
curl -X POST http://localhost:8000/api/generate-route \
  -H 'Content-Type: application/json' \
  -d '{
    "start_lat": 37.5665,
    "start_lon": 126.9780,
    "end_lat": 37.5796,
    "end_lon": 126.9770,
    "candidate_count": 3
  }'
```

## AI에게 작업을 맡길 때 줄 프롬프트 예시

```text
ONESTEP 프로젝트에서 후보 도로 생성 로직을 구현하려고 한다.

수정 대상은 backend/app/services/route_generation.py다.
DB 도로망 조회는 backend/app/services/road_network.py의 헬퍼를 사용한다.
generate_route_candidates(payload)는 RouteGenerationResult를 반환해야 한다.
좌표는 항상 WGS84 lat/lon으로 반환한다.
비용 계산, DEM 고도 평가, 터널 판정은 route_generation.py에서 하지 않는다.

우선 nearest_road_node로 출발/도착 노드를 찾고,
road_links의 start_node_id/end_node_id/length_m를 이용해 최단 경로 후보 1개를 만들고,
가능하면 우회 후보 2개를 추가해줘.
기존 API 응답 형식은 바꾸지 마라.
```

## 관련 문서

- `docs/route-contract.md`: API 입출력 규약
- `docs/route-cost-pipeline.md`: 후보 생성 이후 평가 파이프라인
