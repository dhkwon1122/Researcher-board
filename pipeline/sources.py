"""
3단계 파이프라인(DRM 제거 → DB 스테이징 → 후처리)의 원천 파일 매니페스트.

각 항목: (스테이징명, data/raw/ 안의 원본 xlsx 파일명, 헤더 행 인덱스 0-based)

이 매니페스트를 세 곳에서 공유한다:
  - xlsx_to_raw_csv.py (1단계, Windows) : 원본 xlsx를 전 컬럼 그대로 DRM-free CSV로 변환
  - load_raw_to_db.py  (2단계, Linux)  : raw CSV를 Postgres `{name}_stg` 테이블로 적재
  - source_reader.py   (3단계)         : process_*.py가 read_source(name)으로 원천 조회

새 원천 파일을 추가하려면 이 목록에 한 줄만 추가하면 된다(header_row는 실제
헤더가 몇 번째 행인지 — 파일마다 다르니 아래 SOURCES 값을 확인할 것).
원본 파일의 실제 헤더 위치와 다르면 첫 데이터 행이 컬럼명으로 잘못 들어가므로,
새 파일을 열어볼 수 있으면 반드시 실제 헤더 행을 확인할 것.
(comments_raw.xlsx는 현재 실존하는 원본이 없음 — 부서장 코멘트는 아직 별도
 DRM 소스가 없어 리더십진단의 강점/개선점만 실데이터이고 나머지는 생성 데이터.
 원본이 없어도 1·3단계 모두 [SKIP]으로 안전하게 넘어가며 리더십진단 코멘트는
 별도 경로로 정상 병합된다. 추후 실제 파일이 생기면 header_row 확인 필요.)

※ 전용 처리기가 없는 4개 테이블(technology_transfer/transfers/certifications/
  succession)은 원본 파일이 이미 최종 스키마 컬럼명으로 준비되므로 이 매니페스트에
  포함하지 않는다 — run_pipeline.py의 기존 `{table}_raw.xlsx/csv` 통과 로직을 그대로 사용한다.
"""

SOURCES = [
    ('researchers', '인력현황.xlsx', 0),               # 1번째 행
    ('evaluations', 'T&P_기본_인사_정보.xlsx', 0),      # 1번째 행
    ('patents', '특허 리스트.xlsx', 0),                 # 1번째 행
    ('nurturing', '양성_인력_현황.xlsx', 0),            # 1번째 행
    ('awards', '시상 세부사항.xlsx', 0),                # 1번째 행
    ('education', '임직원_학력.xlsx', 0),               # 1번째 행
    ('leadership', '리더십진단.xlsx', 0),               # 1번째 행
    ('incentive_selection', '핵심이력.xlsx', 0),        # 1번째 행
    ('publications', '개인별논문현황_2016_2026.xlsx', 0),  # 1번째 행
    ('comments', 'comments_raw.xlsx', 0),               # 원본 없음 — 없으면 [SKIP]

    # ── 이후 추가된 기능의 원천 파일 (모두 DRM 걸림) ──────────────────────────
    ('hr_orders', '인사발령이력.xlsx', 0),               # 1번째 행
    ('tasks_information', '과제정보.xlsx', 0),           # 1번째 행
    ('core_technology', '핵심기술.xlsx', 0),             # 1번째 행
    ('tech_ownership', '보유기술.xlsx', 0),              # 1번째 행
    ('job_profile', '임직원_직무이력.xlsx', 0),          # 1번째 행
    ('work_objective_24', '업무목표24.xlsx', 0),         # 1번째 행
    ('work_objective_25', '업무목표25.xlsx', 0),         # 1번째 행
    ('work_objective_26', '업무목표26.xlsx', 0),         # 1번째 행
    ('tasks', '개인별과제투입기간데이터_260114.xlsb', 0),  # 1번째 행 (xlsb)
    ('project_confl_address', '과제별컨플.xlsx', 0),     # 1번째 행
    ('job_profile_info_standard', '직무정보_표준.xlsx', 0),  # 1번째 행
    ('job_profile_info_sait', '직무정보_부서.xlsx', 0),  # 1번째 행
]
