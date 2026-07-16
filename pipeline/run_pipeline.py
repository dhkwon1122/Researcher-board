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

[2026 MIT 10대 기술] ★ 전용 원천 파일에서 자동 추출 (별도 raw 불필요)
  2026MIT10대기술.xlsx (No., 기술명, 설명)
    → data/processed/2026MITTech10.json / 2026MITTech10.html 로 변환
    ※ 처리기: pipeline/process_mit10.py
       run_pipeline.py 에서는 JSON+HTML 변환까지만 자동 실행되며, 기술별 필요
       전문성 분석(사내 LLM, R&D Project Specialist Agent 역할)을 포함하려면
       별도 실행: python pipeline/process_mit10.py --llm

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

[연구원 보유 전문성 분석 / MIT10 적합도 매칭] ★ 사내 LLM 필요, 비용이 커서
  run_pipeline.py 자동 실행에는 포함하지 않음. 위 데이터가 모두 준비된 후
  아래 순서로 별도 실행:
    1) python pipeline/process_researcher_expertise.py
       → data/processed/연구원 보유 전문성 분석.json
         (학력/과제이력/직무이력/핵심기술/보유기술/논문/특허를 종합해 사내
          LLM이 강점 분야·핵심 기술 역량·도메인 지식을 구조화된 JSON으로 분석.
          논문 저널 권위도는 data/processed/journal_authority.json 에 캐시)
    2) python pipeline/process_mit10.py --llm  (아직 안 했다면)
    3) python pipeline/process_mit10_researcher_fit.py
       → data/processed/mit10_fit_by_tech.json, mit10_fit_by_researcher.json,
         mit10_researcher_fit.html
         (사내 임베딩으로 1차 후보를 추린 뒤 사내 LLM이 최종 적합도 판단)

[과제별 컨플루언스 주소] ★ 전용 원천 파일에서 자동 추출 (별도 raw 불필요)
  과제별컨플.xlsx (소속, 과제명, 컨플 주소)
    → data/processed/project_confl_address.csv 로 변환
    ※ 처리기: pipeline/process_project_confl.py

