"""
학력 처리 모듈

원천: source_reader.read_source('education')
  → DB education_stg 테이블 또는 data/raw_csv/education.csv
  (1단계 xlsx_to_raw_csv.py가 data/raw/임직원_학력.xlsx를 DRM 제거해 만든 사본)
출력 파일: data/processed/education.csv

읽는 컬럼:
  사번, 학력, 학교명, 전공, 학위 취득 연도, 졸업일

학위 구분 (다양한 표기를 아래 5가지로 통일):
  박사  : 박사, Doctoral, PhD, Doctor 등
  석사  : 석사, Master, M.S., MBA 등
  학사  : 학사, Bachelor, B.S. 등
  전문대: 전문대, 전문학사, Associate 등
  고교  : 고교, 고등학교, High School 등

※ 연구원별 "최종학력"(가진 학위 중 가장 높은 것, 박사>석사>학사>전문대>고교
  우선순위) 기준으로, 아래 표대로 함께 보여줄 하위 학력만 남기고 나머지는
  제외한다(2026-09-09, 사용자 확정 — 표시 화면 3곳(엑셀 다운로드/연구원
  개별 프로필/A4 인쇄 카드)이 전부 이 education.csv 하나를 공유하므로,
  화면마다 따로 거르지 않고 여기서 한 번만 정리한다):
    최종학력 박사  → 박사, 석사, 학사
    최종학력 석사  → 석사, 학사
    최종학력 학사  → 학사, 전문대, 고교
    최종학력 전문대 → 전문대, 고교
    최종학력 고교  → 고교
  (하위 학력 정보가 원본에 아예 없으면 그 줄은 그냥 없는 것 — 빈 값으로
  채우지 않는다.) 5가지 표준 학위 중 어디에도 안 맞는 원본 표기(예:
  "수료" 등)는 이 필터 대상이 아니며 항상 그대로 보존한다(기존 동작
  유지 — 최종학력 판정 자체도 이 5가지 표준 학위만 대상으로 한다).
  ⚠️ 이 규칙은 education.csv를 만드는 시점(파이프라인)에 적용되므로,
  이미 처리돼 저장된 사람에게 반영하려면 원본 임직원 학력 파일로
  다시 실행(재업로드 포함)해야 한다 — 이번 변경 이전에 이미 걸러져 저장된
  하위 학력(예: 학사가 최종인데 전문대 이력이 있던 경우)은, 그 사람의
  원본 파일이 다시 처리되기 전까지는 이미 사라진 상태 그대로다.

컬럼명 설정은 파일 상단의 COL_* 상수에서 수정하세요.
"""

import os
import sys

import pandas as pd

EDUCATION_PATTERN = '임직원 학력 *.xlsx'
_EDUCATION_HEADER_ROW = 9  # sources.py 매니페스트 기준 (10번째 행)

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_ID        = '사번'
COL_DEGREE    = '학력'
COL_SCHOOL    = '학교명'
COL_MAJOR     = '전공'
COL_GRAD_YEAR = '학위 취득 연도'
COL_GRAD_DATE = '졸업일'
# ─────────────────────────────────────────────────────────────────────────────

# 학위 통일 매핑: (소문자 포함 키워드 목록, 표준 학위명) 순서 중요 — 박사를 먼저 검사
DEGREE_MAP = [
    (['박사', 'doctoral', 'phd', 'ph.d', 'doctor', 'd.sc', 'dsc', '공학박사', '이학박사', '문학박사'], '박사'),
    (['석사', 'master', 'm.s', 'm.a', 'm.eng', 'm.sc', 'msc', 'mba', '공학석사', '이학석사'], '석사'),
    (['학사', 'bachelor', 'b.s', 'b.a', 'b.eng', 'b.sc', 'bsc', '공학학사', '이학학사'], '학사'),
    (['전문대', '전문학사', 'associate', '전문'], '전문대'),
    (['고교', '고등학교', '고졸', 'high school', 'highschool', '고등학교졸업'], '고교'),
]

DEG_ORDER = {'박사': 0, '석사': 1, '학사': 2, '전문대': 3, '고교': 4}

# 최종학력(DEG_ORDER 기준 가장 높은 것)별로 함께 남길 하위 학력 집합
# (2026-09-09, 사용자 확정 — 모듈 docstring 표 참고).
_KEEP_MAP = {
    '박사': {'박사', '석사', '학사'},
    '석사': {'석사', '학사'},
    '학사': {'학사', '전문대', '고교'},
    '전문대': {'전문대', '고교'},
    '고교': {'고교'},
}

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import clean_str, is_blank, read_xlsx, norm_id
from merge_utils import TABLE_KEYS, write_merged
from source_files import find_latest
from source_reader import read_source


