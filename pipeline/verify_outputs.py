"""
run_integration.py 마지막 단계 — 결과 자동 점검(2026-10-12, 사용자 요청).

"실행은 끝났는데 화면은 옛날 그대로"인 경우(옛 이미지로 실행, DB 반영 누락, 4·5단계 일부 실패 등)를
실행 직후 바로 알 수 있도록, 화면이 실제로 쓰는 산출물에 최근 추가된 필드가 들어 있는지 파일과
DB 양쪽을 확인해 [OK]/[WARN]으로 요약한다. 아무것도 고치지 않고 읽기만 한다.

사용법(단독 실행도 가능):
  python pipeline/verify_outputs.py
"""
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE_DIR, OUT_DIR  # noqa: E402

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 화면(조직 분석 탭 등)이 기대하는 최신 열 — 없으면 옛 코드로 만든 파일이다.
CSV_REQUIRED = {
    'collaboration_edges': (['recent_count', 'level1_a', 'level1_b', 'level3_a', 'level3_b'],
                            '부서/과제간 협업', 'run_analysis 4단계(전문성 심화 지표)'),
    'technology_holder_summary': (['aliases'], '기술별 보유자 수', 'run_analysis 4단계(전문성 심화 지표)'),
}


def _csv(name: str) -> pd.DataFrame | None:
    path = os.path.join(OUT_DIR, f'{name}.csv')
    if not os.path.exists(path):
        return None
    try:
        return pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
    except Exception:
        return None


