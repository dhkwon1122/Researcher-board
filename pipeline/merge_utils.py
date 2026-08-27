"""
data/raw 또는 data/updates에서 새로 처리한 DataFrame을 기존 data/processed/*.csv에
업서트(upsert)하는 공용 유틸리티.

동작 원칙: 자연키(natural key)가 일치하는 행은 새 값으로 행 전체를 교체하고,
새로 들어온 파일에 없는 기존 행은 그대로 보존한다(삭제하지 않는다) — 전배·퇴사
등으로 다음 원본 파일에서 빠진 사람의 데이터가 유실되지 않도록 하기 위함
(data/processed/CLAUDE.md '데이터 적재/치환' 절 참고).

TABLE_KEYS: 테이블별 자연키 등록부. 각 process_*.py가 여기서 자기 테이블의
키를 가져다 쓴다 — 키를 바꿀 일이 있으면 이 파일 한 곳만 고치면 된다.
"""

import os

import pandas as pd

# 1인 1행 "현재상태" 테이블 — 키는 researcher_id 하나뿐이라 새 파일에 있으면
# 그 사람 행 전체를 교체, 없으면 보존.
# 이력형(1인 N행) 테이블 — 자연키가 일치하는 이벤트만 교체(정정), 그 외는 누적.
TABLE_KEYS: dict[str, list[str]] = {
    'researchers':          ['researcher_id'],
    'researchers_history':  ['researcher_id', 'valid_year', 'valid_month'],
    'evaluations':          ['researcher_id'],
    'tech_ownership':       ['researcher_id'],
    'job_profile':          ['researcher_id'],
    'work_objective':       ['researcher_id'],
    'hr_orders':            ['researcher_id', 'order_date', 'order_name'],
    'tasks':                ['researcher_id', 'task_name', 'start_date'],
    'patents':               ['application_id', 'researcher_id'],
    'publications':         ['researcher_id', 'title', 'pub_date'],
    'awards':               ['researcher_id', 'award_date', 'award_name'],
    'nurturing':            ['researcher_id', 'start_date', 'category'],
    'core_technology':      ['researcher_id', 'tech_field', 'tech_name'],
    'education':            ['researcher_id', 'degree'],
    'incentive_selection':  ['researcher_id', 'year'],
    'leadership':           ['researcher_id', 'year', 'evaluator_group'],
    'comments':             ['researcher_id', 'year', 'commenter_type'],
    'technology_transfer':  ['researcher_id', 'transfer_date', 'tech_name'],
    'transfers':            ['researcher_id', 'date', 'type'],
    'certifications':       ['researcher_id', 'cert_name', 'date_obtained'],
    'succession':           ['researcher_id', 'org_code', 'rank_type', 'nominated_year'],
    'tasks_information':    ['task_name'],
    'project_confl_address': ['dep_name', 'project_name'],
    # 날짜 기반 누적 테이블 — dep_id별로 valid_year/month/day가 다르면 별개
    # 행으로 계속 쌓인다(같은 날 재저장만 upsert). "현재" 상태는 dep_id별
    # 최신 날짜 행만 골라야 하므로 process_team_refer.py 상단 docstring과
    # rd_specialist_markdown.read_team_refer() 참고.
    'team_refer':            ['dep_id', 'valid_year', 'valid_month', 'valid_day'],

    # ── "현재상태"(1인 1행) 테이블 중 valid_year/valid_month로 시점을 보호하는
    # 4개의 이력 테이블 — write_merged_with_valid_period()가 사용(researcher_id,
    # valid_year, valid_month)가 키라 같은 사람의 같은 연/월 재저장만 그 스냅샷을
    # 덮어쓰고, 다른 연/월은 전부 별도 행으로 계속 쌓인다(researchers_history.csv와
    # 동일한 패턴). 자세한 배경은 write_merged_with_valid_period() docstring 참고.
    'evaluations_history':     ['researcher_id', 'valid_year', 'valid_month'],
    'tech_ownership_history':  ['researcher_id', 'valid_year', 'valid_month'],
    'job_profile_history':     ['researcher_id', 'valid_year', 'valid_month'],
    'work_objective_history':  ['researcher_id', 'valid_year', 'valid_month'],
}

