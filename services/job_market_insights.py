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
  C1 요구사항 커버리지 — 과제 요소(핵심 기술·산출물·기술 난제 문장, 키워드, 필요 역량)를 하나씩 나눠
                    이 사람의 보유 항목과 1:1 비교 → "요구 N개 중 M개 충족"(전체를 뭉친 임베딩 비교의 희석 보완).
  C2 실적 근거    — 최근 5년 논문·특허 제목, 참여 과제명을 과제 내용과 직접 비교한 상위 근거.
  (C3 LLM 확신도/부족한 점은 services/job_market.py의 판정 프롬프트에서.)
  D  과제 참여 이력(2026-10-15) — 이 과제 계열 참여 경험·과거 같은 과제를 한 현재 과제원·현재 과제에서 이 과제로
                    옮긴 선례(services/job_market_history.py). 정렬 가산 HISTORY_WEIGHT × H(0~1).

평가(인사평가) 데이터는 추천 점수에 쓰지 않는다(전문성 적합도와 성과는 다른 축 — 섞으면 "비슷한
사람"이 아니라 "평가 좋은 사람"이 위로 올라와 추천의 의미가 바뀐다). 화면에서 권한이 있는 사용자에게만
참고 열로 보여준다(pages/job_market.py).

LLM을 새로 호출하지 않는다 — 임베딩만 사용(fit.cached_embed, 결과는 텍스트 해시 캐시).
"""
from __future__ import annotations

import os
import re
import sys
import threading
from datetime import date

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
COVER_THRESHOLD = 0.7       # C1: 요구 항목과 보유 항목 유사도가 이 값 이상이면 "충족"
COVER_WEIGHT = 0.2          # C1 정렬 가산: + COVER_WEIGHT × 충족 비율
EVIDENCE_YEARS = 5          # C2: 최근 N년 실적만
EVIDENCE_MIN = 0.5          # C2: 이 값 이상인 실적만 근거로 표시
EVIDENCE_WEIGHT = 0.1       # C2 정렬 가산: + EVIDENCE_WEIGHT × 최고 실적 유사도
# C2: 논문 등급구분 가산(2026-10-14) — 같은 내용이면 최우수·우수 논문이 관련 실적으로 먼저 잡히고 점수도 조금 높게.
EVIDENCE_GRADE_BONUS = {'최우수': 0.05, '우수': 0.03}
MAX_REQUIREMENTS = 20
# D 과제 참여 이력 가산(2026-10-15). scripts/backtest_job_market.py로 실제 과거 이동 적중률을 보고 조정 —
# 서버 환경변수 JM_HISTORY_WEIGHT로 코드 수정 없이 바꿀 수 있다(0이면 표시만 하고 정렬엔 미반영).
# 기본 0.05(2026-10-16 운영 백테스트 3년: 0.05가 현재방식과 적중@1·@3·MRR 동등, 적중@8 소폭 개선 — 0.1부터 적중@1 하락).
try:
    HISTORY_WEIGHT = float(os.environ.get('JM_HISTORY_WEIGHT', '0.05'))
except ValueError:
    HISTORY_WEIGHT = 0.05


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
        self._evidence_cache: dict = {}
        self._evidence_frames = None
        self._history = None
        self.as_of = None   # 백테스트에서 과거 시점 지정(D 과제 참여 이력만 시점 반영)

    @property
    def history(self):
        """D 과제 참여 이력(처음 쓸 때 한 번 로드). 실패하면 False — 그 지표만 생략."""
        if self._history is None:
            try:
                from services import job_market_history as jmh
                self._history = jmh.load()
            except Exception as exc:  # noqa: BLE001
                print(f'[job_market] 과제 참여 이력 로드 실패(지표 생략): {exc}')
                self._history = False
        return self._history

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

    def coverage_items(self, rid: str) -> list:
        """C1용 보유 항목 = person_items + 주요 역할·책임(실제 수행 업무도 요구 충족 근거가 된다)."""
        p = self.profiles.get(rid) or {}
        extra = [str(v).strip() for v in p.get('key_responsibilities') or [] if str(v).strip()]
        return list(dict.fromkeys(self.person_items(rid) + extra))

    def evidence_items(self, rid: str) -> list:
        """C2용 최근 EVIDENCE_YEARS년 실적 [(종류, 제목, 연도)] — 논문 게재·특허 출원·과제 참여(진행 중 포함)."""
        if rid in self._evidence_cache:
            return self._evidence_cache[rid]
        if self._evidence_frames is None:
            self._evidence_frames = (data_store.read_processed('publications'), data_store.read_processed('patents'),
                                     data_store.read_processed('tasks'))
        pubs, pats, tasks = self._evidence_frames
        since = date.today().year - EVIDENCE_YEARS + 1
        out = []

        def _year(*vals):
            for v in vals:
                m = re.match(r'(\d{4})', str(v or ''))
                if m:
                    return int(m.group(1))
            return None

        for df, kind, title_cols, date_cols in ((pubs, '논문', ('title',), ('pub_year', 'pub_date')),
                                                 (pats, '특허', ('title_ko', 'title'), ('application_date',))):
            if df is None or df.empty or 'researcher_id' not in df.columns:
                continue
            for r in df[df['researcher_id'] == rid].fillna('').to_dict('records'):
                title = next((str(r.get(c)).strip() for c in title_cols if str(r.get(c) or '').strip()), '')
                y = _year(*(r.get(c) for c in date_cols))
                if title and y and y >= since:
                    grade = str(r.get('grade_publication') or '').strip() if kind == '논문' else ''
                    # 최우수·우수 논문은 종류에 등급을 붙여 표시하고, evidence_match에서 가산(2026-10-14)
                    out.append((f'{kind}({grade})' if grade in EVIDENCE_GRADE_BONUS else kind, title, y))
        if tasks is not None and not tasks.empty and 'researcher_id' in tasks.columns:
            for r in tasks[tasks['researcher_id'] == rid].fillna('').to_dict('records'):
                title = str(r.get('the_task_name') or r.get('task_name') or '').strip()
                end = str(r.get('end_date') or '').strip()
                y = _year(end) or date.today().year   # 해제일 없음 = 진행 중
                if title and y >= since:
                    out.append(('과제', title, y))
        out = sorted(dict.fromkeys(out), key=lambda x: -x[2])[:40]
        self._evidence_cache[rid] = out
        return out

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


# ─── C1: 요구사항 커버리지 / C2: 실적 근거 ───────────────────────────────────

_SPLIT_RE = re.compile(r'[\n;•·]+|(?<=[.!?])\s+')


def project_requirements(entry: dict | None) -> list:
    """과제 분석(project_expertise_analysis) 항목을 요구 요소 목록으로 — 핵심 기술·산출물·기술 난제는 문장 단위
    (항목당 최대 4개), 키워드(한글 우선)는 그대로. "확인 불가"/너무 짧은 조각은 제외."""
    if not entry:
        return []
    reqs = []
    for key in ('core_tech', 'deliverable', 'challenge'):
        v = str(entry.get(key) or '').strip()
        if not v or v == '확인 불가':
            continue
        parts = [x.strip(' -*\t.。') for x in _SPLIT_RE.split(v)]
        reqs += [x for x in parts if len(x) >= 6][:4]
    kws = [str(k).strip() for k in (entry.get('keywords_kr') or entry.get('keywords_en') or []) if str(k).strip()]
    reqs += kws
    return list(dict.fromkeys(reqs))[:MAX_REQUIREMENTS]


def requirement_coverage(ctx: Context, rid: str, project_name: str, base_requirements: list | None) -> dict | None:
    """요구 요소 + 과제별 필요 역량 이름을 하나씩 이 사람의 보유 항목과 비교. None = 비교할 요구/보유 항목 없음."""
    reqs = list(base_requirements or [])
    item = ctx.gap_item(project_name)
    reqs += [str(c.get('competency') or '').strip() for c in (item or {}).get('competencies') or []]
    reqs = [r for r in dict.fromkeys(reqs) if r][:MAX_REQUIREMENTS]
    have = ctx.coverage_items(rid)
    if not reqs or not have:
        return None
    sims = _cos_matrix(ctx.embed(reqs), ctx.embed(have))
    covered, uncovered = [], []
    for req, row in zip(reqs, sims):
        j = int(np.argmax(row))
        if float(row[j]) >= COVER_THRESHOLD:
            covered.append({'requirement': req, 'item': have[j], 'score': round(float(row[j]), 3)})
        else:
            uncovered.append(req)
    covered.sort(key=lambda x: -x['score'])
    return {'total': len(reqs), 'covered': covered, 'uncovered': uncovered,
            'ratio': round(len(covered) / len(reqs), 3)}


def evidence_match(ctx: Context, rid: str, project_embedding, top: int = 3) -> dict | None:
    """최근 5년 논문·특허·과제 제목 중 과제 내용(분석 텍스트 임베딩)과 가장 가까운 것. None = 실적/과제 분석 없음."""
    items = ctx.evidence_items(rid)
    if project_embedding is None or not items:
        return None
    proj = np.asarray(project_embedding, dtype=np.float32).reshape(1, -1)
    sims = _cos_matrix(proj, ctx.embed([t for _k, t, _y in items]))[0]
    bonus = np.array([next((b for g, b in EVIDENCE_GRADE_BONUS.items() if k.endswith(f'({g})')), 0.0)
                      for k, _t, _y in items], dtype=np.float32)
    sims = sims + bonus   # 정렬은 가산 후 값으로(1.0 상한으로 자르면 동점이 돼 가산 효과가 사라짐), 표시 점수만 1.0 상한
    order = np.argsort(-sims)
    best = min(float(sims[order[0]]), 1.0)
    picks = [{'kind': items[i][0], 'title': items[i][1], 'year': items[i][2], 'score': round(min(float(sims[i]), 1.0), 3)}
             for i in order[:top] if float(sims[i]) >= EVIDENCE_MIN]
    return {'top': round(best, 3), 'items': picks}


def enrich_candidates(ctx: Context, rid: str, scored: list, member_ids_by_project: dict) -> list:
    """job_market._score_candidates() 결과에 A1~A4·C1·C2를 붙이고 adjusted 점수로 재정렬."""
    # 필요한 텍스트를 한 번에 임베딩해 둔다 — 후보마다 따로 부르면 그때마다 임베딩 캐시 파일 전체를 다시 읽는다.
    texts = list(ctx.coverage_items(rid)) + [t for _k, t, _y in ctx.evidence_items(rid)]
    p = ctx.profiles.get(rid) or {}
    for key in ('current_focus_fields', 'past_fields'):
        vals = [str(v) for v in p.get(key) or [] if str(v).strip()]
        if vals:
            texts.append(', '.join(vals))
    for c in scored:
        texts += list(c.get('requirements') or [])
        texts += [str(x.get('competency') or '') for x in (ctx.gap_item(c['project_name']) or {}).get('competencies') or []]
    texts = [t for t in dict.fromkeys(texts) if t]
    if texts:
        ctx.embed(texts)
    out = []
    for c in scored:
        members = member_ids_by_project.get(c['project_name'], [])
        gap = gap_fill(ctx, rid, c['project_name'])
        focus = focus_match(ctx, rid, c.get('a_embedding'))
        coverage = requirement_coverage(ctx, rid, c['project_name'], c.get('requirements'))
        evidence = evidence_match(ctx, rid, c.get('a_embedding'))
        history = (ctx.history.signal(rid, c['project_name'], c.get('member_key', ''), members, as_of=ctx.as_of)
                   if ctx.history else None)
        if history and history.get('peers'):   # 화면 툴팁용 이름(LLM 텍스트에는 인원 수만 — signals_text)
            history = {**history, 'peer_names': [ctx.name_map.get(m, m) for m in history['peers']]}
        base_adjusted = (c['combined'] + (GAP_WEIGHT * gap['score'] if gap else 0.0) + (focus['bonus'] if focus else 0.0)
                         + (COVER_WEIGHT * coverage['ratio'] if coverage else 0.0)
                         + (EVIDENCE_WEIGHT * evidence['top'] if evidence else 0.0))
        adjusted = base_adjusted + (HISTORY_WEIGHT * history['score'] if history else 0.0)
        out.append({**c, 'gap': gap, 'focus': focus, 'coverage': coverage, 'evidence': evidence, 'history': history,
                    'base_adjusted': round(base_adjusted, 4),
                    'collaborators': collaborators(ctx, rid, members),
                    'composition': composition(ctx, rid, members),
                    'adjusted': round(adjusted, 4)})
    out.sort(key=lambda x: -x['adjusted'])
    return out


def signals_text(c: dict) -> str:
    """LLM 후보 블록에 덧붙일 한 줄 요약(사람 이름은 넣지 않는다 — PII 원칙)."""
    parts = []
    cov = c.get('coverage')
    if cov:
        parts.append(f"요구사항 충족 {len(cov['covered'])}/{cov['total']}"
                     + (f" (충족: {', '.join(x['requirement'][:30] for x in cov['covered'][:3])})" if cov['covered'] else '')
                     + (f" (미충족: {', '.join(r[:30] for r in cov['uncovered'][:3])})" if cov['uncovered'] else ''))
    ev = c.get('evidence')
    if ev and ev['items']:
        parts.append('관련 실적: ' + '; '.join(f"[{x['kind']}] {x['title'][:40]}({x['year']})" for x in ev['items'][:2]))
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
    from services.job_market_history import signal_text
    hist = signal_text(c.get('history'))
    if hist:
        parts.append('과제 참여 이력: ' + hist)
    return ' / '.join(parts)


def public_fields(c: dict) -> dict:
    """화면/엑셀/이력 저장용(직렬화 가능한 값만)."""
    return {
        'gap': c.get('gap'), 'focus': ({k: v for k, v in c['focus'].items()} if c.get('focus') else None),
        'collaborators': [list(x) for x in c.get('collaborators') or []],
        'composition': c.get('composition'), 'adjusted': c.get('adjusted'),
        'coverage': ({**c['coverage'], 'covered': c['coverage']['covered'][:8], 'uncovered': c['coverage']['uncovered'][:8]}
                     if c.get('coverage') else None),
        'evidence': c.get('evidence'),
        'history': _public_history(c.get('history')),
    }


def _public_history(h: dict | None) -> dict | None:
    """D 과제 참여 이력 — 화면 툴팁용으로 옛 동료 이름을 붙인다(LLM 프롬프트에는 signals_text의 인원 수만)."""
    if not h or not h.get('score'):
        return None
    return {**h, 'peers': list(h.get('peers') or [])[:20]}


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
    results = {rid: res for rid, res in (results or {}).items() if not res.get('on_leave')}   # 휴직자 제외(2026-10-15)
    for rid, res in results.items():
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
