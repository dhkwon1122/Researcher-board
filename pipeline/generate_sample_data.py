"""
더미 데이터 생성 스크립트 — 개발·테스트 전용
실제 운영 시에는 run_pipeline.py 를 사용하세요.
"""

import os
import random
import sys
from datetime import date

import numpy as np
import pandas as pd

random.seed(42)
np.random.seed(42)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

DEPARTMENTS = {
    'ORG01': '기계시스템연구팀',
    'ORG02': '소재공정연구팀',
    'ORG03': 'AI융합연구팀',
    'ORG04': '바이오헬스연구팀',
    'ORG05': '에너지환경연구팀',
}

POSITIONS = ['연구원', '선임연구원', '책임연구원', '수석연구원']

SURNAMES = ['김', '이', '박', '최', '정', '강', '조', '윤', '장', '임', '한', '오']
GIVEN_NAMES = [
    '준혁', '민준', '현우', '도현', '태양', '지훈', '성민', '재원', '동현', '승우',
    '서연', '지원', '수빈', '나연', '하은', '민지', '예진', '소연', '지수', '유진',
    '준서', '시우', '예준', '주원', '지호', '연우', '서준', '민서', '지아', '하린',
]

SCHOOLS = ['서울대학교', 'KAIST', '연세대학교', '고려대학교', 'POSTECH', '한양대학교', '성균관대학교']

MAJORS = {
    'ORG01': ['기계공학', '항공우주공학', '로봇공학'],
    'ORG02': ['재료공학', '화학공학', '고분자공학'],
    'ORG03': ['컴퓨터공학', '인공지능', '전기전자공학'],
    'ORG04': ['생명과학', '바이오공학', '의공학'],
    'ORG05': ['화학공학', '환경공학', '에너지공학'],
}

JOURNALS = {
    'ORG01': ['Journal of Mechanical Engineering', 'Int. Journal of Robotics Research', 'Mechatronics', 'Robotics and Automation Letters'],
    'ORG02': ['Advanced Materials', 'Journal of Materials Science', 'Acta Materialia', 'Materials Today'],
    'ORG03': ['Nature Machine Intelligence', 'IEEE TPAMI', 'NeurIPS', 'ICML', 'Expert Systems with Applications'],
    'ORG04': ['Nature Biotechnology', 'Journal of Biomedical Engineering', 'Biomaterials', 'Biosensors and Bioelectronics'],
    'ORG05': ['Energy & Environmental Science', 'Applied Energy', 'Renewable Energy', 'Journal of Power Sources'],
}

PATENT_NAMES = {
    'ORG01': ['초정밀 가공 방법', '로봇 제어 시스템', '진동 저감 장치', '스마트 센서 모듈', '구동 메커니즘'],
    'ORG02': ['나노복합소재 제조방법', '고강도 경량합금', '표면처리 기술', '기능성 코팅재', '고분자 복합체'],
    'ORG03': ['딥러닝 기반 영상인식 시스템', 'AI 예측 진단 알고리즘', '자연어처리 모델', '이상감지 시스템', '추천 엔진'],
    'ORG04': ['바이오마커 검출 방법', '약물 전달 시스템', '진단 키트', '세포 배양 장치', '생체신호 측정기'],
    'ORG05': ['고효율 태양전지 소재', '수소 생산 촉매', '에너지 저장 시스템', 'CO2 포집 기술', '열관리 장치'],
}

TECH_RECIPIENTS = [
    '(주)한국기술', '대한전자(주)', '미래소재(주)', '글로벌테크코리아',
    '(주)신기술연구소', 'KT&G 연구소', '삼성전자 기술원', '현대자동차(주)', 'LG화학(주)',
]

TRANSFER_TYPES = ['부서발령', '프로젝트파견', '해외파견', '공동연구']

TRANSFER_DESCS = {
    '부서발령': lambda depts: f'{random.choice(list(depts))} 발령',
    '프로젝트파견': lambda _: f'{random.choice(["산업부", "과기부", "중기부", "방사청"])} 과제 수행',
    '해외파견': lambda _: f'{random.choice(["MIT", "Stanford", "TU Berlin", "ETH Zurich", "RIKEN"])} 공동연구',
    '공동연구': lambda _: f'{random.choice(["삼성전자", "현대자동차", "LG화학", "SK이노베이션"])} 공동연구',
}

