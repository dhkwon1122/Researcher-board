"""
전문성 분석(과제 전문성 + 연구원 전문성 + 매칭) 전용 전처리 실행 스크립트

run_pipeline.py(대시보드용 전처리)와 목적이 다르다 — 이 스크립트는 아래 LLM
분석 체인을 실행하기 전에 필요한 입력 데이터만 준비한다(LLM 호출 없음,
비용 발생 없음). run_pipeline.py와 공통으로 필요한 전처리 모듈(예:
researchers/education/tasks/publications/patents 등)은 이 파일에도
동일하게 포함되어 있다 — 두 스크립트는 서로 import하지 않는 독립 실행
스크립트이므로, 대시보드만 쓰는 사람도 run_pipeline.py만으로 충분하고
전문성 분석만 쓰는 사람도 run_expertise.py만으로 충분하다.

사용법:
  python pipeline/run_expertise.py

이 스크립트가 준비하는 것 (data/raw/ → data/processed/):
  researchers.csv, education.csv, tasks.csv, tasks_information.csv,
  job_profile.csv, job_profile_info_standard.json, job_profile_info_sait.json,
  core_technology.csv, core_technology_grade_info.json, tech_ownership.csv,
  tech_ownership_lv_info.json, publications.csv, patents.csv,
  work_objective.csv, project_confl_address.csv

이 스크립트가 실행하지 않는 것 (사내 Confluence + 사내 LLM 필요, 비용 발생 —
위 전처리가 끝난 뒤 아래 순서로 직접 실행):
  1) python pipeline/process_project_expertise.py      (과제 전문성 분석)
     python pipeline/process_project_search.py         (선택: 유사 기업/학계 탐색)
  2) python pipeline/process_researcher_expertise.py   (연구원 전문성 분석)
  3) python pipeline/process_project_researcher_fit.py (과제·연구원 매칭)
  4) python pipeline/process_researcher_similarity.py  (선택: 연구원 ↔ 연구원 유사도)
  ※ 두 사내 LLM(thinkingcap/gpt-4o)을 비교하려면 각 단계를 --profile thinkingcap로
    한 번 더 실행한 뒤 python pipeline/process_llm_compare.py

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

    # ── 1. 연구원 기본정보: 인력현황.xlsx 우선, 없으면 researchers_raw 폴백 ─
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

    # ── 2. 학력: 임직원_학력.xlsx 우선, 없으면 education_raw 폴백 ──────
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

    # ── 3. 과제 수행 이력: 개인별과제투입기간데이터_260114.xlsb (폴백 없음) ─
    from process_tasks import process as process_tasks
    tasks_ok = process_tasks()
    if not tasks_ok:
        missing.append('tasks (개인별과제투입기간데이터_260114.xlsb)')

    # ── 4. 과제 정보: 과제정보.xlsx 우선, 없으면 tasks_information_raw 폴백 ─
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

    # ── 5. 직무이력: 임직원_직무이력.xlsx 우선, 없으면 job_profile_raw 폴백 ─
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

    # ── 6. 직무정보 참조 데이터: 표준/부서 직무정의 JSON 변환 (폴백 없음) ──
    from process_job_profile_standard import process as process_job_profile_standard
    process_job_profile_standard()
    from process_job_profile_sait import process as process_job_profile_sait
    process_job_profile_sait()

    # ── 7. 핵심기술: 핵심기술.xlsx 우선, 없으면 core_technology_raw 폴백 ─
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

    # ── 8. 등급/Lv 기준표(정적 참조 데이터, 폴백 없음) ────────────────────
    from process_rubrics import process as process_rubrics
    process_rubrics()

    # ── 9. 보유기술: 보유기술.xlsx 우선, 없으면 tech_ownership_raw 폴백 ─
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

    # ── 10. 논문 현황: 개인별논문현황_2016_2026.xlsx 우선, 없으면 publications_raw 폴백 ─
    from process_publications import process as process_publications
    pub_ok = process_publications()
    if not pub_ok:
        df = _read_raw('publications')
        if df is not None:
            out_path = os.path.join(OUT_DIR, 'publications.csv')
            df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
            print(f'  [OK]   publications.csv (publications_raw 폴백, {len(df)}행)')
        else:
            missing.append('publications (개인별논문현황_2016_2026.xlsx 또는 publications_raw)')

    # ── 11. 특허: 특허 리스트.xlsx 우선, 없으면 patents_raw 폴백 ──────
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

    # ── 12. 업무목표: 업무목표24/25/26.xlsx (폴백 없음) ──────────────────
    from process_work_objective import process as process_work_objective
    wobj_ok = process_work_objective()
    if not wobj_ok:
        missing.append('work_objective (업무목표24/25/26.xlsx)')

    # ── 13. 과제별 컨플루언스 주소: 과제별컨플.xlsx (폴백 없음) ───────────
    from process_project_confl import process as process_project_confl
    confl_ok = process_project_confl()
    if not confl_ok:
        missing.append('project_confl_address (과제별컨플.xlsx)')

    if missing:
        print(f'\n누락된 원천 파일: {missing}')
        print('개발용 더미 데이터를 사용하려면:  python pipeline/generate_sample_data.py')
    else:
        print('\n전문성 분석 전처리 완료 — 이어서 아래 순서로 직접 실행하세요 (사내 LLM 호출, 비용 발생):')
        print('  1) python pipeline/process_project_expertise.py')
        print('  2) python pipeline/process_researcher_expertise.py')
        print('  3) python pipeline/process_project_researcher_fit.py')
        print('  4) python pipeline/process_researcher_similarity.py   (선택)')


if __name__ == '__main__':
    run()
