"""
과제별 역량 갭 분석 (전문성 심화 지표 ⑤, 2026-10, 사용자 확정)

process_project_expertise.py가 만든 과제 문서 분석 결과(project_expertise_
analysis.json)에서 과제별 "필요 역량"을 사내 LLM으로 4~8개 뽑고(입력 텍스트
해시 기준 캐시 — 과제 문서가 바뀌지 않으면 재호출 없음), 그 과제 현재 인력의
보유 역량(연구원 보유 전문성 분석.json의 강점 분야(표준화본 우선)/키워드/
전문지식 및 역량)과 BGE-M3 임베딩으로 대조한다.

  - 과제 인력 = researchers.csv에서 org_code == project_name인 현재 재직자
    + project_personnel.csv(과제 문서에 담당 업무가 적힌 사람)의 합집합
  - 필요 역량마다 인력 보유 항목 중 코사인 유사도 최고값이 GAP_THRESHOLD
    (0.75) 이상이면 "충족"(충족자 목록), 미만이면 "갭"
  - 갭 역량은 과제 밖 현재 재직자 중 유사도 GAP_THRESHOLD 이상인 상위 3명을
    "사내 후보"(candidates)로 함께 기록(이동·협업 검토용)
  - (2026-10-08) 역량별 상세 화면용으로 `members`(과제원 전원의 최고 유사도 — 화면이
    0~0.25/0.25~0.5/0.5~0.75/0.75~1 구간으로 나눠 보여줌)와 `outsiders`(비소속 재직자 중
    0.75 이상 상위 OUTSIDER_TOP_N명, 없으면 0.75 미만 대표 최대 5명 — outsider_low=True)를 추가로
    기록하고, 과제의 소속 단계(level1/2/3 = 플랫폼/그룹/과제)도 함께 저장한다.

  - (2026-10-09) "과제별 필요 역량"으로 목적 변경: 충족/갭 판정 대신 필요 역량 이름 + 쉬운 설명(LLM),
    과제원별 임베딩 유사도 + LLM 근거 한 줄, 비소속 상위 OUTSIDER_TOP_N(10)명(+근거)을 기록한다.
    LLM 프롬프트에는 연구원 ID/이름을 넣지 않는다(순번만 사용).

Source:
  data/processed/project_expertise_analysis.json
  data/processed/researchers.csv, project_personnel.csv
  data/processed/연구원 보유 전문성 분석.json, researcher_strength_std.json(있으면)

Output:
  data/processed/project_competency_gap.json
  data/processed/project_competency_cache.json (필요 역량 LLM 결과 캐시)

Confluence 접근이 막혀 있어도(예: 401) 이 단계는 이미 저장된 과제 분석
결과만 읽으므로 그대로 동작한다.

사용법:
  python pipeline/process_project_competency_gap.py [--refresh]
    --refresh : 필요 역량 캐시를 무시하고 전 과제 재추출
"""

import hashlib
import json
import os
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT_DIR  # noqa: E402
import researcher_fit as fit  # noqa: E402
from llm_client import call_llm, extract_json, max_concurrency, run_concurrent  # noqa: E402
from services.llm import LLMError  # noqa: E402

ANALYSIS_FILE = 'project_expertise_analysis.json'
PROFILES_FILE = '연구원 보유 전문성 분석.json'
STRENGTH_STD_FILE = 'researcher_strength_std.json'
OUT_FILE = 'project_competency_gap.json'
CACHE_FILE = 'project_competency_cache.json'

GAP_THRESHOLD = 0.75
CANDIDATE_TOP_N = 3
OUTSIDER_TOP_N = 10      # 비소속 적합자 표시 인원(유사도 상위, 2026-10-09 사용자 확정)
EVIDENCE_MEMBER_MAX = 30  # LLM 근거를 붙이는 과제원 상한(유사도 상위)
EVIDENCE_TOP_ITEMS = 3   # 후보자당 LLM에 넘기는 가까운 보유 항목 수
EVIDENCE_CACHE_FILE = 'project_competency_evidence_cache.json'