PEER_COMMENTS = [
    "{name} 선배님은 전문 지식이 뛰어나고 팀원들을 잘 이끌어 주십니다. 어려운 문제도 명쾌하게 해결해 주셔서 많은 도움을 받고 있습니다.",
    "업무에 대한 열정과 성실함이 인상적이며, 협업 시 원활한 소통으로 팀 분위기를 이끌어 주십니다.",
    "{name} 선배님의 {tech} 분야 기술적 역량이 뛰어나며, 후배들에게 아낌없이 지식을 공유해 주셔서 감사합니다.",
    "꼼꼼하고 체계적인 업무 처리 방식 덕분에 프로젝트가 원활하게 진행됩니다. 좋은 멘토십에 감사드립니다.",
]

COMMENT_TEMPLATES = [
    "{name} 연구원은 탁월한 연구 역량과 창의적인 문제 해결 능력을 보유하고 있습니다. "
    "특히 {tech} 분야에서 두각을 나타내며, 팀 협업에도 적극적으로 기여하고 있습니다. "
    "향후 리더십 역량 개발에 더욱 집중한다면 더 큰 성과를 이룰 수 있을 것으로 기대됩니다. "
    "논문 및 특허 실적도 꾸준히 성장하고 있어 연구소의 핵심 인재로 자리매김하고 있습니다.",

    "{name} 연구원은 성실하고 꼼꼼한 연구 태도로 주변의 신뢰를 받고 있습니다. "
    "{tech} 관련 전문성이 높으며, 다수의 논문 및 특허 실적을 통해 연구소 발전에 기여하고 있습니다. "
    "소통 능력을 더욱 향상시키면 팀 내 시너지 효과가 클 것으로 봅니다. "
    "후배 연구원들에게 좋은 롤모델이 되고 있어 조직 문화에도 긍정적인 영향을 주고 있습니다.",

    "올해 {name} 연구원은 {tech} 프로젝트에서 핵심적인 역할을 수행하여 우수한 결과를 도출하였습니다. "
    "연구 기획력과 실행력이 뛰어나며, 후배 연구원 지도에도 열의를 보이고 있습니다. "
    "지속적인 자기계발 노력이 인상적이며, 외부 협력 네트워크를 더욱 확대할 것을 권장합니다.",

    "{name} 연구원은 연구소 내에서 전문성과 성과 면에서 두드러진 모습을 보여주고 있습니다. "
    "복잡한 기술 과제를 체계적으로 분석하고 해결하는 능력이 돋보이며, {tech} 분야의 핵심 인재로 성장하고 있습니다. "
    "글로벌 연구 역량 강화를 위해 국제 학술 활동 참여를 늘릴 것을 제안합니다.",
]

TECH_AREA = {
    'ORG01': '기계시스템',
    'ORG02': '소재공정',
    'ORG03': 'AI융합',
    'ORG04': '바이오헬스',
    'ORG05': '에너지환경',
}

_used_names = set()


def _make_name():
    for _ in range(100):
        name = random.choice(SURNAMES) + random.choice(GIVEN_NAMES)
        if name not in _used_names:
            _used_names.add(name)
            return name
    return random.choice(SURNAMES) + random.choice(GIVEN_NAMES)


def generate_researchers():
    rows = []
    rid = 1
    for org_code, dept in DEPARTMENTS.items():
        for _ in range(10):
            hire_year = random.randint(2005, 2020)
            birth_year = random.randint(1970, 1992)
            seniority = (2024 - hire_year) // 5
            pos_idx = min(max(seniority + random.randint(-1, 1), 0), 3)
            rows.append({
                'researcher_id': f'R{rid:03d}',
                'name': _make_name(),
                'gender': random.choice(['남', '여']),
                'department': dept,
                'org_code': org_code,
                'position': POSITIONS[pos_idx],
                'hire_year': hire_year,
                'birth_year': birth_year,
                'photo_path': '',
            })
            rid += 1
    return pd.DataFrame(rows)


GRADE_TO_SCORE = {'가': 95, '나': 85, '다': 75, '라': 65, '마': 55}
# 가중치: 가/나 비율을 높게, 마는 드물게
GRADE_WEIGHTS = {'가': 10, '나': 30, '다': 35, '라': 20, '마': 5}
GRADES = list(GRADE_WEIGHTS.keys())
GRADE_W = list(GRADE_WEIGHTS.values())


def generate_evaluations(researchers_df):
    rows = []
    for _, r in researchers_df.iterrows():
        base_idx = random.choices(range(len(GRADES)), weights=GRADE_W)[0]
        for year in [2024, 2025, 2026]:
            idx = max(0, min(len(GRADES) - 1, base_idx + random.randint(-1, 1)))
            grade = GRADES[idx]
            rows.append({
                'researcher_id': r['researcher_id'],
                'year': year,
                'grade': grade,
                'score': GRADE_TO_SCORE[grade],
            })
            base_idx = idx
    return pd.DataFrame(rows)


