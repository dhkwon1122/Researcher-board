"""
기술명 표기 차이 통합(2026-10-09, 사용자 확정: 임베딩 + LLM, 보수적 접근).

"실리콘 포토닉스(SiPh) 기반 FMCW LiDAR" / "실리콘 포토닉스 기반 FMCW LiDAR" /
"실리콘 포토닉스 및 FMCW LiDAR"처럼 이름만 다르고 사실상 같은 기술이 따로 집계되는 것을
막기 위해, 기술명을 BGE-M3 임베딩으로 후보 묶음(코사인 ≥ CANDIDATE_SIM)으로 만들고,
묶음마다 LLM이 "정말 같은 기술인 것끼리만" 다시 나눠 대표 이름을 정한다.

보수적 원칙:
  - 후보 기준이 높고(0.88), LLM이 확실히 같다고 한 것만 합친다.
  - LLM 호출/파싱 실패 또는 임베딩 실패 시 그 묶음은 합치지 않는다(원본 이름 유지).
  - 결과는 입력 텍스트 해시로 캐시(tech_canonical_cache.json) — 같은 묶음은 재호출하지 않는다.
LLM 프롬프트에는 연구원 정보가 들어가지 않는다(기술명만).
"""
import hashlib
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT_DIR  # noqa: E402

CANDIDATE_SIM = 0.88
MAX_CLUSTER = 40
CACHE_FILE = 'tech_canonical_cache.json'

_SYSTEM_PROMPT = """# Role
당신은 R&D 기술 분류 전문가입니다. 기술명 목록이 주어집니다. 표기(띄어쓰기, 괄호, 약어 병기,
조사/접속어 "및·기반·의" 등)만 다르고 *실질적으로 같은 기술*인 것끼리만 묶으세요.

# Guidelines
1. 보수적으로 판단하세요. 세부 대상·방식·응용이 다르면(예: "LiDAR 신호처리" vs "LiDAR 광학 설계")
   서로 다른 기술입니다. 애매하면 묶지 마세요.
2. 각 묶음은 목록의 번호(idx)로 지정하고, 대표 이름(name)은 묶음 안의 이름 중 가장 명확하고
   간결한 것을 그대로 고르거나 가볍게 다듬어 쓰세요.
3. 어느 것과도 같지 않은 기술은 단독 묶음으로 두세요. 모든 idx는 정확히 한 묶음에만 속해야 합니다.
4. 반드시 아래 JSON 형식으로만 출력하세요.

# Output Format (JSON)
{"groups": [{"name": "대표 이름", "idx": [0, 2]}, {"name": "다른 기술", "idx": [1]}]}
"""


def _cache_path() -> str:
    return os.path.join(OUT_DIR, CACHE_FILE)


def _load_cache() -> dict:
    try:
        with open(_cache_path(), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(_cache_path(), 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)


def candidate_clusters(names: list, sims: np.ndarray, threshold: float = CANDIDATE_SIM) -> list:
    """sims(N×N 코사인) 기준 threshold 이상 연결 요소 중 크기 2 이상인 묶음(인덱스 리스트)."""
    n = len(names)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        for j in range(i + 1, n):
            if sims[i][j] >= threshold:
                parent[find(i)] = find(j)
    comp: dict = {}
    for i in range(n):
        comp.setdefault(find(i), []).append(i)
    return [sorted(v) for v in comp.values() if len(v) > 1]


def _llm_groups(members: list, cache: dict, call_llm, extract_json) -> list | None:
    """members: 이름 리스트 → [(대표이름, [이름...]), ...] 또는 None(실패)."""
    key = hashlib.sha256('\n'.join(sorted(members)).encode('utf-8')).hexdigest()
    ordered = sorted(members)
    if key in cache:
        data = cache[key]
    else:
        prompt = '기술명 목록:\n' + '\n'.join(f'[{i}] {n}' for i, n in enumerate(ordered))
        raw = call_llm(prompt, _SYSTEM_PROMPT, temperature=0.0, max_tokens=3000)
        if not raw:
            return None
        try:
            data = json.loads(extract_json(raw))
        except json.JSONDecodeError:
            return None
        cache[key] = data
    out, used = [], set()
    for g in data.get('groups') or []:
        idxs = [i for i in (g.get('idx') or []) if isinstance(i, int) and 0 <= i < len(ordered) and i not in used]
        if not idxs:
            continue
        used.update(idxs)
        out.append((str(g.get('name') or ordered[idxs[0]]).strip() or ordered[idxs[0]], [ordered[i] for i in idxs]))
    return out


def build_canonical_map(names: list, *, embed_fn=None, call_llm=None, extract_json=None) -> dict:
    """기술명 리스트 → {원본이름: 대표이름} (합쳐진 것만 포함). 실패 시 빈 dict."""
    names = sorted({str(n).strip() for n in names if str(n).strip()})
    if len(names) < 2:
        return {}
    try:
        if embed_fn is None:
            import researcher_fit as fit
            embed_fn = fit.cached_embed
        if call_llm is None or extract_json is None:
            from llm_client import call_llm as _c, extract_json as _e
            call_llm, extract_json = call_llm or _c, extract_json or _e
        vec = np.asarray(embed_fn(names), dtype=float)
    except Exception as exc:  # 임베딩/LLM 설정 불가 → 보수적으로 통합 생략
        print(f'  [WARN] 기술명 통합 생략(임베딩 실패): {exc}')
        return {}
    norm = np.linalg.norm(vec, axis=1, keepdims=True)
    norm[norm == 0] = 1
    unit = vec / norm
    clusters = candidate_clusters(names, unit @ unit.T)
    cache = _load_cache()
    mapping: dict = {}
    for cl in clusters:
        members = [names[i] for i in cl]
        for k in range(0, len(members), MAX_CLUSTER):
            chunk = members[k:k + MAX_CLUSTER]
            if len(chunk) < 2:
                continue
            groups = _llm_groups(chunk, cache, call_llm, extract_json)
            if not groups:
                continue
            for canon, ms in groups:
                if len(ms) > 1:
                    for m in ms:
                        mapping[m] = canon
    _save_cache(cache)
    print(f'  기술명 통합: 후보 묶음 {len(clusters)}개 → 합쳐진 이름 {len(mapping)}개')
    return mapping
