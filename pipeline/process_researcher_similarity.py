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
그대로 재사용한다.

학력 하드 파티션(신규, 사용자 확정 2026-08-29): 대상 연구원의 최종학력
(education.csv, 박사/석사/학사/전문대/고교)을 알 수 있으면, 후보를 **같은
학력인 사람으로만** 제한한다. 소프트 가산점(코사인 유사도에 약간의 보너스만
주는 방식)은 검토했으나 채택하지 않았다 — 이미 텍스트 내용(예: "리더십/전략
업무" 같은 표현)이 우연히 겹쳐 유사도가 높게 나온 경우, 약간의 부스트로는
그 순위를 못 뒤집기 때문에 "박사 리더 vs 고졸 리더"처럼 학력 격차가 큰
조합이 신뢰도 낮은 매칭으로 계속 표시되는 문제를 해결하지 못한다. 그래서
CL 시니어/주니어 그룹핑과 동일한 하드 파티션 방식을 학력에도 적용해, 애초에
다른 학력 조합이 후보 풀에 들어오지 못하게 막는다. 본인 학력을 모르면(교육
이력 없음) 필터 없이 기존처럼 전체 후보에서 찾는다(CL 미분류와 동일한 하위
호환 폴백 원칙). 학력이 같은 사람이 적거나 없으면(예: 전문대/고교 학력자가
조직에 거의 없음) 결과가 적거나 비어 있을 수 있다 — 다른 학력 후보로 억지로
채우지 않는다(신뢰할 수 없는 매칭을 보여주지 않는 게 우선이라는 판단).

근속 그룹별 top-K: 학력 파티션으로 좁혀진 후보 풀 안에서, 대상 연구원의
CL/년차 기반 시니어·주니어 구분(Junior/Senior, 아래 3단계 참고)을 알 수
있으면, 후보를 Junior/Senior로 나눠 그룹별로 각각 후보 pool을 찾는다 —
"이 사람과 전문성이 가장 비슷한 Senior"와 "가장 비슷한 Junior"를 시니어
우선 순서로 함께 보여주기 위함이다(결과 리스트는 Senior 그룹을 먼저, Junior
그룹을 나중에 이어붙인다). 후보 중 CL 표기가 없거나(임원 등) 승격기준일이
없어 분류를 모르는 사람은 어느 그룹에도 들어가지 못하므로 이 그룹별 검색에서는
제외된다. 대상 연구원 본인의 분류를 모르면 그룹 구분 없이 학력 파티션 결과
전체 중에서 찾는다(하위 호환 폴백). 임원(상무/사장/고문/부사장/Master —
_EXCLUDED_POSITIONS)은 애초에 후보 자체에서 완전히 빠진다(process()가
profiles를 걸러냄).

그룹별 후보 pool 크기(_CANDIDATE_POOL_K)는 화면에 실제로 표시할 그룹당 최대
개수(MAX_DISPLAY_K, 10)보다 넉넉히 크게 잡는다 — 아래 2단계에서 근거(evidence)가
비어 있는 후보를 걸러내고 나면 일부가 탈락하므로, "표시 개수" 토글(3/5/10,
아래 참고)의 "10"까지 채우려면 애초에 더 많은 후보를 LLM 판정까지 진행시켜야
한다.

2단계(LLM 판정, 후보 pool 전체에 대해): 임베딩 점수만으로는 "왜 유사한지",
"단어만 겹치고 실제 업무는 다른 건 아닌지"를 알 수 없다. 그래서 후보 pool로
추려진 쌍에 대해 "R&D Peer Similarity Agent" 페르소나가 두 프로필을
나란히 보고 (동일 분야/인접 분야/낮음) 정성적 등급, 구체적 근거, 표면적
어휘 일치 여부를 판정한다.

  ※ 근거 기반 필터링: 근거(evidence) 없이 유사도 점수만 높은 후보는
    신뢰도가 낮으므로, LLM 판정 후 evidence가 완전히 비어 있는 후보는
    최종 유사 연구원 목록에서 제외한다(_drop_empty_evidence). 프롬프트
    자체도 "낮음" 판정이라도 근거(왜 낮다고 판단했는지)를 반드시 채우도록
    지시하므로, 실제로는 LLM 호출 자체가 실패한 극히 일부 쌍만 제외된다.
    필터링 후 최종 목록은 Senior/Junior 그룹별로 각각 MAX_DISPLAY_K(10)명
    까지만 유지한다(한쪽이 모자라도 다른 쪽에서 끌어와 채우지 않음 — 화면의
    "표시 개수" 토글이 "시니어 N + 주니어 N"을 뜻하기 때문). HTML은 이 목록을
    그대로 저장해 두고, 3/5/10 토글은 CSS로 그룹별 행을 숨기고 보여주는
    방식이라(재계산 없음) 그룹당 최댓값만큼 미리 준비해 둔다.

  ※ 재현성: LLM 호출은 temperature=0으로 고정하고, 한 번 판정한 쌍은
    researcher_pair_judgment.json에 영구 캐시한다(신규거나 이전에 실패해
    값이 비어 있는 쌍만 다음 실행 때 재시도 — journal_authority 캐시와 동일한
    방식). 캐시가 있는 한 재실행해도 같은 값이 그대로 나온다.
  ※ 대칭성: A~B와 B~A는 같은 질문이므로, researcher_id를 정렬한 고정 키
    ("A|B", A<B)로 쌍을 관리해 실제로는 딱 한 번만 판정하고, 그 결과를
    A쪽 목록과 B쪽 목록 양쪽에 그대로 재사용한다 — 방향에 따라 등급/근거가
    서로 어긋나는 일이 생기지 않는다.
  ※ 캐시 무시하고 전체 쌍을 다시 판정하려면 --refresh-judgments 사용.

3단계(근속 라벨): researchers.csv의 position(CL)/promotion_date로 그때그때
(저장하지 않고 실행 시점 기준) CL/년차를 계산해, CL3 미만은 Junior, CL3
초과는 Senior, CL3는 년차 5 이상이면 Senior·미만이면 Junior 라벨을 결과에
붙인다(사용자 확정 — 예전 "근속 5년" 기준을 대체). 매칭 로직(누가 누구와
유사한지) 자체는 바꾸지 않고, 대상자 본인과 각 유사 연구원에 라벨만
추가한다 — CL 표기가 아니거나 승격기준일이 없으면 라벨 없이(''), HTML에서는
배지를 생략한다.

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
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE_DIR, OUT_DIR  # noqa: E402
sys.path.insert(0, BASE_DIR)
import rd_specialist_markdown as mmd  # noqa: E402
import researcher_fit as fit  # noqa: E402
import result_archive  # noqa: E402
from services.llm import LLMError  # noqa: E402
from services.researcher_profile_export import highest_degree_row, position_years  # noqa: E402

DEFAULT_TOP_K = fit.TOP_K

# 그룹별(Senior/Junior 각각) 후보 pool 크기 — 화면 표시 개수(top_k)보다 넉넉히
# 잡아, 근거 없는 후보가 필터링으로 빠지더라도 표시 개수 토글(3/5/10, 그룹당
# 개수)의 최댓값(10)을 그룹별로 채울 수 있게 한다.
_CANDIDATE_POOL_K = 15

# 근거 필터링 후 최종적으로 저장/표시할 연구원 수 상한 — Senior/Junior 그룹별로
# 각각 이 개수까지 유지한다(표시 개수 토글 3/5/10명은 "그룹당" 개수를 뜻함).
MAX_DISPLAY_K = 10

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
4. evidence는 "유사하다는 근거"가 아니라 "이 등급으로 판단한 근거"입니다.
   level이 "낮음"이더라도 evidence를 절대 빈 배열로 남기지 마세요 — 왜
   낮다고 판단했는지(예: "두 사람 모두 AI 언급하나 응용 분야 상이(신호처리
   vs 자연어처리)", "공통 도메인 지식 없음, 겹치는 Hard Skill 없음")를 1~3개
   적으세요. 두 프로필에서 실제로 다른 부분/공통점이 없는 부분을 구체적으로
   짚으면 됩니다. "근거 없음"처럼 내용 없는 문구만 넣지 말고, 반드시 두
   프로필의 구체적 내용(분야명, 키워드 등)을 인용해 판단 근거를 남기세요.
5. 반드시 아래 JSON 형식으로만 출력하고, 그 외 텍스트는 출력하지 마세요.

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


def compute_similarity(profiles: list, top_k: int = DEFAULT_TOP_K, tenure_map: dict | None = None,
                        degree_map: dict | None = None) -> list:
    """profiles: 연구원 보유 전문성 분석.json의 원소 리스트(researcher_id 포함).

    degree_map: researcher_id -> '박사'/'석사'/'학사'/'전문대'/'고교'/''(모름).
    대상 연구원의 최종학력을 알 수 있으면, 후보를 **같은 학력으로 하드
    필터링**한다(사용자 확정 2026-08-29 — "박사 리더 vs 고졸 리더"처럼 학력
    격차가 큰 조합이 표면적 텍스트 유사도만으로 매칭되는 신뢰성 문제를 막기
    위해, 소프트 가산점이 아니라 후보 풀 자체를 제한). 본인 학력을 모르면
    필터 없이 전체 후보에서 찾는다(하위 호환 폴백).

    tenure_map: researcher_id -> 'Junior'/'Senior'/''(모름). 위 학력 필터로
    좁혀진 풀 안에서, 대상 연구원의 근속을 알 수 있으면 후보를 Junior/Senior로
    나눠 그룹별로 각각 후보 pool을 찾는다(pool 크기는 top_k와
    _CANDIDATE_POOL_K 중 큰 값 — 2단계 근거 필터링에서 일부가 탈락해도 표시
    개수 토글을 채울 수 있도록 넉넉히 확보). 결과는 Senior 그룹을 먼저, Junior
    그룹을 나중에 이어붙인다(시니어 우선 표시). 후보 중 근속을 모르는 사람은
    어느 그룹에도 속하지 못해 이 검색에서 제외된다. 대상 연구원 본인의 근속을
    모르면 그룹 구분 없이 학력 필터 결과 전체 중에서 찾는다(하위 호환 폴백).

    반환: [{'researcher_id', 'similar': [{'researcher_id', 'score'}, ...]}, ...]
    similar은 그룹(Senior 우선) 내 유사도 내림차순. score는 코사인 유사도
    (-1~1, 실제로는 임베딩 특성상 대부분 0~1 범위)를 소수 4자리로 반올림.
    이 시점의 similar 목록은 아직 근거 필터링 전의 "후보 pool"이며, 최종
    표시 목록은 attach_pair_judgments() 이후 _drop_empty_evidence()가 정리한다."""
    tenure_map = tenure_map or {}
    degree_map = degree_map or {}
    researcher_ids = [p['researcher_id'] for p in profiles]
    texts = [fit.researcher_profile_text(p) for p in profiles]

    # 텍스트 해시 기준 캐시(fit.cached_embed) — 같은 연구원 프로필 텍스트를
    # 이미 임베딩해 뒀다면 재계산하지 않는다.
    embeddings = fit.cached_embed(texts)
    sims = fit.cosine_sim_matrix(embeddings, embeddings)

    n = len(researcher_ids)
    pool_k = max(top_k, _CANDIDATE_POOL_K)

    results = []
    for i in range(n):
        row = sims[i].copy()
        row[i] = -1.0  # 자기 자신은 후보에서 제외

        subject_degree = degree_map.get(researcher_ids[i], '')
        if subject_degree:
            degree_pool = [j for j in range(n) if j != i and degree_map.get(researcher_ids[j], '') == subject_degree]
        else:
            degree_pool = [j for j in range(n) if j != i]

        subject_level = tenure_map.get(researcher_ids[i], '')
        if not subject_level:
            top_idx = _top_within(degree_pool, row, min(pool_k, len(degree_pool)))
        else:
            junior_idx = [j for j in degree_pool if tenure_map.get(researcher_ids[j], '') == 'Junior']
            senior_idx = [j for j in degree_pool if tenure_map.get(researcher_ids[j], '') == 'Senior']
            top_idx = _top_within(senior_idx, row, pool_k) + _top_within(junior_idx, row, pool_k)

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
    # thinkingcap처럼 최종 답변 전 사고 과정에도 토큰을 쓰는 추론형 모델은 값이
    # 작으면(예: 400) 사고 과정만으로 예산을 다 써 content가 비고
    # finish_reason=length 경고가 자주 뜬다 — 자체 서버 운영 중이라 비용 부담이
    # 없으므로 넉넉하게 잡는다(실제 API 요청 시 LLM2_MAX_TOKENS_MULTIPLIER가 한 번
    # 더 곱해짐, 기본 3배). 1500(effective 4500)에서도 자주 잘려 2500으로 상향.
    raw = fit.call_llm(prompt, _PAIR_JUDGE_SYSTEM_PROMPT, temperature=0.0, max_tokens=2500)
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
    surface_only)을 덧붙인다. 캐시 미스만 새로 판정한다. 이 시점의 similar
    목록은 아직 근거 필터링 전의 후보 pool이며, evidence가 비어 있는 후보를
    실제로 제외하는 것은 _drop_empty_evidence()가 담당한다(판정 자체를 못
    구한 쌍은 evidence가 빈 값으로 남아 이후 필터링 대상이 됨)."""
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


def _has_evidence(evidence) -> bool:
    """evidence(리스트 또는 하위호환 문자열)가 실제 내용을 담고 있는지 확인."""
    if isinstance(evidence, list):
        return any(str(e).strip() for e in evidence)
    return bool(str(evidence or '').strip())


def _drop_empty_evidence(results: list, tenure_map: dict, max_per_group: int = MAX_DISPLAY_K) -> list:
    """근거 없이 유사도만 높은 후보는 신뢰도가 낮으므로 최종 목록에서 제외한다
    (LLM 판정 자체가 실패한 쌍도 evidence가 비어 있어 함께 제외됨). 화면의
    표시 개수 토글(3/5/10)은 "시니어 N명 + 주니어 N명"을 뜻하므로, Senior와
    Junior를 서로 밀어내지 않도록 각각 독립적으로 max_per_group까지만 자른다
    (한쪽이 모자라면 다른 쪽에서 채우지 않고 있는 만큼만 남긴다). 대상자 근속을
    몰라 그룹 구분 없이 검색한 폴백 케이스만 별도로 max_per_group까지 자른다."""
    for item in results:
        filtered = [s for s in item['similar'] if _has_evidence(s.get('evidence'))]
        senior = [s for s in filtered if tenure_map.get(s['researcher_id'], '') == 'Senior'][:max_per_group]
        junior = [s for s in filtered if tenure_map.get(s['researcher_id'], '') == 'Junior'][:max_per_group]
        others = [
            s for s in filtered
            if tenure_map.get(s['researcher_id'], '') not in ('Senior', 'Junior')
        ][:max_per_group]
        item['similar'] = senior + junior + others
    return results


# CL/년차 기준 시니어/주니어 분류(사용자 확정 — 기존 "근속 5년" 기준을 대체).
# "CL3-5 이상이면 Senior, CL3-4 이하면 Junior"라는 확정 문구를 CL 레벨 전체로
# 일반화하면: CL3보다 낮은 레벨(CL1/CL2)은 항상 Junior, CL3보다 높은 레벨은
# 항상 Senior, 딱 CL3일 때만 년차(5년)로 갈린다.
_CL_SENIOR_THRESHOLD_LEVEL = 3
_CL_SENIOR_THRESHOLD_YEARS = 5

# researchers.csv의 position이 이 값 중 하나면(임원/특별 직책, process_researchers.py의
# POSITION_LABEL_MAP이 영문 원본을 이 한글 라벨로 이미 통일해 둠 — Master는
# 원본 그대로) 유사 연구원 매칭 대상에서 완전히 제외한다(사용자 확정) — 이
# 사람들은 이 리포트에 아예 등장하지 않고(자기 카드 없음), 다른 누구의
# 유사 연구원 후보로도 뽑히지 않는다.
_EXCLUDED_POSITIONS = {'상무', '사장', '고문', '부사장', 'Master'}


def _cl_level(position: str) -> int | None:
    """position이 'CL' + 숫자(예: 'CL3') 형태면 그 숫자를, 아니면(임원 직책 등
    CL 표기가 아니면) None을 반환한다."""
    position = (position or '').strip()
    if position.startswith('CL') and position[2:].isdigit():
        return int(position[2:])
    return None


def _tenure_level(position: str, promotion_date: str) -> str:
    """CL/년차 기준 시니어/주니어 분류. CL3 미만은 'Junior', CL3 초과는
    'Senior', CL3는 년차(승격기준일 기준, services.researcher_profile_export.
    position_years())가 5 이상이면 'Senior', 미만이면 'Junior'. position이
    'CL' 표기가 아니거나(임원 등 — 이미 _EXCLUDED_POSITIONS로 걸러지지만
    방어적으로 처리) 년차를 계산할 수 없으면 빈 문자열(미분류)."""
    cl = _cl_level(position)
    if cl is None:
        return ''
    if cl < _CL_SENIOR_THRESHOLD_LEVEL:
        return 'Junior'
    if cl > _CL_SENIOR_THRESHOLD_LEVEL:
        return 'Senior'
    years = position_years(promotion_date)
    if years is None:
        return ''
    return 'Senior' if years >= _CL_SENIOR_THRESHOLD_YEARS else 'Junior'


def build_tenure_map(researchers_df: pd.DataFrame) -> dict:
    """researcher_id -> 'Junior'/'Senior'/''(미분류) 매핑을 한 번만 계산해,
    compute_similarity()의 그룹별 검색과 attach_tenure_levels()의 라벨 표시가
    같은 맵을 재사용하도록 한다."""
    if researchers_df.empty or 'position' not in researchers_df.columns:
        return {}
    promo_col = 'promotion_date' if 'promotion_date' in researchers_df.columns else None
    result = {}
    for _, row in researchers_df.iterrows():
        promo = row[promo_col] if promo_col else ''
        result[row['researcher_id']] = _tenure_level(row.get('position', ''), promo)
    return result


def build_degree_map(education_df: pd.DataFrame) -> dict:
    """researcher_id -> 최종학력(박사/석사/학사/전문대/고교,
    services.researcher_profile_export.highest_degree_row()와 동일한
    5단계 우선순위) / ''(학력 데이터 없음 — compute_similarity()에서
    필터 없이 취급). build_tenure_map()과 동일한 발상(한 번만 계산해
    compute_similarity()의 하드 파티션이 재사용)."""
    if education_df.empty or 'researcher_id' not in education_df.columns:
        return {}
    result = {}
    for rid, rows in education_df.groupby('researcher_id'):
        row = highest_degree_row(rows.to_dict('records'))
        result[rid] = row.get('degree', '') if row else ''
    return result


def attach_tenure_levels(results: list, tenure_map: dict) -> list:
    """build_tenure_map()이 계산한 CL/년차 기반 Junior/Senior 라벨을
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
    return mmd.strength_section_html(fields, keywords)


