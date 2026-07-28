"""
연구원 ↔ 연구원 유사도 분석 모듈

과제(프로젝트)는 서로 완전히 달라도(예: CPO ↔ CPU) 그 안의 개별 스킬(AI,
회로설계 등)은 겹칠 수 있다. 과제 라벨이 아니라 "실제로 어떤 전문성을
갖고 있는가"로 연구원을 직접 비교하기 위해, process_researcher_expertise.py가
만든 연구원별 전문성 프로필(강점 분야/강점 키워드/Hard Skills/Domain
Knowledge)을 BGE-M3로 임베딩하고 코사인 유사도를 계산한다.

1단계(임베딩)는 사내 chat LLM을 호출하지 않는다(순수 임베딩 유사도) — 후보를
추리는 데는 "의미적으로 얼마나 가까운가"만 필요하므로 비용이 거의 들지 않는다.
임베딩은 표현이 달라도("AI" vs "인공지능") 의미가 비슷하면 가깝게 나오므로,
과제명이 전혀 달라도 실제로 비슷한 일을 하는 연구원을 찾아낼 수 있다.

매칭 로직(코사인 유사도, top-K 추출)은 pipeline/researcher_fit.py 공용 모듈을
그대로 재사용한다(process_project_researcher_fit.py가 과제↔연구원 매칭에
쓰는 것과 동일한 함수들이며, 임베딩 자체는 두 스크립트가 다시 계산한다 —
비교 대상 텍스트 집합이 다르기 때문).

근속 그룹별 top-K: 대상 연구원의 근속(Junior/Senior, 아래 3단계 참고)을 알 수
있으면, 후보를 Junior/Senior로 나눠 그룹별로 각각 top_k명씩(최대 top_k*2명)
찾는다 — "이 사람과 전문성이 가장 비슷한 Junior top_k명"과 "가장 비슷한
Senior top_k명"을 함께 보여주기 위함이다. 후보 중 hire_date가 없어 근속을
모르는 사람은 어느 그룹에도 들어가지 못하므로 이 그룹별 검색에서는 제외된다.
대상 연구원 본인의 근속을 모르면(hire_date 없음) 그룹 구분 없이 기존처럼
전체 후보 중 top_k명을 찾는다(하위 호환 폴백). --top-k는 이제 "그룹당 개수"
(대상자 근속을 아는 경우) 또는 "전체 개수"(모르는 경우, 폴백)를 의미한다.

2단계(LLM 판정, top-K 후보에 대해서만): 임베딩 점수만으로는 "왜 유사한지",
"단어만 겹치고 실제 업무는 다른 건 아닌지"를 알 수 없다. 그래서 top-K로
추려진 후보 쌍에 대해서만 "R&D Peer Similarity Agent" 페르소나가 두 프로필을
나란히 보고 (동일 분야/인접 분야/낮음) 정성적 등급, 구체적 근거, 표면적
어휘 일치 여부를 판정한다.

  ※ 재현성: LLM 호출은 temperature=0으로 고정하고, 한 번 판정한 쌍은
    researcher_pair_judgment.json에 영구 캐시한다(신규거나 이전에 실패해
    값이 비어 있는 쌍만 다음 실행 때 재시도 — journal_authority 캐시와 동일한
    방식). 캐시가 있는 한 재실행해도 같은 값이 그대로 나온다.
  ※ 대칭성: A~B와 B~A는 같은 질문이므로, researcher_id를 정렬한 고정 키
    ("A|B", A<B)로 쌍을 관리해 실제로는 딱 한 번만 판정하고, 그 결과를
    A쪽 목록과 B쪽 목록 양쪽에 그대로 재사용한다 — 방향에 따라 등급/근거가
    서로 어긋나는 일이 생기지 않는다.
  ※ 캐시 무시하고 전체 쌍을 다시 판정하려면 --refresh-judgments 사용.

3단계(근속 라벨): researchers.csv의 hire_date로 그때그때(저장하지 않고 실행
시점 기준) 근속=round((오늘-hire_date).days/365, 2)을 계산해, 5년 미만이면
Junior, 5년 이상이면 Senior 라벨을 결과에 붙인다. 매칭 로직(누가 누구와
유사한지) 자체는 바꾸지 않고, 대상자 본인과 각 유사 연구원에 라벨만
추가한다 — hire_date가 없으면 라벨 없이(''), HTML에서는 배지를 생략한다.

Source:
  data/processed/연구원 보유 전문성 분석.json (process_researcher_expertise.py)
  data/processed/researchers.csv               (HTML에 이름 표시용)

Output:
  data/processed/researcher_similarity.json
  data/processed/researcher_similarity.html
  data/processed/researcher_pair_judgment.json (쌍 판정 캐시 — 누적 재사용)

위 json/html의 '현재본'(data/processed, 매번 덮어씀)과는 별개로, 실행 시각이
붙은 사본을 data/processed/result/04. 연구원_연구원_유사도_매칭/ 아래에
추가로 남겨 이력이 누적되도록 한다(result_archive.py, 덮어쓰기 없음).

사용법:
  python pipeline/process_researcher_similarity.py [--top-k 5] [--refresh-judgments]
"""

