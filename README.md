# ONESTEP

See `docs/geotechnical-tunnel-decision.md` for the MVP tunnel decision update:
overburden, estimated_rock_class, road grade, and cost comparison are now used
when available, while the previous slope/local-relief fallback remains active.

도로 터널 건설 사업의 경제성을 분석하는 웹 서비스입니다.

## 기술 스택

- 프론트엔드: React + Vite
- 백엔드: FastAPI
- 초기 계산 지표: B/C, NPV

## 프로젝트 구조

```text
onestep/
  frontend/          # React + Vite 앱
  backend/           # FastAPI API 서버
  docs/              # 요구사항과 계산 기준 문서
```

## 프론트엔드 실행

```bash
cd frontend
npm install
npm run dev
```

기본 주소는 `http://localhost:5173`입니다.

## 백엔드 실행

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

기본 주소는 `http://localhost:8000`입니다.

## 로컬 DB 실행

다음 과정을 진행하면 이미 전처리된 파일들을 로컬 DB에 적재할 수 있습니다.

```bash
docker compose up -d
python3 scripts/load_postgis.py
python3 scripts/load_road_network.py
python3 scripts/load_dem.py
python3 scripts/load_admin_dong_od.py
python3 scripts/load_geology.py
```
## 기존 방식

PostgreSQL + PostGIS를 Docker로 실행합니다.

```bash
docker compose up -d
```

기본 접속 정보는 다음과 같습니다.

```text
host: localhost
port: 5432
database: onestep
user: onestep
password: onestep
```

애플리케이션에서는 아래 환경변수 형식을 사용합니다.

```bash
DATABASE_URL=postgresql://onestep:onestep@localhost:5432/onestep
```

CSV 전처리 결과를 DB에 적재합니다.

```bash
python3 scripts/preprocess_csv.py
python3 scripts/load_postgis.py
```

도로망 Shapefile을 DB에 적재합니다.

```bash
python3 scripts/extract_road_shapefiles.py
python3 scripts/load_road_network.py
```

DEM 래스터를 DB에 적재합니다.

```bash
python3 scripts/load_dem.py
```

수치지질도 Shapefile을 DB에 적재합니다.

```bash
python3 scripts/load_geology.py
```

DB를 종료하려면 다음을 실행합니다.

```bash
docker compose down
```

DB 데이터를 완전히 초기화하려면 볼륨까지 삭제합니다.

```bash
docker compose down -v
docker compose up -d
python3 scripts/load_postgis.py
```

GDAL을 사용하는 DEM/도로망 분석 기능은 로컬 GDAL 설치가 필요합니다.

```bash
brew install gdal
```

## API

- `GET /health`
- `POST /api/analysis`
- `POST /api/route-cost`

## 법정동 평균 공시지가

`data/processed/csv`에 법정동 코드 CSV를 두고, 프로젝트 루트의 `.env`에
`VWORLD_API_KEY`, `VWORLD_DOMAIN`을 설정합니다. 실제 키가 들어간 `.env`는
Git에 포함하지 않습니다.

```python
from app.services.vworld_land_price import fetch_land_price_summary_by_legal_dong

summary = fetch_land_price_summary_by_legal_dong(
    stdr_year=2022,
    req_lvl=3,
    legal_dong_code="4793025021",
)
price = summary["weighted_average_price_krw_per_sqm"]
```

`legal_dong_code` 대신 CSV의 전체 `legal_dong_name`을 정확히 입력해도 됩니다.

## 행정구역 선택 기반 후보 계산

후보 생성 화면에서 기본값인 `전체 사용`을 해제하면 여러 시도와 경계 여유
거리(기본 10km)를 선택할 수 있습니다. 선택 구역이 없거나 필터가 꺼져 있으면
기존 전체 범위 계산을 그대로 사용합니다.

OD 후보 API는 multipart form의 `selected_regions`, `use_region_filter`,
`region_buffer_km`를 받고, 후보 노선 API는 동일한 이름의 JSON 필드를 받습니다.

```json
{
  "selected_regions": ["서울특별시", "경기도"],
  "use_region_filter": true,
  "region_buffer_km": 10
}
```

응답의 `stats.region_filter_summary` 또는 `region_filter_summary`에서 필터 전후
OD·후보 노드·도로망 크기, DEM 격자 셀 수, A* 호출 수와 실행 시간을 확인할 수
있습니다. 현재 MVP 경계는 `backend/app/config/regions.py`의 WGS84 bounding
box이며 추후 행정구역 polygon으로 교체할 수 있습니다.

## 데이터 전처리

CSV 전처리:

```bash
python3 scripts/preprocess_csv.py
```

도로망 Shapefile 추출:

```bash
python3 scripts/extract_road_shapefiles.py
```

## 개발 문서

- `docs/route-generation-guide.md`: 후보 도로 생성 파트 구현 가이드
- `docs/route-contract.md`: 후보 생성/평가 API 입출력 규약
- `docs/route-cost-pipeline.md`: 후보 생성 이후 평가 파이프라인
