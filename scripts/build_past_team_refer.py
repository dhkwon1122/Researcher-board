"""
과거 월별 조직 개편 이력(team_refer) 산출 스크립트 (2026-08-31, 사용자 확정).

data/raw/past_team_refer/ 안의 월별 "End of Month Headcount" 원본 엑셀에서
"비공식소속부서명" 목록을 뽑아 월별 상위부서명/현소속부서명/비공식소속부서명
3단 매핑표(<원본파일명>_team_refer.xlsx)를 만들고, 연속된 두 달을 비교해
조직 개편(변경/삭제만, 유지·신규는 기록 안 함)을 team_change.xlsx 하나에
모아 기록한다.

원본 파일명 패턴: {YYYYMM}_End of Month Headcount_*_{YYYYMM}.xlsx
전체 대상은 201809~202606(94개월)이지만, 이 스크립트는 우선 처음 4개월
(201809~201812)만 검증용으로 실행하도록 MONTHS를 좁혀 뒀다 — 결과를 실제
파일로 확인한 뒤 MONTHS를 늘려 전체 94개월로 확장하면 된다.

원본 열 위치(사용자 확인 — 모든 월별 파일에서 컬럼 위치 동일):
  BF(58번째) 열 : 비공식소속부서명 — 목록 추출 대상. 혹시 실제로 다른 위치에
                  있을 경우를 대비해, 이 스크립트는 위치가 아니라 헤더 텍스트
                  "비공식소속부서명"을 직접 찾아서 그 열을 쓴다(더 안전).
  S(19번째)  열 : 현소속부서명 — 그 행 자체의 "공식" 현재 소속 부서명.
  EV(152번째) 열 : 상위 조직 조회용 매칭 열(다른 행의 상위부서명을 찾을 때
                  이 열에서 B열 값을 찾는다).
  ES(149번째) 열 : 그 행의 상위부서명 값.
헤더는 파일의 2번째 행에 있고 1번째 행은 무시한다(사용자 확인).

각 월 파일 처리 규칙(사용자 확정 1~10번을 그대로 따르되, Excel 수식을
실제로 넣지 않고 그 수식이 계산할 값을 여기서 직접 계산해 정적 값으로
저장한다 — 어차피 원래 요청의 9번 단계에서 수식을 값으로 바꾸므로 최종
결과는 동일하다):
  1. 헤더 행 확인, 컬럼 162개 확인, "비공식소속부서명" 존재 확인
  2. 비공식소속부서명 값을 중복 제거해 A열로
  3. B열(현소속부서명) = BF열에서 A열 값을 찾아 같은 행의 S열 값
  4. C열(상위부서명) = EV열에서 B열 값을 찾아 같은 행의 ES열 값
     (못 찾으면 S열에서 B열 값을 다시 찾아 ES열 값으로 폴백— VLOOKUP과 동일)
     그 값이 "SAIT"/"대표이사"/"종합기술원" 중 하나면(=이미 최상위) 더 안
     올라가고 B열 값 자체를 상위부서명으로 씀(사용자 확정 2026-08-31, 6번
     수정 — 원래 초안의 조건별/반환값 매칭 방식이 서로 달랐던 것[정확일치
     vs 와일드카드]을 정확일치로 통일해 구현. EV_MATCH_MODE 상수로 필요하면
     와일드카드(접두 일치)로 바꿀 수 있다).
  5. 최종 컬럼 순서: 상위부서명(A) / 현소속부서명(B) / 비공식소속부서명(C)
  6. A→B→C 순 오름차순 정렬 후 저장

월간 비교(team_change.xlsx, 사용자 확정 "A안"):
  두 달의 (상위부서명, 현소속부서명) 조합을 그룹으로 보고, 그 그룹 안의
  비공식소속부서명 집합을 비교한다.
    - 그룹 자체가 다음 달에 없어짐        → 그 그룹의 모든 행을 "삭제"로 기록
    - 그룹은 있고, 없어진 값 1개·새로 생긴 값 1개가 정확히 1:1로 대응할 때만
                                          → "변경"으로 기록(이전값 → 이후값)
    - 그 외(그룹 안에서 여러 개가 동시에 없어지거나 늘어난 경우)
                                          → 없어진 값 각각을 "삭제"로 기록
      (새로 생긴 값은 기록하지 않음 — 유지/신규 추가는 기록 대상 아님)

사용법:
  python scripts/build_past_team_refer.py
"""
import glob
import os
import sys

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

