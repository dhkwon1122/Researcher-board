"""
과제 수행 이력 전처리
Source : source_reader.read_source('tasks')
  → DB tasks_stg 테이블 또는 data/raw_csv/tasks.csv
  (1단계 xlsx_to_raw_csv.py가 data/raw/개인별과제투입기간데이터*.xlsb|xlsx를
   DRM 제거해 만든 사본 — 파일명 접미사/확장자는 가리지 않는다, _find_source_file() 참고)
Output : data/processed/tasks.csv

컬럼 매핑:
  KNOXID → researcher_id (8자리 제로패딩)
  과제명  → task_name    (원본 그대로 — 아래 "과제명 이력 보정" 참고)
  시작일  → start_date  (YYYYMMDD → YYYY-MM-DD)
  해제일  → end_date    (YYYYMMDD → YYYY-MM-DD)
  투입률  → input_rate  (정수 %)

과제명 이력 보정(the_task_name): 원본 "과제명"(task_name)은 과제코드 기준으로
항상 "현재" 이름을 보여준다(예: 예전엔 GRAPH였다가 지금은 2DM으로 개명된
과제라면, 과거 참여 기간도 전부 "2DM"으로 표시됨) — 참여 당시 실제로 불리던
이름이 아니다. tasks_information.csv(process_task_information.py, task_code가
같아도 개명 이력을 write_date별로 별도 행 보존)를 다리 삼아 참여 기간을
실제 개명 시점 기준으로 쪼개, 각 구간의 진짜 당시 이름을 the_task_name에
채운다(자세한 규칙은 _split_by_name_history() 참고) — 화면/엑셀은 task_name
대신 the_task_name(있으면)을 표시해야 한다. 매핑에 실패하거나
tasks_information.csv가 없으면 원본 task_name 그대로 the_task_name에 넣는다
(정보 유실 방지, 사용자 확정).
"""

import glob
import os
import sys
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from merge_utils import TABLE_KEYS, write_merged  # noqa: E402
from excel_reader import is_blank  # noqa: E402

SOURCE_BASENAME = '개인별과제투입기간데이터'   # 접미사(_260114 등)·확장자(xlsb/xlsx)는 가리지 않음
_SOURCE_EXTS = ('.xlsb', '.xlsx')
OUTPUT = os.path.join(OUT_DIR, 'tasks.csv')
TASKS_INFO_PATH = os.path.join(OUT_DIR, 'tasks_information.csv')

COL_ID    = 'KNOXID'
COL_TASK  = '과제명'
COL_START = '시작일'
COL_END   = '해제일'
COL_RATE  = '투입률'


def _parse_rate(val) -> str:
    """투입률 → 정수 문자열(%). 알 수 없으면 빈 문자열."""
    try:
        s = str(val).strip()
        if is_blank(s):
            return ''
        v = float(s)
        if 0.0 < v <= 1.0:
            v = round(v * 100)
        return str(int(round(v)))
    except (TypeError, ValueError):
        return ''


def _same_month(d1: str, d2: str) -> bool:
    """두 'YYYY-MM-DD' 날짜가 같은 해·같은 달인지."""
    return len(d1) >= 7 and len(d2) >= 7 and d1[:7] == d2[:7]


def _collapse_same_start(grp: pd.DataFrame) -> pd.DataFrame:
    """같은 시작일 행이 여럿이면(원본에 투입/해제 이력이 따로 줄로 있는 경우 등) 하나로 합치되,
    해제일이 있는 행이 있으면 그 해제일(가장 늦은 값)을 채택한다. 해제일 빈 행이 뒤에 있다는
    이유로 해제일이 지워져 '진행중'으로 남던 문제(2026-10-08) 방지."""
    if not grp['start_date'].duplicated().any():
        return grp
    rows = []
    for _, sub in grp.groupby('start_date', sort=True):
        ends = [str(e).strip() for e in sub['end_date'] if not is_blank(e) and str(e).strip()]
        last = sub.iloc[-1].copy()
        last['end_date'] = max(ends) if ends else ''
        rows.append(last)
    return pd.DataFrame(rows).reset_index(drop=True)


