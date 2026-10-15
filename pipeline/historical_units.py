"""
협업 당시 소속 판정(2026-10-15, 사용자 확정) — "지금은 다른 부서/과제지만 논문·특허를 쓸 때는 같은 단위였던" 협업을
부서/과제 간 협업에서 빼기 위한 공용 모듈.

  - 문서 기준일: 논문 pub_date(비어 있으면 announce_date — process_publications가 이미 이 규칙으로 pub_date를 채움),
    특허 application_date(없으면 협업 집계 자체에서 빠짐 — 기존과 같음)
  - 그 시점 소속: researchers_history.csv(인력현황 월별 스냅샷)에서 기준일 이전 가장 가까운 월의 org_code.
    이전 기록이 없으면 기준일 이후 FORWARD_MONTHS(3)개월 이내 첫 스냅샷. 그래도 없으면 판정 불가(None)
    → 호출부는 협업으로 그대로 센다(기존 동작).
  - 그 시점 단위명: 팀/리더 참조의 시점별 조직도(similarity_map._team_refer_org_code_timeline)로 그때의
    1단계/3단계부서명. 시점 기록이 없으면 현재 조직도 이름으로 대체.
  - 비교는 그 시점 이름끼리(개편·개명 전후 이름이 달라도 당시 같은 단위였는지로 판정).
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FORWARD_MONTHS = 3


def _ym(date_str: str):
    s = str(date_str or '').strip()
    if len(s) >= 7 and s[:4].isdigit() and s[5:7].isdigit():
        return int(s[:4]), int(s[5:7])
    if len(s) >= 6 and s[:6].isdigit():
        return int(s[:4]), int(s[4:6])
    return None


def doc_date(row: dict, kind: str) -> str:
    """논문: pub_date → announce_date, 특허: application_date. 'YYYY-MM-DD' 또는 ''."""
    keys = ('pub_date', 'announce_date') if kind in ('paper', '논문') else ('application_date',)
    for k in keys:
        v = str(row.get(k) or '').strip()
        if _ym(v):
            return v[:10]
    return ''


class UnitHistory:
    """researcher_id × 날짜 → (당시 1단계부서명, 당시 3단계부서명)."""

    def __init__(self, history: pd.DataFrame | None, timeline: dict | None = None,
                 name_at=None, current_names=None):
        self.snap: dict = {}
        if history is not None and not history.empty and {'researcher_id', 'org_code', 'valid_year', 'valid_month'} <= set(history.columns):
            for rid, org, y, m in zip(history['researcher_id'].astype(str).str.zfill(8), history['org_code'].astype(str),
                                      history['valid_year'], history['valid_month']):
                try:
                    key = (int(float(y)), int(float(m)))
                except (TypeError, ValueError):
                    continue
                if org.strip() and org.strip().lower() != 'nan':
                    self.snap.setdefault(rid, []).append((key, org.strip()))
            for v in self.snap.values():
                v.sort()
        self.timeline = timeline or {}
        self._name_at = name_at
        self._current = current_names
        self._cache: dict = {}

    @property
    def available(self) -> bool:
        return bool(self.snap)

    def org_at(self, rid: str, ym) -> str | None:
        rows = self.snap.get(str(rid).zfill(8))
        if not rows or ym is None:
            return None
        before = [org for key, org in rows if key <= ym]
        if before:
            return before[-1]
        limit = (ym[0] * 12 + ym[1]) + FORWARD_MONTHS
        after = [org for key, org in rows if key[0] * 12 + key[1] <= limit]
        return after[0] if after else None

    def names_at(self, org: str, ym) -> tuple:
        ck = (org, ym)
        if ck in self._cache:
            return self._cache[ck]
        names = ('', '', '')
        if self._name_at is not None and org in self.timeline:
            names = self._name_at(self.timeline[org], (ym[0], ym[1], 31))
        if not any(names) and self._current is not None:
            names = self._current(org)
        self._cache[ck] = names
        return names

    def units_at(self, rid: str, date_str: str):
        """(1단계, 3단계) 또는 판정 불가면 None."""
        ym = _ym(date_str)
        org = self.org_at(rid, ym)
        if org is None:
            return None
        n = self.names_at(org, ym)
        return (n[0], n[2])

    def same_at(self, a: str, b: str, date_str: str) -> tuple[bool, bool]:
        """(당시 같은 1단계였나, 당시 같은 3단계였나). 둘 중 한 명이라도 판정 불가면 (False, False)."""
        ua, ub = self.units_at(a, date_str), self.units_at(b, date_str)
        if ua is None or ub is None:
            return False, False
        return (bool(ua[0]) and ua[0] == ub[0], bool(ua[1]) and ua[1] == ub[1])


def load(history: pd.DataFrame | None = None) -> UnitHistory:
    """researchers_history.csv + 팀/리더 참조 시점별 조직도로 UnitHistory를 만든다(조직도 조회 실패 시 이력만)."""
    if history is None:
        from paths import OUT_DIR
        path = os.path.join(OUT_DIR, 'researchers_history.csv')
        history = pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('') if os.path.exists(path) else pd.DataFrame()
    try:
        from services import similarity_map as sm
    except Exception as exc:  # noqa: BLE001
        print(f'  [WARN] 조직도 조회 불가 — 당시 소속 판정 생략: {exc}')
        return UnitHistory(None)
    try:
        timeline = sm._team_refer_org_code_timeline()
    except Exception as exc:  # noqa: BLE001 — 시점별 조직도가 없어도 현재 조직도 이름으로 판정은 계속
        print(f'  [WARN] 팀/리더 참조 시점별 조직도 조회 실패 — 현재 조직도 이름으로 판정: {exc}')
        timeline = {}
    return UnitHistory(history, timeline, sm._dep_pjt_name_at, sm.org_code_level_names)
