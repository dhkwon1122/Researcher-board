"""
직무 스킬 분석(2026-10-21) — 웹 화면 없이 명령 한 줄로 실행해 엑셀 리포트를 만든다.
Windows 로컬(PowerShell)과 리눅스 서버 호스트(도커 밖) 모두에서 실행할 수 있다.

실행(프로젝트 폴더에서, Windows는 경로 구분자를 \\로):
  python scripts/analyze_job_skills.py                       # 분석 + 엑셀 리포트(기본 data/analysis)
  python scripts/analyze_job_skills.py --llm                 # + 사내 LLM 검토(AI 의견 열·시트)
  python scripts/analyze_job_skills.py --input ~/스킬셋.xlsx --out ~/skill_report   # 파일·출력 위치 직접 지정
  옵션: --job 이름(직무 필터, 여러 번) · --no-embed(임베딩 없이) · --llm-parts same,std,level,comp,dept
        · --llm-workers N(동시 호출, 기본 4) · --open(Windows: 끝나면 엑셀 열기) · --force-convert

입력: --input 파일 → data/raw/스킬셋.xlsx → data/raw_csv/job_skill_set.csv 순. DRM 엑셀은 Windows Excel에서만 열리므로
      서버에서는 DRM 해제본(다른 이름으로 저장)이나 로컬에서 변환한 raw_csv를 쓴다.
출력: <out>/job_skill_analysis_YYYYMMDD_HHMM.xlsx, <out>/job_skill_set.csv(정규화), <out>/.cache/(임베딩·LLM 캐시).
      앱이 쓰는 data/processed는 건드리지 않는다 — 서버 호스트에서 다른 계정으로 돌려도 컨테이너(uid 10001)
      소유 파일(예: embedding_cache.json)의 소유자가 바뀌어 앱이 깨지는 일이 없도록.
접속: .env의 EMBED_BASE_URL·EMBED_API_KEY(임베딩), LLM2_API_URL·LLM2_MODEL(LLM). 도커 안 주소(예: http://bge-embed:7138)가
      호스트에서 안 풀리면 localhost로 바꿔 쓴다(bge-embed 컨테이너는 127.0.0.1:7138로 열려 있음). 접속 대상은 NO_PROXY에 추가.
분석 내용: pipeline/job_skill_analysis.py · LLM 검토: pipeline/job_skill_llm.py · 엑셀: pipeline/job_skill_report.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
import threading
import time
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, 'pipeline'))
sys.path.insert(0, BASE_DIR)

ANALYSIS_DIR = os.path.join(BASE_DIR, 'data', 'analysis')
DOCKER_HOSTS = {'bge-embed', 'ollama', 'app', 'db', 'host.docker.internal'}


def _console_utf8():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors='replace')
        except (AttributeError, ValueError):
            pass


def _resolvable(host: str) -> bool:
    try:
        socket.getaddrinfo(host, None)
        return True
    except OSError:
        return False


def prepare_env(log=print) -> None:
    """.env 로드 → 도커 안에서만 통하는 주소를 localhost로 → 접속 대상을 NO_PROXY에 추가."""
    from services.db import load_env_file
    try:
        load_env_file()
    except OSError as exc:   # 서버에서 .env 읽기 권한이 없는 계정으로 실행한 경우
        log(f'  [WARN] .env를 읽지 못했습니다({exc}) — 임베딩·LLM 주소는 현재 환경변수만 사용합니다.')
    hosts = []
    for var in ('EMBED_BASE_URL', 'LLM2_API_URL'):
        url = os.environ.get(var, '').strip()
        if not url:
            continue
        parts = urlsplit(url)
        host = parts.hostname or ''
        if host in DOCKER_HOSTS and not _resolvable(host):
            netloc = parts.netloc.replace(host, 'localhost', 1)
            os.environ[var] = urlunsplit(parts._replace(netloc=netloc))
            log(f'  [INFO] {var}: {host}는 도커 안 주소라 localhost로 바꿔 씁니다 → {os.environ[var]}')
            host = 'localhost'
        hosts.append(host)
    if not os.environ.get('EMBED_BASE_URL'):
        hosts.append('localhost')
    for var in ('NO_PROXY', 'no_proxy'):
        cur = [h for h in os.environ.get(var, '').split(',') if h]
        add = [h for h in ['localhost', '127.0.0.1', *hosts] if h and h not in cur]
        if add:
            os.environ[var] = ','.join(cur + add)


def make_embed_fn(cache_path: str, disabled: bool, log=print):
    """services.llm.embed + 이 스크립트 전용 캐시(<out>/.cache) — 앱의 data/processed/embedding_cache.json은 쓰지 않는다."""
    if disabled:
        return None
    try:
        from services.llm import embed
    except Exception as exc:  # noqa: BLE001
        log(f'  [WARN] 임베딩 모듈을 불러오지 못했습니다 — 문구 일치도만 사용 ({exc})')
        return None
    lock = threading.Lock()

    def embed_cached(texts):
        cache = {}
        if os.path.exists(cache_path):
            try:
                with open(cache_path, encoding='utf-8') as f:
                    cache = json.load(f)
            except (OSError, ValueError):
                cache = {}
        keys = [hashlib.sha1(t.encode('utf-8')).hexdigest() for t in texts]
        missing = [i for i, k in enumerate(keys) if k not in cache]
        if missing:
            log(f'  임베딩 {len(missing)}건 요청(캐시 {len(texts) - len(missing)}건 재사용)...')
            vecs = embed([texts[i] for i in missing])
            for i, v in zip(missing, vecs):
                cache[keys[i]] = [round(float(x), 6) for x in v]
            with lock:
                os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                tmp = f'{cache_path}.{os.getpid()}.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(cache, f)
                os.replace(tmp, cache_path)
        return [cache[k] for k in keys]
    return embed_cached


def _out_path(out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, f"job_skill_analysis_{datetime.now().strftime('%Y%m%d_%H%M')}")
    path, n = base + '.xlsx', 2
    while os.path.exists(path):
        path, n = f'{base}_{n}.xlsx', n + 1
    return path


def print_summary(df, res, path, elapsed):
    line = '─' * 72
    print(f'\n{line}\n 직무 스킬 분석 결과  ({len(df)}행 · 직무 {df["job_function"].nunique()} · '
          f'부서 {df["department"].nunique()} · 스킬 {df["skill_key"].nunique()})')
    print(f' 유사도: {"의미 유사도(임베딩) + 문구 일치도" if res["mode"] == "sem" else "문구 일치도만(임베딩 미사용)"}')
    st = res.get('llm_stats')
    if st:
        print(f" AI 검토: 호출 {st['calls']}건 · 캐시 {st['cached']}건 · 실패 {st['failed']}건")
    print(line)
    js = res['job_summary']
    if not js.empty:
        print(f' {"직무":<16}{"부서":>4}{"스킬":>6}{"공통":>6}{"일부":>6}{"고유":>6}{"스킬명일치":>10}{"내용일치":>9}{"내용다름":>9}')
        for r in js.to_dict('records'):
            jac = '-' if r['부서 간 스킬명 일치율'] is None else f"{r['부서 간 스킬명 일치율']:.0%}"
            soft = '-' if r['부서 간 내용 일치율'] is None else f"{r['부서 간 내용 일치율']:.0%}"
            print(f" {str(r['직무'])[:15]:<16}{r['부서 수']:>4}{r['스킬 수']:>6}{r['공통']:>6}{r['일부']:>6}{r['고유']:>6}"
                  f"{jac:>10}{soft:>9}{r['그중 내용 다름']:>9}")
    same = res['same_summary']
    if not same.empty:
        diff = same[same['판정'] == '내용 다름'].head(5)
        if len(diff):
            print(f'\n 같은 스킬인데 부서마다 내용이 많이 다른 스킬 (상위 {len(diff)})')
            for r in diff.to_dict('records'):
                ai = f"  [AI: {r['AI 차이 유형']}] {r['AI 차이 요약']}" if r.get('AI 차이 요약') else ''
                print(f"   - [{r['직무']}] {r['스킬명']}  유사도 {r['종합 유사도']:.2f}  · {r['가장 다른 부서 쌍']}{ai}")
    std = res['standardize']
    if not std.empty:
        print(f'\n 표준화 후보(이름은 다른데 비슷한 스킬) {len(std)}쌍 — 상위 5')
        for r in std.head(5).to_dict('records'):
            ai = f"  [AI: {r['AI 같은 스킬?']}{' → ' + r['AI 표준 스킬명'] if r.get('AI 표준 스킬명') else ''}]" \
                if r.get('AI 같은 스킬?') else ''
            print(f"   - {r['스킬명 A']}  ↔  {r['스킬명 B']}  (내용 {r['내용 유사도']:.2f}, {r['근거']}){ai}")
    lv_ai = res.get('level_ai')
    extra = ''
    if lv_ai is not None and not lv_ai.empty:
        extra = f" · AI 레벨 역전·모호 {int(lv_ai['AI 판정'].isin(['역전', '모호']).sum())}행"
    print(f"\n 레벨 점검 {len(res['level'])}행{extra} · 데이터 점검 {len(res['data'])}건 · 직무 간 공유 스킬 {len(res['cross_job'])}개")
    print(f'{line}\n 엑셀 리포트: {path}\n 소요 {elapsed:.1f}초\n{line}')


def main(argv=None) -> int:
    _console_utf8()
    ap = argparse.ArgumentParser(description='직무 스킬 분석(스킬셋 → 엑셀 리포트)')
    ap.add_argument('--input', help='스킬셋 파일(xlsx/csv). 생략하면 data/raw/스킬셋.xlsx → data/raw_csv/job_skill_set.csv')
    ap.add_argument('--out', default=ANALYSIS_DIR, help='출력 폴더(기본 data/analysis)')
    ap.add_argument('--job', action='append', default=[], help='이 이름이 들어간 직무만(여러 번 지정 가능)')
    ap.add_argument('--no-embed', action='store_true', help='사내 임베딩 서버 없이 문구 일치도만 사용')
    ap.add_argument('--llm', action='store_true', help='사내 LLM 검토 추가(AI 의견 열·시트)')
    ap.add_argument('--llm-parts', default='same,std,level,comp,dept',
                    help='LLM 검토 항목(쉼표): same 같은 스킬, std 표준화 후보, level 레벨, comp 구성요소, dept 부서 비교')
    ap.add_argument('--llm-workers', type=int, default=4, help='LLM 동시 호출 수(기본 4 — 운영 앱과 같은 서버를 같이 씀)')
    ap.add_argument('--force-convert', action='store_true', help='data/raw/스킬셋.xlsx를 항상 다시 읽기')
    ap.add_argument('--open', action='store_true', help='끝나면 엑셀 파일 열기(Windows)')
    args = ap.parse_args(argv)

    prepare_env()
    import process_job_skill_set as prep
    from job_skill_analysis import analyze
    from job_skill_report import build_workbook

    out_dir = os.path.abspath(os.path.expanduser(args.out))
    cache_dir = os.path.join(out_dir, '.cache')
    t0 = time.time()
    print('[1/3] 스킬셋 읽기·정규화')
    try:
        df, info = prep.run(os.path.expanduser(args.input) if args.input else None, out_dir, args.force_convert)
    except (FileNotFoundError, ValueError) as exc:
        print(f'  [ERROR] {exc}')
        return 1
    print(f"  {info['source']} → {info['out_path']} ({info['rows']}행, 병합 셀 보정 {info['filled_cells']}칸)")
    if args.job:
        df = df[df['job_function'].map(lambda j: any(k in j for k in args.job))].reset_index(drop=True)
        print(f"  직무 필터 {args.job} → {len(df)}행")
        if df.empty:
            print('  [ERROR] 해당 직무가 없습니다.')
            return 1

    print('[2/3] 분석')
    res = analyze(df, embed_fn=make_embed_fn(os.path.join(cache_dir, 'embedding_cache.json'), args.no_embed))
    if args.llm:
        import llm_client
        from job_skill_llm import PARTS, review
        parts = tuple(p.strip() for p in args.llm_parts.split(',') if p.strip() in PARTS)
        if not llm_client.is_configured():
            print('  [WARN] LLM2_API_URL이 설정되지 않아 AI 검토를 건너뜁니다(.env 확인).')
        elif parts:
            res['llm_parts'] = parts
            review(df, res, parts=parts, cache_path=os.path.join(cache_dir, 'llm_cache.json'),
                   workers=max(1, args.llm_workers))

    print('[3/3] 엑셀 리포트 작성')
    info['run_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    path = build_workbook(df, res, info, _out_path(out_dir))
    print_summary(df, res, path, time.time() - t0)
    if args.open and hasattr(os, 'startfile'):
        os.startfile(path)  # noqa: S606 — 로컬에서 사용자가 요청한 결과 파일 열기
    return 0


if __name__ == '__main__':
    sys.exit(main())