_SYSTEM_PROMPT = """# Role
당신은 R&D 과제 인력 구성 전문가입니다. 과제 문서 요약을 읽고 이 과제를
성공적으로 수행하기 위해 팀에 반드시 있어야 하는 핵심 역량을 도출합니다.

# Guidelines
1. 문서에 드러난 핵심 기술·산출물·기술적 난제를 근거로 4~8개를 도출하세요.
2. 각 역량의 name은 "무엇을 할 수 있어야 하는가"가 드러나는 짧은 명사구로 쓰세요
   (예: "SLAM 알고리즘 설계", "배터리 양극재 합성", "FPGA 하드웨어 가속").
   "소통 능력" 같은 일반 역량은 넣지 마세요.
3. 각 역량의 description은 비전공자도 이해할 수 있게 1~2문장으로 쉽게 설명하세요
   (전문 용어는 풀어 쓰고, 이 과제에서 왜 필요한지를 포함).
4. 문서 근거가 부족하면 개수를 줄이세요(지어내지 마세요).
5. 반드시 아래 JSON 형식으로만 출력하세요.

# Output Format (JSON)
{"required_competencies": [{"name": "역량1", "description": "쉬운 설명"}]}
"""

_EVIDENCE_SYSTEM_PROMPT = """# Role
당신은 R&D 인력 매칭 전문가입니다. 하나의 "필요 역량"과, 후보자별로 임베딩으로 찾은
"가장 가까운 보유 역량 항목(유사도 포함)"이 주어집니다.

# Guidelines
1. 후보자마다 왜 이 필요 역량을 갖췄다고 볼 수 있는지(또는 어느 부분이 가까운지)를
   보유 항목에 근거해 1문장(60자 안팎)으로 쓰세요. 항목에 없는 내용을 지어내지 마세요.
2. 유사도가 낮으면(0.5 미만) "관련성이 낮음"을 솔직히 밝히세요.
3. 후보자는 idx(번호)로만 식별합니다. 반드시 아래 JSON 형식으로만 출력하세요.

# Output Format (JSON)
{"evidence": [{"idx": 0, "reason": "근거 한 문장"}]}
"""


def _read_json(name: str, default):
    path = os.path.join(OUT_DIR, name)
    if not os.path.exists(path):
        return default
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _write_json(name: str, data) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, name), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _read_csv(name: str) -> pd.DataFrame:
    path = os.path.join(OUT_DIR, f'{name}.csv')
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
    if 'researcher_id' in df.columns:
        df['researcher_id'] = df['researcher_id'].astype(str).str.zfill(8)
    return df


def _project_text(item: dict) -> str:
    parts = []
    for label, key in (('핵심 기술', 'core_tech'), ('최종 산출물', 'deliverable'),
                       ('기술적 난제', 'challenge'), ('연구 배경', 'background'),
                       ('기대효과', 'expected_impact')):
        val = str(item.get(key) or '').strip()
        if val:
            parts.append(f'[{label}]\n{val}')
    kws = [str(k).strip() for k in (item.get('keywords_kr') or []) + (item.get('keywords_en') or []) if str(k).strip()]
    if kws:
        parts.append('[키워드]\n' + ', '.join(kws))
    return '\n\n'.join(parts)


def _required_competencies(text: str, cache: dict, refresh: bool) -> list | None:
    """[{'name','description'}, ...]. 캐시 키는 v2 접두(설명 포함 형식)."""
    key = 'v2:' + hashlib.sha256(text.encode('utf-8')).hexdigest()
    if not refresh and key in cache:
        return cache[key]
    raw = call_llm(f'아래는 한 R&D 과제 문서의 분석 요약입니다.\n\n{text}', _SYSTEM_PROMPT,
                   temperature=0.1, max_tokens=3000)
    if not raw:
        return None
    try:
        data = json.loads(extract_json(raw))
    except json.JSONDecodeError:
        return None
    values, seen = [], set()
    for v in data.get('required_competencies') or []:
        if isinstance(v, dict):
            name, desc = str(v.get('name') or '').strip(), str(v.get('description') or '').strip()
        else:
            name, desc = str(v).strip(), ''
        if name and name not in seen:
            seen.add(name)
            values.append({'name': name, 'description': desc})
    cache[key] = values
    return values


