"""
전체 데이터 파이프라인 실행 스크립트

사용법:
  python pipeline/run_pipeline.py

── 원천 파일 위치: data/raw/ ────────────────────────────────────────────────

[평가 데이터] ★ T&P 파일에서 자동 추출 (별도 raw 파일 불필요)
  T&P_기본_인사_정보.xlsx
    → '2024 연봉등급', '2025 연봉등급', '2026 연봉등급' 컬럼 사용
    → 등급 체계: 가/나/다/라/마
    ※ 처리기: pipeline/process_tp_evaluation.py
       (사번 컬럼명 등 설정은 해당 파일 상단에서 변경)

[그 외 데이터] 아래 이름으로 xlsx 또는 csv 파일 준비
  researchers_raw     : researcher_id, name, gender, department, org_code,
                        position, hire_year, birth_year
  incentive_raw       : researcher_id, year, selected, category, note
  awards_raw          : researcher_id, award_date, award_type, award_name,
                        awarding_org, description
                        ※ '시상 세부사항.xlsx' 가 있으면 자동 추출 (별도 raw 불필요)
                           처리기: pipeline/process_awards.py
  publications_raw    : researcher_id, title, journal, pub_year,
                        impact_factor, citation_count, is_corresponding
                        ※ '개인별논문현황_2016_2026.xlsx' 가 있으면 자동 추출 (별도 raw 불필요)
                           처리기: pipeline/process_publications.py
  patents_raw         : researcher_id, application_id, title, title_ko, status,
                        share_ratio, is_lead_inventor, patent_grade, patent_grade_a_sub,
                        application_no, application_date, registration_no,
                        registration_date, country
                        ※ '특허 리스트.xlsx' 가 있으면 자동 추출 (별도 raw 불필요)
                           처리기: pipeline/process_patents.py
  hr_orders_raw       : researcher_id, order_date, order_name, order_dep, order_cl
                        ※ '인사발령이력.xlsx' 가 있으면 자동 추출 (별도 raw 불필요)
                           처리기: pipeline/process_personnel_orders.py
  tasks_information_raw : task_name, task_code, task_collabo, task_goal, task_value,
                        task_howtoget, task_expectissue, task_Activityplan,
                        task_futureusage, write_date
                        ※ '과제정보.xlsx' 가 있으면 자동 추출 (별도 raw 불필요)
                           처리기: pipeline/process_task_information.py
  technology_transfer_raw : researcher_id, transfer_date, tech_name,
                            recipient, amount, transfer_type
  transfers_raw       : researcher_id, date, type, description
  leadership_raw      : researcher_id, year, evaluator_group,
                        미래통찰, 성과창출, 몰입촉진, 인재육성, 자기관리, 저해행동
                        ※ '리더십진단.xlsx' 가 있으면 자동 추출 (별도 raw 불필요)
                           처리기: pipeline/process_leadership.py
  certifications_raw  : researcher_id, cert_type, cert_name, score, grade, date_obtained
  education_raw       : researcher_id, degree, major, school, graduation_year
                        ※ '임직원_학력.xlsx' 가 있으면 자동 추출 (별도 raw 불필요)
                           처리기: pipeline/process_education.py
  comments_raw        : researcher_id, year, commenter_type, comment_raw
                        (선택: comment_summary, strengths, improvements)
  succession_raw      : researcher_id, org_code, rank_type (Ready Now/Ready Later),
                        rank_order, nominated_year
  nurturing_raw       : researcher_id, year, category, content, result
  core_technology_raw : researcher_id, tech_field, tech_name
                        ※ '핵심기술.xlsx' 가 있으면 자동 추출 (별도 raw 불필요)
                           처리기: pipeline/process_core_technology.py
  tech_ownership_raw  : researcher_id, tech_1, lv_1, portion_1, ..., tech_5, lv_5,
                        portion_5, E_support
                        ※ '보유기술.xlsx' 가 있으면 자동 추출 (별도 raw 불필요)
                           처리기: pipeline/process_tech_ownership.py
  job_profile_raw     : researcher_id, name, job_profile_name_1, job_start_date_1,
                        job_end_date_1, ... (사람마다 최대 직무 구간 수만큼 반복)
                        ※ '임직원_직무이력.xlsx' 가 있으면 자동 추출 (별도 raw 불필요)
                           처리기: pipeline/process_job_profile.py
  (업무목표·과제 수행 이력은 별도 _raw 폴백 없음, 아래 전용 파일 항목 참고)

[업무목표] ★ 전용 원천 파일 3개에서 자동 추출 (별도 raw 불필요)
  업무목표24.xlsx / 업무목표25.xlsx / 업무목표26.xlsx (사번, 목표명, 상세설명)
    → data/processed/work_objective.csv (researcher_id, work_objective24~26)
      한 연구원이 한 해에 목표를 여러 개 작성했으면 "- 목표명 - 상세설명" 줄로
      이어붙여 그 해 컬럼 하나에 담는다. process_researcher_expertise.py의
      8번째 입력 소스로 쓰인다(LLM 호출 없이 순수 엑셀 전처리만 수행).
    ※ 처리기: pipeline/process_work_objective.py
       (사번/목표명/상세설명 컬럼명 등 설정은 해당 파일 상단에서 변경)

[과제 수행 이력] ★ 전용 원천 파일에서 자동 추출 (별도 raw 불필요, 폴백 없음)
  개인별과제투입기간데이터_260114.xlsb (KNOXID, 과제명, 시작일, 해제일, 투입률)
    → data/processed/tasks.csv (researcher_id, task_name, start_date, end_date,
      input_rate). 대시보드 타임라인과 process_researcher_expertise.py의
      과제 수행 이력 입력 소스로 모두 쓰인다.
    ※ 처리기: pipeline/process_tasks.py
       (KNOXID 등 컬럼명 설정은 해당 파일 상단에서 변경)

[직무정보 참조 데이터] ★ 전용 원천 파일에서 자동 추출 (별도 raw 불필요)
  직무정보_표준.xlsx (직무, 정의)
    → data/processed/job_profile_info_standard.json 로 변환
    ※ 처리기: pipeline/process_job_profile_standard.py
  직무정보_부서.xlsx (직무, 세부직무, 정의)
    → data/processed/job_profile_info_sait.json 로 변환
    ※ 처리기: pipeline/process_job_profile_sait.py

[등급/Lv 기준표] ★ 원천 파일 없이 정적 데이터로 생성 (run_pipeline.py에서 자동 실행)
  → data/processed/core_technology_grade_info.json (핵심기술 등급 S/A/B 개요)
  → data/processed/tech_ownership_lv_info.json (보유기술 Lv 1~5 개요)
  ※ 처리기: pipeline/process_rubrics.py

[과제별 컨플루언스 주소] ★ 전용 원천 파일에서 자동 추출 (별도 raw 불필요)
  과제별컨플.xlsx (소속, 과제명, 컨플 주소)
    → data/processed/project_confl_address.csv 로 변환
    ※ 처리기: pipeline/process_project_confl.py

[유사 기업/학계 탐색] ★ 사내 Confluence + 사내 LLM 필요, 비용이 커서
  run_pipeline.py 자동 실행에는 포함하지 않음. project_confl_address.csv
  준비 후 별도 실행:
    python pipeline/process_project_search.py
    → data/processed/project_searched_list.csv
      (컨플루언스 페이지를 사내 LLM으로 요약 후, "R&D Enterprise & Academia
       Discovery Agent" 역할로 유사 기업/스타트업/대학연구실을 탐색)
    ※ Confluence 접속: pipeline/llm_config.py의 CONFLUENCE_TOKEN(PAT) 필요
       (llm_config.example.py 참고). atlassian-python-api 패키지 설치 필요.

[과제 전문성 분석 → 연구원 전문성 분석 → 연구원 매칭] ★ 사내 Confluence +
  사내 LLM 필요, 비용이 커서 run_pipeline.py 자동 실행에는 포함하지 않음.
  입력 데이터 전처리는 pipeline/run_expertise.py 로 한 번에 준비한 뒤(내부적으로
  process_project_confl.py 포함, researchers/education/tasks/... 등 이 분석에
  필요한 모든 전처리를 실행), 아래 순서로 별도 실행한다(각 단계는 이전 단계의
  출력 파일을 입력으로 사용하므로 반드시 이 순서를 지킨다):

    0) python pipeline/run_expertise.py
       → project_confl_address.csv 등 이 아래 1)~4) 단계에 필요한 입력을 모두 준비
         (LLM 호출 없음, 비용 발생 없음)

    1) python pipeline/process_project_confl.py   (run_expertise.py에 포함되어 있어 개별 실행 불필요)
       → data/processed/project_confl_address.csv (소속/과제명/컨플 주소)

    2) python pipeline/process_project_expertise.py   (컨플 요약 + 과제 전문성 분석)
       → data/processed/project_expertise_analysis.json / .html
         (컨플루언스 페이지를 사내 LLM으로 요약 후, "R&D Project Specialist Agent"
          역할로 과제별 필요 직무·전문성 딥다이브 분석을 생성. Bootstrap 5 +
          marked.js/DOMPurify로 HTML도 함께 생성)

    3) python pipeline/process_researcher_expertise.py   (연구원 전문성 분석)
       → data/processed/연구원 보유 전문성 분석.json / .html
         (학력/과제이력/직무이력/핵심기술/보유기술/논문/특허/업무목표(24~26년)를
          종합해 사내 LLM이 강점 분야·핵심 기술 역량·도메인 지식을 구조화된
          JSON으로 분석. 진행 중 10명 처리될 때마다 "(완료인원 N명/전체 N명,
          N명 성공, N명 실패, N명 건너뜀)" 요약을 출력. 이미 저장된 JSON을
          LLM 재호출 없이 HTML로만 다시 만들려면 --html-only 옵션 사용)
       ※ 논문 저널 권위도 조회는 pipeline/journal_authority.py로 분리되어 있다
          (data/processed/journal_authority.json 캐시). 이 파일 실행 시 자동으로
          함께 호출되며, 캐시만 갱신하고 싶으면 독립적으로도 실행 가능:
          python pipeline/journal_authority.py [--refresh-journals]
          ※ 사내 LLM 호출(비용 발생) — run_pipeline.py 자동 실행에는 포함되지 않음

    4) python pipeline/process_project_researcher_fit.py   (연구원 매칭)
       → data/processed/project_fit_by_project.json,
         project_fit_by_researcher.json, project_researcher_fit.html
         (임베딩 1차 후보 추출 + 사내 LLM "R&D Talent Matching Agent"로 과제
          기준/인별 기준 두 방향 적합도 판단. 매칭 로직은 pipeline/researcher_fit.py
          공용 모듈을 사용)

    5) python pipeline/process_researcher_similarity.py   (선택: 연구원 ↔ 연구원 유사도)
       → data/processed/researcher_similarity.json, researcher_similarity.html
         (3)의 연구원 전문성 프로필을 BGE-M3로 임베딩해 코사인 유사도를 계산 —
          과제(프로젝트) 라벨과 무관하게 실제 전문성이 겹치는 연구원을 직접
          찾아낸다(예: 서로 다른 과제 소속이어도 둘 다 AI를 하면 유사도가 높게
          나옴). 사내 chat LLM은 호출하지 않고 임베딩만 사용한다. 3)의 출력만
          있으면 되므로 4)와 무관하게 바로 실행 가능)

    ※ 2)~4)는 project_summary.py의 컨플루언스 원문 캐시
       (data/processed/project_page_cache.json)를 공유하므로, 같은 과제를
       두 번 조회하지 않는다.
    ※ Confluence 접속: pipeline/llm_config.py의 CONFLUENCE_TOKEN(PAT) 필요
       (llm_config.example.py 참고). atlassian-python-api 패키지 설치 필요.

출력 위치: data/processed/
"""

