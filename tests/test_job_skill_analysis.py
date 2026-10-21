"""직무 스킬 분석(로컬, 2026-10-21) — 정규화·분석·엑셀 리포트·실행 스크립트."""
import hashlib
import os
import re
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'pipeline'))
sys.path.insert(0, ROOT)
import job_skill_analysis as jsa  # noqa: E402
import process_job_skill_set as prep  # noqa: E402

HEAD = ['스킬명', '부서', '직무', '스킬 정의', 'Level 1', 'Level2', 'LEVEL3', '스킬 구성요소']
ROWS = [
    ['Python 프로그래밍', 'A부서', '회로설계', '파이썬으로 자동화 코드를 작성하는 능력', '기본 문법을 이해한다', '자동화 코드를 구현한다', '코드 구조를 설계한다', '언어'],
    ['회로 시뮬레이션', '', '', 'SPICE로 회로 동작을 검증하는 능력', '지도하에 수행한다', '결과를 분석한다', '검증 전략을 주도한다', '도구, 지식'],
    ['파이썬 코딩', 'B부서', '회로설계', '파이썬으로 자동화 코드를 작성하는 역량', '문법을 이해한다', '코드를 작성한다', '품질 기준을 정립한다', '언어'],
    ['회로 시뮬레이션', '', '', '아날로그 회로 성능을 예측하는 능력', '검증 전략을 주도한다', '시뮬레이션을 수행한다', '시뮬레이션을 수행한다', '기술'],
    ['회로시뮬레이션', '', '', '아날로그 회로 성능을 예측하는 능력', '', '', '', '도구'],
    ['데이터 분석', 'A부서', '소재개발', '실험 데이터를 분석하는 능력', '이해한다', '활용한다', '주도한다', '스킬'],
    ['데이터 분석', 'A부서', '회로설계', '측정 데이터를 분석하는 능력', '이해한다', '활용한다', '주도한다', '스킬'],
]


def _raw():
    return pd.DataFrame(ROWS, columns=HEAD)


def _fake_embed(texts):
    """동의어를 같은 토큰으로 바꾼 단어 주머니 벡터 — 의미 유사도 경로 시험용."""
    syn = {'파이썬': 'python', '코딩': '프로그래밍', '역량': '능력'}
    out = []
    for t in texts:
        s = t.lower()
        for a, b in syn.items():
            s = s.replace(a, b)
        v = np.zeros(128, dtype=np.float32)
        for tok in re.findall(r'[0-9a-z가-힣]+', s):
            v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % 128] += 1
        out.append(v)
    return out


def test_normalize_headers_filldown_and_key():
    df, info = prep.normalize(_raw())
    assert list(df.columns[:8]) == prep.COLUMNS
    assert info['filled_cells'] == 6                                  # 병합 셀(빈 부서·직무) 보정
    assert df.loc[1, 'department'] == 'A부서' and df.loc[3, 'job_function'] == '회로설계'
    assert prep.skill_key('회로 시뮬레이션') == prep.skill_key('회로시뮬레이션')
    with pytest.raises(ValueError, match='현재 파일 헤더'):
        prep.normalize(_raw().drop(columns=['스킬 정의']))


