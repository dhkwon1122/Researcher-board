"""
업무목표 전처리

대상 3개년은 고정 숫자가 아니라 회계연도(매년 3월 시작, services.evaluations.
current_fiscal_year()와 동일 규칙) 기준 최근 3개년 [FY-2, FY-1, FY]로 매번
계산한다(2026-09-01, 사용자 확정 — "업무목표24~26"처럼 특정 연도가 코드에
고정돼 있으면 해가 바뀌어도 자동으로 대상이 안 밀린다). 예: 오늘이 2026-09면
FY=2026이라 [2024, 2025, 2026], 2027-03부터는 FY=2027이라 [2025, 2026, 2027].

원천: source_reader.read_source('work_objective_{연도}') — 연도는 위 규칙으로
매번 계산되는 4자리 실제 연도(예: 'work_objective_2026').
  → DB work_objective_{연도}_stg 테이블 또는 data/raw_csv/work_objective_{연도}.csv
  (1단계 xlsx_to_raw_csv.py가 data/raw/업무목표{YY}.xlsx를 DRM 제거해 만든 사본
   — 원본 파일명은 실무 관행대로 2자리 연도 접미사를 그대로 쓴다, pipeline/sources.py 참고)
Output       : data/processed/work_objective.csv

각 연도 파일은 header_row=0(첫 행)에서 COL_ID/COL_NAME/COL_DETAIL(사번/목표명/
상세설명) 컬럼명을 찾아 사용한다.
한 연구원이 한 해에 목표를 여러 개(여러 행) 작성할 수 있어, 같은 행의
목표명·상세설명을 "- 목표명 - 상세설명"으로 이어붙이고, 같은 연구원의 여러
행은 줄바꿈으로 이어 그 해의 컬럼 하나(work_objective{4자리 연도})에 담는다.
3개 연도 결과를 researcher_id 기준 outer-merge해 연구원 1명당 1행으로 만든다
(어느 해에 데이터가 없으면 그 해 컬럼만 빈 문자열).

컬럼 매핑:
  사번    → researcher_id (8자리 제로패딩)
  목표명 · 상세설명 → work_objective{4자리 연도}(예: work_objective2026)
                    (같은 행끼리 묶어 "- 목표명 - 상세설명" 줄 단위로 저장)

Output 컬럼: researcher_id, work_objective{연도} × 3(그 시점 대상 3개년)

예전 스키마(work_objective24/25/26 — 실제 연도가 아니라 임의의 2자리 슬롯
번호)로 저장된 기존 work_objective.csv는 _migrate_legacy_columns()가 최초
실행 시 자동으로 work_objective2024/2025/2026으로 이관한다(멱등적 — 여러 번
실행해도 안전, 이미 새 이름이면 아무 것도 안 함).

※ 이 모듈은 사내 LLM을 호출하지 않는다(순수 엑셀 추출/정리).
"""

import os
import sys
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE_DIR, RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import clean_str, read_xlsx, norm_id
from merge_utils import TABLE_KEYS, read_existing, write_merged_with_valid_period
from source_reader import read_source

sys.path.insert(0, BASE_DIR)
from services.evaluations import current_fiscal_year  # noqa: E402

# 원본 컬럼 이름 (파일에 없으면 아래 값을 실제 헤더명으로 수정)
# 업무목표 원본에는 부서장 사번 컬럼도 있었는데(예전엔 "사번"으로 표기돼
# 연구원 본인 식별용 "사번"(F열)과 헷갈렸다), 소스 파일에서 그 컬럼을
# "부서장사번"으로 이름을 바꿔 이제 "사번"은 F열(연구원 본인 식별용) 하나만
# 가리킨다 — 그래서 아래 COL_ID는 그대로 '사번'을 쓰면 된다(사용자 확정).
COL_ID = '사번'
COL_NAME = '목표명'
COL_DETAIL = '상세설명'

# 예전 스키마(2자리 슬롯 번호) → 새 스키마(4자리 실제 연도) 컬럼명 이관표.
# "슬롯 24/25/26"이 처음부터 실제 연도 2024/2025/2026과 1:1로 대응하도록
# 운영돼 왔다는 전제(process_researcher_expertise.py가 이미 이 대응으로
# 하드코딩돼 있던 것과 동일 — 2026-09-01 확인).
_LEGACY_COLUMN_MAP = {
    'work_objective24': 'work_objective2024',
    'work_objective25': 'work_objective2025',
    'work_objective26': 'work_objective2026',
}