import html
import json
import os
import sys
from datetime import date, datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE_DIR, OUT_DIR  # noqa: E402
sys.path.insert(0, BASE_DIR)
import rd_specialist_markdown as mmd  # noqa: E402
import researcher_fit as fit  # noqa: E402
import result_archive  # noqa: E402
from services.llm import LLMError  # noqa: E402

DEFAULT_TOP_K = fit.TOP_K

_PAIR_JUDGE_SYSTEM_PROMPT = """# Role
당신은 두 연구원의 전문성 프로필을 비교해, 실제로 얼마나 유사한 분야/업무를
다루는지 판단하는 "R&D Peer Similarity Agent"입니다.

# Goal
두 연구원이 서로 다른 과제(프로젝트)에 소속돼 있더라도(예: 하나는 CPO 과제,
하나는 CPU 과제) 과제명과 무관하게, 실제 보유 전문성이 얼마나 겹치는지
객관적으로 판단합니다.

# Guidelines & Constraints
1. 철저한 팩트 기반: 두 프로필에 명시된 내용만 근거로 삼고, 언급되지 않은
   내용을 임의로 추정해 유사하다고 판단하지 마세요.
2. 표면적 어휘 일치와 실질적 업무 일치를 구분하세요. 예를 들어 둘 다
   "Python"을 언급해도 실제 응용 분야(예: 신호처리 vs 자연어처리)가 다르면
   낮은 등급으로 판단하고, evidence에 그 이유를 명시하세요. 단어만 겹치고
   실질적 업무 영역이 다르면 surface_only를 true로 표시하세요.
3. evidence는 서술형 문장이 아니라 개조식(명사형으로 끝나는 간결한 구/절)
   근거 1~3개를 배열로 작성하세요. 예: "두 사람 모두 강화학습 기반 로봇
   제어 전문성 보유"가 아니라 "강화학습 기반 로봇 제어 전문성 공통 보유".
4. 반드시 아래 JSON 형식으로만 출력하고, 그 외 텍스트는 출력하지 마세요.

# Output Format (JSON)
{
  "level": "동일 분야" 또는 "인접 분야" 또는 "낮음",
  "evidence": ["개조식 근거 1", "개조식 근거 2"],
  "surface_only": true 또는 false
}
"""

_LEVEL_VALUES = ('동일 분야', '인접 분야', '낮음')


def _read_expertise() -> list:
    path = os.path.join(OUT_DIR, '연구원 보유 전문성 분석.json')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _top_within(idx_pool: list, row, k: int) -> list:
    """idx_pool(후보 인덱스 부분집합) 안에서만 row 기준 상위 k개 인덱스를 고른다
    (fit.top_k_idx를 그대로 재사용하기 위해, 후보가 아닌 위치는 -inf로 마스킹)."""
    if not idx_pool or k <= 0:
        return []
    mask = np.full(len(row), -np.inf)
    for j in idx_pool:
        mask[j] = row[j]
    return fit.top_k_idx(mask, min(k, len(idx_pool)))


