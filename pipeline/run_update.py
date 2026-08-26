"""
주기적 데이터 업데이트 실행 스크립트 (업서트 전용, data/raw는 건드리지 않음)

사용법:
  python pipeline/run_update.py

data/updates/ 폴더에 최신 원본 파일(data/raw와 동일한 파일명)을 넣고 이 스크립트를
실행하면, 각 처리기가 그 파일을 읽어 만든 최신 데이터를 기존 data/processed/*.csv에
업서트한다 — 같은 자연키(예: researcher_id, 또는 이력형 테이블의 복합키. 자세한
키 목록은 pipeline/merge_utils.py의 TABLE_KEYS/GROUP_REPLACE_KEYS 참고)가 있으면
그 행을 새 값으로 교체하고, 이번 파일에 없는 기존 행은 삭제하지 않고 그대로 둔다.

data/updates/에 없는 파일(이번에 갱신하지 않는 테이블)은 그냥 건너뛴다 — 부분
업데이트만 하고 싶을 때(예: 이번엔 인력현황.xlsx만 새로 왔을 때) 그 파일 하나만
넣고 돌리면 된다.

data/raw/의 파일은 이 스크립트가 전혀 읽지도 쓰지도 않는다 — 최초 적재(전체
베이스라인)는 계속 data/raw/ + run_pipeline.py로 하고, 이후 주기적 갱신만
data/updates/ + run_update.py로 분리하는 구조다. (참고: process_*.py 자체가
이제 항상 업서트로 동작하므로, run_pipeline.py를 data/raw로 다시 돌려도 이번에
빠진 사람이 삭제되지는 않는다 — 다만 폴더를 분리해두면 "최초 baseline용 파일"과
"주기적 갱신용 파일"이 뒤섞이지 않아 관리가 더 명확하다.)

출력 위치: data/processed/ (기존 파일에 업서트되어 갱신됨)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import UPDATES_DIR  # noqa: E402
from source_files import find_matches, is_wildcard  # noqa: E402


def run():
    os.makedirs(UPDATES_DIR, exist_ok=True)
    files_present = set(os.listdir(UPDATES_DIR))
    if not files_present:
        print(f'[INFO] {UPDATES_DIR} 에 파일이 없습니다 — 갱신할 파일을 넣고 다시 실행하세요.')
        return

    ran = []

    def _has_match(pattern) -> bool:
        """pattern이 와일드카드면 UPDATES_DIR을 스캔, 아니면 정확한 파일명 존재 여부."""
        if is_wildcard(pattern):
            return bool(find_matches(UPDATES_DIR, pattern))
        return pattern in files_present

    def _maybe_run(pattern, label: str, process_fn):
        if not _has_match(pattern):
            return
        print(f'\n── {label} ({pattern}) ──')
        ok = process_fn(raw_dir=UPDATES_DIR)
        if ok:
            ran.append(label)

    from process_researchers import RESEARCHERS_PATTERNS, process as process_researchers
    _maybe_run(RESEARCHERS_PATTERNS, 'researchers', process_researchers)

    from process_tp_evaluation import TP_PATTERN, process as process_tp
    if _has_match(TP_PATTERN):
        print(f'\n── evaluations ({TP_PATTERN}) ──')
        ok, _ = process_tp(raw_dir=UPDATES_DIR)
        if ok:
            ran.append('evaluations')

    from process_patents import process as process_patents
    _maybe_run('특허 리스트.xlsx', 'patents', process_patents)

    from process_personnel_orders import ORDERS_PATTERN, process as process_personnel_orders
    _maybe_run(ORDERS_PATTERN, 'hr_orders', process_personnel_orders)

    from process_nurturing import process as process_nurturing
    _maybe_run('양성_인력_현황.xlsx', 'nurturing', process_nurturing)

    from process_task_information import process as process_task_information
    _maybe_run('과제정보.xlsx', 'tasks_information', process_task_information)

    from process_awards import AWARDS_PATTERN, process as process_awards
    _maybe_run(AWARDS_PATTERN, 'awards', process_awards)

    from process_education import EDUCATION_PATTERN, process as process_education
    _maybe_run(EDUCATION_PATTERN, 'education', process_education)

    from process_leadership import process as process_leadership
    _maybe_run('리더십진단.xlsx', 'leadership', process_leadership)

    from process_incentive import process as process_incentive
    _maybe_run('핵심이력.xlsx', 'incentive_selection', process_incentive)

    from process_core_technology import process as process_core_technology
    _maybe_run('핵심기술.xlsx', 'core_technology', process_core_technology)

    from process_tech_ownership import process as process_tech_ownership
    _maybe_run('보유기술.xlsx', 'tech_ownership', process_tech_ownership)

    from process_job_profile import JOB_PROFILE_PATTERN, process as process_job_profile
    _maybe_run(JOB_PROFILE_PATTERN, 'job_profile', process_job_profile)

    from process_publications import process as process_publications
    _maybe_run('개인별논문현황_2016_2026.xlsx', 'publications', process_publications)

    from process_tasks import process as process_tasks
    _maybe_run('개인별과제투입기간데이터_260114.xlsb', 'tasks', process_tasks)

    if ran:
        print(f'\n갱신 완료: {", ".join(ran)}')
        print('data/processed/ 를 확인하세요. (data/updates/의 파일은 그대로 남아있습니다 — 필요시 직접 정리하세요.)')
    else:
        print('\n[INFO] data/updates/의 파일명이 예상 파일명과 일치하지 않아 아무것도 갱신되지 않았습니다.')
        print(f'       현재 폴더 안 파일: {sorted(files_present)}')


if __name__ == '__main__':
    run()
