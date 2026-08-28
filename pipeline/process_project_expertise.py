"""
과제별 문서 상세 분석 모듈 (사내 Confluence + 사내 LLM)

data/processed/project_confl_address.csv의 각 과제에 대해:
  1) project_summary.py의 "R&D 과제 문서 분석 전문가"로 컨플루언스 페이지를
     상세 분석한다 — 핵심 기술/최종 산출물/기술적 난제/연구 배경/추진 일정/
     기대효과/국영문 키워드, 그리고 문서에 언급된 인력과 그 담당 업무
     (personnel)까지 함께 추출한다.
  2) personnel의 각 사람 이름을, 그 과제(project_name)에 현재 배정된
     연구원(researchers.csv의 org_code == project_name) 중에서 이름이 같은
     사람을 찾아 researcher_id로 매핑한다(_resolve_personnel). 동명이인이면
     문서에 적힌 "이름(NN)" 표기의 NN과 researcher_id 앞 2자리를 비교해
     판별한다. 후보가 없거나 판별이 안 되면 매칭하지 않고 원문 이름만
     남긴다(추측해서 잘못 배정하지 않기 위해).
  3) 콘솔형 리포트(rd_specialist_markdown.console_page, 외부 CDN 없이
     독립적인 정적 페이지)를 그때그때 만든다 — 앱 화면에서는 이 리포트를
     읽지 않고, 앱 밖으로 공유해야 할 때만(--email) 메일로 보낸다. 서버
     파일시스템에 완성된 사본을 남기지 않기 위해 data/processed/에 "현재본"
     .html 파일로는 저장하지 않는다(실행 이력 아카이브 스냅샷은 계속 남김).

※ 예전에는 이 단계 뒤에 "R&D Project Specialist Agent"가 과제별 필요 직무를
  딥다이브 매핑하고, 그 결과를 process_project_researcher_fit.py(과제↔연구원
  매칭)가 읽어 갔다. 그 기능은 완전히 제거됐다 — 이 스크립트의 목적이
  "과제에 필요한 직무를 정의"하는 것에서 "과제 문서 자체를 최대한 상세히
  분석하고, 문서에 실제로 언급된 인력의 담당 업무를 기록"하는 것으로
  바뀌었다(data/processed/CLAUDE.md 참고).

Source:
  data/processed/project_confl_address.csv (dep_name, project_name, confl_address)
  data/processed/researchers.csv           (personnel 이름 → researcher_id 매핑, org_code 기준)

Output:
  data/processed/project_expertise_analysis.json
  data/processed/project_personnel.csv (researcher_id/name/name_suffix/project_name/
    dep_name/role_description — process_researcher_expertise.py가 신규 근거로 읽음)
  (HTML 리포트는 파일로 저장하지 않음 — 아래 --email 참고)

사용법:
  python pipeline/process_project_expertise.py

_SUMMARY_SYSTEM_PROMPT(project_summary.py)가 바뀌어 이미 쌓인 요약 캐시
(project_summary_cache.json)에 새 항목이 비어 있을 때, 캐시를 무시하고
전체 과제를 다시 요약하려면:
  python pipeline/process_project_expertise.py --refresh
(원문 캐시 project_page_cache.json은 그대로 재사용한다 — Confluence/PDF를
다시 조회하지 않는다.)

이 리포트를 앱 밖(다른 부서 등)으로 공유해야 할 때는, 이미 저장된 분석
결과(재분석 없음)로 리포트를 다시 만들어 메일로만 보낸다(파일로 남기지
않음). .env에 MAIL_* 설정이 필요하다(.env.example 참고):
  python pipeline/process_project_expertise.py --email=a@x.com,b@y.com
"""

import csv
import html
import json
import os
import sys
from datetime import datetime

import pandas as pd

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT_DIR  # noqa: E402
import rd_specialist_markdown as mmd  # noqa: E402
import project_summary  # noqa: E402
import researcher_fit as fit  # noqa: E402
import result_archive  # noqa: E402
from mailer import MailError, send_html_email  # noqa: E402
from services.data_store import read_project_expertise_analysis  # noqa: E402


def _read_projects() -> pd.DataFrame:
    path = os.path.join(OUT_DIR, 'project_confl_address.csv')
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')


