"""
전문성 분석(과제 전문성 + 연구원 전문성 + 매칭) 전용 전처리 실행 스크립트

run_pipeline.py(대시보드용 전처리)와 목적이 다르다 — 이 스크립트는 아래 LLM
분석 체인을 실행하기 전에 필요한 입력 데이터만 준비한다(LLM 호출 없음,
비용 발생 없음). run_pipeline.py와 공통으로 필요한 전처리 모듈(예:
researchers/education/tasks/publications/patents 등)은 이 파일에도
동일하게 포함되어 있다 — 두 스크립트는 서로 import하지 않는 독립 실행
스크립트이므로, 대시보드만 쓰는 사람도 run_pipeline.py만으로 충분하고
전문성 분석만 쓰는 사람도 run_expertise.py만으로 충분하다.

실행 마지막에 BGE-M3 임베딩 서버(services/bge_server.py)가 응답하는지 확인하고,
응답하지 않으면 백그라운드로 자동 기동해 둔다(pipeline/embed_server.py) — 이
스크립트 자체는 임베딩을 쓰지 않지만, 바로 이어서 실행할
process_project_researcher_fit.py를 위해 모델 로딩 시간을 미리 없애 둔다.

사용법:
  python pipeline/run_expertise.py

이 스크립트가 준비하는 것 (data/raw/ → data/processed/):
  researchers.csv, education.csv, tasks.csv, tasks_information.csv,
  job_profile.csv, job_profile_info_standard.json, job_profile_info_sait.json,
  core_technology.csv, core_technology_grade_info.json, tech_ownership.csv,
  tech_ownership_lv_info.json, publications.csv, patents.csv,
  work_objective.csv, project_confl_address.csv, analysis_dep.csv

analysis_dep.csv(전문성 분석 부서.xlsx 전처리, 선택)는 process_researcher_expertise.py가
연구원 전문성 분석 대상 부서를 거르는 데 쓰인다 — 연구원의 department(researchers.csv,
현소속부서명)가 이 목록에 있을 때만 분석 대상에 포함한다. 파일이 없으면 부서
필터 없이 전체 연구원을 분석한다(정상 동작이므로 missing 목록에 포함되지 않음).

이 스크립트가 실행하지 않는 것 (사내 Confluence + 사내 LLM 필요, 비용 발생 —
위 전처리가 끝난 뒤 아래 순서로 직접 실행, 또는 pipeline/run_analysis.py로
한 번에 순차 실행):
  1) python pipeline/process_project_expertise.py      (과제 전문성 분석)
     python pipeline/process_project_search.py         (선택: 유사 기업/학계 탐색)
  2) python pipeline/process_researcher_expertise.py   (연구원 전문성 분석)
     ※ 논문 저널 권위도 조회(pipeline/journal_authority.py)가 이 단계 실행 시
       자동으로 함께 호출된다. 독립적으로 캐시만 갱신하려면:
       python pipeline/journal_authority.py [--profile thinkingcap] [--refresh-journals]
  3) python pipeline/process_project_researcher_fit.py (과제·연구원 매칭)
  4) python pipeline/process_researcher_similarity.py  (선택: 연구원 ↔ 연구원 유사도)
  ※ 두 사내 LLM(thinkingcap/gpt-4o)을 비교하려면 각 단계를 --profile thinkingcap로
    한 번 더 실행한 뒤 python pipeline/process_llm_compare.py
  ※ 위 1~3단계(journal_authority 포함)는 모두 개별 항목(과제/연구원/저널 등)
    단위 LLM 호출을 profile의 동시 호출 허용치만큼 스레드풀로 병렬 실행한다.
    profile='default'(전용 vLLM 서버)는 llm_config.LLM2_MAX_CONCURRENT(기본
    8)만큼 동시 호출하고, profile='thinkingcap'(사내 공용 게이트웨이)는 기존
    처럼 시간 기반 순차 제한(초당 최대 4건)을 따른다.
  ※ 1~4단계는 각자 data/processed/의 '현재본' json/html(파이프라인 체인·비교용,
    매번 덮어씀)은 그대로 유지하면서, 실행할 때마다 data/processed/result/ 아래
    산출물별 폴더(01. 과제분석/02. 연구원분석/03. 과제별_연구원별_매칭/
    04. 연구원_연구원_유사도_매칭)에 실행 시각이 붙은 사본을 추가로 쌓는다
    (result_archive.py, 이력 누적·덮어쓰기 없음).

출력 위치: data/processed/
"""