def _merge_consecutive_periods(df: pd.DataFrame) -> pd.DataFrame:
    """같은 (researcher_id, task_name) 내에서 이어지는 구간을 하나로 병합.
    "이어짐"의 기준: 종료일 == 다음 시작일(정확히 일치)이거나, 종료월과 다음
    시작월이 같은 달(월 단위 재참여, 예: 1/15 종료 후 1/28 재참여)인 경우.
    병합 시 최초 시작일 · 마지막 종료일 사용, 투입률은 최신 값.
    """
    result = []
    for (rid, task), grp in df.groupby(['researcher_id', 'task_name'], sort=False):
        grp = grp.sort_values('start_date', kind='stable').reset_index(drop=True)
        grp = _collapse_same_start(grp)

        cur_s = str(grp.iloc[0]['start_date']).strip()
        cur_e = str(grp.iloc[0]['end_date']).strip()
        cur_r = str(grp.iloc[0]['input_rate']).strip()
        if is_blank(cur_e):
            cur_e = ''

        for i in range(1, len(grp)):
            ns = str(grp.iloc[i]['start_date']).strip()
            ne = str(grp.iloc[i]['end_date']).strip()
            nr = str(grp.iloc[i]['input_rate']).strip()
            if is_blank(ne):
                ne = ''

            # 연속 조건: 이전 종료일 == 다음 시작일, 또는 같은 달 안에서 재참여
            if cur_e != '' and (ns == cur_e or _same_month(cur_e, ns)):
                cur_e = ne   # '' (ongoing) 또는 더 늦은 날짜
                cur_r = nr
            else:
                result.append({'researcher_id': rid, 'task_name': task,
                                'start_date': cur_s, 'end_date': cur_e, 'input_rate': cur_r})
                cur_s, cur_e, cur_r = ns, ne, nr

        result.append({'researcher_id': rid, 'task_name': task,
                       'start_date': cur_s, 'end_date': cur_e, 'input_rate': cur_r})

    if not result:
        return pd.DataFrame(columns=['researcher_id', 'task_name',
                                     'start_date', 'end_date', 'input_rate'])
    return pd.DataFrame(result)


def _read_tasks_information() -> pd.DataFrame:
    if not os.path.exists(TASKS_INFO_PATH):
        return pd.DataFrame()
    try:
        return pd.read_csv(TASKS_INFO_PATH, encoding='utf-8-sig', dtype=str).fillna('')
    except Exception:
        return pd.DataFrame()


def _read_task_name_history() -> pd.DataFrame:
    """process_task_information이 중복 제거 전 원본 행으로 만든 (task_code, task_name,
    write_date) 이력. 없으면 빈 DataFrame."""
    path = os.path.join(OUT_DIR, 'task_name_history.csv')
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
    except Exception:
        return pd.DataFrame()


def _name_to_code_map(tasks_info_df: pd.DataFrame) -> dict:
    """task_name → task_code. tasks_information.csv는 이미 task_name 기준
    중복 제거가 돼 있어(process_task_information.py) 1:1로 안전하게 매핑된다."""
    if tasks_info_df.empty or not {'task_name', 'task_code'} <= set(tasks_info_df.columns):
        return {}
    return {
        str(n).strip(): str(c).strip()
        for n, c in zip(tasks_info_df['task_name'], tasks_info_df['task_code'])
        if str(n).strip()
    }


def _code_to_history_map(tasks_info_df: pd.DataFrame) -> dict:
    """task_code → [(write_date, task_name), ...] (write_date 오름차순) —
    같은 과제코드가 여러 write_date에 걸쳐 서로 다른 task_name으로 기록된
    행들(개명 이력)을 시간순으로 모은다. write_date/task_name이 비어 있는
    행은 이력으로 쓸 수 없어 제외."""
    if tasks_info_df.empty or not {'task_code', 'write_date', 'task_name'} <= set(tasks_info_df.columns):
        return {}
    history: dict = {}
    for code, wd, name in zip(tasks_info_df['task_code'], tasks_info_df['write_date'], tasks_info_df['task_name']):
        code, wd, name = str(code).strip(), str(wd).strip(), str(name).strip()
        if not code or not wd or not name:
            continue
        history.setdefault(code, []).append((wd, name))
    for code in history:
        history[code].sort(key=lambda pair: pair[0])
        # 작성일 기준 전후 과제명이 같으면(재작성/재제출) 같은 과제로 보고 가장 이른
        # 작성일 하나만 남긴다 — 이름이 실제로 바뀐 시점만 구간 경계가 되도록.
        collapsed = []
        for wd, name in history[code]:
            if collapsed and collapsed[-1][1] == name:
                continue
            collapsed.append((wd, name))
        history[code] = collapsed
    return history


