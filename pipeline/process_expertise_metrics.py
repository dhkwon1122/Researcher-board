"""
연구원 전문성 심화 지표 — LLM 호출 없는 결정적 계산 모음(2026-10, 사용자 확정)

process_researcher_expertise.py(LLM 전문성 분석)가 끝난 뒤 run_analysis.py가
이어서 실행한다. 여기 있는 지표는 전부 이미 있는 원천/분석 데이터를 집계만
하므로 비용이 들지 않는다.

  0) 강점 분야/키워드 표기 표준화 재할당 → researcher_strength_std.json
     strength_taxonomy.json(build_strength_taxonomy.py의 확정 표준 목록)으로
     연구원별 strength_fields/strength_keywords를 표준명에 다시 매핑한다.
     원본 LLM 결과(연구원 보유 전문성 분석.json)는 건드리지 않는다.
       - 표준명/동의어와 정확히 일치(공백·대소문자 무시) → 그 표준명
       - 없으면 표준명 중 임베딩 코사인 유사도가 가장 높은 것(>= 0.85)
       - 그래도 없으면 원문 그대로 두고 "미분류"로 표시
         (strength_unmapped.json에 모아 사람이 strength_taxonomy.json에
         동의어/표준명으로 추가하도록 안내)
     표준 목록 파일이 아직 없으면 build_strength_taxonomy.build()로 먼저
     부트스트랩한다(그 함수가 최초 1회만 확정본을 만들고 이후로는 사람이
     수정한 내용을 덮어쓰지 않는다).

사용법:
  python pipeline/process_expertise_metrics.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT_DIR  # noqa: E402
import researcher_fit as fit  # noqa: E402
from services.llm import LLMError  # noqa: E402

PROFILES_FILE = '연구원 보유 전문성 분석.json'
TAXONOMY_FILE = 'strength_taxonomy.json'
STRENGTH_STD_FILE = 'researcher_strength_std.json'
UNMAPPED_FILE = 'strength_unmapped.json'

STD_EMBED_THRESHOLD = 0.85


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


def _norm(text: str) -> str:
    return ''.join(str(text).split()).lower()


# ── 0) 강점 분야/키워드 표준화 재할당 ─────────────────────────────────────────

def _load_taxonomy() -> dict:
    taxonomy = _read_json(TAXONOMY_FILE, {})
    if taxonomy:
        return taxonomy
    print('[process_expertise_metrics] strength_taxonomy.json 없음 — build_strength_taxonomy로 부트스트랩')
    try:
        import build_strength_taxonomy
        build_strength_taxonomy.build()
    except Exception as exc:  # noqa: BLE001 — 표준화는 보조 단계라 실패해도 원문으로 진행
        print(f'  [WARN] 표준 목록 생성 실패: {type(exc).__name__}: {exc}')
    return _read_json(TAXONOMY_FILE, {})


def _build_mapper(entries: list, raw_values: set) -> dict:
    """원문 값 → 표준명(또는 None=미분류) 매핑을 한 번에 만든다."""
    exact: dict = {}
    standard_names: list = []
    for e in entries or []:
        std = str(e.get('standard_name', '')).strip()
        if not std:
            continue
        standard_names.append(std)
        exact[_norm(std)] = std
        for syn in e.get('synonyms') or []:
            exact.setdefault(_norm(syn), std)

    mapping: dict = {}
    leftovers: list = []
    for v in raw_values:
        std = exact.get(_norm(v))
        if std:
            mapping[v] = std
        else:
            leftovers.append(v)

    if leftovers and standard_names:
        try:
            left_vec = fit.cached_embed(leftovers)
            std_vec = fit.cached_embed(standard_names)
            sims = fit.cosine_sim_matrix(left_vec, std_vec)
            for i, v in enumerate(leftovers):
                j = int(sims[i].argmax())
                mapping[v] = standard_names[j] if float(sims[i][j]) >= STD_EMBED_THRESHOLD else None
        except LLMError as exc:
            print(f'  [WARN] 임베딩 매칭 생략(정확 일치만 적용): {exc}')
    for v in leftovers:
        mapping.setdefault(v, None)
    return mapping


def standardize_strengths(profiles: list, taxonomy: dict) -> tuple[list, dict]:
    """반환: (연구원별 표준화 결과 리스트, 미분류 요약)."""
    keys = (('strength_fields', 'fields'), ('strength_keywords', 'keywords'))
    mappers = {}
    for key, tax_key in keys:
        raw = {str(v).strip() for p in profiles for v in (p.get(key) or []) if str(v).strip()}
        mappers[key] = _build_mapper(taxonomy.get(tax_key, []), raw)

    results = []
    unmapped: dict = {'fields': {}, 'keywords': {}}
    for p in profiles:
        rid = p.get('researcher_id', '')
        row = {'researcher_id': rid}
        for key, tax_key in keys:
            std_list, miss = [], []
            for v in p.get(key) or []:
                v = str(v).strip()
                if not v:
                    continue
                std = mappers[key].get(v)
                if std is None:
                    miss.append(v)
                    unmapped[tax_key].setdefault(v, set()).add(rid)
                    std = v
                if std not in std_list:
                    std_list.append(std)
            row[f'{key}_std'] = std_list
            row[f'{key}_unmapped'] = miss
        results.append(row)

    summary = {
        tax_key: sorted(
            ({'value': v, 'researcher_count': len(rids)} for v, rids in vals.items()),
            key=lambda x: -x['researcher_count'],
        )
        for tax_key, vals in unmapped.items()
    }
    return results, summary


def run_strength_standardization(profiles: list) -> list:
    taxonomy = _load_taxonomy()
    if not taxonomy:
        print('  [WARN] 표준 목록 없이 진행 — 모든 값을 원문 그대로(미분류) 둡니다.')
    results, summary = standardize_strengths(profiles, taxonomy)
    _write_json(STRENGTH_STD_FILE, results)
    _write_json(UNMAPPED_FILE, summary)
    n_f, n_k = len(summary['fields']), len(summary['keywords'])
    print(f'[OK]   {STRENGTH_STD_FILE} 저장 ({len(results)}명, 미분류 분야 {n_f}종·키워드 {n_k}종 '
          f'→ {UNMAPPED_FILE} 확인 후 {TAXONOMY_FILE}에 추가하세요)')
    return results


def process() -> bool:
    profiles = _read_json(PROFILES_FILE, [])
    if not profiles:
        print(f'[process_expertise_metrics] {PROFILES_FILE} 없음 — 종료 '
              '(process_researcher_expertise.py 먼저 실행)')
        return False
    run_strength_standardization(profiles)
    return True


if __name__ == '__main__':
    process()