# 평가자 1인 1행이라 행 단위 자연키가 없는 테이블 — group_keys가 일치하는
# 그룹 전체를 새 값으로 교체(그룹 내 개별 행은 통째로 다시 쓴다).
GROUP_REPLACE_KEYS: dict[str, list[str]] = {
    # process_leadership.py가 만드는 leadership_comments.csv는 evaluator_group이
    # 아니라 commenter_type('리더십_<평가자그룹>' 형식) 컬럼을 쓴다 — 이 목록은
    # write_merged()에 그대로 전달돼 new DataFrame에서 이 컬럼명을 찾으므로
    # 실제 컬럼명과 반드시 일치해야 한다.
    'leadership_comments': ['researcher_id', 'year', 'commenter_type'],
}


def read_existing(path: str) -> pd.DataFrame:
    """기존 processed CSV를 문자열 DataFrame으로 읽는다. 파일이 없으면 빈 DataFrame."""
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, encoding='utf-8-sig', dtype=str)
    return df.fillna('')


def _ordered_columns(new: pd.DataFrame, merged: pd.DataFrame) -> list[str]:
    cols = list(new.columns)
    for c in merged.columns:
        if c not in cols:
            cols.append(c)
    return cols


def upsert_merge(existing: pd.DataFrame, new: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """existing/new를 keys 기준으로 병합.

    - new에 있는 키 → 그 행 전체를 새 값으로 교체
    - existing에만 있는 키 → 그대로 보존(삭제하지 않음)
    - new에만 있는 키 → 새 행으로 추가
    - new 안에서 키가 중복되면 마지막 행을 채택한다(같은 실행에서 같은 사람이
      두 번 나오면 파일 안에서 아래에 있는 값이 최종본).

    new가 0행(이번 실행에서 반영할 새 데이터 없음)이면 원칙적으로 existing을
    그대로 보존한다. 다만 existing마저 없으면(최초 실행) new의 컬럼 구조라도
    살려서 반환한다 — 그래야 헤더 없는 빈 CSV가 만들어지는 걸 피할 수 있다.
    """
    if len(new) == 0:
        return existing if not existing.empty else new

    new = new.astype(str)
    for k in keys:
        if k not in new.columns:
            raise KeyError(f'upsert_merge: key column {k!r}가 new DataFrame에 없습니다')
    new = new.drop_duplicates(subset=keys, keep='last')

    if existing.empty or any(k not in existing.columns for k in keys):
        # 기존 파일이 없거나(최초 적재), 키 컬럼이 없던 구버전 스키마면
        # 안전하게 새 결과로 전체 교체한다.
        return new.reset_index(drop=True)

    existing = existing.astype(str)
    existing_idx = existing.set_index(keys)
    new_idx = new.set_index(keys)
    kept = existing_idx[~existing_idx.index.isin(new_idx.index)]
    merged = pd.concat([kept, new_idx]).reset_index()

    merged = merged[_ordered_columns(new, merged)]
    return merged.reset_index(drop=True)


def group_replace_merge(existing: pd.DataFrame, new: pd.DataFrame, group_keys: list[str]) -> pd.DataFrame:
    """group_keys가 일치하는 기존 행들을 전부 지우고 new로 교체한다(그룹 단위
    replace). 행 내에 개별 식별자가 없는 테이블(예: 평가자 1인 1행)에 사용."""
    if len(new) == 0:
        return existing if not existing.empty else new

    new = new.astype(str)
    for k in group_keys:
        if k not in new.columns:
            raise KeyError(f'group_replace_merge: key column {k!r}가 new DataFrame에 없습니다')

    if existing.empty or any(k not in existing.columns for k in group_keys):
        return new.reset_index(drop=True)

    existing = existing.astype(str)
    new_groups = new[group_keys].drop_duplicates()
    new_groups_idx = pd.MultiIndex.from_frame(new_groups) if len(group_keys) > 1 else pd.Index(new_groups[group_keys[0]])
    existing_groups_idx = (
        pd.MultiIndex.from_frame(existing[group_keys]) if len(group_keys) > 1
        else pd.Index(existing[group_keys[0]])
    )
    kept = existing[~existing_groups_idx.isin(new_groups_idx)]
    merged = pd.concat([kept, new], ignore_index=True)
    merged = merged[_ordered_columns(new, merged)]
    return merged.reset_index(drop=True)


def write_merged(out_path: str, new: pd.DataFrame, keys: list[str], *, group_replace: bool = False) -> pd.DataFrame:
    """read_existing → (up)merge → CSV 저장까지 한 번에 처리하는 편의 함수.
    각 process_*.py의 기존 `result.to_csv(out_path, ...)` 한 줄을
    `merge_utils.write_merged(out_path, result, keys)`로 바꿔 쓰면 된다."""
    import csv as _csv

    existing = read_existing(out_path)
    merge_fn = group_replace_merge if group_replace else upsert_merge
    merged = merge_fn(existing, new, keys)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    merged.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=_csv.QUOTE_NONNUMERIC)
    return merged


