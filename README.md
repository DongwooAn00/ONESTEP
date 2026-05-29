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
