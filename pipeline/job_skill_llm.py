"""
직무 스킬 분석 — LLM 검토(2026-10-21, `--llm` 옵션). 점수·판정은 계산값(job_skill_analysis) 그대로 두고, 사람이
원문을 읽어야 알던 "무엇이 다른지"를 사내 LLM(LLM2, pipeline/llm_client.call_llm)이 덧붙인다. 결과 열은 'AI '로 시작.

  same  같은 스킬 비교 — 부서별 차이 유형·요약·통합 정의 제안 (스킬 1개 = 1회 호출)
  std   표준화 후보 — 정말 같은 스킬인지, 표준 스킬명·통합 정의 (8쌍 = 1회)
  level 레벨 점검 — L1→L2→L3 단계가 명확히 올라가는지, 수정 제안 (8행 = 1회)
  comp  구성요소 미분류 — 도구/스킬/언어/지식 중 제안 (15행 = 1회)
  dept  부서 간 비교 — 직무마다 부서별 스킬 구성 특징 요약 (직무 1개 = 1회)

프롬프트에는 직무·부서·스킬 문장만 들어간다(스킬셋에는 사번·이름 같은 개인정보가 없음 — 프로젝트 PII 규칙 준수).
응답은 프롬프트 해시로 캐시(cache_path)해 다시 돌릴 때 바뀐 부분만 호출한다.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading

import pandas as pd

PROMPT_VERSION = 'v1'
PARTS = ('same', 'std', 'level', 'comp', 'dept')
SYSTEM = ('당신은 기업 연구소의 직무·스킬 체계를 검토하는 HR 전문가입니다. 주어진 스킬 정의와 레벨 문장만 근거로 판단하고, '
          '추측은 하지 않습니다. 답은 반드시 요청한 JSON 형식 하나만, 한국어로 짧고 구체적으로 씁니다.')
MAX_FIELD = 400


def _cut(text, n=MAX_FIELD) -> str:
    s = str(text or '').strip()
    return s if len(s) <= n else s[:n] + '…'


class LLMCache:
    def __init__(self, path: str | None):
        self.path = path
        self.lock = threading.Lock()
        self.data = {}
        if path and os.path.exists(path):
            try:
                with open(path, encoding='utf-8') as f:
                    self.data = json.load(f)
            except (OSError, ValueError):
                self.data = {}

    @staticmethod
    def key(prompt: str) -> str:
        return hashlib.sha1(f'{PROMPT_VERSION}\n{SYSTEM}\n{prompt}'.encode('utf-8')).hexdigest()

    def get(self, prompt):
        return self.data.get(self.key(prompt))

    def put(self, prompt, value):
        with self.lock:
            self.data[self.key(prompt)] = value

    def save(self):
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = f'{self.path}.{os.getpid()}.{threading.get_ident()}.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False)
        os.replace(tmp, self.path)


def _call(prompt: str, max_tokens: int = 1200):
    """LLM 호출 → dict(파싱 실패·빈 응답이면 None). 테스트에서 바꿔 끼울 수 있게 모듈 함수로 둔다."""
    from llm_client import call_llm, extract_json
    raw = call_llm(prompt, SYSTEM, temperature=0.1, max_tokens=max_tokens)
    if not raw:
        return None
    try:
        return json.loads(extract_json(raw))
    except ValueError:
        return None


# ─── 프롬프트 ────────────────────────────────────────────────────────────────

def _prompt_same(job, skill, recs) -> str:
    lines = [f'직무: {job}', f'스킬명: {skill}', '', '부서별 정의와 레벨:']
    for r in recs:
        lines += [f"[{r['department']}]", f"- 정의: {_cut(r['definition_skill'])}",
                  f"- L1: {_cut(r['skill_level_1'])}", f"- L2: {_cut(r['skill_level_2'])}", f"- L3: {_cut(r['skill_level_3'])}"]
    lines += ['', '같은 스킬을 부서마다 어떻게 다르게 정의했는지 비교하세요. JSON:',
              '{"difference_type": "표현 차이" | "범위 차이" | "수준 차이" | "내용 다름",',
              ' "summary": "부서별로 무엇이 다른지 1~2문장(부서명 포함)",',
              ' "common_core": "부서 공통 핵심 1문장",',
              ' "merged_definition": "부서 차이를 아우르는 통합 정의 제안 1문장"}',
              '표현 차이=뜻은 같고 표현만 다름, 범위 차이=다루는 대상·범위가 다름, 수준 차이=요구 수준(레벨)이 다름, 내용 다름=사실상 다른 스킬.']
    return '\n'.join(lines)


def _prompt_std(items) -> str:
    lines = ['아래 스킬 쌍이 같은 스킬인지(하나로 통합해도 되는지) 판단하세요.', '']
    for i, it in enumerate(items):
        lines += [f'[{i}] A: {it["a"]} — {_cut(it["da"], 250)}', f'    B: {it["b"]} — {_cut(it["db"], 250)}']
    lines += ['', 'JSON: {"items": [{"id": 번호, "same": true|false, "standard_name": "통합 시 표준 스킬명(같을 때만)",',
              ' "merged_definition": "통합 정의 1문장(같을 때만)", "reason": "판단 근거 1문장"}]}']
    return '\n'.join(lines)


def _prompt_level(items) -> str:
    lines = ['각 스킬의 Level 1→2→3 문장이 단계별로 요구 수준이 명확히 올라가는지 점검하세요.', '']
    for i, it in enumerate(items):
        lines += [f'[{i}] {it["skill"]} (직무 {it["job"]}, {it["dept"]})', f'  정의: {_cut(it["def"], 200)}',
                  f'  L1: {_cut(it["l1"], 250)}', f'  L2: {_cut(it["l2"], 250)}', f'  L3: {_cut(it["l3"], 250)}']
    lines += ['', 'JSON: {"items": [{"id": 번호, "verdict": "명확" | "모호" | "역전" | "정보 부족",',
              ' "issue": "문제가 있으면 무엇이 문제인지 1문장(명확이면 빈 문자열)",',
              ' "suggestion": "모호·역전이면 고칠 단계와 수정 문장 제안(예: L2 → ...), 아니면 빈 문자열"}]}']
    return '\n'.join(lines)


def _prompt_comp(items) -> str:
    lines = ['각 스킬의 구성요소를 "도구", "스킬", "언어", "지식" 중 가장 맞는 것 하나로 분류하세요.',
             '도구=소프트웨어·장비 사용, 스킬=수행 기술·방법, 언어=프로그래밍·외국어, 지식=이론·도메인 지식.', '']
    for i, it in enumerate(items):
        lines.append(f'[{i}] {it["skill"]} — {_cut(it["def"], 200)} (현재 값: {it["cur"] or "없음"})')
    lines += ['', 'JSON: {"items": [{"id": 번호, "component": "도구"|"스킬"|"언어"|"지식", "reason": "근거 짧게"}]}']
    return '\n'.join(lines)


def _prompt_dept(job, per_dept) -> str:
    lines = [f'직무: {job}', '부서별 스킬 목록(스킬명: 정의 요약):']
    for dept, skills in per_dept.items():
        lines.append(f'[{dept}]')
        lines += [f'- {n}: {_cut(d, 80)}' for n, d in skills[:40]]
    lines += ['', '같은 직무인데 부서마다 스킬 구성이 어떻게 다른지 요약하세요. JSON:',
              '{"summary": "공통점과 부서별 특징 2~4문장(부서명 포함)", "gaps": "다른 부서엔 있는데 특정 부서에 빠진 주요 스킬 1~2문장(없으면 빈 문자열)"}']
    return '\n'.join(lines)


# ─── 실행 ────────────────────────────────────────────────────────────────────

def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def review(df: pd.DataFrame, res: dict, *, parts=PARTS, cache_path: str | None = None, workers: int = 4,
           log=print) -> dict:
    """res에 AI 열을 붙이고 통계를 돌려준다: {'calls', 'cached', 'failed'}."""
    from llm_client import run_concurrent
    cache = LLMCache(cache_path)
    jobs = []        # (prompt, max_tokens, 적용 함수)

    if 'same' in parts and not res['same_summary'].empty:
        s = res['same_summary']
        for col in ('AI 차이 유형', 'AI 차이 요약', 'AI 통합 정의 제안'):
            s[col] = ''
        from process_job_skill_set import skill_key
        for i, r in s.iterrows():
            g = df[(df['job_function'] == r['직무']) & (df['skill_key'] == skill_key(r['스킬명']))]
            recs = g.drop_duplicates('department').to_dict('records')
            if len(recs) < 2:
                continue

            def apply(out, i=i):
                s.at[i, 'AI 차이 유형'] = out.get('difference_type', '')
                s.at[i, 'AI 차이 요약'] = out.get('summary', '')
                s.at[i, 'AI 통합 정의 제안'] = out.get('merged_definition', '')
            jobs.append((_prompt_same(r['직무'], r['스킬명'], recs), 900, apply))

    if 'std' in parts and not res['standardize'].empty:
        t = res['standardize']
        for col in ('AI 같은 스킬?', 'AI 표준 스킬명', 'AI 통합 정의', 'AI 근거'):
            t[col] = ''
        rows = list(t.index)
        for chunk in _chunks(rows, 8):
            items = [{'a': t.at[i, '스킬명 A'], 'b': t.at[i, '스킬명 B'], 'da': t.at[i, '정의 A'], 'db': t.at[i, '정의 B']}
                     for i in chunk]

            def apply(out, chunk=chunk):
                for it in out.get('items', []) if isinstance(out, dict) else []:
                    k = it.get('id')
                    if isinstance(k, int) and 0 <= k < len(chunk):
                        i = chunk[k]
                        t.at[i, 'AI 같은 스킬?'] = '같음' if it.get('same') else '다름'
                        t.at[i, 'AI 표준 스킬명'] = it.get('standard_name', '') if it.get('same') else ''
                        t.at[i, 'AI 통합 정의'] = it.get('merged_definition', '') if it.get('same') else ''
                        t.at[i, 'AI 근거'] = it.get('reason', '')
            jobs.append((_prompt_std(items), 1500, apply))

    if 'level' in parts:
        rows = [r for r in df.to_dict('records') if any(r[c] for c in ('skill_level_1', 'skill_level_2', 'skill_level_3'))]
        found = []
        res['level_ai'] = pd.DataFrame()
        for chunk in _chunks(rows, 8):
            items = [{'skill': r['skill_name'], 'job': r['job_function'], 'dept': r['department'], 'def': r['definition_skill'],
                      'l1': r['skill_level_1'], 'l2': r['skill_level_2'], 'l3': r['skill_level_3']} for r in chunk]

            def apply(out, chunk=chunk):
                for it in out.get('items', []) if isinstance(out, dict) else []:
                    k = it.get('id')
                    if isinstance(k, int) and 0 <= k < len(chunk):
                        r = chunk[k]
                        found.append({'직무': r['job_function'], '부서': r['department'], '스킬명': r['skill_name'],
                                      'AI 판정': it.get('verdict', ''), 'AI 지적': it.get('issue', ''),
                                      'AI 수정 제안': it.get('suggestion', ''), 'Level 1': r['skill_level_1'],
                                      'Level 2': r['skill_level_2'], 'Level 3': r['skill_level_3'], '원본 행': r['row_no']})
            jobs.append((_prompt_level(items), 1800, apply))
        res['_level_found'] = found

    if 'comp' in parts and not res['data'].empty:
        d = res['data']
        d['AI 제안'] = ''
        idx = [i for i in d.index if d.at[i, '유형'] == '구성요소 미분류']
        by_row = df.set_index('row_no')
        for chunk in _chunks(idx, 15):
            items = []
            for i in chunk:
                rn = d.at[i, '원본 행']
                r = by_row.loc[rn] if rn in by_row.index else None
                items.append({'skill': d.at[i, '스킬명'], 'def': r['definition_skill'] if r is not None else '',
                              'cur': r['components_skill'] if r is not None else ''})

            def apply(out, chunk=chunk):
                for it in out.get('items', []) if isinstance(out, dict) else []:
                    k = it.get('id')
                    if isinstance(k, int) and 0 <= k < len(chunk):
                        d.at[chunk[k], 'AI 제안'] = f"{it.get('component', '')} — {it.get('reason', '')}".strip(' —')
            jobs.append((_prompt_comp(items), 1200, apply))

    if 'dept' in parts:
        for b in res['dept']:
            sub = df[df['job_function'] == b['job']]
            per = {dept: list(zip(g['skill_name'], g['definition_skill']))
                   for dept, g in sub.drop_duplicates(['department', 'skill_key']).groupby('department', sort=False)}

            def apply(out, b=b):
                b['ai_summary'] = out.get('summary', '')
                b['ai_gaps'] = out.get('gaps', '')
            jobs.append((_prompt_dept(b['job'], per), 900, apply))

    stats = {'calls': 0, 'cached': 0, 'failed': 0, 'total': len(jobs)}
    todo = []
    for prompt, mt, apply in jobs:
        hit = cache.get(prompt)
        if hit is not None:
            apply(hit)
            stats['cached'] += 1
        else:
            todo.append((prompt, mt, apply))
    if todo:
        log(f'  AI 검토 {len(todo)}건 호출(캐시 {stats["cached"]}건 재사용, 동시 {workers})...')
        done = {'n': 0}

        def on_complete(i, out, err):
            done['n'] += 1
            prompt, _mt, apply = todo[i]
            if err is None and isinstance(out, dict):
                cache.put(prompt, out)
                apply(out)
                stats['calls'] += 1
            else:
                stats['failed'] += 1
            if done['n'] % 10 == 0 or done['n'] == len(todo):
                log(f'    {done["n"]}/{len(todo)}')
                cache.save()
        run_concurrent([(lambda p=p, mt=mt: _call(p, mt)) for p, mt, _a in todo], max_workers=workers,
                       on_complete=on_complete)
        cache.save()
    found = res.pop('_level_found', None)
    if found is not None:
        lv = pd.DataFrame(found)
        if not lv.empty:
            order = {'역전': 0, '모호': 1, '정보 부족': 2, '명확': 3}
            lv = lv.assign(_o=lv['AI 판정'].map(order).fillna(4)).sort_values(['_o', '직무', '부서']).drop(columns='_o')
        res['level_ai'] = lv.reset_index(drop=True)
    res['llm_stats'] = stats
    return stats