[유사 기업/학계 탐색 · 과제 전문성 분석] ★ 사내 Confluence + 사내 LLM 필요,
  비용이 커서 run_pipeline.py 자동 실행에는 포함하지 않음.
  project_confl_address.csv 준비 후 별도 실행:
    python pipeline/process_project_search.py
    → data/processed/project_searched_list.csv
      (컨플루언스 페이지를 사내 LLM으로 요약 후, "R&D Enterprise & Academia
       Discovery Agent" 역할로 유사 기업/스타트업/대학연구실을 탐색)
    python pipeline/process_project_expertise.py
    → data/processed/project_expertise_analysis.json
      (컨플루언스 페이지를 사내 LLM으로 요약 후, process_mit10.py와 동일한
       "R&D Project Specialist Agent" 역할로 과제별 필요 직무·전문성 딥다이브
       분석을 생성)
    ※ 두 스크립트 모두 project_summary.py를 통해 컨플루언스 요약 결과를
       data/processed/project_summary_cache.json 에 공유 캐시하므로, 같은
       과제를 두 번 요약하지 않는다.
    ※ Confluence 접속: pipeline/llm_config.py의 CONFLUENCE_TOKEN(PAT) 필요
       (llm_config.example.py 참고). atlassian-python-api 패키지 설치 필요.

출력 위치: data/processed/
"""

import csv
import os
import sys

import pandas as pd

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw')
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from excel_reader import read_xlsx, norm_researcher_id_col

# 평가·특허·양성이력·시상·학력·리더십·인센티브·연구원기본정보는 전용 처리기에서 추출하므로 목록에서 제외
TABLES = [
    'publications',
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


def run():
    os.makedirs(OUT_DIR, exist_ok=True)
    missing = []

    # ── 0. 연구원 기본정보: 인력현황.xlsx 우선, 없으면 researchers_raw 폴백 ─
    from process_researchers import process as process_researchers
    res_ok = process_researchers()
    if not res_ok:
        df = _read_raw('researchers')
        if df is not None:
            out_path = os.path.join(OUT_DIR, 'researchers.csv')
            df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
            print(f'  [OK]   researchers.csv (researchers_raw 폴백, {len(df)}행)')
        else:
            missing.append('researchers (인력현황.xlsx 또는 researchers_raw)')

    # ── 1. 평가 데이터: T&P 파일에서 추출 ──────────────────────────────
    from process_tp_evaluation import process as process_tp
    tp_ok, _ = process_tp()   # 두 번째 반환값(researcher updates)은 run_pipeline에서 불필요
    if not tp_ok:
        # T&P 파일 없으면 evaluations_raw 폴백
        df = _read_raw('evaluations')
        if df is not None:
            out_path = os.path.join(OUT_DIR, 'evaluations.csv')
            df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
            print(f'  [OK]   evaluations.csv (evaluations_raw 폴백, {len(df)}행)')
        else:
            missing.append('evaluations (T&P_기본_인사_정보.xlsx 또는 evaluations_raw)')

    # ── 2. 특허 데이터: 특허 리스트.xlsx 우선, 없으면 patents_raw 폴백 ──
    from process_patents import process as process_patents
    pat_ok = process_patents()
    if not pat_ok:
        df = _read_raw('patents')
        if df is not None:
            out_path = os.path.join(OUT_DIR, 'patents.csv')
            df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
            print(f'  [OK]   patents.csv (patents_raw 폴백, {len(df)}행)')
        else:
            missing.append('patents (특허 리스트.xlsx 또는 patents_raw)')

    # ── 3. 인사발령 이력: 인사발령이력.xlsx 우선, 없으면 hr_orders_raw 폴백 ─
    from process_personnel_orders import process as process_personnel_orders
    hro_ok = process_personnel_orders()
    if not hro_ok:
        df = _read_raw('hr_orders')
        if df is not None:
            out_path = os.path.join(OUT_DIR, 'hr_orders.csv')
            df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
            print(f'  [OK]   hr_orders.csv (hr_orders_raw 폴백, {len(df)}행)')
        else:
            missing.append('hr_orders (인사발령이력.xlsx 또는 hr_orders_raw)')

    # ── 4. 양성이력: 양성_인력_현황.xlsx 우선, 없으면 nurturing_raw 폴백 ──
    from process_nurturing import process as process_nurturing
    nur_ok = process_nurturing()
    if not nur_ok:
        df = _read_raw('nurturing')
        if df is not None:
            out_path = os.path.join(OUT_DIR, 'nurturing.csv')
            df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
            print(f'  [OK]   nurturing.csv (nurturing_raw 폴백, {len(df)}행)')
        else:
            missing.append('nurturing (양성_인력_현황.xlsx 또는 nurturing_raw)')

    # ── 5. 과제 정보: 과제정보.xlsx 우선, 없으면 tasks_information_raw 폴백 ─
    from process_task_information import process as process_task_information
    tinfo_ok = process_task_information()
    if not tinfo_ok:
        df = _read_raw('tasks_information')
        if df is not None:
            out_path = os.path.join(OUT_DIR, 'tasks_information.csv')
            df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
            print(f'  [OK]   tasks_information.csv (tasks_information_raw 폴백, {len(df)}행)')
        else:
            missing.append('tasks_information (과제정보.xlsx 또는 tasks_information_raw)')

    # ── 6. 시상이력: 시상 세부사항.xlsx 우선, 없으면 awards_raw 폴백 ────
    from process_awards import process as process_awards
    awd_ok = process_awards()
    if not awd_ok:
        df = _read_raw('awards')
        if df is not None:
            out_path = os.path.join(OUT_DIR, 'awards.csv')
            df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
            print(f'  [OK]   awards.csv (awards_raw 폴백, {len(df)}행)')
        else:
            missing.append('awards (시상 세부사항.xlsx 또는 awards_raw)')

    # ── 7. 학력: 임직원_학력.xlsx 우선, 없으면 education_raw 폴백 ──────
    from process_education import process as process_education
    edu_ok = process_education()
    if not edu_ok:
        df = _read_raw('education')
        if df is not None:
            out_path = os.path.join(OUT_DIR, 'education.csv')
            df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
            print(f'  [OK]   education.csv (education_raw 폴백, {len(df)}행)')
        else:
            missing.append('education (임직원_학력.xlsx 또는 education_raw)')

    # ── 8. 리더십 진단: 리더십진단.xlsx 우선, 없으면 leadership_raw 폴백 ─
    from process_leadership import process as process_leadership
    lea_ok = process_leadership()
    if not lea_ok:
        df = _read_raw('leadership')
        if df is not None:
            out_path = os.path.join(OUT_DIR, 'leadership.csv')
            df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
            print(f'  [OK]   leadership.csv (leadership_raw 폴백, {len(df)}행)')
        else:
            missing.append('leadership (리더십진단.xlsx 또는 leadership_raw)')

    # ── 9. 인센티브 선정 이력: 핵심이력.xlsx 우선, 없으면 incentive_selection_raw 폴백 ─
    from process_incentive import process as process_incentive
    inc_ok = process_incentive()
    if not inc_ok:
        df = _read_raw('incentive_selection')
        if df is not None:
            out_path = os.path.join(OUT_DIR, 'incentive_selection.csv')
            df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
            print(f'  [OK]   incentive_selection.csv (incentive_selection_raw 폴백, {len(df)}행)')
        else:
            missing.append('incentive_selection (핵심이력.xlsx 또는 incentive_selection_raw)')

    # ── 9-1. 핵심기술: 핵심기술.xlsx 우선, 없으면 core_technology_raw 폴백 ─
    from process_core_technology import process as process_core_technology
    ctech_ok = process_core_technology()
    if not ctech_ok:
        df = _read_raw('core_technology')
        if df is not None:
            out_path = os.path.join(OUT_DIR, 'core_technology.csv')
            df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
            print(f'  [OK]   core_technology.csv (core_technology_raw 폴백, {len(df)}행)')
        else:
            missing.append('core_technology (핵심기술.xlsx 또는 core_technology_raw)')

    # ── 9-2. 보유기술: 보유기술.xlsx 우선, 없으면 tech_ownership_raw 폴백 ─
    from process_tech_ownership import process as process_tech_ownership
    town_ok = process_tech_ownership()
    if not town_ok:
        df = _read_raw('tech_ownership')
        if df is not None:
            out_path = os.path.join(OUT_DIR, 'tech_ownership.csv')
            df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
            print(f'  [OK]   tech_ownership.csv (tech_ownership_raw 폴백, {len(df)}행)')
        else:
            missing.append('tech_ownership (보유기술.xlsx 또는 tech_ownership_raw)')

    # ── 9-3. 직무이력: 임직원_직무이력.xlsx 우선, 없으면 job_profile_raw 폴백 ─
    from process_job_profile import process as process_job_profile
    jobp_ok = process_job_profile()
    if not jobp_ok:
        df = _read_raw('job_profile')
        if df is not None:
            out_path = os.path.join(OUT_DIR, 'job_profile.csv')
            df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
            print(f'  [OK]   job_profile.csv (job_profile_raw 폴백, {len(df)}행)')
        else:
            missing.append('job_profile (임직원_직무이력.xlsx 또는 job_profile_raw)')

    # ── 10. 나머지 테이블 (researchers, publications, technology_transfer, transfers, certifications, succession) ──
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

    # ── 11-1. 2026 MIT 10대 기술: JSON 변환 (전문성 분석은 --llm 옵션으로 별도 실행) ─
    from process_mit10 import process as process_mit10
    process_mit10(use_llm=False)

    # ── 11-2. 직무정보 참조 데이터: 표준/부서 직무정의 JSON 변환 ──────────
    from process_job_profile_standard import process as process_job_profile_standard
    process_job_profile_standard()
    from process_job_profile_sait import process as process_job_profile_sait
    process_job_profile_sait()

    # ── 11-3. 등급/Lv 기준표(정적 참조 데이터) ────────────────────────────
    from process_rubrics import process as process_rubrics
    process_rubrics()

    # ※ 연구원별 보유 전문성 분석(사내 LLM, process_researcher_expertise.py)과
    #   MIT10-연구원 적합도 매칭(process_mit10_researcher_fit.py)은 비용이 크고
    #   위 데이터가 모두 준비된 후에만 의미가 있어 자동 실행에 포함하지 않는다.
    #   준비가 끝나면 아래를 순서대로 별도 실행:
    #     python pipeline/process_researcher_expertise.py
    #     python pipeline/process_mit10.py --llm   (아직 안 했다면)
    #     python pipeline/process_mit10_researcher_fit.py

    # ── 11-4. 과제별 컨플루언스 주소 ───────────────────────────────────────
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