RAW_DIR = os.path.join(BASE_DIR, 'data', 'raw', 'past_team_refer')

# 검증용으로 우선 4개월만 — 확인되면 201809~202606 전체(94개월) 리스트로 늘린다.
MONTHS = ['201809', '201810', '201811', '201812']

# ── 원본 파일의 고정 열 위치(1-based, Excel 열 문자 기준 — 사용자 확인:
#    모든 월별 파일에서 동일) ──────────────────────────────────────────────
COL_INFORMAL_DEPT = 58   # BF: 비공식소속부서명(헤더 텍스트로도 재확인함)
COL_CURRENT_DEPT = 19    # S : 현소속부서명
COL_PARENT_MATCH = 152   # EV: 상위 조직 조회용 매칭 열
COL_PARENT_VALUE = 149   # ES: 상위부서명 값

ROOT_MARKERS = {'SAIT', '대표이사', '종합기술원'}  # 이미 최상위인 값들(2026-08-31, 사용자 확정)

# 상위부서명 조회 시 EV열 매칭 방식 — 사용자가 준 원래 수식은 조건 검사(3곳)는
# 정확일치, 실제 반환값(1곳)은 와일드카드(B3&"*")로 서로 달라 앞뒤가 안 맞았다
# (7번 질문 답변). 정확일치로 통일하는 게 의도로 보여 기본값을 'exact'로 뒀다 —
# 실제 파일로 돌려보고 매칭이 잘 안 되면(예: EV열에 접두 코드만 들어있는 경우)
# 'prefix'로 바꿔서 재실행하면 된다.
EV_MATCH_MODE = 'exact'  # 'exact' 또는 'prefix'


def _find_source_file(yyyymm: str) -> str:
    pattern = os.path.join(RAW_DIR, f'{yyyymm}_End of Month Headcount_*_{yyyymm}.xlsx')
    matches = sorted(glob.glob(pattern))
    if not matches:
        raise FileNotFoundError(
            f'{yyyymm}에 해당하는 원본 파일을 찾지 못했습니다: {pattern}\n'
            f'  data/raw/past_team_refer/ 안에 실제 파일이 있는지 확인하세요.'
        )
    if len(matches) > 1:
        raise RuntimeError(f'{yyyymm}에 해당하는 파일이 여러 개 발견됐습니다: {matches}')
    return matches[0]


def _read_source(path: str) -> pd.DataFrame:
    """헤더는 2번째 행(1행 무시) — pandas header=1은 0번째 행을 건너뛰고
    1번째 행(=파일의 2번째 행)을 헤더로 쓴다."""
    df = pd.read_excel(path, header=1, dtype=str)
    if len(df.columns) != 162:
        raise ValueError(
            f'{os.path.basename(path)}: 헤더가 162개가 아니라 {len(df.columns)}개입니다 — '
            f'헤더 행 위치(2행) 가정이 이 파일에는 안 맞을 수 있습니다.'
        )
    if '비공식소속부서명' not in df.columns:
        raise ValueError(f'{os.path.basename(path)}: "비공식소속부서명" 헤더를 찾지 못했습니다.')
    return df


def _col(df: pd.DataFrame, excel_col_1based: int) -> pd.Series:
    return df.iloc[:, excel_col_1based - 1]