def _match_row_html(s: dict, name_map: dict, dept_map: dict, org_map: dict, include_links: bool = True) -> str:
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
    profile_icon = mmd.profile_icon_link_html(rid) if include_links else ''
    return f'''<tr>
  <td>
    <div class="m-name">{name} {tenure_badge}{profile_icon}</div>
    <div class="m-dept">{dept} · {org}</div>
  </td>
  <td>{level_pill}</td>
  <td>{_evidence_html(s.get('evidence'), s.get('surface_only'))}</td>
  <td class="m-score">{round(s['score'] * 100)}%</td>
</tr>'''


def similar_researchers_block_html(item: dict, name_map: dict, dept_map: dict, org_map: dict,
                                    include_links: bool = True) -> str:
    """유사 연구원 섹션(CL 시니어/주니어 뱃지 + 매칭 표 또는 "비교 대상 없음"
    안내)만 kv-block 스타일로 반환한다 — 이름 헤더/강점 칩은 포함하지 않는다.
    이 사람의 보유 전문성 카드(process_researcher_expertise.researcher_card_html())가
    유사도 데이터를 함께 받았을 때 그 카드 안에 이어붙이기 위해 분리했다
    ("연구원"/"연구원 ↔ 연구원" 탭 통합, 2026-09-01 사용자 확정) —
    researcher_match_card_html()도 이 함수를 그대로 재사용한다."""
    tenure_badge = _tenure_badge_html(item.get('tenure_level', ''))
    if item['similar']:
        # 표시 개수(3/5/10) 토글이 "그룹당" 개수를 뜻하므로, Senior/Junior(및
        # 근속 미상 폴백)를 별도 <tbody>로 나눠 렌더링한다 — :nth-child 기반
        # CSS 토글이 각 tbody 안에서 독립적으로 행 위치를 세기 때문에, 이렇게만
        # 나누면 별도 CSS 없이 그룹별 3/5/10 표시가 그대로 적용된다.
        groups = [
            [s for s in item['similar'] if s.get('tenure_level') == 'Senior'],
            [s for s in item['similar'] if s.get('tenure_level') == 'Junior'],
            [s for s in item['similar'] if s.get('tenure_level') not in ('Senior', 'Junior')],
        ]
        tbodies = ''.join(
            f'<tbody>{"".join(_match_row_html(s, name_map, dept_map, org_map, include_links) for s in g)}</tbody>'
            for g in groups if g
        )
        table = (
            '<div class="table-wrap"><table class="match-table">'
            '<thead><tr><th>유사 연구원</th><th>판정</th><th>근거</th><th>유사도</th></tr></thead>'
            f'{tbodies}</table></div>'
        )
    else:
        table = '<p class="empty">비교할 다른 연구원 데이터 없음</p>'
    return f'''<div class="kv-block sim-block">
  <div class="kv-title">유사 연구원 {tenure_badge}</div>
  {table}
</div>'''


