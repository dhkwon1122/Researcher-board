"""
1/2/3단계 부서명(전체 경로 텍스트)만으로 team_refer.csv가 필요로 하는
dep_id/upper_dep_id/team_layer를 자동으로 만들어내는 공용 모듈.

배경(2026-09-11 사용자와의 설계 논의): 지금까지 team_refer.csv는 dep_id/
upper_dep_id/team_layer를 사람이 직접 채워 넣어야 했다(팀참조시트.xlsx에
"부서ID"/"상위부서ID"/"조직 레벨" 컬럼이 실제로 있었음) — 매달 원본을 사람이
하나하나 보며 정리할 수 있는 "현재" 데이터는 가능했지만, 과거 인력현황
파일에서 team_refer를 추출할 때는 이 ID들을 알아낼 방법이 없었다. 이 모듈은
"1단계부서명/2단계부서명/3단계부서명"(그 조직의 전체 소속 경로) 텍스트만
있으면 dep_id/upper_dep_id/team_layer를 결정적으로 계산해, 사람이 ID를
직접 관리할 필요 자체를 없앤다 — "현재"(팀/리더 참조 그리드)와 "과거"(배치
추출)가 완전히 같은 함수를 공유한다.

핵심 설계 결정(사용자 확정):
  - dep_id는 트리를 만들기 위한 정보로만 쓰이고, 시간이 지나 이름이 바뀌어도
    "같은 조직"이라는 연속성을 이어갈 필요가 없다 — 그래서 매번 텍스트에서
    새로 계산해도 안전하다(값이 바뀌면 새 dep_id가 되는 것 자체가 문제가
    아님). 다만 "이번 목록에 없는 옛 dep_id"를 그대로 두면 `_latest_current_
    rows()`가 계속 "현재"로 취급해 유령 노드가 남으므로, 호출부(process_team_
    refer.py)가 이 함수의 결과와 기존 저장값을 비교해 사라진 dep_id를
    deleted='Y'로 마감 처리해야 한다(이 모듈의 책임 밖).
  - dep_code(형제 정렬 순서)는 사내에서 정한 규정이라 사람이 조정해야 한다
    — 이 함수는 입력에 dep_code가 없으면 "처음 등장한 순서"를 기본값으로
    채울 뿐, 이미 정해진 dep_code가 있으면 그 값을 그대로 존중한다.
  - work_type이 없으면(과거 데이터에서 알아낼 수 없음) 'R&D'로 기본
    분류한다(사용자 확정 — 분석 대상에서 조용히 빠지는 것보다 낫다는 판단,
    실제로는 이 값이 영향을 주는 유일한 곳이 "현재" 상태 기준의 보유
    전문성 분석 대상 필터라 영향이 제한적이다).

입력(intake) 형태 — "전체 경로 포함": 각 레코드(dict)는 자신의 소속
경로를 **자기 레벨까지 전부** 채운다(예: 3단계 소속이면 1/2/3단계 이름을
전부 채움, 1단계 소속만이면 1단계만 채움) — 옛 인력현황 파일이 직원 1명당
1행에 소속 전체 경로를 담던 방식과 동일하다. 이 함수가 그 경로들을 보고
1/2/3단계 각각에서 등장하는 고유한 조직을 전부 찾아내(예: 리프가 (A,B,C)면
(A,)/(A,B)/(A,B,C) 3개 조직이 존재한다는 뜻) 조직 단위별 1행으로 묶는다.

출력(저장 스키마) — "자기 레벨 이름만": 기존 pjt_part_name이 그랬던 것과
동일하게, 각 조직 노드는 자기 team_layer에 해당하는 컬럼(dep_1st_name/
dep_2nd_name/dep_3rd_name 중 하나)만 채우고 나머지는 비운다 — 조상 이름은
upper_dep_id를 따라가면 알 수 있으므로 중복 저장하지 않는다.
"""

import hashlib

FIELDS = (
    'org_name_wd', 'work_type', 'dep_1st_name', 'dep_2nd_name', 'dep_3rd_name',
    'dep_code', 'dep_id', 'upper_dep_id', 'team_layer',
    'researcher_id', 'name', 'assignment_name',
)

_LEVEL_FIELDS = ('dep_1st_name', 'dep_2nd_name', 'dep_3rd_name')
_DEFAULT_WORK_TYPE = 'R&D'


def _slug(path: tuple) -> str:
    """경로 튜플(예: ('반도체연구소','소재개발팀'))을 결정적인 dep_id로
    변환. 같은 텍스트는 항상 같은 dep_id가 되고(멱등적), 다른 실행/다른
    시점에서 돌려도 동일하다 — 연속성을 신경 쓰지 않아도 되는 이유가 바로
    이 결정성 때문이다(다시 계산해도 안 바뀐 조직은 같은 dep_id가 나옴)."""
    text = '|'.join(path)
    digest = hashlib.md5(text.encode('utf-8')).hexdigest()[:10]
    return f'AUTO-{digest}'