def compute_similarity(profiles: list, top_k: int = DEFAULT_TOP_K, tenure_map: dict | None = None) -> list:
    """profiles: 연구원 보유 전문성 분석.json의 원소 리스트(researcher_id 포함).
    tenure_map: researcher_id -> 'Junior'/'Senior'/''(모름). 대상 연구원의
    근속을 알 수 있으면, 후보를 Junior/Senior로 나눠 그룹별로 각각 top_k명씩
    (최대 top_k*2명) 찾는다 — 후보 중 근속을 모르는 사람은 어느 그룹에도
    속하지 못해 이 검색에서 제외된다. 대상 연구원 본인의 근속을 모르면
    그룹 구분 없이 기존처럼 전체 후보 중 top_k명을 찾는다(하위 호환 폴백).

    반환: [{'researcher_id', 'similar': [{'researcher_id', 'score'}, ...]}, ...]
    similar은 자기 자신을 제외한 유사도 내림차순. score는 코사인 유사도
    (-1~1, 실제로는 임베딩 특성상 대부분 0~1 범위)를 소수 4자리로 반올림."""
    tenure_map = tenure_map or {}
    researcher_ids = [p['researcher_id'] for p in profiles]
    texts = [fit.researcher_profile_text(p) for p in profiles]

    # 텍스트 해시 기준 캐시(fit.cached_embed) — process_project_researcher_fit.py가
    # 같은 연구원 프로필 텍스트를 이미 임베딩해 뒀다면 재계산하지 않는다.
    embeddings = fit.cached_embed(texts)
    sims = fit.cosine_sim_matrix(embeddings, embeddings)

    n = len(researcher_ids)

    results = []
    for i in range(n):
        row = sims[i].copy()
        row[i] = -1.0  # 자기 자신은 후보에서 제외

        subject_level = tenure_map.get(researcher_ids[i], '')
        if not subject_level:
            k = min(top_k, n - 1) if n > 1 else 0
            top_idx = fit.top_k_idx(row, k) if k > 0 else []
        else:
            junior_idx = [j for j in range(n) if j != i and tenure_map.get(researcher_ids[j], '') == 'Junior']
            senior_idx = [j for j in range(n) if j != i and tenure_map.get(researcher_ids[j], '') == 'Senior']
            top_idx = _top_within(junior_idx, row, top_k) + _top_within(senior_idx, row, top_k)

        similar = [
            {'researcher_id': researcher_ids[j], 'score': round(float(row[j]), 4)}
            for j in top_idx
        ]
        results.append({'researcher_id': researcher_ids[i], 'similar': similar})
    return results


def _pair_key(id_a: str, id_b: str) -> str:
    """A~B와 B~A를 같은 키로 취급하는 대칭 캐시 키(researcher_id 정렬)."""
    a, b = sorted([id_a, id_b])
    return f'{a}|{b}'


PAIR_CACHE_PATH = os.path.join(OUT_DIR, 'researcher_pair_judgment.json')


def _load_pair_cache() -> dict:
    if not os.path.exists(PAIR_CACHE_PATH):
        return {}
    with open(PAIR_CACHE_PATH, encoding='utf-8') as f:
        return json.load(f)