def researcher_match_card_html(item: dict, name_map: dict, dept_map: dict, org_map: dict,
                                profile_by_id: dict, anchor: str = '', include_links: bool = True) -> str:
    """연구원 한 명의 유사 연구원 매칭 카드(강점 칩 + 매칭 표). build_html()의
    조직도 카드 나열뿐 아니라, 개별 연구원 메일 발송(services/similarity_map.py의
    build_researcher_mail_html())에서도 그대로 재사용한다 — anchor가 빈
    문자열이면(메일 등 fragment 링크가 필요 없는 컨텍스트) id 속성 없이 렌더링.
    include_links=False면 프로필/메일 링크(target="_top" 상대경로라 앱 밖
    메일 본문에서는 깨짐 — 사용자 확인)를 카드 헤더와 매칭 표 각 행에서
    모두 뺀다."""
    rid = item['researcher_id']
    name = html.escape(name_map.get(rid, rid))
    icons_html = (
        f'<div class="card-icons">{mmd.profile_link_html(rid)}{mmd.mail_link_html(rid)}</div>'
        if include_links else ''
    )
    id_attr = f' id="{anchor}"' if anchor else ''
    return f'''<div class="card"{id_attr}>
  <div class="card-top"><h3>{name}</h3>
    {icons_html}
  </div>
  {_chip_row_html(profile_by_id.get(rid, {}))}
  {similar_researchers_block_html(item, name_map, dept_map, org_map, include_links)}
</div>'''


