"""
과제 이력 기반 전문성 분석 (사내 LLM)

Source:
  data/processed/tasks.csv              — 연구원별 과제 참여 이력 (task_name, start_date, end_date)
  data/processed/tasks_information.csv  — 과제 상세 정보 (task_name 기준 조인)
Output:
  data/processed/task_expertise.csv     — researcher_id, matched_task_count,
                                           total_task_count, expertise_json

expertise_json 은 다음 형식의 JSON을 문자열로 담는다:
  {
    "expertise": [{"keyword": "...", "evidence": "..."}],
    "caution_flags": [{"from_task": "...", "to_task": "...", "reason": "..."}]
  }

사용법:
  python pipeline/process_task_expertise.py           # LLM 호출 없이 task_name 매칭 현황만 출력
  python pipeline/process_task_expertise.py --llm     # LLM 호출 포함, 실제 분석 생성/저장
"""

import csv
import json
import os
import sys

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR  = os.path.join(BASE_DIR, 'data', 'processed')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_client import call_llm, extract_json

SYSTEM_PROMPT = (
    '당신은 구루 교수급의 전문성을 지닌 R&D 연구소 CTO입니다. '
    '요청한 JSON 형식만 출력하고, 그 외 텍스트는 출력하지 마세요.'
)

_MAX_KEYWORDS = 8
_TASK_INFO_COLS = [
    'task_collabo', 'task_goal', 'task_value', 'task_howtoget',
    'task_expectissue', 'task_Activityplan', 'task_futureusage',
]


def _build_prompt(name: str, joined_tasks: list[dict]) -> str:
    lines = []
    for t in joined_tasks:
        lines.append(
            f"- 과제명: {t.get('task_name', '')} "
            f"(참여기간: {t.get('start_date', '')} ~ {t.get('end_date', '')})\n"
            f"  관계사: {t.get('task_collabo', '')}\n"
            f"  수행목적: {t.get('task_goal', '')}\n"
            f"  가치: {t.get('task_value', '')}\n"
            f"  확보전략: {t.get('task_howtoget', '')}\n"
            f"  예상문제: {t.get('task_expectissue', '')}\n"
            f"  주요 활용 Activity 계획: {t.get('task_Activityplan', '')}\n"
            f"  향후활용계획: {t.get('task_futureusage', '')}"
        )
    tasks_block = '\n'.join(lines)

    return f"""아래는 연구원 {name}이(가) 시간순으로 참여한 과제 이력과 각 과제의 상세 정보입니다.

{tasks_block}

위 정보를 바탕으로 다음을 수행하세요.

1. 이 연구원이 어떤 전문성을 보유하고 있을 것으로 추론되는지, 핵심 키워드 중심으로
   개조식·압축적으로 표현하고 각 키워드마다 근거가 된 과제명을 명시하세요.
   키워드는 {_MAX_KEYWORDS}개 이내로 제한합니다.
2. 반드시 주어진 데이터에 근거해서만 추론하고, 근거가 부족하면 추측하지 말고
   "데이터 부족"이라고 명시하세요.
3. 과제에서 다음 과제로 넘어갈 때 기술적 유사성·연결성을 검토하고, 연결성이
   확연히 떨어지는 전환이 있으면 어떤 과제 간 전환인지와 그 이유를 압축적으로 표시하세요.
   연결성이 명확한 경우 억지로 만들어내지 마세요 (없으면 빈 배열).

다음 JSON 형식으로만 출력하세요:
{{
  "expertise": [
    {{"keyword": "핵심 전문성 키워드", "evidence": "근거가 된 과제명 (쉼표로 구분)"}}
  ],
  "caution_flags": [
    {{"from_task": "이전 과제명", "to_task": "다음 과제명", "reason": "연결성이 약한 이유 (압축적 키워드)"}}
  ]
}}
"""


def _load_joined_tasks(rid: str, tasks_df: pd.DataFrame, info_df: pd.DataFrame) -> list[dict]:
    rows = tasks_df[tasks_df['researcher_id'] == rid].copy()
    if rows.empty:
        return []
    rows = rows.sort_values('start_date')
    joined = rows.merge(info_df, on='task_name', how='inner')
    return joined.to_dict('records')


def process(use_llm: bool = False):
    tasks_path = os.path.join(OUT_DIR, 'tasks.csv')
    info_path = os.path.join(OUT_DIR, 'tasks_information.csv')
    if not os.path.exists(tasks_path):
        print('[process_task_expertise] tasks.csv 없음 — 건너뜀')
        return
    if not os.path.exists(info_path):
        print('[process_task_expertise] tasks_information.csv 없음 — 건너뜀')
        return

    tasks_df = pd.read_csv(tasks_path, encoding='utf-8-sig', dtype=str)
    tasks_df['researcher_id'] = tasks_df['researcher_id'].astype(str).str.zfill(8)
    info_df = pd.read_csv(info_path, encoding='utf-8-sig', dtype=str)
    for col in _TASK_INFO_COLS:
        if col not in info_df.columns:
            info_df[col] = ''

    res_path = os.path.join(OUT_DIR, 'researchers.csv')
    name_map = {}
    if os.path.exists(res_path):
        res_df = pd.read_csv(res_path, dtype=str)
        name_map = res_df.set_index('researcher_id')['name'].to_dict()

    # ── task_name 매칭 현황 리포트 ────────────────────────────────────────
    total = len(tasks_df)
    matched = tasks_df.merge(info_df[['task_name']], on='task_name', how='inner')
    rate = (len(matched) / total * 100) if total else 0.0
    print(f'[process_task_expertise] task_name 매칭: {len(matched)}/{total}행 ({rate:.1f}%)')

    if not use_llm:
        print('[process_task_expertise] --llm 옵션 없이 실행 — 매칭 현황만 출력하고 종료')
        return

    rids = tasks_df['researcher_id'].unique()
    results = []
    print(f'[process_task_expertise] 연구원별 전문성 분석 생성 중 ({len(rids)}명)...')
    for rid in rids:
        name = name_map.get(rid, rid)
        joined = _load_joined_tasks(rid, tasks_df, info_df)
        if not joined:
            print(f'    [{rid}] {name} 매칭된 과제 없음 — 건너뜀')
            continue

        prompt = _build_prompt(name, joined)
        raw = call_llm(prompt, SYSTEM_PROMPT)
        if not raw:
            print(f'    [{rid}] {name} LLM 호출 실패')
            continue
        try:
            parsed = json.loads(extract_json(raw))
        except json.JSONDecodeError:
            print(f'    [{rid}] {name} JSON 파싱 실패')
            continue

        total_for_rid = len(tasks_df[tasks_df['researcher_id'] == rid])
        results.append({
            'researcher_id':      rid,
            'matched_task_count': len(joined),
            'total_task_count':   total_for_rid,
            'expertise_json':     json.dumps(parsed, ensure_ascii=False),
        })
        print(f'    [{rid}] {name} 분석 완료 (매칭 {len(joined)}/{total_for_rid}건)')

    out_df = pd.DataFrame(results, columns=[
        'researcher_id', 'matched_task_count', 'total_task_count', 'expertise_json',
    ])
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'task_expertise.csv')
    out_df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
    print(f'[process_task_expertise] task_expertise.csv 저장 완료 ({len(out_df)}행)')


if __name__ == '__main__':
    process(use_llm='--llm' in sys.argv)
