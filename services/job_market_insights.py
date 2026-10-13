"""
JOB Market 심화 지표(2026-10-13, 사용자 확정 — 주 사용자: 인사/기획 담당자).

services/job_market.py의 기존 추천(A: 과제 분석 유사도, B: 과제원 유사도 → LLM 0~3개 선정)에
"그 과제에 이 사람이 필요한가"와 운영 관점 정보를 더한다. 화면/엑셀/LLM 프롬프트가 같은 값을 쓴다.

  A1 갭 충족      — 과제별 필요 역량(project_competency_gap.json) 중 과제원 최고 유사도가 0.75 미만인
                    약한 역량을 이 사람이 0.75 이상으로 채우는지. 추천 순위에 가산.
  A2 주력 시기    — 과제 내용이 이 사람의 최근 5년 주력과 가까운지, 5년 이전 주력과 더 가까운지(복귀형).
  A3 기존 협업자  — 후보 과제 현재 인원 중 최근 5년 공저·공동발명자 수(collaboration_edges.csv).
  A4 과제 구성    — 후보 과제의 시니어/주니어·주도형 구성과 이 사람이 보완인지.
  A5 근거         — 갭 충족 역량마다 이 사람의 가장 가까운 보유 항목.
  B2 일괄 배치    — 과제 종료 시 과제원 전원을 과제별 인원 상한 안에서 그리디 배정.
  B3 종료 영향    — 종료 과제 인원이 보유자의 절반 이상인 기술/강점(사내 보유 공백 위험).
  B4 육성 경로    — 참여 가능 과제가 없을 때 가장 가까운 과제의 부족 역량 + 멘토(과제원 상위 보유자).
  (B1 인력 요청 / B5 수요·공급 탭은 2026-10-13 사용자 확정으로 제거.)

평가(인사평가) 데이터는 추천 점수에 쓰지 않는다(전문성 적합도와 성과는 다른 축 — 섞으면 "비슷한
사람"이 아니라 "평가 좋은 사람"이 위로 올라와 추천의 의미가 바뀐다). 화면에서 권한이 있는 사용자에게만
참고 열로 보여준다(pages/job_market.py).

LLM을 새로 호출하지 않는다 — 임베딩만 사용(fit.cached_embed, 결과는 텍스트 해시 캐시).
"""
from __future__ import annotations

import os
import sys
import threading

import numpy as np

_PIPELINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pipeline')
if os.path.abspath(_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, os.path.abspath(_PIPELINE_DIR))

import researcher_fit as fit  # noqa: E402
from services import data_store  # noqa: E402

WEAK_THRESHOLD = 0.75       # 과제원 최고 유사도가 이 값 미만인 필요 역량 = 약한 역량(과제별 필요 역량과 동일 기준)
FILL_THRESHOLD = 0.75       # 이 사람이 이 값 이상이면 그 약한 역량을 "채움"
MISSING_THRESHOLD = 0.6     # B4: 이 값 미만이면 "부족 역량"
GAP_WEIGHT = 0.5            # 추천 정렬 가산: adjusted = max(A,B) + GAP_WEIGHT*gap_score + 주력 보정
FOCUS_BONUS = 0.02          # 최근 5년 주력과 일치하면 가산, 복귀형이면 감산
MINORITY_RATIO = 0.3        # 과제 내 시니어(또는 주니어) 비율이 이보다 낮으면 그쪽 인력이 "보완"


def _norm(name: str) -> str:
    return fit.normalize_org_code(name)


def _cos_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-9)
    b = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-9)
    return a @ b.T


# ─── 컨텍스트(검색 1회당 한 번만 읽고 재사용) ──────────────────────────────────