def _day_before(date_str: str) -> str:
    return (datetime.strptime(date_str, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')


def _split_by_name_history(task_name: str, start: str, end: str,
                            name_to_code: dict, code_history: dict) -> list:
    """한 참여 기간(start~end, end=''면 진행중)을 그 과제코드의 개명 이력
    (write_date별 task_name)에 맞춰 실제 당시 이름 구간으로 쪼갠다.

    예) 이력이 GROTH(2019-02-01)/GRAPH(2020-06-01)/2DM(2023-01-01)이고
    참여기간이 2019-06-01~2023-02-01이면:
      GROTH(2019-06-01~2020-05-31), GRAPH(2020-06-01~2022-12-31),
      2DM(2023-01-01~2023-02-01) 3구간으로 나뉜다(사용자 확정 예시와 동일).

    매핑 실패(task_code 못 찾음)/이력 없음/참여 시작일 이전 이력이 아예 없는
    구간은 원본 task_name 그대로 폴백(사용자 확정 — 정보 유실 방지).
    반환: [{'task_code','the_task_name','start_date','end_date'}, ...]."""
    fallback = [{'task_code': '', 'the_task_name': task_name, 'start_date': start, 'end_date': end}]
    if not start:
        return fallback

    code = name_to_code.get(task_name, '')
    if not code:
        return fallback

    history = code_history.get(code, [])
    # 참여 종료 이후에 생긴 개명은 이 기간과 무관하므로 제외.
    relevant = [(wd, name) for wd, name in history if not end or wd <= end]
    if not relevant:
        return [{'task_code': code, 'the_task_name': task_name, 'start_date': start, 'end_date': end}]

    before_start = [pair for pair in relevant if pair[0] <= start]
    after_start = [pair for pair in relevant if pair[0] > start]
    # 참여 시작 시점에 이미 기록이 있으면 그 이름(가장 최근 것)부터, 없으면
    # (이 과제코드의 개명 이력 자체가 참여 시작보다 늦게 시작함) 그 이전 구간은
    # 알 수 없으니 원본 task_name으로 폴백.
    start_name = before_start[-1][1] if before_start else task_name
    boundaries = [(start, start_name)] + after_start

    segments = []
    for i, (seg_start, name) in enumerate(boundaries):
        if i + 1 < len(boundaries):
            seg_end = _day_before(boundaries[i + 1][0])
            if end and seg_end > end:
                seg_end = end
        else:
            seg_end = end
        segments.append({'task_code': code, 'the_task_name': name, 'start_date': seg_start, 'end_date': seg_end})
    return segments


def _apply_name_history(df: pd.DataFrame) -> pd.DataFrame:
    """tasks.csv의 각 행(연속 참여기간)을 tasks_information.csv 이력에 맞춰
    개명 시점 기준으로 쪼개, task_code/the_task_name 컬럼을 채운 새 DataFrame을
    반환한다(원본보다 행 수가 늘어날 수 있음). tasks_information.csv가 없으면
    전부 the_task_name=task_name, task_code=''로 그대로 통과시킨다."""
    tasks_info_df = _read_tasks_information()
    hist_df = _read_task_name_history()
    if hist_df.empty:
        name_to_code = _name_to_code_map(tasks_info_df)
        code_history = _code_to_history_map(tasks_info_df)
    else:
        # 이력 파일이 있으면 그것으로 개명 시점을 계산(과제정보의 중복 제거 영향 배제),
        # 이름→코드 매핑은 두 소스를 합쳐 쓴다.
        name_to_code = {**_name_to_code_map(hist_df), **_name_to_code_map(tasks_info_df)}
        code_history = _code_to_history_map(hist_df)

    rows = []
    for _, row in df.iterrows():
        segments = _split_by_name_history(
            row['task_name'], row['start_date'], row['end_date'], name_to_code, code_history,
        )
        for seg in segments:
            rows.append({
                'researcher_id': row['researcher_id'],
                'task_name': row['task_name'],
                'start_date': seg['start_date'],
                'end_date': seg['end_date'],
                'input_rate': row['input_rate'],
                'task_code': seg['task_code'],
                'the_task_name': seg['the_task_name'],
            })
    columns = ['researcher_id', 'task_name', 'start_date', 'end_date', 'input_rate', 'task_code', 'the_task_name']
    return pd.DataFrame(rows, columns=columns)


def _find_source_file(raw_dir: str) -> str | None:
    """raw_dir에서 과제 수행 이력 원본 하나를 찾는다(2026-10 — xlsb/xlsx 모두 허용).
    1) '개인별과제투입기간데이터'로 시작하는 xlsb/xlsx 중 수정시각이 가장 최근 것
       (예: 개인별과제투입기간데이터.xlsx, 개인별과제투입기간데이터_260114.xlsb)
    2) 없으면(웹 업로드 폴더처럼 이 항목 파일만 있는 폴더) xlsb/xlsx가 정확히 1개일 때 그 파일.
    임시 잠금 파일('~$*')은 제외한다."""
    def _usable(paths):
        return [p for p in paths if not os.path.basename(p).startswith('~$')]

    named = _usable(
        p for ext in _SOURCE_EXTS
        for p in glob.glob(os.path.join(raw_dir, f'{SOURCE_BASENAME}*{ext}'))
    )
    if named:
        return max(named, key=os.path.getmtime)
    anyfile = _usable(
        p for ext in _SOURCE_EXTS for p in glob.glob(os.path.join(raw_dir, f'*{ext}'))
    )
    return anyfile[0] if len(anyfile) == 1 else None


def _drop_stale_task_rows(result: pd.DataFrame) -> None:
    """기존 tasks.csv에서, 이번 파일에 다시 나온 (researcher_id, task_name) 조합의 행을
    먼저 지운다. 자연키가 (researcher_id, task_name, start_date)라서, 연속 기간 병합이나
    과제명 이력 보정으로 구간 경계(start_date)가 달라지면 예전 경계의 행이 지워지지 않고
    새 행과 겹쳐 남기 때문이다(같은 과제가 두 번 보이는 문제). 이번 파일에 없는 과제/사람의
    행은 그대로 보존한다(기존 '없으면 보존' 원칙)."""
    if result.empty or not os.path.exists(OUTPUT):
        return
    try:
        existing = pd.read_csv(OUTPUT, encoding='utf-8-sig', dtype=str, keep_default_na=False)
    except Exception:
        return
    if not {'researcher_id', 'task_name'} <= set(existing.columns):
        return
    fresh = set(zip(result['researcher_id'].astype(str), result['task_name'].astype(str)))
    mask = [(r, t) in fresh for r, t in zip(existing['researcher_id'], existing['task_name'])]
    if not any(mask):
        return
    import csv as _csv
    existing[[not m for m in mask]].to_csv(OUTPUT, index=False, encoding='utf-8-sig', quoting=_csv.QUOTE_NONNUMERIC)
    print(f'[process_tasks] 이번 파일에 다시 나온 과제의 기존 {sum(mask)}행을 먼저 정리(구간 경계 변경으로 인한 중복 방지)')


def process(raw_dir: str = RAW_DIR) -> bool:
    from excel_reader import norm_id, parse_yyyymmdd, read_xlsx
    from source_reader import read_source

    if raw_dir == RAW_DIR:
        df = read_source('tasks')
        if df is None:
            print('[process_tasks] tasks 원천 데이터 없음 '
                  '(DB tasks_stg 또는 data/raw_csv/tasks.csv)')
            return False
    else:
        source = _find_source_file(raw_dir)
        if not source:
            print(f'[process_tasks] 파일 없음: {raw_dir} 안에 {SOURCE_BASENAME}*.xlsb/.xlsx 가 없습니다')
            return False
        print(f'[process_tasks] 읽는 중: {source}')
        df = read_xlsx(source)

    missing = [c for c in [COL_ID, COL_TASK, COL_START, COL_END, COL_RATE]
               if c not in df.columns]
    if missing:
        print(f'[process_tasks] 컬럼 없음: {missing}')
        print(f'  실제 컬럼: {list(df.columns)}')
        return False

    result = pd.DataFrame({
        'researcher_id': df[COL_ID].apply(norm_id),
        'task_name':     df[COL_TASK].astype(str).str.strip(),
        'start_date':    df[COL_START].apply(parse_yyyymmdd),
        'end_date':      df[COL_END].apply(parse_yyyymmdd),
        'input_rate':    df[COL_RATE].apply(_parse_rate),
    })

    result = result[result['researcher_id'] != ''].reset_index(drop=True)

    # 연속 수행기간 병합
    result = _merge_consecutive_periods(result)

    # 과제명 이력 보정(the_task_name) — tasks_information.csv 기준으로 개명
    # 시점에 맞춰 구간을 쪼갠다(모듈 docstring 참고). 이 단계에서 행 수가
    # 늘어날 수 있다.
    before_split = len(result)
    result = _apply_name_history(result)
    if len(result) != before_split:
        print(f'[process_tasks] 과제명 이력 보정으로 {before_split}행 → {len(result)}행'
              f'(개명 이력이 있는 참여기간을 구간별로 분리)')

    result = result.sort_values(['researcher_id', 'start_date']).reset_index(drop=True)

    _drop_stale_task_rows(result)
    merged = write_merged(OUTPUT, result, TABLE_KEYS['tasks'])
    print(f'[process_tasks] 저장 완료: {OUTPUT}  (총 {len(merged)}행, 이번 파일 {len(result)}행 반영)')
    return True


if __name__ == '__main__':
    process()
