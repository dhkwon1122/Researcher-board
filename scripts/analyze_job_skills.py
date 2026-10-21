"""
직무 스킬 분석(로컬 PowerShell 실행, 2026-10-21 1차).

준비: data/raw/스킬셋.xlsx (헤더 1행: 스킬명·부서·직무·스킬 정의·Level1~3·스킬구성요소)
실행(프로젝트 폴더에서):
  python scripts\\analyze_job_skills.py            # 분석 + 엑셀 리포트, 끝나면 요약 출력
  python scripts\\analyze_job_skills.py --open     # 끝나면 엑셀 바로 열기
  python scripts\\analyze_job_skills.py --no-embed # 사내 임베딩 서버 없이(문구 일치도만)
  python scripts\\analyze_job_skills.py --job 회로설계 --job 소재개발   # 특정 직무만(이름 일부)

흐름: 스킬셋.xlsx → data/raw_csv/job_skill_set.csv(원본 헤더, xlsx가 더 새로울 때만 변환)
      → data/processed/job_skill_set.csv(영문 헤더) → 분석 → data/analysis/job_skill_analysis_YYYYMMDD_HHMM.xlsx
임베딩: .env의 EMBED_BASE_URL / EMBED_API_KEY(사내 bge-m3)를 쓰고, 결과는 data/processed/embedding_cache.json에
캐시돼 다시 돌릴 때 빠르다. 접속이 안 되면 경고만 내고 문구 일치도로 계속한다.
분석 내용은 pipeline/job_skill_analysis.py, 엑셀 구성은 pipeline/job_skill_report.py 참고.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, 'pipeline'))
sys.path.insert(0, BASE_DIR)

ANALYSIS_DIR = os.path.join(BASE_DIR, 'data', 'analysis')


def _console_utf8():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors='replace')
        except (AttributeError, ValueError):
            pass


def _load_env():
    path = os.path.join(BASE_DIR, '.env')
    try:
        from dotenv import load_dotenv
        if os.path.exists(path):
            load_dotenv(path)
    except ImportError:
        pass


def _embed_fn(disabled: bool):
    if disabled:
        return None
    try:
        from researcher_fit import cached_embed
        return cached_embed
    except Exception as exc:  # noqa: BLE001
        print(f'  [WARN] 임베딩 모듈을 불러오지 못했습니다 — 문구 일치도만 사용 ({exc})')
        return None


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
    print(f' 유사도: {"의미 유사도(임베딩) + 문구 일치도" if res["mode"] == "sem" else "문구 일치도만(임베딩 미사용)"}\n{line}')
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
                print(f"   - [{r['직무']}] {r['스킬명']}  유사도 {r['종합 유사도']:.2f}  · {r['가장 다른 부서 쌍']}")
    std = res['standardize']
    if not std.empty:
        print(f'\n 표준화 후보(이름은 다른데 비슷한 스킬) {len(std)}쌍 — 상위 5')
        for r in std.head(5).to_dict('records'):
            print(f"   - {r['스킬명 A']}  ↔  {r['스킬명 B']}  (내용 {r['내용 유사도']:.2f}, {r['근거']})")
    print(f"\n 레벨 점검 {len(res['level'])}행 · 데이터 점검 {len(res['data'])}건 · 직무 간 공유 스킬 {len(res['cross_job'])}개")
    print(f'{line}\n 엑셀 리포트: {path}\n 소요 {elapsed:.1f}초\n{line}')


def main(argv=None) -> int:
    _console_utf8()
    ap = argparse.ArgumentParser(description='직무 스킬 분석(스킬셋.xlsx → 엑셀 리포트)')
    ap.add_argument('--no-embed', action='store_true', help='사내 임베딩 서버 없이 문구 일치도만 사용')
    ap.add_argument('--force-convert', action='store_true', help='스킬셋.xlsx를 항상 다시 변환')
    ap.add_argument('--job', action='append', default=[], help='이 이름이 들어간 직무만(여러 번 지정 가능)')
    ap.add_argument('--out', default=ANALYSIS_DIR, help='리포트 저장 폴더(기본 data/analysis)')
    ap.add_argument('--open', action='store_true', help='끝나면 엑셀 파일 열기(Windows)')
    args = ap.parse_args(argv)

    _load_env()
    import process_job_skill_set as prep
    from job_skill_analysis import analyze
    from job_skill_report import build_workbook

    t0 = time.time()
    print('[1/3] 스킬셋 읽기·정규화')
    try:
        df, info = prep.run(force_convert=args.force_convert)
    except (FileNotFoundError, ValueError) as exc:
        print(f'  [ERROR] {exc}')
        return 1
    print(f"  {'xlsx 변환 → ' if info['converted'] else ''}{info['out_path']} ({info['rows']}행, 병합 셀 보정 {info['filled_cells']}칸)")
    if args.job:
        df = df[df['job_function'].map(lambda j: any(k in j for k in args.job))].reset_index(drop=True)
        print(f"  직무 필터 {args.job} → {len(df)}행")
        if df.empty:
            print('  [ERROR] 해당 직무가 없습니다.')
            return 1

    print('[2/3] 분석')
    res = analyze(df, embed_fn=_embed_fn(args.no_embed))

    print('[3/3] 엑셀 리포트 작성')
    info['run_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    path = build_workbook(df, res, info, _out_path(args.out))
    print_summary(df, res, path, time.time() - t0)
    if args.open and hasattr(os, 'startfile'):
        os.startfile(path)  # noqa: S606 — 로컬에서 사용자가 요청한 결과 파일 열기
    return 0


if __name__ == '__main__':
    sys.exit(main())