def _save_pair_cache(cache: dict):
    with open(PAIR_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _collect_pairs(results: list) -> set:
    """top-K 유사도 목록에 등장하는 모든 (researcher_id, researcher_id) 쌍을
    방향과 무관하게 유일하게 모은다(정렬된 튜플이므로 A-B와 B-A는 하나로 합쳐짐)."""
    pairs = set()
    for item in results:
        rid = item['researcher_id']
        for s in item['similar']:
            pairs.add(tuple(sorted([rid, s['researcher_id']])))
    return pairs


def _judge_pair(text_a: str, text_b: str) -> dict | None:
    """두 연구원 프로필 텍스트를 "R&D Peer Similarity Agent"에게 판정시킨다.
    temperature=0으로 고정해 같은 입력엔 항상 같은(또는 최대한 안정적인) 결과가
    나오도록 한다. 실패하거나 형식이 어긋나면 None(캐시에는 빈 값으로 남아
    다음 실행 때 재시도됨)."""
    prompt = (
        f'[연구원 A 전문성 프로필]\n{text_a}\n\n'
        f'[연구원 B 전문성 프로필]\n{text_b}\n\n'
        f'위 두 연구원이 실제로 유사한 분야/업무 전문성을 갖고 있는지 판단해 주세요.'
    )
    raw = fit.call_llm(prompt, _PAIR_JUDGE_SYSTEM_PROMPT, temperature=0.0, max_tokens=400)
    if not raw:
        return None
    try:
        data = json.loads(fit.extract_json(raw))
    except json.JSONDecodeError:
        return None
    level = data.get('level', '')
    if level not in _LEVEL_VALUES:
        return None
    raw_evidence = data.get('evidence', '')
    # 개조식 근거는 리스트로 그대로 저장(화면에서 불릿으로 렌더링). 예전
    # 캐시(서술형 문자열)와의 하위 호환을 위해 문자열이면 그대로 문자열로 남긴다
    # (--refresh-judgments로 재판정하기 전까지는 기존 캐시 값을 그대로 보여줌).
    evidence = [str(e) for e in raw_evidence if str(e).strip()] if isinstance(raw_evidence, list) \
        else str(raw_evidence)
    return {
        'level': level,
        'evidence': evidence,
        'surface_only': bool(data.get('surface_only', False)),
    }


def _update_pair_judgments(pairs: set, text_by_id: dict, cache: dict, force: bool = False) -> dict:
    """캐시에 실제 판정 값이 있는 쌍은 건너뛰고, 값이 비어 있는 쌍(신규거나
    이전 판정이 실패한 것)만 LLM으로 재판정한다(누적 재사용). 쌍은 _pair_key()의
    정렬된 키로 관리하므로 A-B/B-A를 합쳐 한 번만 판정하고, 그 결과를 양쪽
    모두에서 재사용한다(대칭성 보장). force=True(--refresh-judgments)면 캐시와
    무관하게 전달된 쌍 전체를 다시 판정한다.

    동시 호출 허용치(fit.max_concurrency)만큼 스레드풀로 동시 판정한다
    (journal_authority.py 등과 동일한 패턴) — 개별 쌍 판정 중 예기치 못한 예외가
    나도(fit.run_concurrent가 잡아 반환) 다른 쌍 판정은 계속 진행하고, 실패한
    쌍만 에러와 함께 로그로 남긴다. on_complete 콜백으로 진행 상황을 실시간으로
    출력한다(run_concurrent 자체는 전체가 끝나야 반환하므로)."""
    targets = [p for p in pairs if force or not cache.get(_pair_key(*p))]
    if not targets:
        return cache
    label = '전체 재판정' if force else '신규/미확인'
    workers = fit.max_concurrency()
    total = len(targets)
    print(f'[process_researcher_similarity] 연구원 쌍 LLM 판정 중 ({label} {total}쌍, 동시 {workers}건)...')
    completed = 0

    def _on_complete(_i, _result, _error):
        nonlocal completed
        completed += 1
        if completed % 10 == 0 or completed == total:
            print(f'    (진행: {completed}/{total} 완료)')

    tasks = [(lambda a=a, b=b: _judge_pair(text_by_id[a], text_by_id[b])) for a, b in targets]
    task_results = fit.run_concurrent(tasks, max_workers=workers, on_complete=_on_complete)

    for (a, b), (judged, error) in zip(targets, task_results):
        key = _pair_key(a, b)
        if error is not None:
            print(f'    [에러] {a} - {b}: {type(error).__name__}: {error}')
            cache[key] = {}
        else:
            cache[key] = judged or {}
            print(f"    [{'OK' if judged else '실패'}] {a} - {b}")
    _save_pair_cache(cache)
    return cache


def attach_pair_judgments(results: list, profiles: list, force: bool = False) -> list:
    """compute_similarity() 결과의 각 similar 항목에 LLM 판정(level/evidence/
    surface_only)을 덧붙인다. 캐시 미스만 새로 판정하고, 판정을 아예 구하지
    못한 쌍은 빈 값으로 남아 HTML에서는 조용히 생략된다(임베딩 점수만 표시)."""
    text_by_id = {p['researcher_id']: fit.researcher_profile_text(p) for p in profiles}
    pairs = _collect_pairs(results)
    cache = _load_pair_cache()
    cache = _update_pair_judgments(pairs, text_by_id, cache, force=force)

    for item in results:
        rid = item['researcher_id']
        for s in item['similar']:
            judged = cache.get(_pair_key(rid, s['researcher_id'])) or {}
            s['level'] = judged.get('level', '')
            s['evidence'] = judged.get('evidence', '')
            s['surface_only'] = judged.get('surface_only', False)
    return results


_TENURE_JUNIOR_THRESHOLD = 5.0


def _tenure_level(hire_date_str) -> str:
    """근속=round((오늘-hire_date).days/365, 2)를 그때그때 계산해(저장하지 않음)
    5년 미만이면 'Junior', 5년 이상이면 'Senior'를 반환한다. hire_date가 없거나
    형식이 안 맞으면 빈 문자열(미분류 — 호출부가 배지 없이 처리)."""
    s = str(hire_date_str or '').strip()
    if not s:
        return ''
    try:
        hire_dt = datetime.strptime(s[:10], '%Y-%m-%d').date()
    except ValueError:
        return ''
    tenure = round((date.today() - hire_dt).days / 365, 2)
    return 'Junior' if tenure < _TENURE_JUNIOR_THRESHOLD else 'Senior'


def build_tenure_map(researchers_df: pd.DataFrame) -> dict:
    """researcher_id -> 'Junior'/'Senior'/''(모름) 매핑을 한 번만 계산해,
    compute_similarity()의 그룹별 검색과 attach_tenure_levels()의 라벨 표시가
    같은 맵을 재사용하도록 한다."""
    if researchers_df.empty or 'hire_date' not in researchers_df.columns:
        return {}
    hire_map = researchers_df.set_index('researcher_id')['hire_date'].to_dict()
    return {rid: _tenure_level(hd) for rid, hd in hire_map.items()}


def attach_tenure_levels(results: list, tenure_map: dict) -> list:
    """build_tenure_map()이 계산한 근속 Junior(5년 미만)/Senior(5년 이상) 라벨을
    결과에 붙인다 — compute_similarity()/attach_pair_judgments()의 매칭 로직
    (누가 누구와 유사한지)은 그대로 두고, 대상자 본인과 각 유사 연구원 항목에
    tenure_level 필드만 추가한다."""
    for item in results:
        item['tenure_level'] = tenure_map.get(item['researcher_id'], '')
        for s in item['similar']:
            s['tenure_level'] = tenure_map.get(s['researcher_id'], '')
    return results


_LEVEL_CLASS = {'동일 분야': 'good', '인접 분야': 'warn', '낮음': 'low'}
_TENURE_CLASS = {'Junior': 'junior', 'Senior': 'senior'}


def _tenure_badge_html(tenure_level: str) -> str:
    if not tenure_level:
        return ''
    css = _TENURE_CLASS.get(tenure_level, 'junior')
    return f'<span class="badge {css}">{html.escape(tenure_level)}</span>'


def _evidence_html(evidence, surface_only: bool) -> str:
    """evidence가 리스트(신규 개조식 판정)면 불릿 목록으로, 문자열(예전 서술형
    캐시)이면 문단으로 렌더링한다 — 캐시를 --refresh-judgments 없이 그대로 둬도
    예전 형식이 깨지지 않는다. surface_only면 경고 문구를 덧붙인다."""
    if isinstance(evidence, list) and evidence:
        out = f'<ul class="m-ev">{"".join(f"<li>{html.escape(e)}</li>" for e in evidence)}</ul>'
    elif isinstance(evidence, str) and evidence:
        out = f'<p class="m-ev-text">{html.escape(evidence)}</p>'
    else:
        out = ''
    if evidence and surface_only:
        out += '<div class="m-warn">⚠ 단어만 겹치고 실제 업무 영역은 다를 수 있음</div>'
    return out


def _chip_row_html(profile: dict) -> str:
    fields = profile.get('strength_fields') or []
    keywords = profile.get('strength_keywords') or []
    if not fields and not keywords:
        return '<p class="empty">강점 분야/키워드 데이터 없음</p>'
    chips = ''.join(f'<span class="chip">{html.escape(f)}</span>' for f in fields)
    chips += ''.join(f'<span class="chip kw">{html.escape(k)}</span>' for k in keywords)
    return f'<div class="chip-row">{chips}</div>'


def _match_row_html(s: dict, name_map: dict, dept_map: dict, org_map: dict) -> str:
    rid = s['researcher_id']
    name = html.escape(name_map.get(rid, rid))
    dept = html.escape(dept_map.get(rid, ''))
    org = html.escape(org_map.get(rid, ''))
    tenure_badge = _tenure_badge_html(s.get('tenure_level', ''))
    level = s.get('level') or ''
    level_pill = (
        f'<span class="pill {_LEVEL_CLASS.get(level, "low")}">{html.escape(level)}</span>'
        if level else ''
    )
    return f'''<tr>
  <td>
    <div class="m-name">{name} {tenure_badge}</div>
    <div class="m-dept">{dept} · {org}</div>
  </td>
  <td>{level_pill}</td>
  <td class="m-score">{round(s['score'] * 100)}%</td>
  <td>{_evidence_html(s.get('evidence'), s.get('surface_only'))}</td>
</tr>'''


def _build_html(results: list, researchers_df: pd.DataFrame, top_k: int, profile_by_id: dict) -> str:
    """researchers.csv의 department('플랫폼/팀')·org_code('과제/파트')로 좌측
    사이드바 내비게이션과 본문 섹션을 그룹핑하고, 각 카드는 본인의 강점 분야/
    키워드를 칩으로 보여준 뒤 유사 연구원 목록을 표로 보여준다."""
    name_map, dept_map, org_map = {}, {}, {}
    if not researchers_df.empty:
        indexed = researchers_df.set_index('researcher_id')
        name_map = indexed['name'].to_dict()
        dept_map = indexed['department'].to_dict()
        org_map = indexed['org_code'].to_dict()

    anchor_of = {item['researcher_id']: f'r-{item["researcher_id"]}' for item in results}
    count_of = {item['researcher_id']: len(item['similar']) for item in results}

    # 조직도(team_refer.csv)가 있으면 트리로, 없으면 기존 부서 평면 목록으로 폴백.
    analyzed_rids_by_org: dict = {}
    for it in results:
        rid = it['researcher_id']
        analyzed_rids_by_org.setdefault(org_map.get(rid, ''), []).append(rid)

    org_tree = mmd.build_org_tree(mmd.read_team_refer(OUT_DIR))
    if org_tree:
        def _leaf_researchers(node):
            items = [
                (f'#{anchor_of[rid]}', name_map.get(rid, rid), count_of.get(rid))
                for rid in analyzed_rids_by_org.get(node.get('project_name', ''), [])
            ]
            return mmd.nav_items_html(items)

        nav_groups = [mmd.org_tree_html(org_tree, _leaf_researchers)]
    else:
        nav_groups = []
        for dept, items in mmd.group_ordered(results, lambda it: dept_map.get(it['researcher_id'], '')):
            entries = ''.join(
                f'<a class="nav-item" href="#{anchor_of[it["researcher_id"]]}">'
                f'<span>{html.escape(name_map.get(it["researcher_id"], it["researcher_id"]))}</span>'
                f'<span class="n-count">{len(it["similar"])}</span></a>'
                for it in items
            )
            nav_groups.append(f'<div class="nav-group"><div class="nav-group-label">{html.escape(dept)}</div>{entries}</div>')

    total = len(results)
    high_conf = sum(1 for it in results for s in it['similar'] if s.get('score', 0) >= 0.7)
    flagged = sum(1 for it in results for s in it['similar'] if s.get('surface_only'))

    sections = []
    for dept, dept_items in mmd.group_ordered(results, lambda it: dept_map.get(it['researcher_id'], '')):
        sections.append(f'<div class="dept-heading">{html.escape(dept)}</div>')
        for org, org_items in mmd.group_ordered(dept_items, lambda it: org_map.get(it['researcher_id'], '')):
            if org and org != '미분류':
                sections.append(f'<div class="org-heading">{html.escape(org)}</div>')
            for item in org_items:
                rid = item['researcher_id']
                name = html.escape(name_map.get(rid, rid))
                tenure_badge = _tenure_badge_html(item.get('tenure_level', ''))
                if item['similar']:
                    rows = ''.join(_match_row_html(s, name_map, dept_map, org_map) for s in item['similar'])
                    table = (
                        '<div class="table-wrap"><table class="match-table">'
                        '<thead><tr><th>유사 연구원</th><th>판정</th><th>유사도</th><th>근거</th></tr></thead>'
                        f'<tbody>{rows}</tbody></table></div>'
                    )
                else:
                    table = '<p class="empty">비교할 다른 연구원 데이터 없음</p>'
                sections.append(f'''<div class="card" id="{anchor_of[rid]}">
  <div class="card-top"><h3>{name}</h3>{tenure_badge}{mmd.map_link_html(rid)}</div>
  {_chip_row_html(profile_by_id.get(rid, {}))}
  {table}
</div>''')

    sidebar = (
        '<h1>유사도 콘솔</h1>'
        f'<p class="tagline">과제 단위가 아닌 실제 보유 전문성 임베딩 기반 유사도 · 근속 그룹별 각 Top {top_k}</p>'
        f'{"".join(nav_groups)}'
    )
    stats = mmd.stat_row_html([
        (total, '분석 대상 연구원'),
        (high_conf, '고신뢰 매칭 (70%+)'),
        (flagged, '표면 일치 주의 플래그'),
    ])
    return mmd.console_page('연구원 ↔ 연구원 유사도', sidebar, stats + ''.join(sections))


def process(top_k: int = DEFAULT_TOP_K, refresh_judgments: bool = False) -> bool:
    profiles = _read_expertise()
    if not profiles:
        print('[process_researcher_similarity] 연구원 보유 전문성 분석.json 없음 — 종료 '
              '(process_researcher_expertise.py 먼저 실행)')
        return False
    if len(profiles) < 2:
        print('[process_researcher_similarity] 비교할 연구원이 2명 미만 — 종료')
        return False

    researchers_df = fit.read_researchers(OUT_DIR)
    tenure_map = build_tenure_map(researchers_df)

    print(f'[process_researcher_similarity] 연구원 {len(profiles)}명 임베딩 계산 중...')
    try:
        results = compute_similarity(profiles, top_k=top_k, tenure_map=tenure_map)
    except LLMError as exc:
        print(f'[process_researcher_similarity] 임베딩 실패 — 종료: {exc}')
        return False

    results = attach_pair_judgments(results, profiles, force=refresh_judgments)
    results = attach_tenure_levels(results, tenure_map)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'researcher_similarity.json')
    json_text = json.dumps(results, ensure_ascii=False, indent=2)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(json_text)
    print(f'[OK]   researcher_similarity.json 저장 ({len(results)}명)')
    result_archive.archive_copy('04. 연구원_연구원_유사도_매칭', '연구원_연구원_유사도_분석', 'json', json_text)

    profile_by_id = {p['researcher_id']: p for p in profiles}
    html_out = _build_html(results, researchers_df, top_k, profile_by_id)
    html_path = os.path.join(OUT_DIR, 'researcher_similarity.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_out)
    print('[OK]   researcher_similarity.html 저장')
    result_archive.archive_copy('04. 연구원_연구원_유사도_매칭', '연구원_연구원_유사도_분석', 'html', html_out)

    return True


def _parse_top_k_arg(argv: list, default: int) -> int:
    if '--top-k' in argv:
        idx = argv.index('--top-k')
        if idx + 1 < len(argv):
            try:
                return int(argv[idx + 1])
            except ValueError:
                pass
    return default


if __name__ == '__main__':
    process(
        top_k=_parse_top_k_arg(sys.argv, DEFAULT_TOP_K),
        refresh_judgments='--refresh-judgments' in sys.argv,
    )
