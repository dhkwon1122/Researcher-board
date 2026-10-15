"""JOB Market 추천 기준 백테스트(읽기 전용, 2026-10-15).

과제참여이력(tasks.csv)에서 "한 과제를 마치고 바로(−31~+92일) 다른 과제를 시작한" 실제 이동 사례를 뽑아,
그 사람을 이동 시점 기준으로 다시 추천했을 때 실제로 옮긴 과제를 몇 위에 올리는지 기준별로 비교한다.

비교 기준(LLM 최종 판정 전, 상위 8개를 LLM에 넘기는 정렬 단계):
  A        과제 분석(컨플 + 과제정보) 유사도
  B        후보 과제원 중 가장 비슷한 1명(본인 제외)
  A·B      max(A, B) — 기존 기본 점수
  현재방식 A·B + 갭 충족·주력 시기·요구 충족·관련 실적 가산(과제 참여 이력 제외)
  +이력 w  현재방식 + w × 과제 참여 이력 점수 H(이동 시점 이전 데이터만 사용)

지표: 적중@1/@3/@8(실제 이동 과제가 상위 N개 안), MRR(1/순위 평균), 평균 순위.

주의(해석):
  - 전문성 프로필·과제 분석·과제원은 "지금" 데이터라 이동 이후 경험이 섞여 있다 → A·B·현재방식은 실제보다
    유리하게(낙관적으로) 나온다. 과제 참여 이력(H)은 이동 시점 이전 데이터만 쓴다(보수적).
    그래도 +이력이 좋아지면 실제 효과로 볼 수 있다.
  - 실제 이동이 늘 최선의 이동은 아니다 — "현실과 얼마나 맞는가"를 보는 지표.
  - 후보는 현재 과제별컨플의 과제만. 그 밖의 과제로 간 이동은 평가에서 빠진다.

임베딩 API가 필요하다(서버에서 실행). LLM은 호출하지 않는다.
사용법: python scripts/backtest_job_market.py [--years 3] [--limit 300] [--fast] [--csv 경로]
  --fast : 현재방식 가산(갭·요구 충족 등) 계산 생략(A·B·이력만 비교, 빠름)
"""
import argparse
import csv
import os
import sys
from datetime import timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'pipeline'))

WEIGHTS = (0.05, 0.1, 0.2, 0.3, 0.5)
TOPS = (1, 3, 8)


def extract_moves(history, key_to_projects: dict, profiles: dict, years: int) -> list:
    since = history.today - timedelta(days=365 * years)
    seen, moves = set(), []
    for f, t, rid, when in sorted(history.transitions, key=lambda x: x[3]):
        if when < since or t not in key_to_projects or f == t or rid not in profiles or (rid, t) in seen:
            continue
        seen.add((rid, t))
        moves.append({'rid': rid, 'from': f, 'to': t, 'when': when})
    return moves


