"""
"기간(날짜 범위)/시점 지정 조회"가 공유하는 이력 테이블(`<table>_history.csv`,
`researcher_id + valid_year + valid_month` 자연키) 스냅샷 계산 유틸.

원래 `pages/researcher_list.py`의 "누적기준 + 기간 지정" 명단 조회
(2026-08-28) 전용으로 만들어졌던 `_resolve_period_snapshot()`을 그대로
옮긴 것 — `pipeline/process_researcher_expertise.py`의 "과거 시점 온디맨드
전문성 분석"(2026-08-29)도 같은 함수가 필요해, 파이프라인 스크립트가
`pages/*.py`를 import하는 어색한 역방향 의존을 피하려고 공용 서비스
모듈로 옮겼다(동작은 완전히 동일, 호출부만 바뀜).
"""

from datetime import date

import pandas as pd

from services.data_store import read_processed


def resolve_period_snapshot(period: tuple[date, date], table: str = 'researchers_history') -> pd.DataFrame:
    """<table>(기본 researchers_history.csv, researcher_id+valid_year+
    valid_month 자연키를 가진 이력 테이블이면 재사용 가능 — evaluations_
    history.csv/job_profile_history.csv 등)에서 period=(시작일, 종료일)
    구간에 속하는 (valid_year, valid_month) 스냅샷만 골라, researcher_id별로
    그 구간 안에서 가장 최근 스냅샷 1행을 대표값으로 돌려준다 — "이 기간
    동안 소속돼 있었고, 그 기간의 마지막 시점엔 이런 상태였다"는 의미
    (2026-08-28, data/processed/CLAUDE.md 참고). 구간에 스냅샷이 하나도
    없는 사람은 결과에서 빠진다(그 기간엔 존재를 확인할 수 없으므로).

    "특정 시점 하나"만 필요하면 period=(아주 이른 날짜, 그 시점)으로 호출하면
    된다 — "그 시점까지의 최신 스냅샷"이 그대로 나온다(온디맨드 전문성 분석이
    이 방식으로 사용).

    항상 'researcher_id' 컬럼이 있는 DataFrame을 반환한다(구간에 스냅샷이
    하나도 없어도 0행짜리 빈 DataFrame — 완전히 빈 pd.DataFrame()을 반환하면
    호출부의 `eva['researcher_id']`가 KeyError로 죽는다, 2026-08-29 발견·수정)."""
    hist = read_processed(table)
    if hist.empty or not {'valid_year', 'valid_month'} <= set(hist.columns):
        return pd.DataFrame(columns=['researcher_id'])

    start, end = period
    start_key = (start.year, start.month)
    end_key = (end.year, end.month)

    def _period_key(row):
        y, m = str(row.get('valid_year', '')), str(row.get('valid_month', ''))
        if not y or not m:
            return None
        try:
            return (int(y), int(m))
        except ValueError:
            return None

    hist = hist.copy()
    hist['_period_key'] = hist.apply(_period_key, axis=1)
    in_range = hist[hist['_period_key'].apply(lambda k: k is not None and start_key <= k <= end_key)]
    if in_range.empty:
        # 구간에 스냅샷이 하나도 없어도 in_range 자체엔 이미 원본 컬럼
        # ('researcher_id' 포함)이 있으므로 그대로 반환한다(0행) — 완전히
        # 빈 pd.DataFrame()을 반환하면 컬럼 자체가 없어 호출부가 죽는다.
        return in_range.drop(columns=['_period_key'])

    # researcher_id별로 구간 내 최댓값(가장 최근) 스냅샷만 남긴다.
    in_range = in_range.sort_values(['researcher_id', '_period_key'])
    latest = in_range.drop_duplicates(subset=['researcher_id'], keep='last')
    return latest.drop(columns=['_period_key']).reset_index(drop=True)