def _resolve_personnel(project_name: str, personnel: list, researchers_df: pd.DataFrame) -> list:
    """문서에서 뽑은 인력(이름 + name_suffix)을, org_code == project_name인
    연구원 중 이름이 같은 사람과 대조해 researcher_id를 매핑한다. 후보가
    없거나(0명) 동명이인을 판별할 수 없으면(name_suffix 없음/일치 후보 0·2명
    이상) researcher_id를 빈 값으로 남기고 원문 이름은 그대로 보존한다.

    project_name(project_confl_address.csv, "[탐색] 가나다라마바사"처럼 대괄호
    태그+띄어쓰기가 있을 수 있음)과 org_code(researchers.csv, "가나다라마바사"처럼
    태그/공백 없음)는 표기 형식이 달라 fit.normalize_org_code()로 정규화한
    뒤 비교한다."""
    if researchers_df.empty:
        candidates_df = pd.DataFrame()
    else:
        target = fit.normalize_org_code(project_name)
        candidates_df = researchers_df[
            researchers_df['org_code'].astype(str).apply(fit.normalize_org_code) == target
        ]

    resolved = []
    for p in personnel or []:
        name = str(p.get('name') or '').strip()
        if not name:
            continue
        suffix = str(p.get('name_suffix') or '').strip()
        role_description = str(p.get('role_description') or '').strip()

        researcher_id = ''
        if not candidates_df.empty:
            name_matches = candidates_df[candidates_df['name'].astype(str).str.strip() == name]
            if len(name_matches) == 1:
                researcher_id = name_matches.iloc[0]['researcher_id']
            elif len(name_matches) > 1 and suffix:
                prefix_matches = name_matches[name_matches['researcher_id'].astype(str).str[:2] == suffix]
                if len(prefix_matches) == 1:
                    researcher_id = prefix_matches.iloc[0]['researcher_id']
            # 후보 0명이거나 동명이인을 suffix로도 못 가르면 researcher_id는 빈 값 그대로 둔다.

        resolved.append({
            'name': name, 'name_suffix': suffix,
            'researcher_id': researcher_id, 'role_description': role_description,
        })
    return resolved


def _write_personnel_csv(rows: list):
    """project_personnel.csv 저장 — process_researcher_expertise.py가 이 파일을
    researcher_id 기준으로 조인해 새 근거([과제 내 담당 업무])로 사용한다."""
    out_path = os.path.join(OUT_DIR, 'project_personnel.csv')
    columns = ['researcher_id', 'name', 'name_suffix', 'project_name', 'dep_name', 'role_description']
    df = pd.DataFrame(rows, columns=columns)
    df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
    print(f'[OK]   project_personnel.csv 저장 ({len(df)}행, '
          f'{sum(1 for r in rows if r["researcher_id"])}건 매칭)')


def build_html(items: list, total_projects: int, include_links: bool = True) -> str:
    """과제(project_confl_address.csv의 '소속' → dep_name)를 '플랫폼/팀'으로
    라벨링해 좌측 사이드바와 본문을 그룹핑해 보여준다. include_links=False면
    (앱 밖 메일 본문 — 사용자 확인) 인력 목록의 전문성 MAP 링크를 뺀다."""
    anchor_of = {it['project_name']: f'p-{i}' for i, it in enumerate(items, start=1)}

    nav_groups = []
    for dept, dept_items in mmd.group_ordered(items, lambda it: it.get('dep_name', '')):
        entries = ''.join(
            f'<a class="nav-item" href="#{anchor_of[it["project_name"]]}">'
            f'<span>{html.escape(it["project_name"])}</span>'
            f'<span class="n-count">{len(it.get("personnel") or [])}</span></a>'
            for it in dept_items
        )
        nav_groups.append(f'<div class="nav-group"><div class="nav-group-label">{html.escape(dept)}</div>{entries}</div>')

    all_personnel = [p for it in items for p in (it.get('personnel') or [])]
    matched_count = sum(1 for p in all_personnel if p.get('researcher_id'))
    stats = mmd.stat_row_html([
        mmd.coverage_stat(len(items), total_projects, '분석 완료 / 분석 대상 과제'),
        (len(all_personnel), '문서에서 발견된 인력 수'),
        (matched_count, '연구원과 매칭된 인력 수'),
        mmd.generated_at_stat(datetime.now().strftime('%Y-%m-%d %H:%M')),
    ])

    sections = []
    for dept, dept_items in mmd.group_ordered(items, lambda it: it.get('dep_name', '')):
        sections.append(f'<div class="dept-heading">{html.escape(dept)}</div>')
        for it in dept_items:
            sections.append(mmd.project_card_html(it, anchor_of[it['project_name']], include_links))

    sidebar = (
        '<h1>과제 전문성 콘솔</h1>'
        '<p class="tagline">컨플루언스 문서 상세 분석 + 문서 내 인력·담당 업무 매칭</p>'
        f'{"".join(nav_groups)}'
    )
    return mmd.console_page('과제 전문성 분석', sidebar, stats + ''.join(sections))