def test_analysis_text_mode():
    df, _ = prep.normalize(_raw())
    res = jsa.analyze(df, embed_fn=None, log=lambda *a: None)
    assert res['mode'] == 'char'
    circuit = next(b for b in res['matrix'] if b['job'] == '회로설계')
    kinds = dict(zip(circuit['table']['스킬명'], circuit['table']['구분']))
    assert kinds['회로 시뮬레이션'] == '공통' and kinds['Python 프로그래밍'] == '고유'
    same = res['same_summary']
    assert set(same['스킬명']) == {'회로 시뮬레이션'} and same.iloc[0]['부서 수'] == 2
    assert not res['same_detail'].empty
    level = res['level']
    assert any('역전' in x for x in level['점검 결과'])                  # 주도 → 적용 → 적용
    assert any('L2·L3 문구 거의 동일' in x for x in level['점검 결과'])
    assert any('빈칸: L1, L2, L3' in x for x in level['점검 결과'])
    kinds = set(res['data']['유형'])
    assert {'중복 행', '스킬명 표기 다름', '구성요소 미분류'} <= kinds
    assert list(res['cross_job']['스킬명']) == ['데이터 분석']
    comp = res['components']
    a = comp[(comp['직무'] == '회로설계') & (comp['부서'] == 'A부서')].iloc[0]
    assert a['도구'] == 1 and a['지식'] == 1 and a['언어'] == 1 and a['스킬'] == 1
    assert not res['dept'][0]['jaccard'].empty


def test_analysis_semantic_mode_finds_synonym_skill():
    df, _ = prep.normalize(_raw())
    res = jsa.analyze(df, embed_fn=_fake_embed, log=lambda *a: None)
    assert res['mode'] == 'sem'
    std = res['standardize']
    pair = {frozenset((a, b)) for a, b in zip(std['스킬명 A'], std['스킬명 B'])}
    assert frozenset(('Python 프로그래밍', '파이썬 코딩')) in pair
    blk = next(b for b in res['dept'] if b['job'] == '회로설계')
    assert blk['soft'].loc['A부서', 'B부서'] > blk['jaccard'].loc['A부서', 'B부서']   # 이름 달라도 내용 같은 스킬 반영


def test_embedding_failure_falls_back_to_text():
    df, _ = prep.normalize(_raw())

    def broken(_texts):
        raise RuntimeError('서버 없음')
    msgs = []
    res = jsa.analyze(df, embed_fn=broken, log=msgs.append)
    assert res['mode'] == 'char' and '서버 없음' in res['sem_error']
    assert any('임베딩 서버 사용 불가' in m for m in msgs)


def _isolate_env(monkeypatch):
    for var in ('NO_PROXY', 'no_proxy', 'EMBED_BASE_URL', 'LLM2_API_URL'):
        monkeypatch.setenv(var, '')


def test_report_and_script(tmp_path, monkeypatch):
    _isolate_env(monkeypatch)
    raw_dir, raw_csv_dir = tmp_path / 'raw', tmp_path / 'raw_csv'
    for d in (raw_dir, raw_csv_dir):
        d.mkdir()
    monkeypatch.setattr(prep, 'RAW_DIR', str(raw_dir))
    monkeypatch.setattr(prep, 'RAW_CSV_PATH', str(raw_csv_dir / 'job_skill_set.csv'))
    _raw().to_csv(raw_csv_dir / 'job_skill_set.csv', index=False, encoding='utf-8-sig')
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    import analyze_job_skills
    out = tmp_path / 'report'
    assert analyze_job_skills.main(['--no-embed', '--out', str(out)]) == 0
    files = [f for f in os.listdir(out) if f.endswith('.xlsx')]
    assert len(files) == 1 and files[0].startswith('job_skill_analysis_')
    assert (out / 'job_skill_set.csv').exists()                       # 정규화 CSV도 출력 폴더에(앱 data/processed 아님)
    from openpyxl import load_workbook
    wb = load_workbook(out / files[0])
    assert wb.sheetnames == ['요약', '스킬 매트릭스', '같은 스킬 비교', '같은 스킬 상세', '표준화 후보', '부서 간 유사도',
                             '구성요소 비율', '레벨 점검', '데이터 점검', '직무 간 공유 스킬', '정규화 데이터']
    assert analyze_job_skills.main(['--no-embed', '--job', '없는직무', '--out', str(tmp_path / 'r2')]) == 1
    # --input으로 다른 위치의 파일 지정
    other = tmp_path / '스킬셋_사본.csv'
    _raw().to_csv(other, index=False, encoding='utf-8-sig')
    assert analyze_job_skills.main(['--no-embed', '--input', str(other), '--out', str(tmp_path / 'r3')]) == 0
    assert analyze_job_skills.main(['--no-embed', '--input', str(tmp_path / '없음.xlsx'), '--out', str(tmp_path / 'r4')]) == 1