class Context:
    """한 번의 검색에서 여러 사람×여러 후보 과제에 걸쳐 재사용하는 데이터 묶음.
    embed_fn은 테스트에서 교체할 수 있게 주입한다(기본 fit.cached_embed)."""

    def __init__(self, expertise_profiles: dict, embed_fn=None):
        self.profiles = expertise_profiles or {}
        self.embed_fn = embed_fn or fit.cached_embed
        self._emb: dict = {}
        self._lock = threading.Lock()   # 추천은 사람별로 스레드 동시 실행 — 임베딩 캐시 파일 동시 쓰기 방지
        self.researchers = data_store.read_processed('researchers')
        self.name_map = (dict(zip(self.researchers['researcher_id'], self.researchers['name'].astype(str)))
                         if not self.researchers.empty and 'name' in self.researchers.columns else {})
        self.org_map = (dict(zip(self.researchers['researcher_id'], self.researchers['org_code'].astype(str)))
                        if not self.researchers.empty and 'org_code' in self.researchers.columns else {})
        self.gap_by_norm = {_norm(i.get('project_name', '')): i for i in (data_store.read_project_competency_gap() or [])}
        self.partners = _recent_partners(data_store.read_processed('collaboration_edges'))
        self.tenure = _tenure_map(self.researchers)
        self.contrib = _contribution_map(data_store.read_processed('researcher_contribution_metrics'))
        self._items_cache: dict = {}

    # 임베딩: 검색 동안 메모리에 모아 두고, 처음 보는 텍스트만 한 번에 계산
    def embed(self, texts: list) -> np.ndarray:
        with self._lock:
            missing = [t for t in dict.fromkeys(texts) if t not in self._emb]
            if missing:
                for t, v in zip(missing, self.embed_fn(missing)):
                    self._emb[t] = np.asarray(v, dtype=np.float32)
            return np.array([self._emb[t] for t in texts], dtype=np.float32)

    def person_items(self, rid: str) -> list:
        """이 사람의 보유 역량 문구(강점 분야(표준화본 우선)/키워드/전문지식 — 과제별 필요 역량과 같은 기준)."""
        if rid not in self._items_cache:
            p = self.profiles.get(rid) or {}
            fields = p.get('strength_fields_std') or p.get('strength_fields') or []
            vals = []
            for v in list(fields) + list(p.get('strength_keywords') or []) + list(p.get('domain_knowledge_skill') or []):
                v = str(v).strip()
                if v and v not in vals:
                    vals.append(v)
            self._items_cache[rid] = vals
        return self._items_cache[rid]

    def gap_item(self, project_name: str) -> dict | None:
        return self.gap_by_norm.get(_norm(project_name))


def _recent_partners(edges) -> dict:
    """researcher_id -> {최근 5년 협업 상대} (recent_count 없으면 total_count로 대체)."""
    out: dict = {}
    if edges is None or edges.empty or 'researcher_a' not in edges.columns:
        return out
    col = 'recent_count' if 'recent_count' in edges.columns else 'total_count'
    for a, b, n in zip(edges['researcher_a'].astype(str), edges['researcher_b'].astype(str), edges[col]):
        try:
            n = float(n or 0)
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            a, b = a.zfill(8), b.zfill(8)
            out.setdefault(a, set()).add(b)
            out.setdefault(b, set()).add(a)
    return out


def _tenure_map(researchers) -> dict:
    try:
        from process_researcher_similarity import build_tenure_map
        return build_tenure_map(researchers)
    except Exception:
        return {}


def _contribution_map(df) -> dict:
    if df is None or df.empty or 'contribution_type' not in df.columns:
        return {}
    return dict(zip(df['researcher_id'], df['contribution_type'].astype(str)))


# ─── A1 + A5: 갭 충족(근거 포함) ─────────────────────────────────────────────

def _competency_scores(ctx: Context, rid: str, comps: list) -> list:
    """comps(필요 역량 dict 목록)마다 (이 사람 최고 유사도, 가장 가까운 보유 항목)."""
    items = ctx.person_items(rid)
    names = [str(c.get('competency') or '') for c in comps]
    if not items or not names:
        return [(0.0, '') for _ in comps]
    sims = _cos_matrix(ctx.embed(names), ctx.embed(items))
    out = []
    for row in sims:
        j = int(np.argmax(row))
        out.append((float(row[j]), items[j]))
    return out


def gap_fill(ctx: Context, rid: str, project_name: str) -> dict | None:
    """후보 과제의 약한 역량(과제원 최고 < WEAK_THRESHOLD)을 이 사람이 채우는지.
    반환 None = 그 과제의 필요 역량 분석이 없음. score = 약한 역량들에서 (이 사람 - 과제원 최고)의
    양수 부분 평균(0~1)."""
    item = ctx.gap_item(project_name)
    comps = (item or {}).get('competencies') or []
    if not comps:
        return None
    scores = _competency_scores(ctx, rid, comps)
    weak, filled, gains = 0, [], []
    for c, (ps, evidence) in zip(comps, scores):
        team_best = max((float(m.get('score', 0)) for m in c.get('members') or []), default=0.0)
        if team_best >= WEAK_THRESHOLD:
            continue
        weak += 1
        gains.append(max(0.0, ps - team_best))
        if ps >= FILL_THRESHOLD:
            filled.append({'competency': c.get('competency', ''), 'person_score': round(ps, 3),
                           'team_best': round(team_best, 3), 'evidence': evidence})
    return {'weak_count': weak, 'filled': filled, 'total': len(comps),
            'score': round(sum(gains) / weak, 3) if weak else 0.0}


# ─── A2: 최근 5년 / 5년 이전 주력 중 어느 쪽과 가까운가 ────────────────────────