def _lookup_dict(keys: pd.Series, values: pd.Series) -> dict:
    """Excel MATCH(...,0)/VLOOKUP(...,0)과 동일하게 "처음 나온 값"만 남긴다
    (키가 중복되면 첫 매칭 행을 쓰는 Excel 동작과 일치시키기 위함)."""
    out = {}
    for k, v in zip(keys, values):
        k = (k or '').strip() if isinstance(k, str) else k
        if not k or k in out:
            continue
        out[k] = v
    return out


def build_team_refer(yyyymm: str) -> str:
    """<원본파일명>_team_refer.xlsx를 만들고 그 경로를 반환한다."""
    src_path = _find_source_file(yyyymm)
    df = _read_source(src_path)

    informal_col = df['비공식소속부서명']  # 헤더 텍스트로 직접 찾음(BF열이라는 가정보다 안전)
    bf_col = _col(df, COL_INFORMAL_DEPT)
    if not informal_col.equals(bf_col):
        print(f'[경고] {yyyymm}: "비공식소속부서명" 헤더 위치가 BF열(58번째)이 아닙니다 — '
              f'헤더 텍스트로 찾은 열을 사용합니다.', file=sys.stderr)
        informal_source = informal_col
    else:
        informal_source = bf_col

    s_col = _col(df, COL_CURRENT_DEPT)
    ev_col = _col(df, COL_PARENT_MATCH)
    es_col = _col(df, COL_PARENT_VALUE)

    # B열(현소속부서명): BF열(비공식소속부서명) → S열(현소속부서명)
    bf_to_s = _lookup_dict(bf_col, s_col)
    # C열(상위부서명) 1차: EV열(상위 조직 조회용) → ES열(상위부서명)
    ev_to_es = _lookup_dict(ev_col, es_col)
    # C열(상위부서명) 폴백: S열(현소속부서명, 자기 자신) → ES열(상위부서명) — VLOOKUP(B3,S:ES,131,0)과 동일
    s_to_es = _lookup_dict(s_col, es_col)

    # 1) 비공식소속부서명 중복 제거(첫 등장 순서 유지 — Excel "중복된 항목 제거"와 동일)
    informal_values = [v.strip() for v in informal_source.dropna() if str(v).strip()]
    seen, unique_informal = set(), []
    for v in informal_values:
        if v not in seen:
            seen.add(v)
            unique_informal.append(v)

    def _lookup_parent(current_dept: str) -> str:
        parent = ev_to_es.get(current_dept) if EV_MATCH_MODE == 'exact' else None
        if EV_MATCH_MODE == 'prefix' or parent is None:
            if EV_MATCH_MODE == 'prefix':
                parent = next((v for k, v in ev_to_es.items() if k.startswith(current_dept)), None)
            if parent is None:
                parent = s_to_es.get(current_dept)
        if parent in ROOT_MARKERS or parent is None:
            return current_dept
        return parent

    rows = []
    for informal in unique_informal:
        current_dept = bf_to_s.get(informal, '')
        parent_dept = _lookup_parent(current_dept) if current_dept else ''
        rows.append((parent_dept, current_dept, informal))

    # 10) C→B→A(=상위부서명→현소속부서명→비공식소속부서명) 오름차순 정렬
    rows.sort(key=lambda r: (r[0], r[1], r[2]))

    out_path = src_path[:-len('.xlsx')] + '_team_refer.xlsx'
    wb = Workbook()
    ws = wb.active
    ws.title = 'team_refer'
    headers = ['상위부서명', '현소속부서명', '비공식소속부서명']
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = Font(bold=True)
    for row_idx, row in enumerate(rows, start=2):
        for col_idx, value in enumerate(row, start=1):
            ws.cell(row=row_idx, column=col_idx, value=value)
    for col_idx, width in enumerate([30, 30, 30], start=1):
        ws.column_dimensions[chr(ord('A') + col_idx - 1)].width = width
    wb.save(out_path)
    print(f'[OK] {os.path.basename(out_path)} 생성 ({len(rows)}행)')
    return out_path


def _read_team_refer(path: str) -> list:
    df = pd.read_excel(path, dtype=str).fillna('')
    return df.to_dict('records')