def test_prepare_env_rewrites_docker_hosts(monkeypatch):
    _isolate_env(monkeypatch)
    monkeypatch.setenv('EMBED_BASE_URL', 'http://bge-embed:7138')
    monkeypatch.setenv('LLM2_API_URL', 'http://75.12.15.121:8000/v1/chat/completions')
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    import analyze_job_skills
    analyze_job_skills.prepare_env(log=lambda *a: None)
    assert os.environ['EMBED_BASE_URL'] == 'http://localhost:7138'
    assert os.environ['LLM2_API_URL'].startswith('http://75.12.15.121:8000')
    assert '75.12.15.121' in os.environ['NO_PROXY'] and 'localhost' in os.environ['no_proxy']


def test_llm_review_fills_ai_columns_and_caches(tmp_path, monkeypatch):
    import job_skill_llm as jl
    df, _ = prep.normalize(_raw())
    res = jsa.analyze(df, embed_fn=_fake_embed, log=lambda *a: None)
    calls = []

    def fake_call(prompt, max_tokens=1200):
        calls.append(prompt)
        assert '사번' not in prompt                                     # PII 없음(스킬셋엔 원래 없음)
        if '같은 스킬을 부서마다' in prompt:
            return {'difference_type': '범위 차이', 'summary': 'A부서는 SPICE, B부서는 성능 예측',
                    'merged_definition': '회로 동작·성능을 검증하는 능력'}
        if '같은 스킬인지' in prompt:
            return {'items': [{'id': 0, 'same': True, 'standard_name': 'Python 프로그래밍',
                               'merged_definition': '파이썬 코드 작성 능력', 'reason': '정의 동일'}]}
        if 'Level 1→2→3' in prompt:
            n = prompt.count('\n  L1:')
            return {'items': [{'id': i, 'verdict': '역전' if i == 0 else '명확', 'issue': 'L1이 가장 높음' if i == 0 else '',
                               'suggestion': ''} for i in range(n)]}
        if '구성요소를' in prompt:
            return {'items': [{'id': 0, 'component': '도구', 'reason': '시뮬레이터 사용'}]}
        if '부서별 스킬 목록' in prompt:
            return {'summary': 'A부서는 언어 중심', 'gaps': ''}
        return None
    monkeypatch.setattr(jl, '_call', fake_call)
    cache = str(tmp_path / 'llm.json')
    st = jl.review(df, res, cache_path=cache, workers=2, log=lambda *a: None)
    assert st['failed'] == 0 and st['calls'] == len(calls) > 0
    assert res['same_summary'].iloc[0]['AI 차이 유형'] == '범위 차이'
    assert (res['standardize']['AI 같은 스킬?'] == '같음').any()
    assert res['level_ai'].iloc[0]['AI 판정'] == '역전'
    assert (res['data']['AI 제안'] != '').any()
    assert res['dept'][0]['ai_summary'] == 'A부서는 언어 중심'
    res['llm_parts'] = jl.PARTS
    from job_skill_report import build_workbook
    from openpyxl import load_workbook
    path = build_workbook(df, res, {'source': 'x', 'run_at': 'now'}, str(tmp_path / 'r.xlsx'))
    assert '레벨 AI 점검' in load_workbook(path).sheetnames
    # 다시 돌리면 캐시만 사용
    res2 = jsa.analyze(df, embed_fn=_fake_embed, log=lambda *a: None)
    n = len(calls)
    st2 = jl.review(df, res2, cache_path=cache, workers=2, log=lambda *a: None)
    assert len(calls) == n and st2['calls'] == 0 and st2['cached'] == st['calls']
