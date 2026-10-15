"""인력현황 월별 이력(researchers_history) 보유 현황 확인(읽기 전용, 2026-10-15).

협업(플랫폼/과제)의 "논문·특허 작성 당시 같은 단위였던 협업 제외"는 이 이력으로 당시 소속을 판정한다.
이력이 비어 있는 달이 많으면 판정할 수 없는 협업이 늘어(그 건은 제외하지 않고 그대로 셈) 효과가 줄어든다.

출력:
  1) 이력 보유 개월 수, 기간(처음~마지막), 월별 인원 수
  2) 최근 N개월(기본 60) 중 이력이 없는 달
  3) 최근 5년 공저 논문·공동발명 특허의 연구원 쌍 중 당시 소속 판정 가능 비율(현재 서로 다른 부서/과제인 쌍 기준)
사용법: python scripts/check_history_months.py [개월수=60]
"""
import os
import sys
from datetime import date

import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'pipeline'))


def main(months: int = 60) -> None:
    from services.data_store import read_processed
    hist = read_processed('researchers_history')
    if hist.empty or not {'valid_year', 'valid_month'} <= set(hist.columns):
        print('researchers_history 없음 — 인력현황을 한 번도 올리지 않았거나 시점 열이 없습니다.')
        return
    ym = pd.to_numeric(hist['valid_year'], errors='coerce') * 100 + pd.to_numeric(hist['valid_month'], errors='coerce')
    counts = ym.dropna().astype(int).value_counts().sort_index()
    print(f'[1] 이력 보유 {len(counts)}개월 · 기간 {str(counts.index[0])[:4]}-{str(counts.index[0])[4:]} ~ '
          f'{str(counts.index[-1])[:4]}-{str(counts.index[-1])[4:]} · 총 {len(hist)}행')
    for k, n in counts.items():
        print(f'    {str(k)[:4]}-{str(k)[4:]}: {n}명')

    today = date.today()
    want = []
    y, m = today.year, today.month
    for _ in range(months):
        want.append(y * 100 + m)
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    missing = sorted(k for k in want if k not in counts.index)
    print(f'\n[2] 최근 {months}개월 중 이력 있는 달 {months - len(missing)}개 / 없는 달 {len(missing)}개')
    if missing:
        print('    없는 달: ' + ', '.join(f'{str(k)[:4]}-{str(k)[4:]}' for k in missing))

    import historical_units as hu
    import process_expertise_metrics as pem
    history = hu.load(hist.fillna('').astype(str))
    researchers = read_processed('researchers')
    levels = pem.current_levels(researchers.fillna('').astype(str)) if not researchers.empty else {}
    since = today.year - pem.COLLAB_RECENT_YEARS + 1
    pubs = read_processed('publications').fillna('').astype(str)
    pats = read_processed('patents').fillna('').astype(str)
    total = decided = same1 = same3 = 0
    for _kind, members, year, d in pem._collab_groups(pubs, pats):
        if not year or year < since:
            continue
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                la, lb = levels.get(a), levels.get(b)
                if not la or not lb or la[0] == lb[0] and la[1] == lb[1]:
                    continue   # 현재 같은 단위이거나 제외 대상 — 원래 협업 집계 대상 아님
                total += 1
                if d and history.units_at(a, d) is not None and history.units_at(b, d) is not None:
                    decided += 1
                    s1, s3 = history.same_at(a, b, d)
                    same1 += s1 and la[0] != lb[0]
                    same3 += s3 and la[1] != lb[1]
    pct = f'{decided * 100 / total:.1f}%' if total else '-'
    print(f'\n[3] 최근 5년 협업(현재 서로 다른 단위인 연구원 쌍) {total}건 중 당시 소속 판정 가능 {decided}건({pct})')
    print(f'    → 당시 같은 부서라 부서 기준에서 빠지는 건 {same1}건, 당시 같은 과제라 과제 기준에서 빠지는 건 {same3}건')


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
