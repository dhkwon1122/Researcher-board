"""
직무 스킬 분석(2026-10-21, 1차) — 정규화된 스킬셋(process_job_skill_set)으로 아래를 계산한다. 엑셀 리포트는
job_skill_report.py, 실행은 scripts/analyze_job_skills.py(로컬 PowerShell).

  핵심  skill_matrix          같은 직무 안에서 부서별 스킬 구성(공통/일부/고유)
        same_skill_compare    같은 스킬명이 부서마다 정의·Level1~3을 얼마나 다르게 쓰는지
  1     standardization_candidates  이름은 다른데 내용이 거의 같은 스킬(표준화 후보)
  2     dept_similarity       같은 직무 안 부서 간 스킬 구성 유사도(이름 일치 Jaccard + 내용 기준 일치율)
  3     component_ratio       부서·직무별 구성요소(도구/스킬/언어/지식) 비율
  4     level_check           Level1~3 빈칸·단계 간 문구 거의 동일·수준 표현 역전
  5     data_check            필수값 누락·중복 행·스킬명 표기 흔들림·구성요소 미분류
  6     cross_job_skills      여러 직무에 걸친 공유 스킬

유사도: 문구 일치도(글자 2~3gram TF-IDF 코사인, 항상) + 의미 유사도(사내 임베딩 bge-m3 코사인, 접속되면).
판정·후보 기준은 의미 유사도가 있으면 그것을, 없으면 문구 일치도를 쓴다(아래 임계값).
"""
from __future__ import annotations

import itertools
import re
import unicodedata
from collections import Counter

import numpy as np
import pandas as pd

COMPONENTS = ['도구', '스킬', '언어', '지식']
LEVELS = ['skill_level_1', 'skill_level_2', 'skill_level_3']
FIELDS = [('definition_skill', '정의'), ('skill_level_1', 'L1'), ('skill_level_2', 'L2'), ('skill_level_3', 'L3')]

# 임계값 — 의미(sem, bge-m3 코사인) / 문구(char, TF-IDF 코사인). 0.85는 강점 분야 표준화(build_strength_taxonomy)와 같은 값.
JUDGE = {'sem': (0.85, 0.70), 'char': (0.80, 0.50)}        # (같은 내용 이상, 일부 다름 이상) — 그 아래는 '내용 다름'
STANDARDIZE = {'sem': 0.85, 'char': 0.60}                  # 이름 다른 스킬의 내용 유사도 기준
NAME_SIMILAR_CHAR = 0.75                                   # 이름 자체가 비슷한(표기 변형) 스킬
DEPT_SOFT = {'sem': 0.85, 'char': 0.60}                    # 부서 간 '내용 기준 일치율'에서 같은 스킬로 볼 기준
LEVEL_DUP_CHAR = 0.90                                      # 단계 간 문구 거의 동일
MAX_STANDARDIZE_PAIRS = 1000

# 수준 표현(단계가 올라갈수록 높아져야 하는 말) — 휴리스틱. '지도하에'(1)와 '지도'(3)를 구분하려고 1단계부터 지운다.
LEVEL_WORDS = [
    (1, ['지도하에', '지도 하에', '지도를 받아', '도움을 받아', '이해', '인지', '알고', '안다', '기초', '기본적',
         '보조', '습득', '학습', '설명할 수']),
    (2, ['적용', '활용', '수행', '독립', '독자적', '분석', '해결', '개선', '운영', '구현', '응용']),
    (3, ['주도', '리드', '선도', '총괄', '전략', '설계', '기획', '지도', '코칭', '멘토', '전파', '교육',
         '전문가', '최적화', '창출', '혁신', '표준화', '제시', '정립', '고도화']),
]
TIER_LABEL = {0: '-', 1: '기초', 2: '적용', 3: '주도'}


# ─── 텍스트 유사도 ───────────────────────────────────────────────────────────

def _norm_text(text: str) -> str:
    s = unicodedata.normalize('NFKC', str(text or '')).lower()
    return re.sub(r'\s+', ' ', s).strip()


