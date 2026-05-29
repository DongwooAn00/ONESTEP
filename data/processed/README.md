# 전처리 데이터

`scripts/preprocess_csv.py` 실행 결과가 `data/processed/csv`에 생성됩니다.

## 생성 파일

- `zones.csv`: 존 코드와 행정구역명 기준 테이블
- `od_by_mode.csv`: 수단별 여객 O/D
- `od_by_purpose.csv`: 목적별 여객 O/D
- `freight_vehicle_od.csv`: 화물자동차 O/D, 단위 대/일
- `freight_tonnage_od.csv`: 화물물동량 O/D, 단위 톤/년, wide 형식
- `freight_tonnage_od_long.csv`: 화물물동량 O/D, 품목별 long 형식

## 주요 전처리 규칙

- 원본 파일은 `data/raw`에 그대로 보존합니다.
- 빈 컬럼을 제거합니다.
- 설명행이 있는 화물 O/D 파일은 실제 헤더부터 사용합니다.
- 쉼표와 공백이 포함된 숫자 문자열을 숫자형으로 변환합니다.
- 중복 컬럼명 `대존O_17`은 출발/도착 대존 컬럼으로 분리합니다.
- DB 적재와 집계를 쉽게 하기 위해 화물물동량은 wide 형식과 long 형식을 함께 생성합니다.

## 검증 메모

- `od_by_mode.csv`, `od_by_purpose.csv`는 원본 합계와 세부 항목 합계 사이에 최대 2 수준의 차이가 있습니다. 원본의 반올림 또는 집계 처리 차이로 보고 원본 합계를 유지합니다.
- `freight_vehicle_od.csv`는 세부 차종 합계와 `total`이 일치합니다.
- `freight_tonnage_od.csv`의 `total`은 `container`를 포함한 단순 합계로 보이지 않는 행이 있습니다. 따라서 `total`과 `container`는 모두 원본 값을 보존하고, 품목 합산 검증에서는 별도 해석이 필요합니다.