def write_merged_with_valid_period(out_path: str, hist_path: str, new: pd.DataFrame,
                                    keys: list[str], hist_keys: list[str]) -> dict:
    """T&P(평가)/보유기술/직무이력/업무목표처럼 "1인 1행 현재상태" 테이블에
    시점 보호를 추가한 업서트(사용자 확정 — data/processed/CLAUDE.md 참고).

    new에는 valid_year/valid_month 컬럼이 이미 있어야 한다(process_*.py가
    관리자가 지정한 기준 연/월을 찍어서 넘김 — team_refer의 "입력 날짜"와
    같은 방식, 기본값은 오늘). researchers.csv처럼 파일 전체 최댓값으로
    is_current를 재계산하는 대신, 훨씬 단순하게 "그 사람의 기존 저장값보다
    과거 시점이면 그 사람 행은 이번엔 반영하지 않고 건너뛴다"만 적용한다
    (이 4개는 dep_id별 독립 판정 같은 복잡한 요구가 없어 team_refer 방식까지는
    필요 없음).

    이력 테이블(hist_path)에는 건너뛴 사람 포함, 이번에 들어온 데이터 전체를
    그대로 (researcher_id, valid_year, valid_month) 키로 쌓는다 — "그 시점에
    이런 값이 있었다"는 사실 자체는 현재값 채택 여부와 무관하게 보존한다.

    반환: {'updated_rows': int, 'skipped': list[dict]} — skipped 각 항목은
    {'researcher_id', 'existing_period', 'new_period'}로, process_*.py가
    이 내용을 그대로 실행결과 메시지에 보여줄 수 있다.
    """
    new = new.copy()
    new['valid_year'] = new['valid_year'].astype(str)
    new['valid_month'] = new['valid_month'].astype(str)

    existing = read_existing(out_path)
    skipped = []
    if not existing.empty and {'valid_year', 'valid_month'} <= set(existing.columns):
        existing_period = {
            row['researcher_id']: (str(row.get('valid_year', '')), str(row.get('valid_month', '')))
            for _, row in existing.iterrows()
        }
        keep = []
        for _, row in new.iterrows():
            rid = row['researcher_id']
            new_period = (row['valid_year'], row['valid_month'])
            old_period = existing_period.get(rid)
            if old_period and old_period[0] and new_period < old_period:
                skipped.append({
                    'researcher_id': rid,
                    'existing_period': f'{old_period[0]}-{old_period[1]}',
                    'new_period': f'{new_period[0]}-{new_period[1]}',
                })
                keep.append(False)
            else:
                keep.append(True)
        new_to_apply = new[pd.Series(keep, index=new.index)]
    else:
        new_to_apply = new

    if len(new_to_apply):
        write_merged(out_path, new_to_apply, keys)
    updated_rows = len(new_to_apply)

    # 이력 테이블은 스킵 여부와 무관하게 이번 업로드 전체를 쌓는다.
    write_merged(hist_path, new, hist_keys)

    return {'updated_rows': updated_rows, 'skipped': skipped}