def build_html(results: list, researchers_df: pd.DataFrame, profile_by_id: dict) -> str:
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
                for rid in analyzed_rids_by_org.get(node.get('org_name_wd', ''), [])
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

    sections = []
    for dept, dept_items in mmd.group_ordered(results, lambda it: dept_map.get(it['researcher_id'], '')):
        sections.append(f'<div class="dept-heading">{html.escape(dept)}</div>')
        for org, org_items in mmd.group_ordered(dept_items, lambda it: org_map.get(it['researcher_id'], '')):
            if org and org != '미분류':
                sections.append(f'<div class="org-heading">{html.escape(org)}</div>')
            for item in org_items:
                rid = item['researcher_id']
                sections.append(researcher_match_card_html(
                    item, name_map, dept_map, org_map, profile_by_id, anchor_of[rid],
                ))

    sidebar = (
        '<h1>유사도 콘솔</h1>'
        '<p class="tagline">과제 단위가 아닌 실제 보유 전문성 임베딩 기반 유사도 · '
        'CL 시니어 우선 · 근거 있는 매칭만 표시</p>'
        f'{mmd.org_search_input_html()}'
        f'{"".join(nav_groups)}'
    )
    # 사용자 요청으로 요약 카드를 "마지막 갱신" 하나만 남긴다(긴 직사각형으로
    # 표시 — .stat-row가 grid-template-columns: repeat(auto-fit, minmax(150px,1fr))
    # 라 카드가 1개면 자동으로 전체 폭을 채운다, CSS 변경 불필요).
    computed_at = results[0].get('computed_at') if results else None
    stats = mmd.stat_row_html([mmd.generated_at_stat(computed_at)])
    # 표시 개수(3/5/10, 그룹당) 토글 — JS 없이 radio + 형제 선택자로 행을 숨김/표시.
    # Senior/Junior가 각각 별도 <tbody>이므로 CSS의 tr:nth-child가 그룹별로 독립
    # 적용된다(3명 선택 시 시니어 3 + 주니어 3, 있는 만큼만). 데이터는 이미
    # MAX_DISPLAY_K(10)까지 그룹별로 저장돼 있으므로 재계산 없이 CSS만으로 전환된다.
    count_toggle = (
        '<input type="radio" name="cnt" id="count-3" class="cnt-radio" checked>'
        '<input type="radio" name="cnt" id="count-5" class="cnt-radio">'
        '<input type="radio" name="cnt" id="count-10" class="cnt-radio">'
        '<div class="count-bar">'
        '<span>표시 개수</span>'
        '<label for="count-3">3명</label>'
        '<label for="count-5">5명</label>'
        '<label for="count-10">10명</label>'
        '</div>'
    )
    body = count_toggle + stats + f'<div class="sim-sections">{"".join(sections)}</div>'
    return mmd.console_page('연구원 ↔ 연구원 유사도', sidebar, body, detail_view=True)