def target_years(today: date | None = None) -> list[int]:
    """회계연도 기준 최근 3개년 [FY-2, FY-1, FY](오름차순). services/
    web_pipeline_runner.py가 관리자 화면의 업무목표 3개 슬롯 라벨/업로드
    파일명을 계산할 때도 그대로 재사용한다(같은 규칙을 두 곳에서 각자
    구현하지 않기 위함)."""
    fy = current_fiscal_year(today)
    return [fy - 2, fy - 1, fy]


def _year_files(today: date | None = None) -> dict[int, str]:
    """4자리 연도 → 원천 파일명(2자리 연도 접미사, 실무 관행)."""
    return {y: f'업무목표{y % 100:02d}.xlsx' for y in target_years(today)}


def _migrate_legacy_columns(df: pd.DataFrame) -> pd.DataFrame:
    """예전 스키마(work_objective24/25/26 — 임의의 2자리 슬롯 번호)를 실제
    연도 기반 컬럼명(work_objective2024 등)으로 1회성 이관한다(2026-09-01,
    사용자 확정 — 매년 3월 롤링 윈도우를 구현하려면 컬럼명 자체가 실제
    연도를 가리켜야 한다). 이미 새 컬럼명으로 저장돼 있으면 아무 것도 안
    한다(멱등적 — process()를 몇 번을 다시 돌려도 안전)."""
    if df.empty:
        return df
    rename = {old: new for old, new in _LEGACY_COLUMN_MAP.items()
              if old in df.columns and new not in df.columns}
    if rename:
        print(f'[OK]   예전 스키마 컬럼 이관: {rename}')
        df = df.rename(columns=rename)
    return df


def _combine_row(name, detail) -> str:
    name = clean_str(name)
    detail = clean_str(detail)
    if name and detail:
        return f'- {name} - {detail}'
    if name or detail:
        return f'- {name or detail}'
    return ''


def _read_year_file(year: int, filename: str, raw_dir: str) -> pd.DataFrame:
    """한 연도 파일을 읽어 (researcher_id, work_objective{4자리 연도}) DataFrame으로
    반환. 파일이 없거나 비어 있으면 빈 DataFrame(같은 컬럼 구조)을 반환한다."""
    col = f'work_objective{year}'
    empty = pd.DataFrame(columns=['researcher_id', col])
    source_name = f'work_objective_{year}'

    if raw_dir == RAW_DIR:
        df = read_source(source_name)
        if df is None:
            print(f'[SKIP] {source_name} 원천 데이터 없음 '
                  f'(DB {source_name}_stg 또는 data/raw_csv/{source_name}.csv)')
            return empty
    else:
        path = os.path.join(raw_dir, filename)
        if not os.path.exists(path):
            print(f'[SKIP] {path} 파일 없음')
            return empty

        df = read_xlsx(path, header_row=2)  # sources.py 매니페스트 기준 (3번째 행)
        if df.empty:
            print(f'[SKIP] {filename} 읽기 결과가 비어 있습니다.')
            return empty

    missing = [c for c in (COL_ID, COL_NAME, COL_DETAIL) if c not in df.columns]
    if missing:
        sample = ', '.join(f'"{c}"' for c in list(df.columns)[:20])
        raise ValueError(
            f'\n[오류] {filename}에 다음 컬럼을 찾지 못했습니다: {missing}\n'
            f'파일의 컬럼(앞 20개): {sample}\n'
            f'→ process_work_objective.py 상단의 COL_ID/COL_NAME/COL_DETAIL을 '
            f'실제 컬럼명으로 수정하세요.'
        )

    df = df.copy()
    df['researcher_id'] = df[COL_ID].apply(norm_id)
    df = df[df['researcher_id'] != '']

    df['_line'] = df.apply(lambda r: _combine_row(r.get(COL_NAME), r.get(COL_DETAIL)), axis=1)
    df = df[df['_line'] != '']
    if df.empty:
        return empty

    grouped = (
        df.groupby('researcher_id')['_line']
        .apply(lambda lines: '\n'.join(lines))
        .reset_index()
        .rename(columns={'_line': col})
    )
    print(f'[OK]   {filename} → {len(grouped)}명 (목표 {len(df)}행)')
    return grouped


