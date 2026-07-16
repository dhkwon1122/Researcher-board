"""
과제별 전문성 분석 모듈 (사내 Confluence + 사내 LLM)

data/processed/project_confl_address.csv의 각 과제에 대해:
  1) project_summary.py로 컨플루언스 페이지를 요약(핵심 기술/최종 산출물/
     기술적 난제/국영문 키워드) — process_project_search.py와 공유하는 캐시
     (project_summary_cache.json)를 사용해 중복 조회를 피한다.
  2) process_mit10.py의 "R&D Project Specialist Agent" 페르소나를 그대로
     재사용해(mit_markdown.analyze_expertise), MIT10 기술 대신 이 과제에 대해
     동일한 형식(연구개발 프로젝트 개요 / R&D 필수 전문성 및 직무 딥다이브 매핑 /
     인력 수급 매트릭스 / HR 제언)의 전문성 분석을 생성한다.

Source:
  data/processed/project_confl_address.csv (dep_name, project_name, confl_address)

Output:
  data/processed/project_expertise_analysis.json

사용법:
  python pipeline/process_project_expertise.py
"""

import json
import os
import sys

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE_DIR, 'data', 'processed')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mit_markdown as mmd  # noqa: E402
import project_summary  # noqa: E402


def _read_projects() -> pd.DataFrame:
    path = os.path.join(OUT_DIR, 'project_confl_address.csv')
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')


def _summary_description(summary: dict) -> str:
    """R&D Project Specialist Agent 프롬프트에 넣을 '연구 내용' 텍스트를
    컨플루언스 요약 결과로부터 구성."""
    keywords = ', '.join((summary.get('keywords_kr') or []) + (summary.get('keywords_en') or []))
    parts = [
        f"핵심 연구 대상 기술: {summary.get('core_tech') or '확인 불가'}",
        f"최종 산출물: {summary.get('deliverable') or '확인 불가'}",
        f"현재 직면한 기술적 장벽/난제: {summary.get('challenge') or '확인 불가'}",
    ]
    if keywords:
        parts.append(f'관련 키워드: {keywords}')
    return '\n'.join(parts)


def process() -> bool:
    projects = _read_projects()
    if projects.empty:
        print('[process_project_expertise] project_confl_address.csv 없음 — 종료 '
              '(process_project_confl.py 먼저 실행)')
        return False

    summary_cache = project_summary.load_cache()
    results = []
    print(f'[process_project_expertise] 과제 {len(projects)}건 전문성 분석 중...')
    for _, proj in projects.iterrows():
        dep_name = proj['dep_name']
        project_name = proj['project_name']
        confl_address = proj['confl_address']

        summary = project_summary.get_project_summary(project_name, confl_address, summary_cache)
        if summary is None:
            print(f'  [{project_name}] 건너뜀')
            continue

        description = _summary_description(summary)
        expertise_analysis = mmd.analyze_expertise(project_name, description)
        if not expertise_analysis:
            print(f'  [{project_name}] 전문성 분석 실패 — 건너뜀')
            continue

        results.append({
            'dep_name': dep_name,
            'project_name': project_name,
            'core_tech': summary.get('core_tech', ''),
            'deliverable': summary.get('deliverable', ''),
            'challenge': summary.get('challenge', ''),
            'keywords_kr': summary.get('keywords_kr') or [],
            'keywords_en': summary.get('keywords_en') or [],
            'expertise_analysis': expertise_analysis,
        })
        print(f'  [{project_name}] 분석 완료')

    project_summary.save_cache(summary_cache)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'project_expertise_analysis.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f'[OK]   project_expertise_analysis.json 저장 ({len(results)}건)')
    return True


if __name__ == '__main__':
    process()