import csv
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
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

    # ── 1. 연구원 기본정보: 인력현황.xlsx 우선, 없으면 researchers_raw 폴백 ─
    from process_researchers import process as process_researchers
    _run_with_fallback(process_researchers, 'researchers', '인력현황.xlsx 또는 researchers_raw', missing)

    # ── 2. 학력: 임직원_학력.xlsx 우선, 없으면 education_raw 폴백 ──────
    from process_education import process as process_education
    _run_with_fallback(process_education, 'education', '임직원_학력.xlsx 또는 education_raw', missing)

    # ── 3. 과제 수행 이력: 개인별과제투입기간데이터_260114.xlsb (폴백 없음) ─
    from process_tasks import process as process_tasks
    if not process_tasks():
        missing.append('tasks (개인별과제투입기간데이터_260114.xlsb)')

    # ── 4. 과제 정보: 과제정보.xlsx 우선, 없으면 tasks_information_raw 폴백 ─
    from process_task_information import process as process_task_information
    _run_with_fallback(process_task_information, 'tasks_information',
                        '과제정보.xlsx 또는 tasks_information_raw', missing)

    # ── 5. 직무이력: 임직원_직무이력.xlsx 우선, 없으면 job_profile_raw 폴백 ─
    from process_job_profile import process as process_job_profile
    _run_with_fallback(process_job_profile, 'job_profile', '임직원_직무이력.xlsx 또는 job_profile_raw', missing)

    # ── 6. 직무정보 참조 데이터: 표준/부서 직무정의 JSON 변환 (폴백 없음) ──
    from process_job_profile_standard import process as process_job_profile_standard
    process_job_profile_standard()
    from process_job_profile_sait import process as process_job_profile_sait
    process_job_profile_sait()

    # ── 7. 핵심기술: 핵심기술.xlsx 우선, 없으면 core_technology_raw 폴백 ─
    from process_core_technology import process as process_core_technology
    _run_with_fallback(process_core_technology, 'core_technology',
                        '핵심기술.xlsx 또는 core_technology_raw', missing)

    # ── 8. 등급/Lv 기준표(정적 참조 데이터, 폴백 없음) ────────────────────
    from process_rubrics import process as process_rubrics
    process_rubrics()

    # ── 9. 보유기술: 보유기술.xlsx 우선, 없으면 tech_ownership_raw 폴백 ─
    from process_tech_ownership import process as process_tech_ownership
    _run_with_fallback(process_tech_ownership, 'tech_ownership',
                        '보유기술.xlsx 또는 tech_ownership_raw', missing)

    # ── 10. 논문 현황: 개인별논문현황_2016_2026.xlsx 우선, 없으면 publications_raw 폴백 ─
    from process_publications import process as process_publications
    _run_with_fallback(process_publications, 'publications',
                        '개인별논문현황_2016_2026.xlsx 또는 publications_raw', missing)

    # ── 11. 특허: 특허 리스트.xlsx 우선, 없으면 patents_raw 폴백 ──────
    from process_patents import process as process_patents
    _run_with_fallback(process_patents, 'patents', '특허 리스트.xlsx 또는 patents_raw', missing)

    # ── 12. 업무목표: 업무목표24/25/26.xlsx (폴백 없음) ──────────────────
    from process_work_objective import process as process_work_objective
    if not process_work_objective():
        missing.append('work_objective (업무목표24/25/26.xlsx)')

    # ── 13. 과제별 컨플루언스 주소: 과제별컨플.xlsx (폴백 없음) ───────────
    from process_project_confl import process as process_project_confl
    if not process_project_confl():
        missing.append('project_confl_address (과제별컨플.xlsx)')

    # ── 14. 전문성 분석 대상 부서: 전문성 분석 부서.xlsx (폴백 없음, 선택) ──
    # 없어도 process_researcher_expertise.py가 부서 필터 없이 전체 연구원을
    # 분석하므로(정상 동작) missing 목록에는 추가하지 않는다.
    from process_analysis_dep import process as process_analysis_dep
    process_analysis_dep()

    if missing:
        print(f'\n누락된 원천 파일: {missing}')
        print('개발용 더미 데이터를 사용하려면:  python pipeline/generate_sample_data.py')
    else:
        print('\n전문성 분석 전처리 완료 — 이어서 아래 순서로 직접 실행하세요 (사내 LLM 호출, 비용 발생):')
        print('  1) python pipeline/process_project_expertise.py')
        print('  2) python pipeline/process_researcher_expertise.py')
        print('       (논문 저널 권위도 조회 pipeline/journal_authority.py가 자동으로 함께 호출됨)')
        print('  3) python pipeline/process_project_researcher_fit.py')
        print('  4) python pipeline/process_researcher_similarity.py   (선택)')
        print('  ※ 1~3단계는 profile의 동시 호출 허용치만큼 병렬로 LLM을 호출합니다')
        print('     (llm_config.LLM2_MAX_CONCURRENT, profile=default 기본 8건).')

    # ── BGE-M3 임베딩 서버 사전 기동 ────────────────────────────────────
    # 이 스크립트 자체는 임베딩/LLM을 호출하지 않지만, 바로 다음 실행할
    # process_project_researcher_fit.py(임베딩 1차 후보 추출)를 위해 미리
    # 띄워 둔다 — 이미 응답 중이면 재기동하지 않고, 응답하지 않으면 백그라운드로
    # 새로 기동해 모델 로딩을 지금 끝내 둔다.
    print('\nBGE-M3 임베딩 서버 사전 기동 확인 중 (다음 단계 process_project_researcher_fit.py 대비)...')
    from embed_server import ensure_embed_server
    ensure_embed_server()


if __name__ == '__main__':
    run()