def focus_match(ctx: Context, rid: str, project_embedding) -> dict | None:
    p = ctx.profiles.get(rid) or {}
    cur = [str(v) for v in p.get('current_focus_fields') or [] if str(v).strip()]
    past = [str(v) for v in p.get('past_fields') or [] if str(v).strip()]
    if project_embedding is None or not (cur or past):
        return None
    proj = np.asarray(project_embedding, dtype=np.float32).reshape(1, -1)
    c_score = float(_cos_matrix(proj, ctx.embed([', '.join(cur)]))[0, 0]) if cur else None
    p_score = float(_cos_matrix(proj, ctx.embed([', '.join(past)]))[0, 0]) if past else None
    if p_score is not None and (c_score is None or p_score - c_score > 0.05):
        return {'type': 'past', 'label': '복귀형(5년 이전 주력과 더 가까움)', 'bonus': -FOCUS_BONUS,
                'current': c_score, 'past': p_score}
    return {'type': 'current', 'label': '최근 5년 주력과 일치', 'bonus': FOCUS_BONUS,
            'current': c_score, 'past': p_score}


# ─── A3 / A4: 기존 협업자, 과제 구성 ──────────────────────────────────────────

def collaborators(ctx: Context, rid: str, member_ids: list) -> list:
    """후보 과제 현재 인원 중 최근 5년 공저·공동발명자 [(사번, 이름)]."""
    mine = ctx.partners.get(rid, set())
    return [(m, ctx.name_map.get(m, m)) for m in member_ids if m in mine and m != rid]


def composition(ctx: Context, rid: str, member_ids: list) -> dict | None:
    if not member_ids:
        return None
    n = len(member_ids)
    seniors = sum(1 for m in member_ids if ctx.tenure.get(m) == 'Senior')
    juniors = sum(1 for m in member_ids if ctx.tenure.get(m) == 'Junior')
    leads = sum(1 for m in member_ids if ctx.contrib.get(m) == '주도형')
    me = ctx.tenure.get(rid, '')
    complement = ''
    if me == 'Senior' and seniors / n < MINORITY_RATIO:
        complement = '시니어 보완'
    elif me == 'Junior' and juniors / n < MINORITY_RATIO:
        complement = '주니어 보완'
    me_label = {'Senior': '시니어', 'Junior': '주니어'}.get(me, '미분류')
    return {'total': n, 'seniors': seniors, 'juniors': juniors, 'leads': leads,
            'me': me_label, 'me_contrib': ctx.contrib.get(rid, ''), 'complement': complement}


def enrich_candidates(ctx: Context, rid: str, scored: list, member_ids_by_project: dict) -> list:
    """job_market._score_candidates() 결과에 A1~A4를 붙이고 adjusted 점수로 재정렬."""
    out = []
    for c in scored:
        members = member_ids_by_project.get(c['project_name'], [])
        gap = gap_fill(ctx, rid, c['project_name'])
        focus = focus_match(ctx, rid, c.get('a_embedding'))
        adjusted = c['combined'] + (GAP_WEIGHT * gap['score'] if gap else 0.0) + (focus['bonus'] if focus else 0.0)
        out.append({**c, 'gap': gap, 'focus': focus,
                    'collaborators': collaborators(ctx, rid, members),
                    'composition': composition(ctx, rid, members),
                    'adjusted': round(adjusted, 4)})
    out.sort(key=lambda x: -x['adjusted'])
    return out


def signals_text(c: dict) -> str:
    """LLM 후보 블록에 덧붙일 한 줄 요약(사람 이름은 넣지 않는다 — PII 원칙)."""
    parts = []
    gap = c.get('gap')
    if gap:
        if gap['filled']:
            parts.append('이 연구원이 채울 수 있는 약한 필요 역량: ' + ', '.join(f['competency'] for f in gap['filled']))
        else:
            parts.append(f"약한 필요 역량 {gap['weak_count']}개 중 이 연구원이 채우는 것 없음")
    if c.get('focus'):
        parts.append(c['focus']['label'])
    if c.get('collaborators'):
        parts.append(f"최근 5년 공동 연구자 {len(c['collaborators'])}명 재직")
    comp = c.get('composition')
    if comp and comp.get('complement'):
        parts.append(comp['complement'])
    return ' / '.join(parts)


def public_fields(c: dict) -> dict:
    """화면/엑셀/이력 저장용(직렬화 가능한 값만)."""
    return {
        'gap': c.get('gap'), 'focus': ({k: v for k, v in c['focus'].items()} if c.get('focus') else None),
        'collaborators': [list(x) for x in c.get('collaborators') or []],
        'composition': c.get('composition'), 'adjusted': c.get('adjusted'),
    }