def _normalize_degree(val: str) -> str:
    v = str(val).strip().lower()
    for keywords, standard in DEGREE_MAP:
        for kw in keywords:
            if kw in v:
                return standard
    return str(val).strip()


def _extract_year(year_val, date_val) -> str:
    """학위 취득 연도 우선, 없으면 졸업일에서 연도 추출."""
    for v in (year_val, date_val):
        s = str(v).strip()
        if is_blank(s):
            continue
        try:
            y = int(float(s))
            if 1900 <= y <= 2100:
                return str(y)
        except (ValueError, OverflowError):
            pass
        try:
            return pd.to_datetime(s).strftime('%Y')
        except Exception:
            pass
    return ''


def process(raw_dir: str = RAW_DIR) -> bool:
    if raw_dir == RAW_DIR:
        df = read_source('education')
        if df is None:
            print('[SKIP] education 원천 데이터 없음 '
                  '(DB education_stg 또는 data/raw_csv/education.csv) — education_raw 폴백 시도')
    else:
        raw_path = find_latest(raw_dir, EDUCATION_PATTERN)
        if raw_path is not None:
            df = read_xlsx(raw_path, header_row=_EDUCATION_HEADER_ROW)
        else:
            df = None
            print(f'[SKIP] {EDUCATION_PATTERN} 파일 없음({raw_dir})')

    if df is None:
        return False
    df.columns = [str(c).strip() for c in df.columns]

    if COL_ID not in df.columns:
        print(
            f'[ERROR] 필수 컬럼 없음: [{COL_ID}]\n'
            f'  process_education.py 상단의 COL_ID를 실제 헤더에 맞게 수정하세요.\n'
            f'  현재 파일 헤더: {list(df.columns)}'
        )
        return False

    df['researcher_id'] = df[COL_ID].apply(norm_id)
    df = df[df['researcher_id'] != ''].copy()

    def _col(name):
        return df[name].astype(str).str.strip() if name in df.columns else pd.Series('', index=df.index)

    df['_degree_std'] = _col(COL_DEGREE).apply(_normalize_degree)

    yr_series   = df[COL_GRAD_YEAR] if COL_GRAD_YEAR in df.columns else pd.Series('', index=df.index)
    date_series = df[COL_GRAD_DATE] if COL_GRAD_DATE in df.columns else pd.Series('', index=df.index)
    df['_grad_year'] = [_extract_year(y, d) for y, d in zip(yr_series, date_series)]

    rows = []
    for rid, grp in df.groupby('researcher_id'):
        # 최종학력(DEG_ORDER 우선순위상 가장 높은 표준 학위) 판정 — DEG_ORDER의
        # 키 순회 순서가 곧 박사>석사>학사>전문대>고교 우선순위다. 5가지 표준
        # 학위 중 어디에도 안 맞는 원본 표기만 있으면(전부 매칭 실패) 최종학력을
        # 판정할 수 없으므로 keep_set=None으로 두어 이 사람 행은 필터 없이
        # 전부 통과시킨다(기존 동작 유지).
        present = set(grp['_degree_std'])
        final_degree = next((d for d in DEG_ORDER if d in present), None)
        keep_set = _KEEP_MAP.get(final_degree) if final_degree else None
        for _, row in grp.iterrows():
            deg = row['_degree_std']
            # keep_set에 없는 표준 학위만 제외한다 — 표준 학위가 아닌 원본
            # 표기(deg not in DEG_ORDER)는 이 필터 대상이 아니라 항상 통과.
            if keep_set is not None and deg in DEG_ORDER and deg not in keep_set:
                continue
            school = str(row.get(COL_SCHOOL, '')).strip() if COL_SCHOOL in df.columns else ''
            major  = str(row.get(COL_MAJOR,  '')).strip() if COL_MAJOR  in df.columns else ''
            rows.append({
                'researcher_id':   rid,
                'degree':          deg,
                'school':          clean_str(school),
                'major':           clean_str(major),
                'graduation_year': row['_grad_year'],
            })

    result = pd.DataFrame(rows, columns=['researcher_id', 'degree', 'school', 'major', 'graduation_year'])
    result['_ord'] = result['degree'].map(DEG_ORDER).fillna(5)
    result = (result
              .sort_values(['researcher_id', '_ord'])
              .drop(columns=['_ord'])
              .reset_index(drop=True))

    out_path = os.path.join(OUT_DIR, 'education.csv')
    merged = write_merged(out_path, result, TABLE_KEYS['education'])

    n = merged['researcher_id'].nunique()
    print(f'[OK]   education.csv 저장 (총 {len(merged)}행, {n}명, 이번 파일 {len(result)}행 반영)')
    return True


if __name__ == '__main__':
    process()
