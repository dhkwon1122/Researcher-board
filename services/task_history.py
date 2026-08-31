"""
과제 수행 이력 — 같은 과제명(the_task_name 우선, 없으면 task_name)으로
여러 줄 참여 이력이 있을 때 하나로 합치는 로직.

엑셀 다운로드(services/researcher_profile_export.py의 _col_tasks)와
화면 표(components/profile_sections.py의 tasks_block)가 동일한 병합
규칙을 공유해야 해서(사용자 요청 2026-08-31, "화면에도 동일하게 반영")
여기 하나로 모았다 — 두 호출부는 날짜 표시 형식(연도만 vs 연-월)과
투입률 표시 여부만 다르고, "어떤 구간을 합칠지" 판단 자체는 같아야 한다.

병합 규칙(사용자 확정): 한 구간의 시작연도가 다른 구간의 종료연도+1
이하면(연도 기준 "포함" 또는 "연결") 하나로 합친다. 진행중(종료일 없음)
구간과 합쳐지면 그 그룹은 계속 진행중으로 남고, 그 뒤에 시작하는 어떤
구간도 자동으로 흡수한다(진행중이면 끝이 없으므로).
"""
from __future__ import annotations

import math


def _s(v) -> str:
    if v is None:
        return ''
    try:
        if isinstance(v, float) and math.isnan(v):
            return ''
    except TypeError:
        pass
    s = str(v).strip()
    return '' if s.lower() in ('nan', 'none', 'nat') else s


def task_year(date_str) -> int | None:
    """앞 4자리가 숫자면 연도로 파싱, 아니면 None(결측/이상 형식)."""
    s = _s(date_str)
    if len(s) >= 4 and s[:4].isdigit():
        return int(s[:4])
    return None


def task_display_name(row: dict, name_key: str = 'the_task_name', fallback_key: str = 'task_name') -> str:
    """the_task_name(참여 당시 실제 과제명, pipeline/process_tasks.py가
    tasks_information.csv 개명 이력으로 보정)이 있으면 그걸, 없으면
    (구버전 CSV/매핑 실패 폴백) 원본 task_name."""
    return _s(row.get(name_key)) or _s(row.get(fallback_key)) or '-'


def merge_task_rows(items: list, *, name_key: str = 'the_task_name', fallback_key: str = 'task_name',
                     start_key: str = 'start_date', end_key: str = 'end_date') -> list:
    """과제명별로 참여 구간을 연도 기준으로 병합한다(모듈 독스트링 참고).

    반환: [{'name', 'current', 'start_row', 'end_row', 'current_row', 'rows'}, ...]
      - start_row: 그룹의 시작을 나타내는 원본 행(그룹 내 가장 이른 시작연도).
      - end_row: 진행중이면 None, 아니면 그룹 내 가장 늦은 종료연도의 원본 행
        (표시용 원본 날짜 문자열이 그대로 필요한 호출부를 위해 연도가 아니라
        행 자체를 돌려준다).
      - current_row: 진행중이면 그 진행중 상태를 만든 원본 행 중 시작이
        가장 늦은 것(="지금 실제 이어지고 있는 구간"), 아니면 None — 병합된
        구간의 투입률처럼 "지금 값"이 필요한 호출부가 여기서 고른다
        (사용자 확정 2026-08-31: 값이 다르면 가장 최근 구간 값만 표시).
      - rows: 이 그룹에 합쳐진 원본 행 전부(시작연도 오름차순).
    같은 과제명이라도 시작연도를 파싱할 수 없는 행은 연도 비교 자체가
    불가능하므로 병합하지 않고 하나씩 그대로 남긴다."""
    by_name: dict = {}
    order: list = []
    for t in items:
        name = task_display_name(t, name_key, fallback_key)
        by_name.setdefault(name, []).append(t)
        if name not in order:
            order.append(name)

    result = []
    for name in order:
        decorated = []
        for t in by_name[name]:
            start_year = task_year(t.get(start_key))
            end_year = task_year(t.get(end_key))
            decorated.append({'row': t, 'start': start_year, 'end': end_year, 'current': end_year is None})

        known = sorted((d for d in decorated if d['start'] is not None), key=lambda d: d['start'])
        unknown = [d for d in decorated if d['start'] is None]

        groups: list = []
        for d in known:
            if groups:
                g = groups[-1]
                g_end_cmp = math.inf if g['current'] else g['end']
                if d['start'] <= g_end_cmp + 1:
                    if d['current']:
                        g['current'] = True
                        g['end'] = None
                        g['end_row'] = None
                        g['current_row'] = d['row']
                    elif not g['current'] and (g['end'] is None or d['end'] > g['end']):
                        g['end'] = d['end']
                        g['end_row'] = d['row']
                    g['rows'].append(d['row'])
                    continue
            groups.append({
                'start': d['start'], 'start_row': d['row'],
                'end': d['end'], 'end_row': (None if d['current'] else d['row']),
                'current': d['current'], 'current_row': (d['row'] if d['current'] else None),
                'rows': [d['row']],
            })

        for g in groups:
            result.append({
                'name': name, 'current': g['current'],
                'start_row': g['start_row'], 'end_row': g['end_row'], 'current_row': g['current_row'],
                'rows': g['rows'],
            })
        for d in unknown:
            result.append({
                'name': name, 'current': d['current'],
                'start_row': d['row'], 'end_row': (None if d['current'] else d['row']),
                'current_row': (d['row'] if d['current'] else None),
                'rows': [d['row']],
            })

    return result


def sort_key(m: dict, start_key: str = 'start_date') -> tuple:
    """진행중('현재')인 과제를 맨 위로, 그 다음은 최근 시작연도 순(내림차순)
    — 시작연도를 모르는 행은 맨 뒤(사용자 확정 2026-08-31)."""
    start_year = task_year(m['start_row'].get(start_key))
    return (0 if m['current'] else 1, -(start_year if start_year is not None else -9999))
