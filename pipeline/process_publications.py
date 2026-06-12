"""
논문 현황 전처리
Source : data/raw/개인별논문현황_2016_2026.xlsx  (헤더: 3번째 행, header_row=2)
Output : data/processed/publications.csv

컬럼 매핑:
  사번          → researcher_id  (8자리 제로패딩)
  저자구분       → author_type
  교신저자여부   → is_corresponding
  논문제목       → title
  게재/발표처    → journal
  발표형태       → pub_type
  실적일         → pub_date  (YYYYMMDD → YYYY-MM-DD), pub_year 파생
  저자순위       → author_rank  (정수)
  총저자수       → total_authors (정수)
  전체 저자정보 → author_info + 기여도 파생
    └ 마지막 '(기여도 : XX%)' 추출 → contribution 컬럼 (정수 %, 없으면 빈 문자열)
"""

import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR  = os.path.join(BASE_DIR, 'data', 'raw')
OUT_DIR  = os.path.join(BASE_DIR, 'data', 'processed')

SOURCE = os.path.join(RAW_DIR, '개인별논문현황_2016_2026.xlsx')
OUTPUT = os.path.join(OUT_DIR, 'publications.csv')

# 원본 컬럼 이름
COL_ID          = '사번'
COL_AUTHOR_TYPE = '저자구분'
COL_CORR        = '교신저자여부'
COL_TITLE       = '논문제목'
COL_JOURNAL     = '게재/발표처'
COL_PUB_TYPE    = '발표형태'
COL_DATE        = '실적일'
COL_RANK        = '저자순위'
COL_TOTAL       = '총저자수'
COL_AUTHOR_INFO = '전체 저자정보'

REQUIRED_COLS = [
    COL_ID, COL_AUTHOR_TYPE, COL_CORR, COL_TITLE,
    COL_JOURNAL, COL_PUB_TYPE, COL_DATE, COL_RANK,
    COL_TOTAL, COL_AUTHOR_INFO,
]

_CONTRIBUTION_RE = re.compile(r'\(기여도\s*:\s*(\d+)\s*%\)\s*$')


def _parse_date(val) -> str:
    """YYYYMMDD(숫자 또는 문자열) → YYYY-MM-DD. 변환 불가 시 빈 문자열."""
    if val is None:
        return ''
    s = str(val).strip().split('.')[0]
    if s in ('', 'nan', 'None', 'NaT'):
        return ''
    if len(s) == 8 and s.isdigit():
        return f'{s[:4]}-{s[4:6]}-{s[6:]}'
    # 이미 YYYY-MM-DD 형태인 경우
    if len(s) >= 10 and s[4] == '-':
        return s[:10]
    return s


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


def process():
    from excel_reader import norm_id, read_xlsx

    if not os.path.exists(SOURCE):
        print(f'[process_publications] 파일 없음: {SOURCE}')
        return

    print(f'[process_publications] 읽는 중: {SOURCE}  (헤더: 3번째 행)')
    df = read_xlsx(SOURCE, header_row=2)

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        print(f'[process_publications] 컬럼 없음: {missing}')
        print(f'  실제 컬럼: {list(df.columns)}')
        return

    result = pd.DataFrame({
        'researcher_id':  df[COL_ID].apply(norm_id),
        'author_type':    df[COL_AUTHOR_TYPE].astype(str).str.strip(),
        'is_corresponding': df[COL_CORR].apply(_parse_is_corresponding),
        'title':          df[COL_TITLE].astype(str).str.strip(),
        'journal':        df[COL_JOURNAL].astype(str).str.strip(),
        'pub_type':       df[COL_PUB_TYPE].astype(str).str.strip(),
        'pub_date':       df[COL_DATE].apply(_parse_date),
        'author_rank':    df[COL_RANK].apply(_parse_int),
        'total_authors':  df[COL_TOTAL].apply(_parse_int),
        'author_info':    df[COL_AUTHOR_INFO].apply(_strip_contribution),
        'contribution':   df[COL_AUTHOR_INFO].apply(_extract_contribution),
    })

    # pub_year: pub_date 앞 4자리
    result['pub_year'] = result['pub_date'].str[:4].where(
        result['pub_date'].str.len() >= 4, ''
    )

    result = result[result['researcher_id'] != ''].reset_index(drop=True)
    result = result.sort_values(['researcher_id', 'pub_date'], ascending=[True, False]).reset_index(drop=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    result.to_csv(OUTPUT, index=False, encoding='utf-8-sig')
    print(f'[process_publications] 저장 완료: {OUTPUT}  ({len(result)}행)')


if __name__ == '__main__':
    process()
