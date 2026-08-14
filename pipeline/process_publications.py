"""
논문 현황 전처리
Source : 기본은 source_reader.read_source('publications')
         → DB publications_stg 테이블 또는 data/raw_csv/publications.csv
         (1단계 xlsx_to_raw_csv.py가 data/raw/개인별논문현황_2016_2026.xlsx를
          DRM 제거해 만든 사본 — 헤더 행 위치(1번째 행, header_row=0)는 그 단계에서
          이미 처리됨). raw_dir이 명시적으로 오버라이드되면(예: data/updates) 그
          폴더의 xlsx를 header_row=0으로 직접 읽는다.
Output : data/processed/publications.csv

컬럼 매핑:
  사번          → researcher_id  (8자리 제로패딩)
  저자구분       → author_type
  교신저자여부   → is_corresponding
  논문제목       → title
  게재/발표처    → journal
  발표형태       → pub_type
  진행상태       → paper_status  (텍스트, 예: 최종완료/ACCEPT 완료)
  발표일         → announce_date  (YYYYMMDD → YYYY-MM-DD)
  실적일         → pub_date  (YYYYMMDD → YYYY-MM-DD), pub_year 파생
    └ paper_status가 "최종완료" 또는 "ACCEPT 완료"(공백·대소문자 무관)이고
      실적일 또는 발표일 중 하나라도 있는 행만 결과에 포함한다(실적일이
      없으면 발표일로 대체). 그 외 행(진행상태가 유효하지 않거나, 유효해도
      실적일·발표일이 둘 다 없는 경우)은 통째로 제외한다.
  저자순위       → author_rank  (정수)
  총저자수       → total_authors (정수)
  전체 저자정보 → author_info + 기여도 파생
    └ 마지막 '(기여도 : XX%)' 추출 → contribution 컬럼 (정수 %, 없으면 빈 문자열)
  과제명   → project_name (선택, 원본에 없으면 빈 문자열)
  과제코드 → project_code (선택, 원본에 없으면 빈 문자열)
    └ 타임라인(components/timeline_data.py)에서 이 논문이 어떤 과제
      (task_name/task_code)에 속하는지 연결하는 데 쓰인다. 값이 없거나
      매칭되는 과제가 없으면 "과제에 속하지 않는 논문"으로 표시된다.
"""

import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from merge_utils import TABLE_KEYS, write_merged  # noqa: E402

SOURCE_FILE = '개인별논문현황_2016_2026.xlsx'
_PUBLICATIONS_HEADER_ROW = 0  # sources.py 매니페스트 기준 (1번째 행)
OUTPUT = os.path.join(OUT_DIR, 'publications.csv')

# 원본 컬럼 이름
COL_ID          = '사번'
COL_AUTHOR_TYPE = '저자구분'
COL_CORR        = '교신저자여부'
COL_TITLE       = '논문제목'
COL_JOURNAL     = '게재/발표처'
COL_PUB_TYPE    = '발표형태'
COL_STATUS      = '진행상태'
COL_ANNOUNCE    = '발표일'
COL_DATE        = '실적일'
COL_RANK        = '저자순위'
COL_TOTAL       = '총저자수'
COL_AUTHOR_INFO = '전체 저자정보'

REQUIRED_COLS = [
    COL_ID, COL_AUTHOR_TYPE, COL_CORR, COL_TITLE,
    COL_JOURNAL, COL_PUB_TYPE, COL_STATUS, COL_ANNOUNCE, COL_DATE, COL_RANK,
    COL_TOTAL, COL_AUTHOR_INFO,
]

# 실적일을 유효한 값으로 카운트하는 진행상태(공백 제거 + 대소문자 무관 비교)
_VALID_STATUS_VALUES = ('최종완료', 'ACCEPT 완료')


def _normalize_status(val) -> str:
    return re.sub(r'\s+', '', str(val or '')).upper()


_VALID_STATUS_NORM = {_normalize_status(v) for v in _VALID_STATUS_VALUES}

# 있으면 추가로 가져오는 선택 컬럼(없어도 처리 계속, 빈 문자열로 채움)
COL_PROJECT_NAME = '과제명'
COL_PROJECT_CODE = '과제코드'

_CONTRIBUTION_RE = re.compile(r'\(기여도\s*:\s*(\d+)\s*%\)\s*$')


def _parse_int(val) -> str:
    """정수 변환. 실패 시 빈 문자열."""
    try:
        s = str(val).strip().split('.')[0]
        if s.lower() in ('', 'nan', 'none', 'nat'):
            return ''
        return str(int(s))
    except (ValueError, TypeError):
        return ''


