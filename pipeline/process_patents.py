"""
특허 리스트 처리 모듈

원천: source_reader.read_source('patents')
  → DB patents_stg 테이블 또는 data/raw_csv/patents.csv
  (1단계 xlsx_to_raw_csv.py가 data/raw/특허 리스트.xlsx를 DRM 제거해 만든 사본)
출력 파일: data/processed/patents.csv

처리 로직:
  - 동일 접수ID → 동일 특허 (발명자별 1행 유지)
  - 사번으로 발명자(연구원) 구분, 8자리 텍스트로 정규화
  - status: 원본 '진행상태' 컬럼을 쓰지 않고, 등록번호·출원번호 값 존재 여부로 도출
      등록번호 있음        → '등록'
      등록번호 없고 출원번호 있음 → '출원'
      둘 다 없음           → '' (공란)
  - 기술건(representative_invention, 2026-10 추가): 같은 특허를 여러 나라에
    출원하면 국가별로 여러 행이 생기는데, 그중 이 특허를 대표하는 행만
    'Y'/'y'로 표시한다. **Y/y인 행만 유효한 발명건으로 저장**하고 나머지는
    버린다(건수·지분율이 국가 수만큼 부풀지 않도록). 원본에 '기술건' 컬럼이
    없으면 모든 행이 유효하지 않은 것으로 보고, 기존 patents.csv를 지우는
    사고를 막기 위해 아무것도 저장하지 않고 중단한다. 기존 patents.csv에
    이 컬럼이 없던 시절(legacy)에 쌓인 행은 이번 실행에서 함께 삭제한다.
  - 발명 명칭: title=발명명칭 - 영문, title_ko=발명명칭 - 국문. 화면은 국문을
    우선하고 비어 있으면 영문으로 대체한다.
  - project_name/project_code: 원본에 '과제명'/'과제코드' 컬럼이 있으면 함께
    저장(OPTIONAL_COLS). 타임라인(components/timeline_data.py)에서 이 특허가
    어떤 과제(task_name/task_code)에 속하는지 연결하는 데 쓰인다. 원본에
    해당 컬럼이 없거나 값이 비어 있으면 빈 문자열로 남고, 타임라인에서는
    "과제에 속하지 않는 특허"로 표시된다.

컬럼 설정 (실제 파일 헤더에 맞게 상단 상수 수정):
  COL_ID      : 사번 컬럼명
  COL_APP_ID  : 접수ID 컬럼명
  COL_TITLE   : 발명명칭 - 영문 컬럼명
  COL_TITLE_KO: 발명명칭 - 국문 컬럼명
  COL_REP     : 기술건(유효 발명건 Y/y) 컬럼명
  COL_SHARE   : 지분율 컬럼명
  COL_LEAD    : 대표발명자여부 컬럼명
  COL_GRADE   : 현재등급 컬럼명
  COL_GRADE_A : 현재등급 - A급구분 컬럼명
"""

import os
import sys

import pandas as pd

PATENT_FILE = '특허 리스트.xlsx'
_PATENT_HEADER_ROW = 0  # sources.py 매니페스트 기준 (1번째 행)

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_ID       = '사번'
COL_APP_ID   = '접수ID'
COL_TITLE    = '발명명칭 - 영문'
COL_TITLE_KO = '발명명칭 - 국문'
COL_REP      = '기술건'
COL_SHARE    = '지분율'
COL_LEAD     = '대표발명자여부'
COL_GRADE    = '현재등급'
COL_GRADE_A  = '현재등급 - A급구분'

# 있으면 추가로 가져오는 선택 컬럼 (원본명 → CSV 컬럼명)
# project_name/project_code: 타임라인에서 특허를 과제(task_name/task_code)와
# 연결하는 데 사용(components/timeline_data.py). 원본에 없으면 빈 값으로 남고,
# 이 경우 타임라인에서는 "과제에 속하지 않는 특허"로 표시된다.
OPTIONAL_COLS = [
    ('출원번호', 'application_no'),
    ('출원일',   'application_date'),
    ('출원일자', 'application_date'),   # '출원일' 없으면 '출원일자' 시도
    ('등록번호', 'registration_no'),
    ('등록일',   'registration_date'),
    ('등록일자', 'registration_date'),  # '등록일' 없으면 '등록일자' 시도
    ('국가',     'country'),
    ('국가명',   'country'),   # '국가' 없으면 '국가명' 시도
    ('과제명',   'project_name'),
    ('과제코드', 'project_code'),
]
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import is_blank, parse_yyyymmdd, read_xlsx, norm_id
from merge_utils import TABLE_KEYS, write_merged
from source_reader import read_source

_DATE_DST_COLS = {'application_date', 'registration_date'}


def _purge_stale_rows(out_path: str, new_file_app_ids: set) -> None:
    """병합 전에 기존 patents.csv에서 (1) 기술건 컬럼이 없던 시절의 legacy 행 전체,
    (2) 이번 파일에 다시 등장한 접수ID의 기존 행(유효 여부가 바뀌었을 수 있음)을
    지운다. 나머지 기존 유효 행은 그대로 두고 write_merged()가 업서트한다."""
    import csv as _csv
    from merge_utils import read_existing

    existing = read_existing(out_path)
    if existing.empty:
        return
    if 'representative_invention' not in existing.columns:
        kept = existing.iloc[0:0]
        print(f'[patents] 기존 patents.csv {len(existing)}행은 기술건 도입 이전 데이터라 삭제합니다.')
    else:
        keep = (existing['representative_invention'].astype(str).str.strip().str.upper() == 'Y') \
            & ~existing['application_id'].astype(str).str.strip().isin(new_file_app_ids)
        kept = existing[keep]
        if len(kept) != len(existing):
            print(f'[patents] 기존 {len(existing) - len(kept)}행 정리(재등장 접수ID/유효하지 않은 행).')
    kept.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=_csv.QUOTE_NONNUMERIC)


