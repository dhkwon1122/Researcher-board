"""
3단계 파이프라인(DRM 제거 → DB 스테이징 → 후처리)의 원천 파일 매니페스트.

각 항목: (스테이징명, data/raw/ 안의 원본 xlsx 파일명, 헤더 행 인덱스 0-based)

이 매니페스트를 세 곳에서 공유한다:
  - xlsx_to_raw_csv.py (1단계, Windows) : 원본 xlsx를 전 컬럼 그대로 DRM-free CSV로 변환
  - load_raw_to_db.py  (2단계, Linux)  : raw CSV를 Postgres `{name}_stg` 테이블로 적재
  - source_reader.py   (3단계)         : process_*.py가 read_source(name)으로 원천 조회

새 원천 파일을 추가하려면 이 목록에 한 줄만 추가하면 된다(header_row는 실제
헤더가 몇 번째 행인지 — 인력현황은 1(2번째 행), 개인별논문현황은 2(3번째 행),
나머지는 0). 원본 파일의 실제 헤더 위치와 다르면 첫 데이터 행이 컬럼명으로
잘못 들어가므로, 새 파일을 열어볼 수 있으면 반드시 실제 헤더 행을 확인할 것.

※ 전용 처리기가 없는 4개 테이블(technology_transfer/transfers/certifications/
  succession)은 원본 파일이 이미 최종 스키마 컬럼명으로 준비되므로 이 매니페스트에
  포함하지 않는다 — run_pipeline.py의 기존 `{table}_raw.xlsx/csv` 통과 로직을 그대로 사용한다.
"""

SOURCES = [
    ('researchers', '인력현황.xlsx', 1),  # 첫 행은 헤더가 아님 — 실제 헤더는 2번째 행
    ('evaluations', 'T&P_기본_인사_정보.xlsx', 0),
    ('patents', '특허 리스트.xlsx', 0),
    ('nurturing', '양성_인력_현황.xlsx', 0),
    ('awards', '시상 세부사항.xlsx', 0),
    ('education', '임직원_학력.xlsx', 0),
    ('leadership', '리더십진단.xlsx', 0),
    ('incentive_selection', '핵심이력.xlsx', 0),
    ('publications', '개인별논문현황_2016_2026.xlsx', 2),
    ('comments', 'comments_raw.xlsx', 0),
]