import csv
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import read_xlsx, norm_researcher_id_col

# 평가·특허·양성이력·시상·학력·리더십·인센티브·연구원기본정보·논문은 전용 처리기에서 추출하므로 목록에서 제외
TABLES = [
    'technology_transfer',
    'transfers',
    'certifications',
    'succession',
]


def _read_raw(name: str) -> pd.DataFrame | None:
    """xlsx 우선(xlwings DRM 지원), 없으면 csv 시도. researcher_id 자동 정규화."""
    for ext in ('xlsx', 'csv'):
        path = os.path.join(RAW_DIR, f'{name}_raw.{ext}')
        if os.path.exists(path):
            if ext == 'xlsx':
                df = read_xlsx(path)
            else:
                df = pd.read_csv(path, encoding='utf-8-sig', dtype=str)
            return norm_researcher_id_col(df)
    return None


def _run_with_fallback(process_fn, table: str, hint: str, missing: list) -> bool:
    """전용 처리기(process_fn)를 실행하고, 실패하면 {table}_raw 폴백을 시도한다.
    폴백까지 실패하면 missing에 '{table} ({hint})' 안내를 추가한다."""
    if process_fn():
        return True
    df = _read_raw(table)
    if df is not None:
        out_path = os.path.join(OUT_DIR, f'{table}.csv')
        df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
        print(f'  [OK]   {table}.csv ({table}_raw 폴백, {len(df)}행)')
        return True
    missing.append(f'{table} ({hint})')
    return False