def _comp_name(c) -> str:
    return str(c.get('name') if isinstance(c, dict) else c).strip()


def _comp_desc(c) -> str:
    return str(c.get('description') or '').strip() if isinstance(c, dict) else ''


def _researcher_items(profiles: list, strength_std: list) -> dict:
    """researcher_id -> 보유 역량 문구 리스트(강점 분야는 표준화본 우선)."""
    std_by_id = {str(s.get('researcher_id', '')): s for s in strength_std or []}
    items = {}
    for p in profiles:
        rid = str(p.get('researcher_id', '')).zfill(8)
        std = std_by_id.get(rid) or {}
        fields = std.get('strength_fields_std') or p.get('strength_fields') or []
        vals = []
        for v in list(fields) + list(p.get('strength_keywords') or []) + list(p.get('domain_knowledge_skill') or []):
            v = str(v).strip()
            if v and v not in vals:
                vals.append(v)
        if vals:
            items[rid] = vals
    return items


def analyze_gaps(projects: list, required: dict, members: dict, items: dict, current: set,
                 levels: dict | None = None) -> list:
    """required: project_name -> [역량], members: project_name -> set(rid).
    임베딩은 fit.cached_embed(실패 시 LLMError 전파)."""
    levels = levels or {}
    flat = [(rid, v) for rid, vals in items.items() for v in vals]
    comp_all = sorted({_comp_name(c) for vals in required.values() for c in vals})
    if not flat or not comp_all:
        return []
    item_vec = fit.cached_embed([v for _, v in flat])
    comp_vec = fit.cached_embed(comp_all)
    sims = fit.cosine_sim_matrix(comp_vec, item_vec)  # (역량, 항목)
    comp_idx = {c: i for i, c in enumerate(comp_all)}
    idx_by_rid: dict = {}
    for j, (rid, _v) in enumerate(flat):
        idx_by_rid.setdefault(rid, []).append(j)

    def _top_items(rid, row_sims):
        js = sorted(idx_by_rid.get(rid, []), key=lambda j: -float(row_sims[j]))[:EVIDENCE_TOP_ITEMS]
        return [{'item': flat[j][1], 'score': round(float(row_sims[j]), 3)} for j in js]

    results = []
    for proj in projects:
        name = proj.get('project_name', '')
        comps = required.get(name) or []
        if not comps:
            continue
        team = members.get(fit.normalize_org_code(name), set())
        rows = []
        for comp in comps:
            c, desc = _comp_name(comp), _comp_desc(comp)
            row_sims = sims[comp_idx[c]]
            best_by_rid: dict = {}
            for j, (rid, v) in enumerate(flat):
                sc = float(row_sims[j])
                if rid not in best_by_rid or sc > best_by_rid[rid][1]:
                    best_by_rid[rid] = (v, sc)
            team_hits = sorted(((rid, v, sc) for rid, (v, sc) in best_by_rid.items() if rid in team),
                               key=lambda x: -x[2])
            best = team_hits[0][2] if team_hits else 0.0
            covered = best >= GAP_THRESHOLD
            entry = {
                'competency': c,
                'description': desc,
                'covered': covered,
                'best_score': round(best, 3),
                'covered_by': [{'researcher_id': rid, 'item': v, 'score': round(sc, 3)}
                               for rid, v, sc in team_hits if sc >= GAP_THRESHOLD][:5],
                'candidates': [],
            }
            outside_all = sorted(((rid, v, sc) for rid, (v, sc) in best_by_rid.items()
                                  if rid not in team and rid in current), key=lambda x: -x[2])
            high = [x for x in outside_all if x[2] >= GAP_THRESHOLD]
            if not covered:
                entry['candidates'] = [{'researcher_id': rid, 'item': v, 'score': round(sc, 3)}
                                       for rid, v, sc in high[:CANDIDATE_TOP_N]]
            # 역량별 상세 화면용: 과제원(유사도 순) + 비소속 재직자 유사도 상위 OUTSIDER_TOP_N명
            entry['members'] = [{'researcher_id': rid, 'item': v, 'score': round(sc, 3),
                                 'top_items': _top_items(rid, row_sims)}
                                for rid, v, sc in team_hits]
            entry['outsiders'] = [{'researcher_id': rid, 'item': v, 'score': round(sc, 3),
                                   'top_items': _top_items(rid, row_sims)}
                                  for rid, v, sc in outside_all[:OUTSIDER_TOP_N]]
            entry['outsider_low'] = False
            rows.append(entry)
        n_cov = sum(1 for r in rows if r['covered'])
        l1, l2, l3 = levels.get(name, ('', '', ''))
        results.append({
            'project_name': name,
            'dep_name': proj.get('dep_name', ''),
            'level1': l1, 'level2': l2, 'level3': l3,
            'member_count': len(team),
            'analyzed_member_count': len([r for r in team if r in items]),
            'coverage_pct': round(n_cov * 100.0 / len(rows), 1) if rows else 0.0,
            'gap_count': len(rows) - n_cov,
            'competencies': rows,
        })
    results.sort(key=lambda r: (r['coverage_pct'], -r['gap_count']))
    return results