class TextIndex:
    """분석에 쓰는 모든 문장을 한 번에 벡터화해 두고 쌍별 유사도를 돌려준다.
    char: 글자 2~3gram TF-IDF(L2 정규화) — sklearn이 없으면 글자 2gram 빈도 코사인.
    sem : embed_fn(texts) → 벡터(정규화). embed_fn이 없거나 실패하면 None(문구 일치도만 사용)."""

    def __init__(self, texts, embed_fn=None, log=print):
        uniq = sorted({_norm_text(t) for t in texts if _norm_text(t)})
        self.pos = {t: i for i, t in enumerate(uniq)}
        self.texts = uniq
        self.char_vecs = self._char_vectors(uniq)
        self.sem_vecs = None
        self.sem_error = ''
        if embed_fn is not None and uniq:
            try:
                vecs = np.asarray(embed_fn(uniq), dtype=np.float32)
                norms = np.linalg.norm(vecs, axis=1, keepdims=True)
                self.sem_vecs = vecs / np.where(norms == 0, 1, norms)
            except Exception as exc:  # noqa: BLE001 — 임베딩 서버 문제는 문구 일치도만으로 계속
                self.sem_error = f'{type(exc).__name__}: {exc}'
                log(f'  [WARN] 임베딩 서버 사용 불가 — 문구 일치도만으로 분석합니다 ({self.sem_error[:200]})')

    @property
    def mode(self) -> str:
        return 'sem' if self.sem_vecs is not None else 'char'

    @staticmethod
    def _char_vectors(texts):
        if not texts:
            return None
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            return TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 3), sublinear_tf=True).fit_transform(texts)
        except ImportError:
            vocab: dict = {}
            rows = []
            for t in texts:
                c = Counter(t[i:i + 2] for i in range(max(len(t) - 1, 1)))
                rows.append({vocab.setdefault(k, len(vocab)): v for k, v in c.items()})
            mat = np.zeros((len(texts), len(vocab)), dtype=np.float32)
            for i, r in enumerate(rows):
                for j, v in r.items():
                    mat[i, j] = v
            norms = np.linalg.norm(mat, axis=1, keepdims=True)
            return mat / np.where(norms == 0, 1, norms)

    def _idx(self, text):
        return self.pos.get(_norm_text(text))

    def char(self, a, b):
        i, j = self._idx(a), self._idx(b)
        if i is None or j is None:
            return None
        if i == j:
            return 1.0
        v = self.char_vecs[i] @ self.char_vecs[j].T
        return float(v.toarray()[0, 0] if hasattr(v, 'toarray') else v)

    def sem(self, a, b):
        if self.sem_vecs is None:
            return None
        i, j = self._idx(a), self._idx(b)
        if i is None or j is None:
            return None
        return float(self.sem_vecs[i] @ self.sem_vecs[j])

    def best(self, a, b):
        """판정에 쓰는 유사도(의미 있으면 의미, 없으면 문구)."""
        return self.sem(a, b) if self.sem_vecs is not None else self.char(a, b)

    def matrix(self, texts_a, texts_b, kind=None) -> np.ndarray:
        kind = kind or self.mode
        ia = [self._idx(t) for t in texts_a]
        ib = [self._idx(t) for t in texts_b]
        out = np.zeros((len(ia), len(ib)), dtype=np.float32)
        va = [k for k, i in enumerate(ia) if i is not None]
        vb = [k for k, i in enumerate(ib) if i is not None]
        if not va or not vb:
            return out
        A = [ia[k] for k in va]
        B = [ib[k] for k in vb]
        if kind == 'sem':
            sub = self.sem_vecs[A] @ self.sem_vecs[B].T
        else:
            sub = self.char_vecs[A] @ self.char_vecs[B].T
            sub = sub.toarray() if hasattr(sub, 'toarray') else sub
        out[np.ix_(va, vb)] = sub
        return out