def generate_incentive_selection(researchers_df, evaluations_df):
    rows = []
    for _, r in researchers_df.iterrows():
        for year in [2024, 2025, 2026]:
            ev = evaluations_df[
                (evaluations_df['researcher_id'] == r['researcher_id']) &
                (evaluations_df['year'] == year)
            ]
            if ev.empty:
                continue
            grade = ev.iloc[0]['grade']
            if grade == '가':
                selected, category = True, '최우수연구원'
            elif grade == '나' and random.random() > 0.45:
                selected, category = True, '우수연구원'
            else:
                selected, category = False, ''
            rows.append({
                'researcher_id': r['researcher_id'],
                'year': year,
                'selected': selected,
                'category': category,
                'note': '인센티브 지급' if selected else '',
            })
    return pd.DataFrame(rows)


def generate_publications(researchers_df):
    rows = []
    for _, r in researchers_df.iterrows():
        n = random.randint(0, 14)
        journals = JOURNALS.get(r['org_code'], ['Journal of Research'])
        for _ in range(n):
            rows.append({
                'researcher_id': r['researcher_id'],
                'title': (
                    f'{random.choice(["Development of", "Study on", "Analysis of", "Novel", "Improved"])} '
                    f'{random.choice(["Advanced", "High-performance", "Efficient", "Intelligent", "Robust"])} '
                    f'Approach for {TECH_AREA.get(r["org_code"], "Engineering")} Applications'
                ),
                'journal': random.choice(journals),
                'pub_year': random.randint(2018, 2024),
                'impact_factor': round(random.uniform(0.8, 15.0), 2),
                'citation_count': random.randint(0, 180),
                'is_corresponding': random.random() > 0.55,
            })
    return pd.DataFrame(rows)


def generate_patents(researchers_df):
    rows = []
    for _, r in researchers_df.iterrows():
        n = random.randint(0, 7)
        names = PATENT_NAMES.get(r['org_code'], ['신기술'])
        for i in range(n):
            app_year = random.randint(2019, 2024)
            app_date = date(app_year, random.randint(1, 12), random.randint(1, 28)).isoformat()
            is_reg = random.random() > 0.4 and app_year <= 2023
            reg_date = ''
            if is_reg:
                reg_year = min(app_year + random.randint(1, 2), 2024)
                reg_date = date(reg_year, random.randint(1, 12), random.randint(1, 28)).isoformat()
            rows.append({
                'researcher_id': r['researcher_id'],
                'title': f'{random.choice(names)} {i + 1:02d}',
                'application_no': f'{random.randint(10000000, 99999999)}',
                'application_date': app_date,
                'registration_no': f'{random.randint(1000000, 9999999)}' if is_reg else '',
                'registration_date': reg_date,
                'country': random.choice(['국내', '국내', '국내', '해외']),
                'status': '등록' if is_reg else '출원',
            })
    return pd.DataFrame(rows)


def generate_technology_transfer(researchers_df):
    rows = []
    for _, r in researchers_df.iterrows():
        n = random.choices([0, 1, 2, 3], weights=[0.55, 0.28, 0.12, 0.05])[0]
        names = PATENT_NAMES.get(r['org_code'], ['신기술'])
        for _ in range(n):
            t_year = random.randint(2020, 2024)
            rows.append({
                'researcher_id': r['researcher_id'],
                'transfer_date': date(t_year, random.randint(1, 12), random.randint(1, 28)).isoformat(),
                'tech_name': random.choice(names),
                'recipient': random.choice(TECH_RECIPIENTS),
                'amount': random.choice([500, 1000, 2000, 3000, 5000, 8000, 10000]),
                'transfer_type': random.choice(['특허실시', '기술이전', '기술이전']),
            })
    return pd.DataFrame(rows)


def generate_leadership(researchers_df):
    dims = ['vision', 'communication', 'execution', 'collaboration', 'development']
    rows = []
    for _, r in researchers_df.iterrows():
        bases = {d: random.randint(55, 92) for d in dims}
        for year in [2022, 2023, 2024]:
            scores = {d: int(min(100, max(40, bases[d] + random.randint(-4, 5)))) for d in dims}
            rows.append({
                'researcher_id': r['researcher_id'],
                'year': year,
                'overall_score': round(sum(scores.values()) / len(dims), 1),
                **scores,
            })
            bases = scores
    return pd.DataFrame(rows)