def _evidence_task(comp: str, desc: str, persons: list, cache: dict):
    """한 (과제, 역량)의 후보자들에 대한 LLM 근거 {idx: reason}. persons: [{'top_items': [...]}, ...]
    (순번 idx = 리스트 위치). 캐시는 프롬프트 해시 기준."""
    lines = []
    for i, p in enumerate(persons):
        its = '; '.join(f"{t['item']}({t['score']:.2f})" for t in p.get('top_items') or [])
        lines.append(f'[{i}] {its or "(보유 항목 없음)"}')
    prompt = (f'필요 역량: {comp}\n설명: {desc}\n\n후보자별 가까운 보유 항목(유사도):\n' + '\n'.join(lines))
    key = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
    if key in cache:
        return cache[key]
    raw = call_llm(prompt, _EVIDENCE_SYSTEM_PROMPT, temperature=0.1, max_tokens=3000)
    if not raw:
        return None
    try:
        data = json.loads(extract_json(raw))
    except json.JSONDecodeError:
        return None
    out = {}
    for e in data.get('evidence') or []:
        try:
            out[int(e.get('idx'))] = str(e.get('reason') or '').strip()
        except (TypeError, ValueError):
            continue
    cache[key] = {str(k): v for k, v in out.items()}
    return cache[key]


def attach_evidence(results: list, cache: dict) -> int:
    """results의 역량별 members(상위 EVIDENCE_MEMBER_MAX명)+outsiders에 LLM 근거(reason)를 붙인다.
    LLM 실패 시 해당 역량은 근거 없이 둔다(화면은 가까운 항목으로 대체). 반환: 성공 건수."""
    jobs = []
    for r in results:
        for c in r.get('competencies') or []:
            persons = (c.get('members') or [])[:EVIDENCE_MEMBER_MAX] + (c.get('outsiders') or [])
            if persons:
                jobs.append((c, persons))
    tasks = [(lambda c=c, ps=ps: _evidence_task(c.get('competency', ''), c.get('description', ''), ps, cache))
             for c, ps in jobs]
    done = 0
    for (c, persons), (res, err) in zip(jobs, run_concurrent(tasks, max_workers=max_concurrency())):
        if err or not res:
            continue
        for i, p in enumerate(persons):
            reason = res.get(str(i)) if isinstance(res, dict) and str(i) in res else (res.get(i) if isinstance(res, dict) else None)
            if reason:
                p['reason'] = reason
        done += 1
    print(f'  근거 생성 {done}/{len(jobs)}건')
    return done