def _json(name: str):
    path = os.path.join(OUT_DIR, name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def check_files() -> list[tuple[str, str]]:
    """[(level, message)] — level은 'OK' 또는 'WARN'."""
    out = []
    for name, (cols, label, step) in CSV_REQUIRED.items():
        df = _csv(name)
        if df is None:
            out.append(('WARN', f'[{label}] {name}.csv 없음 — {step}가 실행되지 않았거나 실패'))
            continue
        missing = [c for c in cols if c not in df.columns]
        if missing:
            out.append(('WARN', f'[{label}] {name}.csv에 최신 열 {missing} 없음 — 옛 코드로 생성됨'
                                f'(이미지 재빌드 후 다시 실행 필요)'))
            continue
        if name == 'collaboration_edges':
            n = len(df)
            mapped = int(((df['level1_a'] != '') & (df['level1_b'] != '')).sum())
            recent = int((pd.to_numeric(df['recent_count'], errors='coerce').fillna(0) > 0).sum())
            msg = f'[{label}] 연구원 쌍 {n}건, 최근 5년 협업 {recent}건, 양쪽 1단계부서 매핑 {mapped}건'
            out.append(('WARN' if n and not mapped else 'OK',
                        msg + (' — 부서 매핑 0건: 팀참조(team_refer) 확인 필요' if n and not mapped else '')))
        else:
            merged = int((df['aliases'] != '').sum())
            out.append(('OK', f'[{label}] 기술 {len(df)}개, 표기 통합된 기술 {merged}개'
                              + (' (0개면 통합 대상이 없거나 임베딩/LLM 실패 — 실행 로그의 "기술명 통합" 줄 확인)'
                                 if not merged else '')))

    gap = _json('project_competency_gap.json')
    label = '과제별 필요 역량'
    if not gap:
        out.append(('WARN', f'[{label}] project_competency_gap.json 없음/비어 있음 — run_analysis 5단계 미실행 또는 실패'))
    else:
        comps = [c for p in gap for c in (p.get('competencies') or [])]
        with_desc = sum(1 for c in comps if str(c.get('description') or '').strip())
        persons = [x for c in comps for x in (c.get('members') or []) + (c.get('outsiders') or [])]
        with_reason = sum(1 for x in persons if str(x.get('reason') or '').strip())
        if comps and not with_desc and not any('description' in c for c in comps):
            out.append(('WARN', f'[{label}] 설명(description) 필드 없음 — 옛 코드로 생성됨(이미지 재빌드 후 다시 실행 필요)'))
        else:
            level = 'OK' if with_desc else 'WARN'
            out.append((level, f'[{label}] 과제 {len(gap)}건, 필요 역량 {len(comps)}개 중 설명 {with_desc}개, '
                               f'인원 근거 {with_reason}/{len(persons)}건'
                               + (' — 설명 0개: LLM 응답 확인 필요' if not with_desc else '')))

    analysis = _json('project_expertise_analysis.json')
    confl = _csv('project_confl_address')
    if analysis is not None and confl is not None:
        out.append(('OK' if len(analysis) >= len(confl) else 'WARN',
                    f'[과제 문서 분석] 과제 {len(confl)}건 중 분석 결과 {len(analysis)}건'
                    + ('' if len(analysis) >= len(confl) else ' — 일부 과제는 원문 조회/요약 실패(실행 로그 확인)')))

    profiles = _json('연구원 보유 전문성 분석.json')
    if profiles:
        with_focus = sum(1 for p in profiles if 'current_focus_fields' in p)
        out.append(('OK' if with_focus else 'WARN',
                     f'[연구원 전문성] {len(profiles)}명, 주력 분야(최근 5년/5년 이전) 필드 포함 {with_focus}명'))
    return out


def check_db() -> list[tuple[str, str]]:
    """DB가 설정돼 있으면, 화면이 실제로 읽는 DB 테이블이 파일과 같은 최신 상태인지 확인."""
    try:
        from services.db import get_engine, load_env_file
        load_env_file()
        engine = get_engine()
    except Exception as exc:
        return [('WARN', f'[DB] 접속 준비 실패: {exc}')]
    if engine is None:
        return [('OK', '[DB] DATABASE_URL 미설정 — 앱이 파일을 직접 읽으므로 DB 점검 생략')]
    from sqlalchemy import inspect, text
    out = []
    try:
        insp = inspect(engine)
        tables = set(insp.get_table_names())
        for name, (cols, label, _step) in CSV_REQUIRED.items():
            if name not in tables:
                out.append(('WARN', f'[DB:{label}] 테이블 {name} 없음 — DB 반영 필요'))
                continue
            have = {c['name'] for c in insp.get_columns(name)}
            missing = [c for c in cols if c not in have]
            out.append(('WARN', f'[DB:{label}] 최신 열 {missing} 없음 — 파일은 새것이어도 화면은 옛 DB를 읽음. '
                                f'DB 반영(관리자 화면 또는 load_to_db.py) 필요') if missing
                       else ('OK', f'[DB:{label}] 최신 열 반영됨'))
        if 'project_competency_gap' in tables:
            with engine.connect() as conn:
                rows = [r[0] for r in conn.execute(text('SELECT data FROM project_competency_gap'))]
            items = [r if isinstance(r, dict) else json.loads(r) for r in rows]
            comps = [c for p in items for c in (p.get('competencies') or [])]
            with_desc = sum(1 for c in comps if str(c.get('description') or '').strip())
            out.append(('OK' if with_desc else 'WARN',
                        f'[DB:과제별 필요 역량] 필요 역량 {len(comps)}개 중 설명 {with_desc}개'
                        + ('' if with_desc else ' — DB가 옛 결과: DB 반영 필요')))
        else:
            out.append(('WARN', '[DB:과제별 필요 역량] 테이블 project_competency_gap 없음 — DB 반영 필요'))
    except Exception as exc:
        out.append(('WARN', f'[DB] 점검 중 오류: {type(exc).__name__}: {exc}'))
    return out


def run() -> bool:
    """점검 결과를 출력하고, WARN이 하나도 없으면 True."""
    results = check_files() + check_db()
    print('\n[verify_outputs] 결과 자동 점검')
    for level, msg in results:
        print(f'  [{level:<4}] {msg}')
    warns = sum(1 for level, _ in results if level == 'WARN')
    if warns:
        print(f'[verify_outputs] 경고 {warns}건 — 위 안내를 확인하세요.')
    else:
        print('[verify_outputs] 이상 없음')
    return warns == 0


if __name__ == '__main__':
    sys.exit(0 if run() else 1)