def collect_texts(df: pd.DataFrame) -> list:
    """TextIndex에 넣을 문장 — 정의·Level·스킬명, 표준화 후보용 '스킬명. 정의'."""
    texts = []
    for col, _ in FIELDS:
        texts += df[col].tolist()
    texts += df['skill_name'].tolist()
    texts += [_skill_text(n, d) for n, d in zip(df['skill_name'], df['definition_skill'])]
    return texts


def _skill_text(name, definition) -> str:
    return f'{name}. {definition}' if definition else str(name)


def _rep(values) -> str:
    """가장 많이 쓰인 비어 있지 않은 값(같으면 먼저 나온 값)."""
    vals = [v for v in values if v]
    return Counter(vals).most_common(1)[0][0] if vals else ''


def _judge(score, mode) -> str:
    if score is None:
        return '-'
    same, partial = JUDGE[mode]
    return '같은 내용' if score >= same else ('일부 다름' if score >= partial else '내용 다름')


def _r(x):
    return None if x is None else round(float(x), 3)


# ─── 핵심: 직무별 스킬 매트릭스 ───────────────────────────────────────────────

def _dept_order(sub: pd.DataFrame) -> list:
    return list(dict.fromkeys(sub['department']))


def skill_matrix(df: pd.DataFrame) -> list:
    """직무마다 {'job', 'depts', 'table'} — table: 스킬명·구성요소·부서 수·구분 + 부서별 ●."""
    blocks = []
    for job, sub in df.groupby('job_function', sort=False):
        depts = _dept_order(sub)
        rows = []
        for key, g in sub.groupby('skill_key', sort=False):
            have = set(g['department'])
            n = len(have)
            if len(depts) == 1:
                kind = '단일 부서'
            elif n == len(depts):
                kind = '공통'
            elif n == 1:
                kind = '고유'
            else:
                kind = '일부'
            row = {'스킬명': _rep(g['skill_name']), '구성요소': _rep(g['components_skill']),
                   '부서 수': n, '구분': kind}
            row.update({d: ('●' if d in have else '') for d in depts})
            rows.append(row)
        order = {'공통': 0, '일부': 1, '고유': 2, '단일 부서': 3}
        table = pd.DataFrame(rows)
        if not table.empty:
            first_dept = table[depts].eq('●').values.argmax(axis=1)
            table = (table.assign(_o=table['구분'].map(order), _n=-table['부서 수'], _d=first_dept)
                     .sort_values(['_o', '_n', '_d', '스킬명']).drop(columns=['_o', '_n', '_d']).reset_index(drop=True))
        counts = table['구분'].value_counts().to_dict() if not table.empty else {}
        blocks.append({'job': job, 'depts': depts, 'table': table, 'counts': counts})
    return blocks


# ─── 핵심: 같은 스킬, 부서별 정의·레벨 비교 ───────────────────────────────────