def diff_month(prev_rows: list, curr_rows: list) -> list:
    """두 달치 team_refer 행을 비교해 (상태, 상위부서명, 현소속부서명,
    이전 비공식소속부서명, 이후 비공식소속부서명) 튜플 목록을 반환한다
    — "변경"/"삭제"만(유지·신규 추가는 반환하지 않음, 사용자 확정 A안)."""
    def _group(rows):
        groups = {}
        for r in rows:
            key = (r['상위부서명'], r['현소속부서명'])
            groups.setdefault(key, set()).add(r['비공식소속부서명'])
        return groups

    prev_groups = _group(prev_rows)
    curr_groups = _group(curr_rows)

    changes = []
    for key, prev_set in prev_groups.items():
        curr_set = curr_groups.get(key)
        if curr_set is None:
            for informal in sorted(prev_set):
                changes.append(('삭제', key[0], key[1], informal, ''))
            continue
        removed = prev_set - curr_set
        added = curr_set - prev_set
        if len(removed) == 1 and len(added) == 1:
            changes.append(('변경', key[0], key[1], next(iter(removed)), next(iter(added))))
        else:
            for informal in sorted(removed):
                changes.append(('삭제', key[0], key[1], informal, ''))
    return changes


def build_team_change(team_refer_paths: dict) -> str:
    """team_refer_paths: {yyyymm: team_refer.xlsx 경로} — MONTHS 순서대로
    연속된 두 달씩 diff_month()로 비교해 전부 team_change.xlsx 한 파일에
    모은다(달마다 별도 시트가 아니라, "비교 기준" 컬럼으로 구분되는 한 표)."""
    months_sorted = sorted(team_refer_paths)
    all_changes = []
    for prev_m, curr_m in zip(months_sorted, months_sorted[1:]):
        prev_rows = _read_team_refer(team_refer_paths[prev_m])
        curr_rows = _read_team_refer(team_refer_paths[curr_m])
        for status, parent, current, before, after in diff_month(prev_rows, curr_rows):
            all_changes.append((f'{prev_m}->{curr_m}', status, parent, current, before, after))
        print(f'[OK] {prev_m} -> {curr_m} 비교 완료 '
              f'({sum(1 for c in all_changes if c[0] == f"{prev_m}->{curr_m}")}건 변경/삭제)')

    out_path = os.path.join(RAW_DIR, 'team_change.xlsx')
    wb = Workbook()
    ws = wb.active
    ws.title = 'team_change'
    headers = ['비교 기준(이전월->이후월)', '상태', '상위부서명', '현소속부서명',
               '비공식소속부서명(이전)', '비공식소속부서명(이후)']
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = Font(bold=True)
    for row_idx, row in enumerate(all_changes, start=2):
        for col_idx, value in enumerate(row, start=1):
            ws.cell(row=row_idx, column=col_idx, value=value)
    for col_idx, width in enumerate([18, 8, 26, 26, 26, 26], start=1):
        ws.column_dimensions[chr(ord('A') + col_idx - 1)].width = width
    wb.save(out_path)
    print(f'[OK] {os.path.basename(out_path)} 생성 (총 {len(all_changes)}건 변경/삭제)')
    return out_path


def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    if not os.path.isdir(RAW_DIR) or not os.listdir(RAW_DIR):
        print(f'[안내] {RAW_DIR} 에 원본 "End of Month Headcount" 엑셀 파일을 먼저 넣어주세요.')
        return

    team_refer_paths = {}
    for yyyymm in MONTHS:
        try:
            team_refer_paths[yyyymm] = build_team_refer(yyyymm)
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            print(f'[오류] {yyyymm}: {exc}', file=sys.stderr)

    if len(team_refer_paths) >= 2:
        build_team_change(team_refer_paths)
    else:
        print('[안내] team_refer.xlsx가 2개 이상 만들어져야 team_change.xlsx 비교를 할 수 있습니다.')


if __name__ == '__main__':
    main()
