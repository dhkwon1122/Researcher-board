"""
data/processed/*.csv + LLM 파생 JSON 전체에 걸친 컬럼명 -> 한글 표시 라벨
매핑. 자연어 질문(services/nl_query.py, services/open_data_query.py) 결과
테이블 헤더를 사람이 읽기 편한 이름으로 보여주기 위한 용도 — 원본 CSV
컬럼명이 어느 파일에서 왔든(researchers.csv든 succession.csv든) 같은 개념은
항상 같은 한글 라벨로 통일해서 보여준다(연구원 인터뷰 결정: 소스별 원본
헤더 텍스트를 그대로 쓰지 않고, 의미 기준으로 통일된 라벨 사용).

매핑에 없는 컬럼은 원래 이름을 그대로 보여준다(폴백) — 새 파이프라인/컬럼이
추가될 때마다 여기를 갱신해야 하는 건 아니고, 자주 노출되는 컬럼부터
점진적으로 채워도 된다.
"""

import re

_EVAL_COLUMN_RE = re.compile(r'^(\d{4})_(salary_grade|first_half_grade|second_half_grade)$')
_EVAL_COLUMN_SUFFIX_LABEL = {
    'salary_grade': '연봉등급',
    'first_half_grade': '상반기업적',
    'second_half_grade': '하반기업적',
}