def generate_certifications(researchers_df):
    opic_grades = ['IM1', 'IM2', 'IM3', 'IH', 'AL']
    rows = []
    for _, r in researchers_df.iterrows():
        if random.random() > 0.3:
            rows.append({
                'researcher_id': r['researcher_id'],
                'cert_type': '어학',
                'cert_name': 'TOEIC',
                'score': random.choice([700, 730, 760, 800, 830, 860, 900, 930, 950]),
                'grade': None,
                'date_obtained': date(random.randint(2015, 2023), random.randint(1, 12), 1).isoformat(),
            })
        if random.random() > 0.5:
            rows.append({
                'researcher_id': r['researcher_id'],
                'cert_type': '어학',
                'cert_name': 'OPIc',
                'score': None,
                'grade': random.choice(opic_grades),
                'date_obtained': date(random.randint(2015, 2023), random.randint(1, 12), 1).isoformat(),
            })
        if random.random() > 0.7:
            rows.append({
                'researcher_id': r['researcher_id'],
                'cert_type': '자격증',
                'cert_name': '기술사',
                'score': None,
                'grade': '합격',
                'date_obtained': date(random.randint(2010, 2022), random.randint(1, 12), 1).isoformat(),
            })
    return pd.DataFrame(rows)


def generate_education(researchers_df):
    rows = []
    for _, r in researchers_df.iterrows():
        major = random.choice(MAJORS.get(r['org_code'], ['공학']))
        bach_year = r['birth_year'] + 22 + random.randint(0, 2)
        rows.append({'researcher_id': r['researcher_id'], 'degree': '학사', 'major': major,
                     'school': random.choice(SCHOOLS), 'graduation_year': int(bach_year)})
        if random.random() > 0.15:
            mast_year = bach_year + 2 + random.randint(0, 2)
            rows.append({'researcher_id': r['researcher_id'], 'degree': '석사', 'major': major,
                         'school': random.choice(SCHOOLS), 'graduation_year': int(mast_year)})
            if random.random() > 0.35:
                phd_year = mast_year + 4 + random.randint(0, 2)
                rows.append({'researcher_id': r['researcher_id'], 'degree': '박사', 'major': major,
                             'school': random.choice(SCHOOLS), 'graduation_year': int(phd_year)})
    return pd.DataFrame(rows)


def generate_transfers(researchers_df):
    rows = []
    depts = list(DEPARTMENTS.values())
    for _, r in researchers_df.iterrows():
        n = random.choices([0, 1, 2, 3, 4], weights=[0.2, 0.3, 0.25, 0.15, 0.1])[0]
        for _ in range(n):
            t_year = random.randint(max(2015, int(r['hire_year'])), 2024)
            t_type = random.choice(TRANSFER_TYPES)
            desc = TRANSFER_DESCS[t_type](depts)
            rows.append({
                'researcher_id': r['researcher_id'],
                'date': date(t_year, random.randint(1, 12), 1).isoformat(),
                'type': t_type,
                'description': desc,
            })
    return pd.DataFrame(rows).sort_values(['researcher_id', 'date'])


def generate_comments(researchers_df):
    rows = []
    for _, r in researchers_df.iterrows():
        tech = TECH_AREA.get(r['org_code'], '연구')
        for year in [2024, 2025, 2026]:
            # 부서장 코멘트
            raw = random.choice(COMMENT_TEMPLATES).format(name=r['name'], tech=tech)
            rows.append({
                'researcher_id': r['researcher_id'],
                'year': year,
                'commenter_type': '부서장',
                'comment_raw': raw,
                'comment_summary': raw[:120] + '...',
                'strengths': f'{tech} 전문성, 연구 성과 우수',
                'improvements': '리더십 역량 강화, 외부 네트워크 확대',
            })
            # 부서원 코멘트 (약 50% 확률)
            if random.random() > 0.5:
                peer_raw = random.choice(PEER_COMMENTS).format(name=r['name'], tech=tech)
                rows.append({
                    'researcher_id': r['researcher_id'],
                    'year': year,
                    'commenter_type': '부서원',
                    'comment_raw': peer_raw,
                    'comment_summary': peer_raw,
                    'strengths': '전문성 공유, 협업',
                    'improvements': '',
                })
    return pd.DataFrame(rows)


