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

── 예외자 override(exception_job_function.csv, 2026-09-09 추가) ──────────────
특정 연구원은 위 매칭 결과와 무관하게 SAIT 직군만 강제로 다른 값으로
표시해야 할 수 있다(예: 원래 로직대로면 R직군이어야 하지만 예외자 명단에
있어 E직군으로 표기). exception_job_function.csv(researcher_id 키)에
등록된 사람은 SAIT 직군을 그 파일의 exception_job_category 값으로
override한다 — DS 직군은 그대로 매칭 결과 유지. 이 override는 기본 매칭의
성공/실패와 완전히 무관하게 항상 적용된다(사용자 확정) — job_function이
mapping_job_function.csv에 없어 DS가 '-'인 사람도, exception 명단에
있으면 SAIT는 예외값으로 표시된다.

이 모듈이 유일한 매칭/override 창구다 — 연구원 개별 프로필(pages/
researcher_profile.py)과 전문성 MAP 유사 연구원 지도 호버 라벨
(services/similarity_map.py)이 함께 재사용한다.
"""

import pandas as pd

_BLANK = '-'


def _clean(val) -> str:
    s = str(val or '').strip()
    return '' if s.lower() in ('nan', 'none', 'nat') else s


def _exception_map(exception_df: pd.DataFrame | None) -> dict:
    """researcher_id -> exception_job_category. 값이 비어있으면 '-'.
    researcher_id가 중복이면(전처리 단계에서 이미 걸러지지만 방어적으로)
    첫 번째 행만 채택."""
    result: dict[str, str] = {}
    if exception_df is None or exception_df.empty or 'researcher_id' not in exception_df.columns:
        return result
    deduped = exception_df.drop_duplicates(subset=['researcher_id'], keep='first')
    for _, row in deduped.iterrows():
        rid = _clean(row.get('researcher_id'))
        if not rid:
            continue
        result[rid] = _clean(row.get('exception_job_category')) or _BLANK
    return result


def build_job_category_map(researchers_df: pd.DataFrame, mapping_df: pd.DataFrame,
                            exception_df: pd.DataFrame | None = None) -> dict:
    """researcher_id -> (job_category_DS, job_category_SAIT) 매핑을 한 번에
    만든다(여러 연구원을 순회할 때 매번 매핑표를 다시 조회하지 않도록).
    빈 값/매칭 실패는 전부 ('-', '-'). exception_df에 등록된 researcher_id는
    SAIT만 예외값으로 override(DS는 그대로)."""
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

    exception_map = _exception_map(exception_df)

    for _, row in researchers_df.iterrows():
        rid = _clean(row.get('researcher_id'))
        if not rid:
            continue
        job_function = _clean(row.get('job_function'))
        ds, sait = job_lookup.get(job_function, (_BLANK, _BLANK))
        if rid in exception_map:
            sait = exception_map[rid]
        result[rid] = (ds, sait)
    return result


def job_category_for(rid: str, researchers_df: pd.DataFrame, mapping_df: pd.DataFrame,
                      exception_df: pd.DataFrame | None = None) -> tuple:
    """연구원 1명분만 필요할 때(build_job_category_map()을 전체 빌드하지
    않고 바로 조회) — 연구원 개별 프로필 화면/인쇄 카드가 사용. exception_df에
    이 rid가 등록돼 있으면 기본 매칭 성공/실패와 무관하게 SAIT를 예외값으로
    override한다(DS는 그대로)."""
    ds, sait = _BLANK, _BLANK
    if (
        researchers_df is not None and not researchers_df.empty
        and mapping_df is not None and not mapping_df.empty
        and 'researcher_id' in researchers_df.columns
        and 'job_function' in mapping_df.columns
    ):
        rows = researchers_df[researchers_df['researcher_id'] == rid]
        if not rows.empty:
            job_function = _clean(rows.iloc[0].get('job_function'))
            if job_function:
                match = mapping_df[mapping_df['job_function'] == job_function]
                if not match.empty:
                    m = match.iloc[0]
                    ds = _clean(m.get('job_category_DS')) or _BLANK
                    sait = _clean(m.get('job_category_SAIT')) or _BLANK

    exception_map = _exception_map(exception_df)
    if rid in exception_map:
        sait = exception_map[rid]
    return ds, sait