def _extract_contribution(val) -> str:
    """'전체 저자정보' 값 마지막의 '(기여도 : XX%)' 에서 숫자만 추출."""
    if val is None:
        return ''
    s = str(val).strip()
    m = _CONTRIBUTION_RE.search(s)
    return m.group(1) if m else ''


def _strip_contribution(val) -> str:
    """'전체 저자정보' 에서 끝의 '(기여도 : XX%)' 부분을 제거한 텍스트."""
    if val is None:
        return ''
    return _CONTRIBUTION_RE.sub('', str(val)).strip()


def _parse_is_corresponding(val) -> bool:
    """교신저자여부 → True/False."""
    s = str(val).strip().lower() if val is not None else ''
    return s in ('y', 'yes', '예', 'o', '○', '1', 'true', '교신')


def process(raw_dir: str = RAW_DIR) -> bool:
    from excel_reader import norm_id, parse_yyyymmdd, read_xlsx
    from source_reader import read_source

    if raw_dir == RAW_DIR:
        df = read_source('publications')
        if df is None:
            print('[process_publications] 원천 데이터 없음 '
                  '(DB publications_stg 또는 data/raw_csv/publications.csv)')
            return False
    else:
        source = os.path.join(raw_dir, SOURCE_FILE)
        if not os.path.exists(source):
            print(f'[process_publications] 파일 없음: {source}')
            return False
        print(f'[process_publications] 읽는 중: {source}  (헤더: 3번째 행)')
        df = read_xlsx(source, header_row=_PUBLICATIONS_HEADER_ROW)

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        print(f'[process_publications] 컬럼 없음: {missing}')
        print(f'  실제 컬럼: {list(df.columns)}')
        return False

    paper_status = df[COL_STATUS].astype(str).str.strip()
    raw_pub_date = df[COL_DATE].apply(parse_yyyymmdd)
    announce_date = df[COL_ANNOUNCE].apply(parse_yyyymmdd)
    is_valid_status = paper_status.apply(_normalize_status).isin(_VALID_STATUS_NORM)
    # 유효한 진행상태에서 실적일이 비어 있으면 발표일로 대체한다.
    pub_date = raw_pub_date.mask(raw_pub_date == '', announce_date)

    # 진행상태가 유효하지 않거나(최종완료/ACCEPT 완료가 아님), 유효하더라도
    # 실적일·발표일이 둘 다 없어 실적일을 채울 수 없는 행은 통째로 제외한다.
    keep = is_valid_status & (pub_date != '')
    df = df[keep].reset_index(drop=True)
    paper_status = paper_status[keep].reset_index(drop=True)
    announce_date = announce_date[keep].reset_index(drop=True)
    pub_date = pub_date[keep].reset_index(drop=True)

    result = pd.DataFrame({
        'researcher_id':  df[COL_ID].apply(norm_id),
        'author_type':    df[COL_AUTHOR_TYPE].astype(str).str.strip(),
        'is_corresponding': df[COL_CORR].apply(_parse_is_corresponding),
        'title':          df[COL_TITLE].astype(str).str.strip(),
        'journal':        df[COL_JOURNAL].astype(str).str.strip(),
        'pub_type':       df[COL_PUB_TYPE].astype(str).str.strip(),
        'paper_status':   paper_status,
        'announce_date':  announce_date,
        'pub_date':       pub_date,
        'author_rank':    df[COL_RANK].apply(_parse_int),
        'total_authors':  df[COL_TOTAL].apply(_parse_int),
        'author_info':    df[COL_AUTHOR_INFO].apply(_strip_contribution),
        'contribution':   df[COL_AUTHOR_INFO].apply(_extract_contribution),
    })

    result['project_name'] = df[COL_PROJECT_NAME].astype(str).str.strip() if COL_PROJECT_NAME in df.columns else ''
    result['project_code'] = df[COL_PROJECT_CODE].astype(str).str.strip() if COL_PROJECT_CODE in df.columns else ''

    # pub_year: pub_date 앞 4자리
    result['pub_year'] = result['pub_date'].str[:4].where(
        result['pub_date'].str.len() >= 4, ''
    )

    result = result[result['researcher_id'] != ''].reset_index(drop=True)
    result = result.sort_values(['researcher_id', 'pub_date'], ascending=[True, False]).reset_index(drop=True)

    merged = write_merged(OUTPUT, result, TABLE_KEYS['publications'])
    print(f'[process_publications] 저장 완료: {OUTPUT}  (총 {len(merged)}행, 이번 파일 {len(result)}행 반영)')
    return True


if __name__ == '__main__':
    process()