def main():
    """
    data/processed/ 에 대시보드용 CSV 파일을 준비합니다.

    우선순위:
      1순위 — data/raw/ 에 실제 xlsx/csv 원천 파일이 있으면 그것을 사용
      2순위 — 평가 데이터는 T&P_기본_인사_정보.xlsx 에서 추출
      3순위 — 원천 파일이 없는 항목만 샘플(더미) 데이터로 채움
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw')
    TP_FILE = os.path.join(RAW_DIR, 'T&P_기본_인사_정보.xlsx')

    # ── 헬퍼 ─────────────────────────────────────────────────────────────────

    def _raw_path(name):
        """data/raw/{name}_raw.xlsx 또는 .csv 가 있으면 경로 반환, 없으면 None"""
        for ext in ('xlsx', 'csv'):
            p = os.path.join(RAW_DIR, f'{name}_raw.{ext}')
            if os.path.exists(p):
                return p
        return None

    def _read(path):
        """xlsx → xlwings(DRM 지원), csv → pandas"""
        if path.endswith('.xlsx'):
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from excel_reader import read_xlsx
            return read_xlsx(path)
        return pd.read_csv(path, encoding='utf-8-sig')

    def _load_or_gen(name, gen_func, *gen_args):
        """
        실제 raw 파일이 있으면 읽어서 반환, 없으면 gen_func(*gen_args)로 샘플 생성.
        반환값: (DataFrame, source_label)
        """
        p = _raw_path(name)
        if p:
            df = _read(p)
            return df, f'[RAW]   {os.path.basename(p)}'
        df = gen_func(*gen_args)
        return df, f'[샘플]  {name} ({len(df)}행 생성)'

    # ── 1. 연구원 기본 정보 ───────────────────────────────────────────────────
    researchers, src = _load_or_gen('researchers', generate_researchers)
    log = {'researchers': src}

    # ── 2. 평가 데이터 (T&P > evaluations_raw > 샘플) ─────────────────────────
    evaluations = None
    skip_eval_save = False  # T&P 처리기가 직접 저장하므로 중복 저장 방지

    if os.path.exists(TP_FILE):
        # T&P 파일 있음 → process_tp_evaluation 으로 추출
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from process_tp_evaluation import process as _tp_process
        ok = _tp_process()
        if ok:
            eval_out = os.path.join(OUTPUT_DIR, 'evaluations.csv')
            evaluations = pd.read_csv(eval_out, encoding='utf-8-sig')
            log['evaluations'] = '[RAW]   T&P_기본_인사_정보.xlsx → evaluations'
            skip_eval_save = True  # 이미 저장됨

    if evaluations is None:
        evaluations, src = _load_or_gen('evaluations', generate_evaluations, researchers)
        log['evaluations'] = src

    # ── 3. 나머지 데이터 ──────────────────────────────────────────────────────
    incentives,    log['incentive_selection']    = _load_or_gen('incentive_selection',  generate_incentive_selection,  researchers, evaluations)
    publications,  log['publications']           = _load_or_gen('publications',         generate_publications,         researchers)
    patents,       log['patents']                = _load_or_gen('patents',              generate_patents,               researchers)
    tech_transfers,log['technology_transfer']    = _load_or_gen('technology_transfer',  generate_technology_transfer,  researchers)
    leadership,    log['leadership']             = _load_or_gen('leadership',           generate_leadership,           researchers)
    certifications,log['certifications']         = _load_or_gen('certifications',       generate_certifications,       researchers)
    education,     log['education']              = _load_or_gen('education',            generate_education,            researchers)
    transfers,     log['transfers']              = _load_or_gen('transfers',            generate_transfers,            researchers)
    comments,      log['comments']               = _load_or_gen('comments',             generate_comments,             researchers)

    # ── 4. CSV 저장 ───────────────────────────────────────────────────────────
    datasets = {
        'researchers':        researchers,
        'evaluations':        evaluations,
        'incentive_selection':incentives,
        'publications':       publications,
        'patents':            patents,
        'technology_transfer':tech_transfers,
        'leadership':         leadership,
        'certifications':     certifications,
        'education':          education,
        'transfers':          transfers,
        'comments':           comments,
    }

    for name, df in datasets.items():
        if name == 'evaluations' and skip_eval_save:
            continue  # T&P 처리기가 이미 저장함
        path = os.path.join(OUTPUT_DIR, f'{name}.csv')
        df.to_csv(path, index=False, encoding='utf-8-sig')

    # ── 5. 결과 출력 ──────────────────────────────────────────────────────────
    print('\n데이터 준비 완료')
    print(f'  {"항목":<25}  {"출처/처리":<50}  {"행 수":>6}')
    print('  ' + '-' * 85)
    for name, df in datasets.items():
        source = log.get(name, '')
        print(f'  {name:<25}  {source:<50}  {len(df):>6}행')


if __name__ == '__main__':
    main()