def rank_of(order: list, targets: set):
    for i, name in enumerate(order, start=1):
        if name in targets:
            return i
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--years', type=int, default=3)
    ap.add_argument('--limit', type=int, default=300)
    ap.add_argument('--fast', action='store_true')
    ap.add_argument('--csv', default='')
    args = ap.parse_args()

    import researcher_fit as fit
    from services import data_store
    from services import job_market as jm
    from services import job_market_history as jmh
    from services import job_market_insights as jmi

    profiles = data_store.read_expertise_profiles_std()
    history = jmh.load()
    print('[1] 후보 과제 풀 준비(임베딩)...')
    pool = jm._build_candidate_pool(set(), profiles)
    key_of_project = {name: history.key_for_project(name, c.get('member_key', ''), c.get('member_ids') or [])
                      for name, c in pool.items()}
    key_to_projects: dict = {}
    for name, k in key_of_project.items():
        if k:
            key_to_projects.setdefault(k, set()).add(name)
    print(f'    후보 과제 {len(pool)}개 중 과제참여이력과 연결된 과제 {sum(1 for k in key_of_project.values() if k)}개')

    moves = extract_moves(history, key_to_projects, profiles, args.years)
    print(f'[2] 최근 {args.years}년 실제 이동 사례 {len(moves)}건' + (f' → 최근 {args.limit}건 평가' if len(moves) > args.limit else ''))
    moves = moves[-args.limit:]
    if not moves:
        print('    평가할 이동 사례가 없습니다(과제참여이력의 과제명이 과제별컨플 과제와 연결되는지 확인).')
        return

    ctx = jmi.Context(profiles)
    ctx._history = False          # 이력 점수는 아래에서 시점별로 직접 계산(과제원도 그 시점 기준)
    methods = ['A', 'B', 'A·B'] + ([] if args.fast else ['현재방식']) + [f'+이력 {w}' for w in WEIGHTS]
    ranks = {m: [] for m in methods}
    details, skipped = [], 0
    for i, mv in enumerate(moves, 1):
        rid, as_of = mv['rid'], mv['when']
        before = as_of - timedelta(days=1)
        excluded_keys = history.current_keys(rid, before) | {mv['from']}
        view = {}
        for name, c in pool.items():
            if key_of_project.get(name) in excluded_keys:
                continue
            keep = [(e, t) for (e, t), mid in zip(c['b_members'], c.get('b_member_ids') or []) if mid != rid]
            if c['a_embedding'] is None and not keep:
                continue
            view[name] = {**c, 'b_members': keep,
                          'member_ids': [m for m in c.get('member_ids') or [] if m != rid]}
        targets = key_to_projects.get(mv['to'], set()) & set(view)
        if not targets:
            skipped += 1
            continue
        emb = fit.cached_embed([fit.researcher_profile_text(profiles[rid])])[0]
        scored = jm._score_candidates(emb, view)
        if not args.fast:
            scored = jmi.enrich_candidates(ctx, rid, scored, {n: v['member_ids'] for n, v in view.items()})
        for c in scored:
            k = key_of_project.get(c['project_name'])
            members = history.members_at(k, before) if k else set()
            h = history.signal(rid, c['project_name'], c.get('member_key', ''), members, as_of=as_of,
                               from_keys={mv['from']}, key=k)
            c['_h'] = (h or {}).get('score', 0.0)
            c['_base'] = c.get('base_adjusted', c['combined']) if not args.fast else c['combined']

        def _order(key_fn):
            return [c['project_name'] for c in sorted(scored, key=key_fn, reverse=True)]
        orders = {'A': _order(lambda c: c['score_a'] if c['score_a'] is not None else -9),
                  'B': _order(lambda c: c['score_b'] if c['score_b'] is not None else -9),
                  'A·B': _order(lambda c: c['combined'])}
        if not args.fast:
            orders['현재방식'] = _order(lambda c: c['_base'])
        for w in WEIGHTS:
            orders[f'+이력 {w}'] = _order(lambda c, w=w: c['_base'] + w * c['_h'])
        row = {'researcher_id': rid, 'from': mv['from'], 'to': mv['to'], 'when': as_of.isoformat(),
               'candidates': len(view)}
        for m in methods:
            r = rank_of(orders[m], targets)
            ranks[m].append(r)
            row[m] = r
        details.append(row)
        if i % 50 == 0:
            print(f'    {i}/{len(moves)} 처리')

    n = len(details)
    print(f'\n[3] 결과 — 평가 {n}건 (후보 풀에서 이동 과제를 찾을 수 없어 제외 {skipped}건)')
    header = f"{'기준':<12}" + ''.join(f'{"적중@" + str(t):>9}' for t in TOPS) + f"{'MRR':>8}{'평균순위':>9}"
    print(header)
    summary = {}
    for m in methods:
        rs = [r for r in ranks[m] if r]
        hits = {t: sum(1 for r in rs if r <= t) / n for t in TOPS}
        mrr = sum(1 / r for r in rs) / n
        avg = sum(rs) / len(rs) if rs else 0
        summary[m] = (hits[3], mrr)
        print(f'{m:<12}' + ''.join(f'{hits[t] * 100:>8.1f}%' for t in TOPS) + f'{mrr:>8.3f}{avg:>9.1f}')
    best = max((m for m in methods if m.startswith('+이력')), key=lambda m: summary[m])
    base = '현재방식' if not args.fast else 'A·B'
    print(f'\n→ 과제 참여 이력 가중치 추천: {best.split()[-1]} (적중@3 {summary[best][0] * 100:.1f}%, '
          f'{base} {summary[base][0] * 100:.1f}%). 서버 환경변수 JM_HISTORY_WEIGHT로 설정(기본 0.1).')
    print('  ※ A·B·현재방식은 현재 프로필(이동 이후 경험 포함)을 써서 낙관적으로, 이력은 이동 이전 데이터만 써서 '
          '보수적으로 나옵니다.')
    if args.csv and details:
        with open(args.csv, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=list(details[0].keys()))
            w.writeheader()
            w.writerows(details)
        print(f'  상세(사례별 순위) 저장: {args.csv}')


if __name__ == '__main__':
    main()