def process(raw_dir: str = RAW_DIR, valid_date: date | None = None) -> bool:
    """valid_date: 이번 업로드분의 기준 연/월(기본값 오늘) — work_objective.csv에
    이미 저장된 사람보다 과거 시점이면 그 사람 행은 갱신하지 않고 건너뛴다
    (work_objective_history.csv에는 건너뛴 것 포함 전부 쌓임). 연도별 컬럼
    보존(아래)과는 별개 안전장치 — 이건 "이 업로드 자체가 기존보다 오래된
    스냅샷인지"를 본다.

    대상 3개년(target_years())은 valid_date가 아니라 오늘 날짜 기준으로
    계산한다 — valid_date는 "이 데이터가 어느 시점 것인지"를 나타낼 뿐,
    "지금 몇 년치를 다루고 있는지"는 항상 현재 회계연도 기준이어야 한다."""
    year_files = _year_files()
    year_dfs = [_read_year_file(year, filename, raw_dir) for year, filename in year_files.items()]
    if all(d.empty for d in year_dfs):
        print('[SKIP] 업무목표 파일을 하나도 찾지 못했습니다.')
        return False

    merged = None
    for d in year_dfs:
        if d.empty:
            continue
        merged = d if merged is None else merged.merge(d, on='researcher_id', how='outer')

    # 이번 실행에 파일이 없던 연도(웹 업로드처럼 연도별로 따로 갱신하는 경우
    # 흔함 — 예: 최근 연도 파일만 새로 올라온 경우)는 무조건 빈 값으로 채우면
    # 안 된다 — write_merged()가 researcher_id 하나로 행 전체를 교체하므로,
    # 이미 저장돼 있던 다른 연도 값까지 함께 지워버리는 데이터 유실 버그가
    # 된다. 기존 work_objective.csv에서 그 연도 값을 찾아 이어붙이고(없으면
    # 그때 처음으로 빈 값), 있던 값은 그대로 보존한다.
    out_path = os.path.join(OUT_DIR, 'work_objective.csv')
    existing_raw = read_existing(out_path)
    existing = _migrate_legacy_columns(existing_raw)
    if not existing.empty and list(existing.columns) != list(existing_raw.columns):
        # write_merged_with_valid_period()가 out_path를 자체적으로 다시 읽으므로,
        # 이관 결과를 디스크에도 먼저 반영해둬야 그 안에서도 새 컬럼명으로 병합된다
        # (안 그러면 예전 컬럼명이 그대로 남아 새 컬럼명과 함께 뒤섞여 저장되는 버그가 됨).
        import csv as _csv
        existing.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=_csv.QUOTE_NONNUMERIC)
    for year, d in zip(year_files, year_dfs):
        col = f'work_objective{year}'
        if col in merged.columns:
            continue
        if not existing.empty and col in existing.columns:
            merged = merged.merge(existing[['researcher_id', col]], on='researcher_id', how='left')
        else:
            merged[col] = ''
    merged = merged.fillna('')

    out_cols = ['researcher_id'] + [f'work_objective{year}' for year in year_files]
    merged = merged[out_cols].sort_values('researcher_id').reset_index(drop=True)

    valid_date = valid_date or date.today()
    merged['valid_year'] = f'{valid_date.year:04d}'
    merged['valid_month'] = f'{valid_date.month:02d}'

    hist_path = os.path.join(OUT_DIR, 'work_objective_history.csv')
    outcome = write_merged_with_valid_period(
        out_path, hist_path, merged, TABLE_KEYS['work_objective'], TABLE_KEYS['work_objective_history'])

    print(f'[OK]   work_objective.csv 저장 (이번 파일 {len(merged)}명 중 {outcome["updated_rows"]}명 반영, '
          f'대상 연도: {sorted(year_files)})')
    if outcome['skipped']:
        print(f'  [WARN] {len(outcome["skipped"])}명은 기존 저장된 값이 더 최신이라 건너뜀:')
        for s in outcome['skipped'][:10]:
            print(f'    · {s["researcher_id"]}: 기존 {s["existing_period"]} > 이번 {s["new_period"]}')
        if len(outcome['skipped']) > 10:
            print(f'    · 외 {len(outcome["skipped"]) - 10}명')
    return True


if __name__ == '__main__':
    process()