def process(force: bool = False) -> bool:
    """force=True(--refresh)면 project_summary_cache.json에 이미 값이 있는
    과제도 무시하고 전체를 다시 요약한다(원문 캐시는 재사용) — 요약 프롬프트가
    바뀌어 예전 캐시에 새 필드가 비어 있을 때 쓴다."""
    projects = _read_projects()
    if projects.empty:
        print('[process_project_expertise] project_confl_address.csv 없음 — 종료 '
              '(process_project_confl.py 먼저 실행)')
        return False

    researchers_df = fit.read_researchers(OUT_DIR)

    page_cache = project_summary.load_page_cache()
    summary_cache = project_summary.load_cache()
    label = '전체 재분석(--refresh)' if force else '분석'
    print(f'[process_project_expertise] 과제 {len(projects)}건 문서 {label} 중...')

    results = []
    personnel_rows = []
    completed = 0
    total = len(projects)
    for _, proj in projects.iterrows():
        dep_name = proj['dep_name']
        project_name = proj['project_name']
        confl_address = proj['confl_address']

        summary = project_summary.get_project_summary(project_name, confl_address, page_cache, summary_cache,
                                                        force=force)
        completed += 1
        if summary is None:
            print(f'  [{project_name}] 건너뜀')
            if completed % 5 == 0 or completed == total:
                print(f'    (진행: {completed}/{total})')
            continue

        matched_personnel = _resolve_personnel(project_name, summary.get('personnel') or [], researchers_df)
        for p in matched_personnel:
            personnel_rows.append({
                'researcher_id': p['researcher_id'], 'name': p['name'], 'name_suffix': p['name_suffix'],
                'project_name': project_name, 'dep_name': dep_name, 'role_description': p['role_description'],
            })

        results.append({
            'dep_name': dep_name,
            'project_name': project_name,
            'core_tech': summary.get('core_tech', ''),
            'deliverable': summary.get('deliverable', ''),
            'challenge': summary.get('challenge', ''),
            'background': summary.get('background', ''),
            'milestones': summary.get('milestones') or [],
            'expected_impact': summary.get('expected_impact', ''),
            'keywords_kr': summary.get('keywords_kr') or [],
            'keywords_en': summary.get('keywords_en') or [],
            'personnel': matched_personnel,
        })
        print(f'  [{project_name}] 분석 완료 (인력 {len(matched_personnel)}명 발견)')
        if completed % 5 == 0 or completed == total:
            print(f'    (진행: {completed}/{total})')

    project_summary.save_page_cache(page_cache)
    project_summary.save_cache(summary_cache)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'project_expertise_analysis.json')
    json_text = json.dumps(results, ensure_ascii=False, indent=2)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(json_text)
    print(f'[OK]   project_expertise_analysis.json 저장 ({len(results)}건)')
    result_archive.archive_copy('01. 과제분석', '과제 전문성 분석', 'json', json_text)

    _write_personnel_csv(personnel_rows)

    # 화면은 이 HTML을 파일로 읽지 않는다(앱 밖 공유가 필요하면 --email로
    # 그때그때 메일 발송). 다만 실행 이력 아카이브(data/processed/result/,
    # 권한은 scripts/secure_data_permissions.sh로 잠금)에는 계속 스냅샷을 남긴다.
    html_out = build_html(results, len(projects))
    result_archive.archive_copy('01. 과제분석', '과제 전문성 분석', 'html', html_out)
    return True


def email_report(recipients: list[str]) -> bool:
    """이미 저장된 project_expertise_analysis(DB 우선/JSON 폴백)로 리포트를
    다시 만들어 메일로만 보낸다(Confluence/LLM 재분석 없음, 파일로 남기지
    않음) — 앱 밖으로 공유해야 할 때
    'python pipeline/process_project_expertise.py --email=a@x.com,b@y.com'로 실행하거나
    관리자 화면(/admin)의 "리포트 메일 발송" 카드에서 실행한다.

    분석 데이터가 아직 없으면 False를 반환한다(호출부가 "먼저 파이프라인을
    실행하세요" 안내로 구분해 처리하도록). 메일 발송 자체가 실패하면
    MailError를 그대로 전파한다 — pages/admin.py는 이걸 잡아 실패 사유를
    화면에 보여주고, CLI(__main__)는 잡아서 한 줄로 출력한다."""
    results = read_project_expertise_analysis()
    if not results:
        print('[process_project_expertise] project_expertise_analysis 데이터 없음 — 종료 '
              '(먼저 python pipeline/process_project_expertise.py 실행)')
        return False

    total_projects = len(_read_projects()) or len(results)
    # include_links=False — 인력 목록의 "전문성 MAP" 링크는 target="_top"
    # 상대경로라 앱 밖 메일 본문에서는 깨진다(사용자 확인, 개별 연구원 메일의
    # 프로필/메일 링크와 동일한 문제).
    html_out = build_html(results, total_projects, include_links=False)
    send_html_email(recipients, '과제 전문성 분석 리포트', html_out)
    print(f'[OK]   과제 전문성 분석 리포트 메일 발송 ({len(recipients)}명)')
    return True


if __name__ == '__main__':
    _email_arg = next((a for a in sys.argv if a.startswith('--email=')), None)
    if _email_arg:
        try:
            email_report(_email_arg.split('=', 1)[1].split(','))
        except MailError as exc:
            print(f'[process_project_expertise] 메일 발송 실패: {exc}')
    else:
        process(force='--refresh' in sys.argv)