def run():
    os.makedirs(OUT_DIR, exist_ok=True)
    missing = []

    # ── 0. 연구원 기본정보: 인력현황.xlsx 우선, 없으면 researchers_raw 폴백 ─
    from process_researchers import process as process_researchers
    _run_with_fallback(process_researchers, 'researchers', '인력현황.xlsx 또는 researchers_raw', missing)

    # ── 1. 평가 데이터: T&P 파일에서 추출, 없으면 evaluations_raw 폴백 ────
    from process_tp_evaluation import process as process_tp
    _run_with_fallback(lambda: process_tp()[0], 'evaluations',
                        'T&P_기본_인사_정보.xlsx 또는 evaluations_raw', missing)

    # ── 2. 특허 데이터: 특허 리스트.xlsx 우선, 없으면 patents_raw 폴백 ──
    from process_patents import process as process_patents
    _run_with_fallback(process_patents, 'patents', '특허 리스트.xlsx 또는 patents_raw', missing)

    # ── 3. 인사발령 이력: 인사발령이력.xlsx 우선, 없으면 hr_orders_raw 폴백 ─
    from process_personnel_orders import process as process_personnel_orders
    _run_with_fallback(process_personnel_orders, 'hr_orders', '인사발령이력.xlsx 또는 hr_orders_raw', missing)

    # ── 4. 양성이력: 양성_인력_현황.xlsx 우선, 없으면 nurturing_raw 폴백 ──
    from process_nurturing import process as process_nurturing
    _run_with_fallback(process_nurturing, 'nurturing', '양성_인력_현황.xlsx 또는 nurturing_raw', missing)

    # ── 5. 과제 정보: 과제정보.xlsx 우선, 없으면 tasks_information_raw 폴백 ─
    from process_task_information import process as process_task_information
    _run_with_fallback(process_task_information, 'tasks_information',
                        '과제정보.xlsx 또는 tasks_information_raw', missing)

    # ── 6. 시상이력: 시상 세부사항.xlsx 우선, 없으면 awards_raw 폴백 ────
    from process_awards import process as process_awards
    _run_with_fallback(process_awards, 'awards', '시상 세부사항.xlsx 또는 awards_raw', missing)

    # ── 7. 학력: 임직원_학력.xlsx 우선, 없으면 education_raw 폴백 ──────
    from process_education import process as process_education
    _run_with_fallback(process_education, 'education', '임직원_학력.xlsx 또는 education_raw', missing)

    # ── 8. 리더십 진단: 리더십진단.xlsx 우선, 없으면 leadership_raw 폴백 ─
    from process_leadership import process as process_leadership
    _run_with_fallback(process_leadership, 'leadership', '리더십진단.xlsx 또는 leadership_raw', missing)

    # ── 9. 인센티브 선정 이력: 핵심이력.xlsx 우선, 없으면 incentive_selection_raw 폴백 ─
    from process_incentive import process as process_incentive
    _run_with_fallback(process_incentive, 'incentive_selection',
                        '핵심이력.xlsx 또는 incentive_selection_raw', missing)

    # ── 9-1. 핵심기술: 핵심기술.xlsx 우선, 없으면 core_technology_raw 폴백 ─
    from process_core_technology import process as process_core_technology
    _run_with_fallback(process_core_technology, 'core_technology',
                        '핵심기술.xlsx 또는 core_technology_raw', missing)

    # ── 9-2. 보유기술: 보유기술.xlsx 우선, 없으면 tech_ownership_raw 폴백 ─
    from process_tech_ownership import process as process_tech_ownership
    _run_with_fallback(process_tech_ownership, 'tech_ownership',
                        '보유기술.xlsx 또는 tech_ownership_raw', missing)

    # ── 9-3. 직무이력: 임직원_직무이력.xlsx 우선, 없으면 job_profile_raw 폴백 ─
    from process_job_profile import process as process_job_profile
    _run_with_fallback(process_job_profile, 'job_profile', '임직원_직무이력.xlsx 또는 job_profile_raw', missing)

    # ── 9-4. 업무목표: 업무목표24/25/26.xlsx (LLM 호출 없음, 폴백 없음) ──
    from process_work_objective import process as process_work_objective
    if not process_work_objective():
        missing.append('work_objective (업무목표24/25/26.xlsx)')

    # ── 9-5. 논문 현황: 개인별논문현황_2016_2026.xlsx 우선, 없으면 publications_raw 폴백 ─
    from process_publications import process as process_publications
    _run_with_fallback(process_publications, 'publications',
                        '개인별논문현황_2016_2026.xlsx 또는 publications_raw', missing)

    # ── 9-6. 과제 수행 이력: 개인별과제투입기간데이터_260114.xlsb (LLM 호출 없음, 폴백 없음) ─
    from process_tasks import process as process_tasks
    if not process_tasks():
        missing.append('tasks (개인별과제투입기간데이터_260114.xlsb)')

    # ── 10. 나머지 테이블 (technology_transfer, transfers, certifications, succession) ──
    for table in TABLES:
        df = _read_raw(table)
        if df is None:
            missing.append(table)
            print(f'  [SKIP] {table}_raw 파일 없음')
            continue
        out_path = os.path.join(OUT_DIR, f'{table}.csv')
        df.to_csv(out_path, index=False, encoding='utf-8-sig')
        print(f'  [OK]   {table}.csv ({len(df)}행)')

    # ── 11. 코멘트: 별도 처리 (LLM 요약 옵션 포함) ───────────────────────
    from process_comments import process as process_comments
    process_comments(use_llm=False)

    # ── 11-1. 직무정보 참조 데이터: 표준/부서 직무정의 JSON 변환 ──────────
    from process_job_profile_standard import process as process_job_profile_standard
    process_job_profile_standard()
    from process_job_profile_sait import process as process_job_profile_sait
    process_job_profile_sait()

    # ── 11-2. 등급/Lv 기준표(정적 참조 데이터) ────────────────────────────
    from process_rubrics import process as process_rubrics
    process_rubrics()

    # ── 11-3. 과제별 컨플루언스 주소 ───────────────────────────────────────
    from process_project_confl import process as process_project_confl
    process_project_confl()

    # ※ 유사 기업/학계 탐색(사내 Confluence + 사내 LLM, process_project_search.py)은
    #   비용이 크고 Confluence 접속 설정이 필요해 자동 실행에 포함하지 않는다.
    #   준비가 끝나면 별도 실행: python pipeline/process_project_search.py

    # ── 12. DATABASE_URL 설정 시 PostgreSQL 적재 ────────────────────────
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from services.db import db_enabled
        if db_enabled():
            from load_to_db import load as load_to_db
            print('\nDATABASE_URL 감지 — PostgreSQL 적재 시작')
            load_to_db()
    except Exception as exc:
        print(f'[run_pipeline] DB 적재 건너뜀: {exc}')

    if missing:
        print(f'\n누락된 원천 파일: {missing}')
        print('개발용 더미 데이터를 사용하려면:  python pipeline/generate_sample_data.py')
    else:
        print('\n파이프라인 완료 — data/processed/ 를 확인하세요.')


if __name__ == '__main__':
    run()
