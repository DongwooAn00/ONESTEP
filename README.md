# ONESTEP

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

## 데이터 전처리

CSV 전처리:

```bash
python3 scripts/preprocess_csv.py
```

도로망 Shapefile 추출:

```bash
python3 scripts/extract_road_shapefiles.py
```