COLUMN_LABELS = {
    # 공통 식별자
    'researcher_id': '사번',
    'name': '성명',
    'knox_id': 'Knox ID',

    # 인사 기본정보 (researchers.csv)
    'gender': '성별',
    'department': '부서',
    'org_code': '과제',
    'position': 'CL',
    'hire_year': '입사연도',
    'hire_date': '입사일',
    'birth_year': '출생연도',
    'promotion_date': '승격기준일',
    'job_function': '직무',
    'job_type': '직종',
    'nationality': '국적',
    'photo_path': '사진',

    # 학력 (education.csv)
    'degree': '학위',
    'major': '전공',
    'school': '학교',
    'graduation_year': '졸업연도',

    # 평가 (evaluations.csv) — 실제 컬럼은 {연도}_salary_grade/
    # {연도}_first_half_grade/{연도}_second_half_grade처럼 연도가 붙는 동적
    # 컬럼이라 고정 매핑이 안 됨 — label_for()의 정규식 분기 참고.

    # 인센티브/핵심인재 선정 (incentive_selection.csv)
    'selected': '선정여부',
    'category': '구분',
    'note': '비고',

    # 양성이력 (nurturing.csv)
    'subcategory': '세부구분',
    'start_date': '시작일',
    'end_date': '종료일',
    'country': '국가',
    'city': '도시',
    'institution': '기관',
    'service_end_date': '의무복무 종료일',

    # 수상 (awards.csv)
    'award_date': '수상일',
    'award_type': '수상유형',
    'award_name': '수상명',
    'awarding_org': '수여기관',
    'description': '설명',

    # 논문 (publications.csv)
    'author_type': '저자유형',
    'is_corresponding': '교신저자여부',
    'title': '제목',
    'journal': '저널',
    'pub_type': '논문유형',
    'pub_date': '발표일',
    'pub_year': '발표연도',
    'author_rank': '저자순위',
    'total_authors': '총저자수',
    'author_info': '저자정보',
    'contribution': '기여도',
    'project_name': '과제명',
    'project_code': '과제코드',

    # 특허 (patents.csv)
    'application_id': '출원ID',
    'title_ko': '제목(국문)',
    'status': '상태',
    'share_ratio': '지분율',
    'is_lead_inventor': '대표발명자여부',
    'patent_grade': '특허등급',
    'patent_grade_a_sub': '특허등급(A 세부)',
    'application_no': '출원번호',
    'application_date': '출원일',
    'registration_no': '등록번호',
    'registration_date': '등록일',

    # 보유기술 (tech_ownership.csv) — 슬롯 1~5는 label_for()가 접미사로 처리
    'tech_1': '보유기술1', 'lv_1': '보유기술1 수준', 'portion_1': '보유기술1 비율',
    'tech_2': '보유기술2', 'lv_2': '보유기술2 수준', 'portion_2': '보유기술2 비율',
    'tech_3': '보유기술3', 'lv_3': '보유기술3 수준', 'portion_3': '보유기술3 비율',
    'tech_4': '보유기술4', 'lv_4': '보유기술4 수준', 'portion_4': '보유기술4 비율',
    'tech_5': '보유기술5', 'lv_5': '보유기술5 수준', 'portion_5': '보유기술5 비율',
    'E_support': 'E/R직군',

    # 핵심기술 (core_technology.csv)
    'tech_field': '기술분야',
    'tech_name': '기술명',
    'tech_grade': '기술등급',

    # 과제 수행이력 (tasks.csv)
    'task_name': '과제(수행)명',
    'task_code': '과제코드(내부)',
    'input_rate': '투입률',

    # 인사발령 (hr_orders.csv)
    'order_date': '발령일',
    'order_name': '발령명',
    'order_dep': '발령부서',
    'order_cl': '발령구분',
    'order_assignment': '발령배치',

    # 자격증 (certifications.csv)
    'cert_type': '자격유형',
    'cert_name': '자격명',
    'date_obtained': '취득일',

    # 코멘트 (comments.csv)
    'year': '연도',
    'commenter_type': '작성자유형',
    'comment_raw': '코멘트 원문',
    'comment_summary': '코멘트 요약',
    'strengths': '강점',
    'improvements': '개선점',

    # 승계후보 (succession.csv)
    'rank_type': '후보구분',
    'rank_order': '순위',
    'nominated_year': '지명연도',

    # 리더십진단 (leadership.csv)
    'overall_score': '종합점수',
    'vision': '비전',
    'communication': '소통',
    'execution': '실행',
    'collaboration': '협업',
    'development': '육성',

    # 직무이력 (job_profile.csv) — job_profile_name_N 등은 label_for()가 처리
    'job_profile_name': '직무명',
    'job_start_date': '직무 시작일',
    'job_end_date': '직무 종료일',

    # 업무목표 (work_objective.csv) — work_objective24 등은 label_for()가 처리
    'work_objective': '업무목표',

    # 기술이전 (technology_transfer.csv)
    'transfer_date': '이전일',
    'recipient': '이전처',
    'amount': '금액',
    'transfer_type': '이전유형',

    # 전배 (transfers.csv)
    'date': '일자',
    'type': '유형',

    # 조직도 (team_refer.csv)
    'end_name': '최종조직명',
    'team_layer': '조직레벨',
    'assignment_name': '배치명',
    'dep_id': '부서ID',
    'upper_dep_id': '상위부서ID',
    'dep_name': '소속',

    # 과제 전문성/매칭 (LLM 파생)
    'job_title': '직무',
    'fit_score': '적합도',
    'reason': '근거',
    'strength_fields': '강점분야',
    'strength_keywords': '강점키워드',
    'key_responsibilities': '주요 역할·책임',
    'domain_knowledge_skill': '전문지식 및 역량',

    # 자연어 질문 화면 전용 파생 컬럼
    'age': '나이',
    'degree_major': '학력/전공',
    'position_year': 'CL/년차',
    'matched_term_count': '일치 키워드 수',
    'score': '유사도점수',
    'level': '유사도 등급',
    'evidence': '유사 근거',
    'grade_evidence': '평가등급 근거',
}


def label_for(column: str) -> str:
    """컬럼명 -> 한글 라벨. 매핑에 없으면 원래 이름을 그대로 반환(폴백).
    job_profile_name_1, work_objective24처럼 숫자 접미사가 붙는 동적 컬럼도
    베이스 이름으로 매핑을 찾아 접미사를 붙여 돌려준다."""
    if column in COLUMN_LABELS:
        return COLUMN_LABELS[column]
    for base in ('job_profile_name_', 'job_start_date_', 'job_end_date_'):
        if column.startswith(base):
            suffix = column[len(base):]
            return f'{COLUMN_LABELS[base.rstrip("_")]}{suffix}'
    if column.startswith('work_objective') and column[len('work_objective'):].isdigit():
        return f'업무목표 20{column[len("work_objective"):]}'
    eval_match = _EVAL_COLUMN_RE.match(column)
    if eval_match:
        year, suffix = eval_match.groups()
        return f'{year} {_EVAL_COLUMN_SUFFIX_LABEL[suffix]}'
    return column


def label_columns(columns: list) -> list:
    return [label_for(c) for c in columns]
