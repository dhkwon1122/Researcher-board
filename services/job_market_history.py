"""
JOB Market — 과제 참여 이력 기준(D, 2026-10-15 사용자 확정).

근거 A(과제 문서)·B(과제원 전문성)는 둘 다 AI가 만든 문장의 임베딩 유사도라 서로 상관이 높다. 이 기준은
"실제로 무엇을 했는가"라는 행동 데이터(과제참여이력 tasks.csv)로 독립적인 축을 더한다(LLM·임베딩 호출 없음).

  D1 경험     — 이 사람이 후보 과제(같은 과제코드 계열 — 개명 전 이름 포함)에 참여한 적이 있는가
  D2 옛 동료  — 후보 과제의 현재 인원 중 예전에 같은 과제에서 30일 이상 함께 참여했던 사람 수
  D3 이동 패턴 — 이 사람의 현재 과제(들)에서 끝난 사람들이 실제로 옮겨 간 과제 중 후보 과제의 비율
  점수 H = 0.5·D1 + 0.3·min(1, D2/3) + 0.2·D3 (0~1) → 추천 정렬에 HISTORY_WEIGHT × H 가산.

as_of(날짜)를 주면 그 시점 이전 데이터만 쓴다 — scripts/backtest_job_market.py가 실제 과거 이동을
"이동 직전 시점"에서 다시 추천해 보는 데 쓴다(미래 정보 누설 방지).

과제 계열 키: task_code(있으면) → 과제정보/과제명 이력(task_name_history.csv)의 이름→코드 → 정규화된 과제명.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date, timedelta

_PIPELINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pipeline')
if os.path.abspath(_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, os.path.abspath(_PIPELINE_DIR))

import researcher_fit as fit  # noqa: E402

PEER_MIN_DAYS = 30            # 같은 과제에서 이 일수 이상 겹치면 "함께 참여"
MOVE_GAP_BEFORE = 31          # 이동: 앞 과제 해제일 이 일수 전 ~
MOVE_GAP_AFTER = 92           # ~ 해제일 이 일수 후 사이에 시작한 다른 과제
RECENT_EXPERIENCE_YEARS = 5   # 이 기간 안의 참여면 D1=1.0, 그 이전이면 0.6
W_EXP, W_PEER, W_FLOW = 0.5, 0.3, 0.2
PEER_FULL = 3                 # 옛 동료 3명 이상이면 D2 만점


def _norm(name) -> str:
    return fit.normalize_org_code(str(name or ''))


def _date(v):
    s = str(v or '').strip()
    m = re.match(r'^(\d{4})-?(\d{2})-?(\d{2})', s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


class TaskHistory:
    def __init__(self, tasks, name_code_pairs=(), today: date | None = None):
        self.today = today or date.today()
        self.key_of_name: dict = {}
        for name, code in name_code_pairs:
            n, c = _norm(name), str(code or '').strip()
            if n and c:
                self.key_of_name.setdefault(n, c)
        self.segs: dict = {}      # rid -> [(key, start, end|None)]
        self.by_key: dict = {}    # key -> [(rid, start, end|None)]
        if tasks is not None and not getattr(tasks, 'empty', True):
            for r in tasks.fillna('').to_dict('records'):
                rid = str(r.get('researcher_id') or '').strip().zfill(8)
                start = _date(r.get('start_date'))
                if not rid.strip('0') or start is None:
                    continue
                names = [n for n in (_norm(r.get('task_name')), _norm(r.get('the_task_name'))) if n]
                code = str(r.get('task_code') or '').strip()
                key = code or next((self.key_of_name[n] for n in names if n in self.key_of_name), '') \
                    or (names[0] if names else '')
                if not key:
                    continue
                for n in names:
                    self.key_of_name.setdefault(n, key)
                seg = (key, start, _date(r.get('end_date')))
                self.segs.setdefault(rid, []).append(seg)
                self.by_key.setdefault(key, []).append((rid, seg[1], seg[2]))
        for v in self.segs.values():
            v.sort(key=lambda s: s[1])
        self._peer_cache: dict = {}
        self.transitions = self._build_transitions()

    # ── 기본 조회 ─────────────────────────────────────────────────────────
    def key_for_project(self, project_name: str, member_key: str = '', member_ids=()) -> str | None:
        """과제별컨플 과제 → 과제 계열 키. 이름(정규화)으로 못 찾으면, 그 과제 현재 인원이 지금 참여 중인 과제 계열 중
        과반(2명 이상)이 같은 것(과제별컨플 과제명과 과제참여이력 과제명 표기가 다른 경우 대비)."""
        for n in (_norm(project_name), _norm(member_key)):
            if n and n in self.key_of_name:
                return self.key_of_name[n]
        ids = [str(m).zfill(8) for m in member_ids or []]
        if len(ids) >= 2:
            from collections import Counter
            votes = Counter(k for m in ids for k in self.current_keys(m))
            if votes:
                k, n = votes.most_common(1)[0]
                if n >= 2 and n * 2 >= len(ids):
                    return k
        return None

    def _end(self, end, as_of):
        return min(end or as_of, as_of)

    def segments(self, rid: str, as_of: date | None = None) -> list:
        as_of = as_of or self.today
        return [(k, s, self._end(e, as_of)) for k, s, e in self.segs.get(str(rid).zfill(8), []) if s < as_of]

    def current_keys(self, rid: str, as_of: date | None = None) -> set:
        """as_of 시점에 진행 중인 과제 계열(해제일 없음 또는 as_of 이후)."""
        as_of = as_of or self.today
        return {k for k, s, e in self.segs.get(str(rid).zfill(8), []) if s <= as_of and (e is None or e >= as_of)}

    def members_at(self, key: str, as_of: date | None = None) -> set:
        as_of = as_of or self.today
        return {rid for rid, s, e in self.by_key.get(key, []) if s <= as_of and (e is None or e >= as_of)}

    # ── D1 경험 ──────────────────────────────────────────────────────────
    def experience(self, rid: str, key: str, as_of: date | None = None) -> dict | None:
        as_of = as_of or self.today
        segs = [(s, e) for k, s, e in self.segments(rid, as_of) if k == key]
        if not segs:
            return None
        days = sum(max((e - s).days, 0) for s, e in segs)
        last = max(e for _s, e in segs)
        recent = last >= as_of - timedelta(days=365 * RECENT_EXPERIENCE_YEARS)
        return {'months': round(days / 30.4), 'last_year': last.year, 'score': 1.0 if recent else 0.6}

    # ── D2 옛 동료 ───────────────────────────────────────────────────────
    def past_peers(self, rid: str, as_of: date | None = None) -> set:
        as_of = as_of or self.today
        ck = (str(rid).zfill(8), as_of)
        if ck in self._peer_cache:
            return self._peer_cache[ck]
        out = set()
        for key, s, e in self.segments(rid, as_of):
            for other, os_, oe in self.by_key.get(key, []):
                if other == ck[0] or os_ >= as_of:
                    continue
                overlap = (min(e, self._end(oe, as_of)) - max(s, os_)).days
                if overlap >= PEER_MIN_DAYS:
                    out.add(other)
        self._peer_cache[ck] = out
        return out

    # ── D3 이동 패턴 ─────────────────────────────────────────────────────
    def _build_transitions(self) -> list:
        """[(from_key, to_key, rid, when)] — 한 과제 해제 직후(-31~+92일)에 다른 과제 계열을 시작한 경우."""
        out = []
        for rid, segs in self.segs.items():
            for key, s, e in segs:
                if e is None:
                    continue
                for k2, s2, _e2 in segs:
                    if k2 == key or s2 <= s:
                        continue
                    if e - timedelta(days=MOVE_GAP_BEFORE) <= s2 <= e + timedelta(days=MOVE_GAP_AFTER):
                        out.append((key, k2, rid, s2))
        return out

    def flow(self, from_keys: set, to_key: str, as_of: date | None = None) -> dict | None:
        """from_keys에서 끝난 사람들의 이동 중 to_key로 간 비율(as_of 이전 이동만)."""
        as_of = as_of or self.today
        if not from_keys:
            return None
        moves = [(t, rid) for f, t, rid, w in self.transitions if f in from_keys and w < as_of]
        if not moves:
            return None
        hit = len({rid for t, rid in moves if t == to_key})
        total = len({(t, rid) for t, rid in moves})
        return {'count': hit, 'total': total, 'share': round(hit / total, 3) if total else 0.0}

    # ── 종합 ─────────────────────────────────────────────────────────────
    def signal(self, rid: str, project_name: str, member_key: str = '', member_ids=(),
               as_of: date | None = None, from_keys: set | None = None, key: str | None = None) -> dict | None:
        """후보 과제 하나에 대한 D1~D3과 점수 H. 과제 계열을 못 찾으면 D2(옛 동료)만으로 계산.
        key를 주면 그 계열로(백테스트처럼 과제원은 과거 시점, 계열 판정은 현재 인원으로 할 때)."""
        as_of = as_of or self.today
        rid = str(rid).zfill(8)
        key = key or self.key_for_project(project_name, member_key, member_ids)
        exp = self.experience(rid, key, as_of) if key else None
        peers = sorted(self.past_peers(rid, as_of) & {str(m).zfill(8) for m in member_ids or [] if str(m).zfill(8) != rid})
        flow = None
        if key:
            fk = self.current_keys(rid, as_of) if from_keys is None else set(from_keys)
            flow = self.flow(fk - {key}, key, as_of)
        if not exp and not peers and not (flow and flow['count']):
            return {'score': 0.0, 'experience': None, 'peers': [], 'flow': flow}
        score = (W_EXP * (exp['score'] if exp else 0.0) + W_PEER * min(1.0, len(peers) / PEER_FULL)
                 + W_FLOW * (flow['share'] if flow else 0.0))
        return {'score': round(score, 4), 'experience': exp, 'peers': peers, 'flow': flow}


def load(today: date | None = None) -> TaskHistory:
    """tasks.csv + 과제정보/과제명 이력의 이름→코드로 TaskHistory 생성."""
    from services import data_store
    tasks = data_store.read_processed('tasks')
    pairs = []
    for name in ('tasks_information', 'task_name_history'):
        df = data_store.read_processed(name)
        if not df.empty and {'task_name', 'task_code'} <= set(df.columns):
            pairs += list(zip(df['task_name'].astype(str), df['task_code'].astype(str)))
    return TaskHistory(tasks, pairs, today)


def signal_text(h: dict | None) -> str:
    """LLM 후보 블록용(이름 없음 — PII 원칙)."""
    if not h or not h.get('score'):
        return ''
    parts = []
    if h.get('experience'):
        e = h['experience']
        parts.append(f"이 과제(계열) 참여 경험 약 {e['months']}개월(마지막 {e['last_year']}년)")
    if h.get('peers'):
        parts.append(f"과거 같은 과제에서 함께 일한 현재 과제원 {len(h['peers'])}명")
    f = h.get('flow')
    if f and f.get('count'):
        parts.append(f"현재 과제에서 이 과제로 옮긴 선례 {f['count']}건(전체 이동 {f['total']}건 중)")
    return ', '.join(parts)