def _project_levels(projects: list) -> dict:
    """project_name -> (플랫폼, 그룹, 과제) — team_refer의 1/2/3단계부서명 칸 값(과제명을
    org_name_wd로 매칭). team_refer가 없거나 매칭이 없으면 ('', '', '')."""
    try:
        from services import similarity_map as sm
        return {p.get('project_name', ''): sm.org_code_level_names(fit.normalize_org_code(p.get('project_name', '')))
                for p in projects}
    except Exception as exc:  # team_refer 없음 등 — 단계 구분 없이 진행
        print(f'  [WARN] 과제 소속 단계 조회 실패(단계 없이 저장): {exc}')
        return {}


def process(refresh: bool = False) -> bool:
    projects = _read_json(ANALYSIS_FILE, [])
    if not projects:
        print(f'[process_project_competency_gap] {ANALYSIS_FILE} 없음 — 종료 '
              '(process_project_expertise.py 먼저 실행)')
        return False
    profiles = _read_json(PROFILES_FILE, [])
    if not profiles:
        print(f'[process_project_competency_gap] {PROFILES_FILE} 없음 — 종료')
        return False

    researchers = _read_csv('researchers')
    current = set(researchers['researcher_id']) if not researchers.empty else set()
    if not researchers.empty and 'is_current' in researchers.columns:
        current = set(researchers.loc[researchers['is_current'].str.upper() != 'N', 'researcher_id'])
    members: dict = {}
    if not researchers.empty and 'org_code' in researchers.columns:
        for rid, org in zip(researchers['researcher_id'], researchers['org_code']):
            if rid in current and str(org).strip():
                members.setdefault(fit.normalize_org_code(str(org)), set()).add(rid)
    personnel = _read_csv('project_personnel')
    if not personnel.empty and 'project_name' in personnel.columns:
        for rid, pname in zip(personnel['researcher_id'], personnel['project_name']):
            if rid and rid != '00000000' and str(pname).strip():
                members.setdefault(fit.normalize_org_code(str(pname)), set()).add(rid)

    cache = _read_json(CACHE_FILE, {})
    required = {}
    print(f'[process_project_competency_gap] 과제 {len(projects)}건 필요 역량 추출 중...')
    for proj in projects:
        name = proj.get('project_name', '')
        text = _project_text(proj)
        if not name or not text:
            continue
        try:
            comps = _required_competencies(text, cache, refresh)
        except LLMError as exc:
            print(f'  [{name}] 필요 역량 추출 실패: {exc}')
            continue
        if comps:
            required[name] = comps
    _write_json(CACHE_FILE, cache)

    items = _researcher_items(profiles, _read_json(STRENGTH_STD_FILE, []))
    levels = _project_levels(projects)
    try:
        results = analyze_gaps(projects, required, members, items, current, levels)
    except LLMError as exc:
        print(f'  [WARN] 임베딩 실패 — 역량 갭 분석 중단: {exc}')
        return False
    ev_cache = _read_json(EVIDENCE_CACHE_FILE, {})
    attach_evidence(results, ev_cache)
    _write_json(EVIDENCE_CACHE_FILE, ev_cache)
    computed_at = datetime.now().strftime('%Y-%m-%d %H:%M')
    for r in results:
        r['computed_at'] = computed_at
    _write_json(OUT_FILE, results)
    gaps = sum(r['gap_count'] for r in results)
    print(f'[OK]   {OUT_FILE} 저장 (과제 {len(results)}건, 갭 역량 총 {gaps}개)')
    return True


if __name__ == '__main__':
    process(refresh='--refresh' in sys.argv)