def same_skill_compare(df: pd.DataFrame, idx: TextIndex) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(요약, 상세). 같은 직무에서 2개 이상 부서가 가진 스킬만. 유사도는 부서 쌍 평균, 판정은 정의·L1~L3 평균 기준.
    정렬: 가장 다르게 쓰는 스킬부터."""
    mode = idx.mode
    summary, detail = [], []
    for (job, key), g in df.groupby(['job_function', 'skill_key'], sort=False):
        g = g.drop_duplicates('department')
        if len(g) < 2:
            continue
        recs = g.to_dict('records')
        row = {'직무': job, '스킬명': _rep(g['skill_name']), '부서 수': len(recs),
               '부서': ', '.join(r['department'] for r in recs)}
        field_scores = []
        pair_scores: dict = {}
        for col, label in FIELDS:
            chars, sems = [], []
            for a, b in itertools.combinations(recs, 2):
                c, s = idx.char(a[col], b[col]), idx.sem(a[col], b[col])
                if c is not None:
                    chars.append(c)
                if s is not None:
                    sems.append(s)
                use = s if mode == 'sem' else c
                if use is not None:
                    pair_scores.setdefault((a['department'], b['department']), []).append(use)
            row[f'{label} 문구 일치도'] = _r(np.mean(chars)) if chars else None
            row[f'{label} 의미 유사도'] = _r(np.mean(sems)) if sems else None
            main = sems if mode == 'sem' else chars
            if main:
                field_scores.append(float(np.mean(main)))
        overall = float(np.mean(field_scores)) if field_scores else None
        row['종합 유사도'] = _r(overall)
        row['판정'] = _judge(overall, mode)
        if pair_scores:
            (da, db), sc = min(pair_scores.items(), key=lambda kv: np.mean(kv[1]))
            row['가장 다른 부서 쌍'] = f'{da} ↔ {db} ({np.mean(sc):.2f})'
        else:
            row['가장 다른 부서 쌍'] = '-'
        summary.append(row)
        for r in recs:
            detail.append({'직무': job, '스킬명': row['스킬명'], '판정': row['판정'], '종합 유사도': row['종합 유사도'],
                           '부서': r['department'], '스킬 정의': r['definition_skill'], 'Level 1': r['skill_level_1'],
                           'Level 2': r['skill_level_2'], 'Level 3': r['skill_level_3'],
                           '구성요소': r['components_skill']})
    s = pd.DataFrame(summary)
    d = pd.DataFrame(detail)
    if not s.empty:
        s = s.sort_values(['종합 유사도', '직무', '스킬명'], na_position='last').reset_index(drop=True)
        order = {(j, n): i for i, (j, n) in enumerate(zip(s['직무'], s['스킬명']))}
        d = d.assign(_o=[order[(j, n)] for j, n in zip(d['직무'], d['스킬명'])]).sort_values(['_o']).drop(columns='_o')
        d = d.reset_index(drop=True)
    return s, d


# ─── 1. 표준화 후보(이름은 다른데 내용이 거의 같은 스킬) ──────────────────────

def standardization_candidates(df: pd.DataFrame, idx: TextIndex, max_pairs: int = MAX_STANDARDIZE_PAIRS) -> pd.DataFrame:
    """스킬명(키)이 다른 두 스킬이 (a) 스킬명+정의 내용이 비슷하거나 (b) 이름 표기가 비슷하거나 (c) 이름 뜻이 같으면(의미 유사도)
    후보. 한 스킬이 부서마다 정의가 다를 수 있어 (스킬명, 정의) 변형끼리 모두 비교하고 스킬 쌍마다 가장 높은 값을 쓴다."""
    var = df[['skill_key', 'skill_name', 'definition_skill']].drop_duplicates().reset_index(drop=True)
    if var['skill_key'].nunique() < 2:
        return pd.DataFrame()
    mode = idx.mode
    thr = STANDARDIZE[mode]
    texts = [_skill_text(n, d) for n, d in zip(var['skill_name'], var['definition_skill'])]
    names = var['skill_name'].tolist()
    content = idx.matrix(texts, texts)
    name_char = idx.matrix(names, names, kind='char')
    name_sem = idx.matrix(names, names, kind='sem') if mode == 'sem' else None
    keys = var['skill_key'].to_numpy()
    iu, ju = np.triu_indices(len(var), k=1)
    diff_key = keys[iu] != keys[ju]
    hit = diff_key & ((content[iu, ju] >= thr) | (name_char[iu, ju] >= NAME_SIMILAR_CHAR)
                      | ((name_sem[iu, ju] >= thr) if name_sem is not None else False))
    best: dict = {}
    for i, j in zip(iu[hit], ju[hit]):
        a, b = (i, j) if keys[i] < keys[j] else (j, i)
        pair = (keys[a], keys[b])
        cur = best.get(pair)
        if cur is None or content[a, b] > content[cur[0], cur[1]]:
            best[pair] = (a, b)
    info = {k: g for k, g in df.groupby('skill_key', sort=False)}
    rows = []
    for (ka, kb), (a, b) in best.items():
        ga, gb = info[ka], info[kb]
        ja, jb = list(dict.fromkeys(ga['job_function'])), list(dict.fromkeys(gb['job_function']))
        mask = (keys == ka)[:, None] & (keys == kb)[None, :]
        c_max = float(content[mask].max())
        nc = float(name_char[mask].max())
        ns = float(name_sem[mask].max()) if name_sem is not None else None
        why = []
        if c_max >= thr:
            why.append('내용')
        if nc >= NAME_SIMILAR_CHAR:
            why.append('이름 표기')
        if ns is not None and ns >= thr:
            why.append('이름 뜻')
        common = [x for x in ja if x in jb]
        rows.append({
            '스킬명 A': _rep(ga['skill_name']), '스킬명 B': _rep(gb['skill_name']),
            '내용 유사도': _r(c_max), '이름 문구 일치도': _r(nc), '이름 의미 유사도': _r(ns),
            '근거': ' · '.join(why) + ' 비슷',
            '같은 직무': ', '.join(common) if common else '-',
            '직무 A': ', '.join(ja), '직무 B': ', '.join(jb),
            '부서 A': ', '.join(dict.fromkeys(ga['department'])), '부서 B': ', '.join(dict.fromkeys(gb['department'])),
            '정의 A': var.at[a, 'definition_skill'] if keys[a] == ka else var.at[b, 'definition_skill'],
            '정의 B': var.at[b, 'definition_skill'] if keys[b] == kb else var.at[a, 'definition_skill'],
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    if name_sem is None:
        out = out.drop(columns=['이름 의미 유사도'])
    return out.sort_values(['내용 유사도', '이름 문구 일치도'], ascending=False).head(max_pairs).reset_index(drop=True)


# ─── 2. 부서 간 스킬 구성 유사도 ─────────────────────────────────────────────

def dept_similarity(df: pd.DataFrame, idx: TextIndex) -> list:
    """직무마다 {'job', 'depts', 'jaccard', 'soft'} — jaccard: 스킬명(키) 일치 비율, soft: 이름이 달라도 내용이 같은
    스킬(DEPT_SOFT 이상)까지 같은 스킬로 본 일치율. 부서가 2개 이상인 직무만."""
    mode = idx.mode
    thr = DEPT_SOFT[mode]
    blocks = []
    for job, sub in df.groupby('job_function', sort=False):
        depts = _dept_order(sub)
        if len(depts) < 2:
            continue
        per = {}
        for d in depts:
            g = sub[sub['department'] == d].drop_duplicates('skill_key')
            per[d] = {'keys': list(g['skill_key']),
                      'texts': [_skill_text(n, x) for n, x in zip(g['skill_name'], g['definition_skill'])]}
        jac = pd.DataFrame(index=depts, columns=depts, dtype=float)
        soft = pd.DataFrame(index=depts, columns=depts, dtype=float)
        for a in depts:
            for b in depts:
                ka, kb = set(per[a]['keys']), set(per[b]['keys'])
                jac.loc[a, b] = round(len(ka & kb) / len(ka | kb), 3) if ka | kb else None
                if a == b:
                    soft.loc[a, b] = 1.0
                    continue
                m = idx.matrix(per[a]['texts'], per[b]['texts'])
                same_key = np.array([[x == y for y in per[b]['keys']] for x in per[a]['keys']], dtype=bool)
                match = (m >= thr) | same_key
                n_a = int(match.any(axis=1).sum()) if match.size else 0
                n_b = int(match.any(axis=0).sum()) if match.size else 0
                total = len(per[a]['keys']) + len(per[b]['keys'])
                soft.loc[a, b] = round((n_a + n_b) / total, 3) if total else None
        pairs = [jac.loc[a, b] for a, b in itertools.combinations(depts, 2)]
        spairs = [soft.loc[a, b] for a, b in itertools.combinations(depts, 2)]
        blocks.append({'job': job, 'depts': depts, 'jaccard': jac, 'soft': soft,
                       'avg_jaccard': _r(np.nanmean(pairs)) if pairs else None,
                       'avg_soft': _r(np.nanmean(spairs)) if spairs else None})
    return blocks


# ─── 3. 구성요소 비율 ────────────────────────────────────────────────────────

def split_components(text: str) -> list:
    parts = [p.strip() for p in re.split(r'[,/·;\n、]+', str(text or '')) if p.strip()]
    return parts


def component_ratio(df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    def _row(job, dept, g):
        cnt = Counter()
        for v in g['components_skill']:
            parts = split_components(v)
            if not parts:
                cnt['미기재'] += 1
            for p in parts:
                cnt[p if p in COMPONENTS else '기타'] += 1
        total = sum(cnt.values()) or 1
        r = {'직무': job, '부서': dept, '스킬 수': len(g)}
        for c in COMPONENTS + ['기타', '미기재']:
            r[c] = cnt.get(c, 0)
        for c in COMPONENTS:
            r[f'{c} %'] = round(cnt.get(c, 0) / total, 3)
        top = max(COMPONENTS, key=lambda c: cnt.get(c, 0))
        r['비중 최대'] = top if cnt.get(top, 0) else '-'
        return r

    for job, sub in df.groupby('job_function', sort=False):
        for dept in _dept_order(sub):
            rows.append(_row(job, dept, sub[sub['department'] == dept]))
        if sub['department'].nunique() > 1:
            rows.append(_row(job, '(직무 전체)', sub))
    return pd.DataFrame(rows)


# ─── 4. 레벨 체계 점검 ───────────────────────────────────────────────────────

def level_tier(text: str) -> int:
    """문장의 수준 표현 단계(0: 없음, 1 기초 · 2 적용 · 3 주도) — 가장 높은 단계."""
    s = str(text or '')
    tier = 0
    for t, words in LEVEL_WORDS:
        for w in words:
            if w in s:
                tier = max(tier, t)
                if t == 1:
                    s = s.replace(w, ' ')
    return tier


def level_check(df: pd.DataFrame, idx: TextIndex) -> pd.DataFrame:
    rows = []
    for r in df.to_dict('records'):
        lv = [r[c] for c in LEVELS]
        issues = []
        blank = [f'L{i + 1}' for i, v in enumerate(lv) if not v]
        if blank:
            issues.append('빈칸: ' + ', '.join(blank))
        for i in range(2):
            if lv[i] and lv[i + 1]:
                c = idx.char(lv[i], lv[i + 1])
                if c is not None and c >= LEVEL_DUP_CHAR:
                    issues.append(f'L{i + 1}·L{i + 2} 문구 거의 동일({c:.2f})')
        tiers = [level_tier(v) for v in lv]
        for i in range(2):
            if tiers[i] and tiers[i + 1] and tiers[i + 1] < tiers[i]:
                issues.append(f'수준 표현 역전(L{i + 1} {TIER_LABEL[tiers[i]]} → L{i + 2} {TIER_LABEL[tiers[i + 1]]})')
        if issues:
            rows.append({'직무': r['job_function'], '부서': r['department'], '스킬명': r['skill_name'],
                         '점검 결과': ' / '.join(issues),
                         '수준 표현(L1→L2→L3)': ' → '.join(TIER_LABEL[t] for t in tiers),
                         'Level 1': lv[0], 'Level 2': lv[1], 'Level 3': lv[2], '원본 행': r['row_no']})
    return pd.DataFrame(rows)


# ─── 5. 데이터 점검 ──────────────────────────────────────────────────────────

def data_check(df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    def add(kind, r, content):
        rows.append({'유형': kind, '직무': r.get('job_function', ''), '부서': r.get('department', ''),
                     '스킬명': r.get('skill_name', ''), '내용': content, '원본 행': r.get('row_no', '')})

    for r in df.to_dict('records'):
        if not r['job_function'] or not r['department']:
            add('필수값 누락', r, '직무 또는 부서 없음')
        if not r['definition_skill']:
            add('필수값 누락', r, '스킬 정의 없음')
        if not any(r[c] for c in LEVELS):
            add('필수값 누락', r, 'Level 1~3 모두 없음')
        parts = split_components(r['components_skill'])
        if not parts:
            add('구성요소 미분류', r, '스킬구성요소 없음')
        else:
            bad = [p for p in parts if p not in COMPONENTS]
            if bad:
                add('구성요소 미분류', r, f'도구/스킬/언어/지식 외 값: {", ".join(bad)}')
    for (job, dept, key), g in df.groupby(['job_function', 'department', 'skill_key'], sort=False):
        if len(g) > 1:
            r = g.iloc[0].to_dict()
            add('중복 행', r, f'같은 직무·부서에 {len(g)}행 (원본 행 {", ".join(map(str, g["row_no"]))})')
    for key, g in df.groupby('skill_key', sort=False):
        names = list(dict.fromkeys(g['skill_name']))
        if len(names) > 1:
            add('스킬명 표기 다름', {'skill_name': names[0], 'job_function': ', '.join(dict.fromkeys(g['job_function']))},
                ' / '.join(f'"{n}"' for n in names))
    out = pd.DataFrame(rows, columns=['유형', '직무', '부서', '스킬명', '내용', '원본 행'])
    order = {'필수값 누락': 0, '중복 행': 1, '스킬명 표기 다름': 2, '구성요소 미분류': 3}
    return out.assign(_o=out['유형'].map(order)).sort_values(['_o'], kind='stable').drop(columns='_o').reset_index(drop=True)


# ─── 6. 직무 간 공유 스킬 ────────────────────────────────────────────────────

def cross_job_skills(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for key, g in df.groupby('skill_key', sort=False):
        jobs = list(dict.fromkeys(g['job_function']))
        if len(jobs) < 2:
            continue
        rows.append({'스킬명': _rep(g['skill_name']), '직무 수': len(jobs), '직무': ', '.join(jobs),
                     '부서 수': g['department'].nunique(), '구성요소': _rep(g['components_skill'])})
    out = pd.DataFrame(rows, columns=['스킬명', '직무 수', '직무', '부서 수', '구성요소'])
    return out.sort_values(['직무 수', '부서 수', '스킬명'], ascending=[False, False, True]).reset_index(drop=True)


# ─── 전체 실행 ───────────────────────────────────────────────────────────────

def analyze(df: pd.DataFrame, embed_fn=None, log=print) -> dict:
    log(f'  문장 벡터화 중(문구 일치도{" + 의미 유사도" if embed_fn else ""})...')
    idx = TextIndex(collect_texts(df), embed_fn=embed_fn, log=log)
    log('  분석 중...')
    matrix = skill_matrix(df)
    same_s, same_d = same_skill_compare(df, idx)
    dept = dept_similarity(df, idx)
    level = level_check(df, idx)
    result = {
        'mode': idx.mode, 'sem_error': idx.sem_error,
        'matrix': matrix, 'same_summary': same_s, 'same_detail': same_d,
        'standardize': standardization_candidates(df, idx),
        'dept': dept, 'components': component_ratio(df),
        'level': level, 'data': data_check(df), 'cross_job': cross_job_skills(df),
    }
    result['job_summary'] = job_summary(df, result)
    return result


def job_summary(df: pd.DataFrame, res: dict) -> pd.DataFrame:
    dept_avg = {b['job']: (b['avg_jaccard'], b['avg_soft']) for b in res['dept']}
    same = res['same_summary']
    level = res['level']
    rows = []
    for b in res['matrix']:
        job = b['job']
        c = b['counts']
        s = same[same['직무'] == job] if not same.empty else same
        rows.append({
            '직무': job, '부서 수': len(b['depts']), '스킬 수': len(b['table']),
            '공통': c.get('공통', 0), '일부': c.get('일부', 0), '고유': c.get('고유', 0),
            '부서 간 스킬명 일치율': dept_avg.get(job, (None, None))[0],
            '부서 간 내용 일치율': dept_avg.get(job, (None, None))[1],
            '같은 스킬(2개+ 부서)': len(s),
            '그중 내용 다름': int((s['판정'] == '내용 다름').sum()) if len(s) else 0,
            '레벨 점검 건수': int((level['직무'] == job).sum()) if not level.empty else 0,
        })
    return pd.DataFrame(rows)
