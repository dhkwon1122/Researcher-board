"""직무_직군_맵핑(mapping_job_function.csv) 기반 DS/SAIT 직군 조회.

기존에는 연구원 개별 프로필 "보유기술" 배지가 tech_ownership.csv의
E_support 컬럼만 보고 R직군/E직군 하나만 표시했는데(components/
detail_tabs.py의 옛 `_e_support_pill()`), 이걸 job_category_DS/
job_category_SAIT 두 개 값으로 교체했다(2026-09-04, 사용자 확정).

매칭 규칙: mapping_job_function.csv에는 researcher_id가 없다(순수
job_function 텍스트 키 참조 테이블) — researchers.csv에서 그 연구원의
job_function 값을 먼저 찾은 뒤, 그 값을 mapping_job_function.csv의
job_function과 텍스트로 비교해 일치하는 행의 job_category_DS/
job_category_SAIT를 가져온다. 매칭 실패(job_function이 비어있거나
매핑표에 없음)이거나 매칭은 됐지만 값이 비어있으면 둘 다 '-'.

이 모듈이 유일한 매칭 창구다 — 연구원 개별 프로필(pages/
researcher_profile.py)과 전문성 MAP 유사 연구원 지도 호버 라벨
(services/similarity_map.py)이 함께 재사용한다.
"""

import pandas as pd

_BLANK = '-'


def _clean(val) -> str:
    s = str(val or '').strip()
    return '' if s.lower() in ('nan', 'none', 'nat') else s


def build_job_category_map(researchers_df: pd.DataFrame, mapping_df: pd.DataFrame) -> dict:
    """researcher_id -> (job_category_DS, job_category_SAIT) 매핑을 한 번에
    만든다(여러 연구원을 순회할 때 매번 매핑표를 다시 조회하지 않도록).
    빈 값/매칭 실패는 전부 ('-', '-')."""
    result: dict[str, tuple[str, str]] = {}
    if researchers_df is None or researchers_df.empty or 'researcher_id' not in researchers_df.columns:
        return result

    job_lookup: dict[str, tuple[str, str]] = {}
    if mapping_df is not None and not mapping_df.empty and 'job_function' in mapping_df.columns:
        # job_function이 중복되면(전처리 단계에서 이미 걸러지지만 방어적으로)
        # 첫 번째 행만 채택 — 항상 1:1 매칭이 되도록 한다.
        deduped = mapping_df.drop_duplicates(subset=['job_function'], keep='first')
        for _, row in deduped.iterrows():
            key = _clean(row.get('job_function'))
            if not key:
                continue
            job_lookup[key] = (
                _clean(row.get('job_category_DS')) or _BLANK,
                _clean(row.get('job_category_SAIT')) or _BLANK,
            )

    for _, row in researchers_df.iterrows():
        rid = _clean(row.get('researcher_id'))
        if not rid:
            continue
        job_function = _clean(row.get('job_function'))
        result[rid] = job_lookup.get(job_function, (_BLANK, _BLANK))
    return result


def job_category_for(rid: str, researchers_df: pd.DataFrame, mapping_df: pd.DataFrame) -> tuple:
    """연구원 1명분만 필요할 때(build_job_category_map()을 전체 빌드하지
    않고 바로 조회) — 연구원 개별 프로필 화면/인쇄 카드가 사용."""
    if (
        researchers_df is None or researchers_df.empty
        or mapping_df is None or mapping_df.empty
        or 'researcher_id' not in researchers_df.columns
        or 'job_function' not in mapping_df.columns
    ):
        return _BLANK, _BLANK

    rows = researchers_df[researchers_df['researcher_id'] == rid]
    if rows.empty:
        return _BLANK, _BLANK
    job_function = _clean(rows.iloc[0].get('job_function'))
    if not job_function:
        return _BLANK, _BLANK

    match = mapping_df[mapping_df['job_function'] == job_function]
    if match.empty:
        return _BLANK, _BLANK
    m = match.iloc[0]
    return (
        _clean(m.get('job_category_DS')) or _BLANK,
        _clean(m.get('job_category_SAIT')) or _BLANK,
    )
