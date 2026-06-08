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

# 평가·특허·양성이력·시상·학력·리더십·인센티브는 전용 처리기에서 추출하므로 목록에서 제외
TABLES = [
    'researchers',
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

    # ── 3. 양성이력: 양성_인력_현황.xlsx 우선, 없으면 nurturing_raw 폴백 ──
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

    # ── 4. 시상이력: 시상 세부사항.xlsx 우선, 없으면 awards_raw 폴백 ────
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

    # ── 5. 학력: 임직원_학력.xlsx 우선, 없으면 education_raw 폴백 ──────
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

    # ── 6. 리더십 진단: 리더십진단.xlsx 우선, 없으면 leadership_raw 폴백 ─
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

    # ── 7. 인센티브 선정 이력: 핵심이력.xlsx 우선, 없으면 incentive_selection_raw 폴백 ─
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

    # ── 8. 나머지 테이블 (researchers, publications, technology_transfer, transfers, certifications, succession) ──
    for table in TABLES:
        df = _read_raw(table)
        if df is None:
            missing.append(table)
            print(f'  [SKIP] {table}_raw 파일 없음')
            continue
        out_path = os.path.join(OUT_DIR, f'{table}.csv')
        df.to_csv(out_path, index=False, encoding='utf-8-sig')
        print(f'  [OK]   {table}.csv ({len(df)}행)')

    # ── 9. 코멘트: 별도 처리 (LLM 요약 옵션 포함) ───────────────────────
    from process_comments import process as process_comments
    process_comments(use_llm=False)

    if missing:
        print(f'\n누락된 원천 파일: {missing}')
        print('개발용 더미 데이터를 사용하려면:  python pipeline/generate_sample_data.py')
    else:
        print('\n파이프라인 완료 — data/processed/ 를 확인하세요.')


if __name__ == '__main__':
    run()