def process(top_k: int = DEFAULT_TOP_K, refresh_judgments: bool = False) -> bool:
    fit.reset_truncation_count()
    profiles = _read_expertise()
    if not profiles:
        print('[process_researcher_similarity] 연구원 보유 전문성 분석.json 없음 — 종료 '
              '(process_researcher_expertise.py 먼저 실행)')
        return False

    researchers_df = fit.read_researchers(OUT_DIR)
    position_map = (
        researchers_df.set_index('researcher_id')['position'].to_dict()
        if not researchers_df.empty and 'position' in researchers_df.columns else {}
    )
    # 임원(상무/사장/고문/부사장/Master)은 유사 연구원 매칭에서 완전히 제외
    # (사용자 확정) — 자기 카드도 안 생기고, 다른 사람 후보로도 안 뽑힌다.
    before = len(profiles)
    profiles = [p for p in profiles if position_map.get(p.get('researcher_id', ''), '') not in _EXCLUDED_POSITIONS]
    excluded_count = before - len(profiles)
    if excluded_count:
        print(f'[process_researcher_similarity] 임원 {excluded_count}명 제외 '
              f'({sorted(_EXCLUDED_POSITIONS)})')

    # 현재 미소속(전배·퇴사 — researchers.csv의 is_current='N', pipeline/process_researchers.py
    # 참고)인 사람도 후보에서 완전히 제외한다. 임원 제외와 동일한 이유: 화면(AI 검색/
    # 보유 전문성 "누적기준" 패널)에서는 조회 대상 자신은 미소속이어도 찾을 수 있게
    # 앱단에서 따로 열어주지만(services/nl_query.py, pages/researcher_similarity_map.py),
    # "추천되는 유사 연구원 후보"는 실제로 협업 가능한 사람이어야 하므로 이 배치 계산
    # 단계에서부터 아예 빼는 게 맞다 — 안 그러면 조직도 기반 정적 리포트(최신기준
    # 화면에 그대로 뜨는 연구원 ↔ 연구원 탭)에는 걸러지지 않은 채로 남는다.
    # is_current 컬럼이 없으면(구버전 데이터/원본에 인원실적년월이 없는 경우) 판단
    # 근거가 없으므로 아무도 제외하지 않는다(services.data_store.filter_current와 동일 원칙).
    if not researchers_df.empty and 'is_current' in researchers_df.columns:
        current_map = researchers_df.set_index('researcher_id')['is_current'].to_dict()
        before = len(profiles)
        profiles = [p for p in profiles if current_map.get(p.get('researcher_id', ''), 'Y') != 'N']
        not_current_count = before - len(profiles)
        if not_current_count:
            print(f'[process_researcher_similarity] 현재 미소속(전배·퇴사) {not_current_count}명 제외')

    if len(profiles) < 2:
        print('[process_researcher_similarity] 비교할 연구원이 2명 미만 — 종료')
        return False

    tenure_map = build_tenure_map(researchers_df)
    degree_map = build_degree_map(fit.read_education(OUT_DIR))

    print(f'[process_researcher_similarity] 연구원 {len(profiles)}명 임베딩 계산 중...')
    try:
        results = compute_similarity(profiles, top_k=top_k, tenure_map=tenure_map, degree_map=degree_map)
    except LLMError as exc:
        print(f'[process_researcher_similarity] 임베딩 실패 — 종료: {exc}')
        return False

    results = attach_pair_judgments(results, profiles, force=refresh_judgments)
    results = _drop_empty_evidence(results, tenure_map)
    results = attach_tenure_levels(results, tenure_map)

    # 화면(build_html())이 "언제 기준 데이터인지"를 보여줄 때 이 값을 그대로
    # 쓴다(마지막 갱신 표시가 render 시점이 아니라 실제 계산 시점을 보여주도록
    # — 사용자 지적, data/processed/CLAUDE.md 참고). 이번 배치 전체가 같은
    # 시각을 공유하므로 항목마다 새로 계산하지 않고 한 번만 찍는다.
    computed_at = datetime.now().strftime('%Y-%m-%d %H:%M')
    for r in results:
        r['computed_at'] = computed_at

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'researcher_similarity.json')
    json_text = json.dumps(results, ensure_ascii=False, indent=2)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(json_text)
    print(f'[OK]   researcher_similarity.json 저장 ({len(results)}명)')
    result_archive.archive_copy('04. 연구원_연구원_유사도_매칭', '연구원_연구원_유사도_분석', 'json', json_text)

    # 화면은 이제 이 HTML을 파일로 읽지 않고 build_html()을 그때그때 호출해
    # 직접 렌더링한다(pages/researcher_similarity_map.py) — data/processed에
    # 누구나 열어볼 수 있는 완성된 리포트 사본을 남기지 않기 위해서다. 다만
    # 실행 이력 아카이브(data/processed/result/, 권한은 scripts/
    # secure_data_permissions.sh로 잠금)에는 계속 스냅샷을 남긴다.
    profile_by_id = {p['researcher_id']: p for p in profiles}
    html_out = build_html(results, researchers_df, profile_by_id)
    result_archive.archive_copy('04. 연구원_연구원_유사도_매칭', '연구원_연구원_유사도_분석', 'html', html_out)

    truncation_count = fit.get_truncation_count()
    if truncation_count:
        print(f'[알림] LLM 응답 content가 비어(주로 finish_reason=length) 대체 처리된 '
              f'횟수: {truncation_count}회 — 잦으면 max_tokens를 더 늘려야 할 수 있습니다.')

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