# ─── B4: 육성 경로 ───────────────────────────────────────────────────────────

def growth_path(ctx: Context, rid: str, project_name: str, nurturing=None) -> dict | None:
    """가장 가까운 과제에서 이 사람이 부족한(< MISSING_THRESHOLD) 필요 역량 + 멘토 후보(그 역량의
    과제원 상위 2명)와 멘토의 양성 이력(있으면)."""
    item = ctx.gap_item(project_name)
    comps = (item or {}).get('competencies') or []
    if not comps:
        return None
    if nurturing is None:
        nurturing = data_store.read_processed('nurturing')
    nur_by = {}
    if nurturing is not None and not nurturing.empty and 'researcher_id' in nurturing.columns:
        for r in nurturing.fillna('').to_dict('records'):
            label = ' '.join(str(r.get(k, '')).strip() for k in ('category', 'subcategory', 'institution', 'major')
                             if str(r.get(k, '')).strip())
            if label:
                nur_by.setdefault(str(r['researcher_id']).zfill(8), []).append(label)
    missing = []
    for c, (ps, _ev) in zip(comps, _competency_scores(ctx, rid, comps)):
        if ps >= MISSING_THRESHOLD:
            continue
        mentors = sorted(c.get('members') or [], key=lambda m: -float(m.get('score', 0)))[:2]
        missing.append({
            'competency': c.get('competency', ''), 'description': c.get('description', ''),
            'person_score': round(ps, 3),
            'mentors': [{'researcher_id': m.get('researcher_id', ''),
                         'name': ctx.name_map.get(m.get('researcher_id', ''), m.get('researcher_id', '')),
                         'score': round(float(m.get('score', 0)), 3),
                         'nurturing': nur_by.get(m.get('researcher_id', ''), [])[:2]} for m in mentors],
        })
    return {'project_name': project_name, 'missing': missing}


# ─── B2: 일괄 배치 시뮬레이션 ────────────────────────────────────────────────

def plan_assignment(results: dict, capacity: int = 2) -> dict:
    """사람별 후보(shortlist: adjusted 점수 포함) 중에서, 과제당 최대 capacity명으로 전체 점수가 높도록
    그리디 배정한다(높은 점수 쌍부터 — 사람은 1과제, 과제는 capacity명까지).
    반환: {'assigned': [{researcher_id, project_name, dep_name, score, gap_filled}], 'unassigned': [rid],
           'load': {project_name: 인원}}."""
    pairs = []
    for rid, res in (results or {}).items():
        for c in res.get('shortlist') or []:
            pairs.append((float(c.get('adjusted') or 0), rid, c))
    pairs.sort(key=lambda x: -x[0])
    assigned, load, done = [], {}, set()
    for score, rid, c in pairs:
        if rid in done or load.get(c['project_name'], 0) >= capacity:
            continue
        done.add(rid)
        load[c['project_name']] = load.get(c['project_name'], 0) + 1
        assigned.append({'researcher_id': rid, 'project_name': c['project_name'], 'dep_name': c.get('dep_name', ''),
                         'score': round(score, 3), 'gap_filled': len(((c.get('gap') or {}).get('filled')) or [])})
    unassigned = [rid for rid in (results or {}) if rid not in done]
    return {'assigned': assigned, 'unassigned': unassigned, 'load': load}


# ─── B3: 종료 영향 분석 ──────────────────────────────────────────────────────

def ending_impact(member_ids: list, holders_df=None, min_share: float = 0.5, limit: int = 15) -> list:
    """종료 과제 인원이 보유자의 min_share 이상을 차지하는 기술/강점 — 종료 후 재배치되지 않으면 사내
    활용 공백이 생길 수 있는 항목. technology_holder_summary.csv(현재 재직자 기준 보유자 명단) 사용."""
    if holders_df is None:
        holders_df = data_store.read_processed('technology_holder_summary')
    if holders_df is None or holders_df.empty or 'holder_ids' not in holders_df.columns:
        return []
    ending = {str(m).zfill(8) for m in member_ids}
    out = []
    for r in holders_df.fillna('').to_dict('records'):
        holders = {h.zfill(8) for h in str(r.get('holder_ids', '')).split(';') if h}
        if not holders:
            continue
        inside = holders & ending
        share = len(inside) / len(holders)
        if inside and share >= min_share:
            out.append({'technology': r.get('technology', ''), 'source': r.get('source', ''),
                        'holders': len(holders), 'ending_holders': len(inside),
                        'remaining': len(holders) - len(inside), 'share': round(share, 2)})
    out.sort(key=lambda x: (-x['share'], x['remaining'], x['technology']))
    return out[:limit]