def _own_path(record: dict) -> tuple:
    """레코드에서 dep_1st_name/dep_2nd_name/dep_3rd_name을 순서대로 읽어,
    처음 빈 값을 만나는 지점까지만 잘라 경로 튜플을 만든다(중간에 빈 값이
    있으면 그 뒤는 무시 — 방어적 처리, 정상 입력이라면 발생하지 않음)."""
    path = []
    for field in _LEVEL_FIELDS:
        value = str(record.get(field) or '').strip()
        if not value:
            break
        path.append(value)
    return tuple(path)


def derive_hierarchy(records: list) -> list:
    """전체 경로가 채워진 레코드 목록 → team_refer.csv 저장 스키마(자기
    레벨 이름만 채운, 조직 단위별 1행)로 변환한다.

    각 레코드가 나타내는 최심 경로(own_path)뿐 아니라 그 모든 접두사
    (조상)도 조직 단위로 등록된다 — 예를 들어 어떤 직원의 경로가
    (A,B,C)라면 A(1단계 단독)/A>B(2단계)/A>B>C(3단계, 이 직원의 소속) 3개
    조직이 전부 존재하는 것으로 취급한다. org_name_wd/work_type/researcher_id/
    name/assignment_name 같은 "이 조직 자체의 속성" 값은, 그 조직이 어떤
    레코드의 own_path와 정확히 일치할 때만(=그 레코드가 실제로 그 레벨
    소속임을 뜻할 때만) 채워진다 — 단순히 조상으로만 등장한 조직에는
    붙지 않는다. 같은 조직에 대해 여러 레코드가 속성값을 줄 수 있는데,
    먼저 나온 비어있지 않은 값을 채택한다(첫 값 우선).

    빈 경로(own_path가 아예 없는 레코드)는 건너뛴다."""
    nodes: dict = {}   # path tuple -> node dict
    order: list = []   # 최초 등장 순서(dep_code 기본값용)

    def _ensure_node(path: tuple) -> dict:
        if path not in nodes:
            dep_id = _slug(path)
            upper_path = path[:-1]
            node = {f: '' for f in FIELDS}
            node['dep_id'] = dep_id
            node['upper_dep_id'] = _slug(upper_path) if upper_path else ''
            node['team_layer'] = str(len(path))
            node[_LEVEL_FIELDS[len(path) - 1]] = path[-1]
            nodes[path] = node
            order.append(path)
        return nodes[path]

    for record in records:
        own_path = _own_path(record)
        if not own_path:
            continue
        # own_path 자신과 모든 접두사(조상)를 조직 단위로 등록한다.
        for depth in range(1, len(own_path) + 1):
            _ensure_node(own_path[:depth])

        # 이 레코드가 실제로 own_path 레벨 소속임을 나타내는 속성값은
        # own_path 노드에만 채운다(조상 노드에는 채우지 않음).
        node = nodes[own_path]
        for field in ('org_name_wd', 'work_type', 'dep_code', 'researcher_id', 'name', 'assignment_name'):
            value = str(record.get(field) or '').strip()
            if value and not node[field]:
                node[field] = value

    result = []
    for i, path in enumerate(order):
        node = nodes[path]
        if not node['dep_code']:
            node['dep_code'] = f'{i:04d}'
        if not node['work_type']:
            node['work_type'] = _DEFAULT_WORK_TYPE
        result.append(node)
    return result


def backfill_full_path(rows: list) -> list:
    """derive_hierarchy()의 역방향 — 저장 스키마(own-level-only, 각 행이
    자기 team_layer 레벨 이름만 채움)를 받아, upper_dep_id 체인을 따라 올라가며
    조상 레벨 이름까지 전부 채운 "전체 경로 포함" 형태로 되돌린다.

    관리자 화면 그리드(services.team_refer_store)가 이 함수로 저장된 조직을
    다시 불러와 사람이 읽고 고칠 수 있는(1/2/3단계 이름이 전부 보이는) 행으로
    보여준다 — derive_hierarchy()가 그 결과를 다시 own-level-only로 압축하므로
    왕복해도 안전하다(멱등적: 같은 텍스트 경로는 항상 같은 dep_id로 재계산됨).
    dep_id/upper_dep_id/team_layer 등 각 행 자신의 값은 그대로 두고, 비어 있는
    조상 레벨 이름 필드만 채운다(자기 자신의 값을 덮어쓰지 않음)."""
    by_id = {r.get('dep_id'): r for r in rows if r.get('dep_id')}
    result = []
    for row in rows:
        full = dict(row)
        node = row
        seen: set = set()
        while node:
            try:
                layer = int(node.get('team_layer') or 0)
            except (TypeError, ValueError):
                layer = 0
            if 1 <= layer <= len(_LEVEL_FIELDS):
                field = _LEVEL_FIELDS[layer - 1]
                value = str(node.get(field) or '').strip()
                if value and not full.get(field):
                    full[field] = value
            upper = str(node.get('upper_dep_id') or '').strip()
            if not upper or upper in seen:
                break
            seen.add(upper)
            node = by_id.get(upper)
        result.append(full)
    return result