def process(raw_dir: str = RAW_DIR) -> bool:
    if raw_dir == RAW_DIR:
        df = read_source('patents')
        if df is None:
            print('[SKIP] patents 원천 데이터 없음 '
                  '(DB patents_stg 또는 data/raw_csv/patents.csv) — patents_raw 폴백 시도')
    else:
        raw_path = os.path.join(raw_dir, PATENT_FILE)
        if os.path.exists(raw_path):
            df = read_xlsx(raw_path, header_row=_PATENT_HEADER_ROW)
        else:
            df = None
            print(f'[SKIP] {PATENT_FILE} 파일 없음({raw_dir})')

    if df is None:
        return False

    # 컬럼명 앞뒤 공백·숨김문자 제거 (Excel에서 흔히 발생)
    df.columns = [str(c).strip() for c in df.columns]

    missing = [c for c in [COL_ID, COL_APP_ID] if c not in df.columns]
    if missing:
        print(
            f'[ERROR] 필수 컬럼 없음: {missing}\n'
            f'  process_patents.py 상단의 컬럼명 상수를 실제 헤더에 맞게 수정하세요.\n'
            f'  현재 파일 헤더: {list(df.columns)}'
        )
        return False

    if COL_REP not in df.columns:
        print(
            f'[ERROR] 필수 컬럼 없음: [{COL_REP}] — 기술건이 Y/y인 행만 유효한 발명건이라 '
            f'이 컬럼이 없으면 저장할 데이터가 없습니다(기존 patents.csv는 그대로 둡니다).\n'
            f'  현재 파일 헤더: {list(df.columns)}'
        )
        return False

    # 사번 정규화
    df['researcher_id'] = df[COL_ID].apply(norm_id)
    df = df[df['researcher_id'] != ''].copy()

    # 기술건(대표 행) 필터 — 국가별로 여러 행인 같은 특허가 여러 건으로 보이지 않게
    # Y/y인 행만 남긴다. 이번 파일에 등장한 접수ID는(유효 행이 없더라도) 기존
    # 저장분에서 먼저 지워 두어, 예전에 유효로 저장됐던 행이 남지 않게 한다.
    all_app_ids = set(df[COL_APP_ID].astype(str).str.strip())
    df = df[df[COL_REP].astype(str).str.strip().str.upper() == 'Y'].copy()
    if df.empty:
        print('[ERROR] 기술건이 Y인 유효 발명건이 없습니다 — 기존 patents.csv는 그대로 둡니다.')
        return False

    # ── 핵심 컬럼 매핑 ─────────────────────────────────────────────────────────
    def _col(name):
        return df[name].astype(str).str.strip() if name in df.columns else pd.Series('', index=df.index)

    result = pd.DataFrame({
        'researcher_id':      df['researcher_id'],
        'application_id':     _col(COL_APP_ID),
        'representative_invention': 'Y',
        'title':              _col(COL_TITLE),
        'title_ko':           _col(COL_TITLE_KO),
        'share_ratio':        _col(COL_SHARE),
        'is_lead_inventor':   _col(COL_LEAD),
        'patent_grade':       _col(COL_GRADE),
        'patent_grade_a_sub': _col(COL_GRADE_A),
    })

    # ── 선택 컬럼 (출원번호·출원일·등록번호·등록일·국가) ──────────────────────
    filled = set()
    for src_col, dst_col in OPTIONAL_COLS:
        if dst_col in filled:
            continue
        if src_col in df.columns:
            if dst_col in _DATE_DST_COLS:
                result[dst_col] = df[src_col].apply(parse_yyyymmdd)
            else:
                result[dst_col] = df[src_col].astype(str).str.strip()
            filled.add(dst_col)
    for dst_col in ['application_no', 'application_date', 'registration_no',
                    'registration_date', 'country', 'project_name', 'project_code']:
        if dst_col not in result.columns:
            result[dst_col] = ''

    # ── status 도출: 등록번호 있으면 '등록', 없고 출원번호 있으면 '출원', 둘 다 없으면 공란 ──
    def _has_value(series):
        return ~series.apply(is_blank)

    result['status'] = ''
    result.loc[_has_value(result['application_no']), 'status'] = '출원'
    result.loc[_has_value(result['registration_no']), 'status'] = '등록'

    result = result.sort_values(['researcher_id', 'application_id']).reset_index(drop=True)

    out_path = os.path.join(OUT_DIR, 'patents.csv')
    _purge_stale_rows(out_path, all_app_ids)
    merged = write_merged(out_path, result, TABLE_KEYS['patents'])

    n_patents   = merged['application_id'].nunique()
    n_inventors = merged['researcher_id'].nunique()
    print(f'[OK]   patents.csv 저장 (총 {len(merged)}행 / 특허 {n_patents}건 / 발명자 {n_inventors}명, 이번 파일 {len(result)}행 반영)')
    return True


if __name__ == '__main__':
    process()
