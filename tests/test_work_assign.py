"""업무 시나리오 > 업무분장 — 월말 기준 일정, 자동 발송, 회신 파일 제출 현황·통합표(2026-11-20)."""
import io
from datetime import date, datetime

import pandas as pd
import pytest

from services import auth
from services import hr_order_mail as hom
from services import work_assign as wa

ADMIN = {'user_id': 'adm', 'display_name': '관리자', 'email': '', 'role': 'executive_org', 'is_admin': True, 'permissions': {}}


@pytest.fixture
def paths(tmp_path, monkeypatch):
    for name in ('CONTACTS_PATH', 'SETTINGS_PATH', 'LOG_PATH'):
        monkeypatch.setattr(hom, name, str(tmp_path / f'hr_{name}'))
    for name in ('SETTINGS_PATH', 'LOG_PATH', 'AUTO_SENT_PATH', 'AUTO_LOCK_PATH', 'SUBMISSIONS_PATH'):
        monkeypatch.setattr(wa, name, str(tmp_path / f'wa_{name}'))
    monkeypatch.setattr(wa, 'AUTO_FILES_DIR', str(tmp_path / 'wa_auto'))
    monkeypatch.setattr(wa, 'SUBMIT_DIR', str(tmp_path / 'wa_sub'))
    monkeypatch.setenv('MAIL_FROM', 'people.sait@samsung.com')
    monkeypatch.setattr(auth, 'list_users', lambda: [ADMIN])
    with auth.acting_as(ADMIN):
        hom.save_contacts([{'dept': 'AI플랫폼', 'name': '김', 'email': 'a@x.com'},
                           {'dept': '소재 연구', 'name': '이', 'email': 'b@x.com'}])
    return tmp_path


def _xlsx(rows, title=True) -> bytes:
    buf = io.BytesIO()
    df = pd.DataFrame(rows)
    with pd.ExcelWriter(buf, engine='openpyxl') as xw:
        df.to_excel(xw, index=False, startrow=2 if title else 0)
        if title:
            xw.sheets['Sheet1']['A1'] = '2026년 12월 업무분장표'
    return buf.getvalue()


def test_month_end_schedule(paths):
    assert wa.last_workday(2026, 11) == date(2026, 11, 30)          # 월요일
    assert wa.last_workday(2026, 10) == date(2026, 10, 30)          # 31일 토요일 → 30일(금)
    assert wa.base_date('2026-12') == date(2026, 11, 30)
    assert wa.send_date('2026-12') == date(2026, 11, 25)            # 기본 3일 전
    assert wa.reply_due('2026-12') == date(2026, 11, 30)            # 발송 후 3일
    with auth.acting_as(ADMIN):
        assert wa.set_workdays(0, 5) == (0, 5)
        with pytest.raises(ValueError):
            wa.set_workdays(16, 3)
    assert wa.send_date('2026-12') == date(2026, 11, 30) and wa.reply_due('2026-12') == date(2026, 12, 7)
    assert wa.render('{대상월} {대상월_숫자} {회신일_월일}', '2026-12', date(2026, 11, 30)) == '2026년 12월 2026.12 11월 30일(월)'


def test_auto_send_once_with_shared_recipients(paths, monkeypatch):
    import pipeline.mailer as mailer
    sent = []
    monkeypatch.setattr(mailer, 'send_html_email', lambda to, s, b, a=None, sender_email=None, sender_user_id=None,
                        cc=None, bcc=None: sent.append((to, s, b, cc)))
    hom._update_settings(recipients={'cc': [{'rid': '1', 'name': '동료', 'dept': '인사', 'email': 'm@x.com'}],
                                     'bcc': [], 'mode': 'single'})
    with auth.acting_as(ADMIN):
        wa.save_template('[업무분장] {대상월}', '회신 {회신일_월일}까지')
        wa.add_auto_files([('양식.xlsx', b'1')])
        wa.save_auto(True, 9, hom.SHARED_SENDER)
    wa._update_settings(auto={**wa._settings()['auto'], 'set_at': '2026-11-01T00:00:00'})
    assert wa.next_auto_send(datetime(2026, 11, 20, 10)) == ('2026-12', datetime(2026, 11, 25, 9))
    assert wa.run_auto_if_due(datetime(2026, 11, 25, 8)) is None
    r = wa.run_auto_if_due(datetime(2026, 11, 25, 9, 5))
    assert r['target'] == '2026-12'
    assert sent == [(['a@x.com', 'b@x.com'], '[업무분장] 2026년 12월', sent[0][2], ['m@x.com'])]   # 인사발령 명단·참조·방식
    assert '11월 30일(월)까지' in sent[0][2]
    assert wa.run_auto_if_due(datetime(2026, 11, 25, 9, 30)) is None and len(sent) == 1
    log = wa.read_log()[0]
    assert log['target'] == '2026-12' and log['kind'] == 'auto'
    assert hom.read_log() == []                                       # 인사발령 이력과 분리


def test_submissions_status_and_merged(paths):
    with auth.acting_as(ADMIN):
        done, errors = wa.save_uploads('2026-12', [
            ('업무분장_AI플랫폼.xlsx', _xlsx([{'성명': '김', '담당 업무': '기획'}, {'성명': '박', '담당 업무': '개발'}])),
            ('소재연구_회신.xlsx', _xlsx([{'성명': '이', '담당 업무': '분석', '비고': 'x'}], title=False)),
            ('모름.xlsx', _xlsx([{'a': 1}])),
            ('메모.txt', b'x'),
        ])
        assert [d for d, _ in done] == ['AI플랫폼', '소재 연구'] and len(errors) == 2   # 공백 무시 매칭
        st = {r['dept']: r for r in wa.status('2026-12')}
        assert st['AI플랫폼']['submitted'] and st['AI플랫폼']['rows'] == 2
        df = wa.merged('2026-12')
        assert list(df.columns) == ['부서', '성명', '담당 업무', '비고']
        assert df['부서'].tolist() == ['AI플랫폼', 'AI플랫폼', '소재 연구'] and df['비고'].tolist() == ['', '', 'x']
        assert wa.merged_excel('2026-12')[:2] == b'PK'
        wa.save_uploads('2026-12', [('다시.csv', '성명,담당 업무\n최,총괄\n'.encode('utf-8'))], dept='AI플랫폼')
        assert wa.merged('2026-12')['성명'].tolist() == ['최', '이']                # 같은 부서는 교체
        wa.delete_submission('2026-12', 'AI플랫폼')
        assert not wa.status('2026-12')[0]['submitted'] and wa.submission_file('2026-12', 'AI플랫폼') is None
        with pytest.raises(ValueError):
            wa.save_submission('2026-12', '없는부서', 'a.xlsx', _xlsx([{'a': 1}]))


def _real_form(rows_target, rows_ref) -> bytes:
    """실제 "업무분장 양식" 구조 — 1행 병합 묶음 머리글, 2행 열 이름(대상월·참고 10개 열 반복)."""
    from openpyxl import Workbook
    cols = ['플랫폼', '그룹', '과제/파트명', '성명', '담당업무', '상세업무', '인력 Assign 형태', '주과제 참여율', '부과제명', '비고']
    wb = Workbook()
    ws = wb.active
    ws['A1'], ws['C1'], ws['M1'] = 'Knox ID, 재직현황', "'26년 12월 1일자", "참고 : '26년 11월 1일자"
    ws.merge_cells('A1:B1'), ws.merge_cells('C1:L1'), ws.merge_cells('M1:V1')
    ws.append(['Knox ID', '재직현황'] + cols + cols)
    for t, r in zip(rows_target, rows_ref):
        ws.append(t + r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_real_form_two_row_header_and_reference_columns(paths):
    t1 = ['gd.hong', '재직', 'P1', 'G1', '과제A', '홍길동', '기획', '상세', '전담', '100%', '', '']
    r1 = ['P1', 'G1', '과제A', '홍길동', '분석', '', '전담', '100%', '', '']
    empty = [''] * 12
    r2 = ['P1', 'G1', '과제B', '퇴사자', '개발', '', '겸임', '50%', '', '']
    content = _real_form([t1, empty], [r1, r2])
    df = wa.read_table('AI플랫폼.xlsx', content)
    assert list(df.columns)[:3] == ['Knox ID', '재직현황', '플랫폼'] and '참고_담당업무' in df.columns
    assert not any(c.endswith('_2') for c in df.columns)
    with auth.acting_as(ADMIN):
        rec = wa.save_submission('2026-12', 'AI플랫폼', 'AI플랫폼.xlsx', content)
    assert rec['rows'] == 1                                         # 참고만 채워진 행은 세지 않음
    m = wa.merged('2026-12')
    assert len(m) == 1 and m.loc[0, '담당업무'] == '기획' and not any(c.startswith('참고_') for c in m.columns)
    m2 = wa.merged('2026-12', include_ref=True)
    assert len(m2) == 2 and m2['참고_성명'].tolist() == ['홍길동', '퇴사자']


def _researchers_df():
    rows = [
        ('1', '홍길동', 'P-A1', 'gd.hong', 'Y', 'CL3', '재직'),
        ('2', '새사람', 'P-A2', 'new.one', 'Y', 'CL2', '휴직'),
        ('3', '임원', 'P-A1', 'boss', 'Y', '상무', '재직'),          # 대상 직급 아님
        ('4', '소재인', 'P-B1', 'mat.kim', 'Y', 'H2', '재직'),
        ('5', '퇴사자', 'P-A1', 'gone', 'N', 'CL3', '퇴직'),        # 최신 명단 아님
        ('6', '과장', 'P-A1', 'cl4.park', 'Y', 'CL4', '재직'),
    ]
    return pd.DataFrame([{'researcher_id': r, 'name': n, 'org_code': oc, 'knox_id': k, 'is_current': cur, 'position': pos,
                          'employment_status': st} for r, n, oc, k, cur, pos, st in rows])


@pytest.fixture
def forms(paths, monkeypatch, tmp_path):
    from services import work_assign_form as waf
    import services.similarity_map as sm
    monkeypatch.setattr(waf, 'TEMPLATE_PATH', str(tmp_path / 'tpl.xlsx'))
    monkeypatch.setattr(waf, 'REF_DIR', str(tmp_path / 'ref'))
    df = _researchers_df()
    monkeypatch.setattr(waf.data_store, 'read_processed', lambda name: df if name == 'researchers' else pd.DataFrame())
    monkeypatch.setattr(sm, 'org_code_level_name_map', lambda: {
        'P-A1': ('AI플랫폼', '그룹1', '과제A'), 'P-A2': ('AI플랫폼', '그룹2', '과제B'), 'P-B1': ('소재 연구', '그룹9', '파트Z')})
    monkeypatch.setattr(sm, 'org_code_dep_code_map', lambda: {'P-A1': '001', 'P-A2': '002', 'P-B1': '100'})
    monkeypatch.setattr(sm, 'dep_name_for_org_code', lambda oc: '')
    return waf


def _sheet(content):
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(content)).active
    return [[c.value for c in row] for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=22)]


def test_platform_form_from_latest_roster_and_positions(forms):
    assert forms.platforms() == ['AI플랫폼', '소재 연구']
    name, content = forms.build_form('2026-12', 'AI플랫폼')
    assert name == '업무분장_26년12월_AI플랫폼.xlsx'
    rows = _sheet(content)
    assert rows[0][2] == "'26년 12월 1일자" and rows[0][12] == "참고 : '26년 11월 1일자"
    assert [r[:8] for r in rows[2:]] == [
        ['cl4.park', '재직', 'AI플랫폼', '그룹1', '과제A', '과장', None, None],       # 조직 순서 → 이름
        ['gd.hong', '재직', 'AI플랫폼', '그룹1', '과제A', '홍길동', None, None],
        ['new.one', '휴직', 'AI플랫폼', '그룹2', '과제B', '새사람', None, None]]    # 상무·퇴사자 제외, 담당업무는 비움
    rows = _sheet(forms.build_form('2027-01', '소재 연구')[1])
    assert rows[0][2] == "'27년 1월 1일자" and rows[0][12] == "참고 : '26년 12월 1일자"
    assert rows[2][:6] == ['mat.kim', '재직', '소재 연구', '그룹9', '파트Z', '소재인']


def test_reference_excel_fills_previous_month(forms):
    ref = _real_form(
        [['gd.hong', '재직', 'AI플랫폼', '그룹1', '과제A', '홍길동', '기획', '상세', '전담', '100%', '', ''],
         ['ex.lee', '재직', 'AI플랫폼', '그룹1', '과제C', '전출자', '개발', '', '겸임', '50%', '', '']],
        [['old'] * 10] * 2)                                              # 참고 엑셀의 "참고" 묶음(두 달 전)은 쓰지 않음
    with auth.acting_as(ADMIN):
        assert forms.save_ref('2026-12', '11월 업무분장.xlsx', ref)['rows'] == 2
        with pytest.raises(ValueError):
            forms.save_ref('2026-12', 'x.xlsx', _xlsx([{'a': 1}], title=False))
    assert forms.ref_info('2026-12')['name'] == '11월 업무분장.xlsx'
    rows = _sheet(forms.build_form('2026-12', 'AI플랫폼')[1])
    hong = next(r for r in rows if r[0] == 'gd.hong')
    assert hong[5] == '홍길동' and hong[6] is None and hong[12:17] == ['AI플랫폼', '그룹1', '과제A', '홍길동', '기획']
    assert rows[-1][:2] == ['ex.lee', '현 명단 없음'] and rows[-1][5] is None and rows[-1][15] == '전출자'
    # 다시 올린 회신은 대상월 칸만 통합표로(참고 열은 기본 제외), 파일명으로 플랫폼 자동 연결
    name, content = forms.build_form('2026-12', 'AI플랫폼')
    with auth.acting_as(ADMIN):
        done, _ = wa.save_uploads('2026-12', [(name, content), forms.build_form('2026-12', '소재 연구')])
    assert [d for d, _ in done] == ['AI플랫폼', '소재 연구']
    with auth.acting_as(ADMIN):
        forms.delete_ref('2026-12')
    assert forms.ref_info('2026-12') == {}


def test_send_platform_file_only_to_that_platform_contact(forms, monkeypatch):
    import pipeline.mailer as mailer
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(forms.default_template()))
    wb.active['A5'] = '예시 값'
    buf = io.BytesIO()
    wb.save(buf)
    with auth.acting_as(ADMIN):
        assert forms.save_template('우리양식.xlsx', buf.getvalue())['template_name'] == '우리양식.xlsx'
        hom.save_contacts([{'dept': 'AI플랫폼', 'name': '김', 'email': 'a@x.com'},
                           {'dept': '소재 연구', 'name': '이', 'email': 'b@x.com'},
                           {'dept': '없는플랫폼', 'name': '박', 'email': 'c@x.com'}])
    assert '예시 값' not in str(_sheet(forms.build_form('2026-12', '소재 연구')[1]))
    plan = forms.plan('2026-12')
    assert [(p['platform'], p['count'], [c['email'] for c in p['contacts']]) for p in plan['platforms']] == [
        ('AI플랫폼', 3, ['a@x.com']), ('소재 연구', 1, ['b@x.com'])]
    assert [c['email'] for c in plan['unmatched_contacts']] == ['c@x.com']
    sent = []
    monkeypatch.setattr(mailer, 'send_html_email', lambda to, s, b, a=None, sender_email=None, sender_user_id=None,
                        cc=None, bcc=None: sent.append((to, [n for n, _ in a])))
    with auth.acting_as(ADMIN):
        res = wa.send(hom.load_contacts(), '제목', '본문', [], hom.SHARED_SENDER, '2026-12', mode='single', gen_forms=True)
    assert sorted(sent) == [(['a@x.com'], ['업무분장_26년12월_AI플랫폼.xlsx']),
                            (['b@x.com'], ['업무분장_26년12월_소재_연구.xlsx'])]     # 자기 플랫폼 파일만
    assert [(r['email'], r['ok']) for r in res] == [('a@x.com', True), ('b@x.com', True), ('c@x.com', False)]
    assert wa.read_log()[0]['gen_forms'] is True
    with auth.acting_as(ADMIN):
        with pytest.raises(ValueError):
            wa.send(hom.load_contacts(), '제목', '본문', [], hom.SHARED_SENDER, '2026-12')
    import zipfile
    z = zipfile.ZipFile(io.BytesIO(forms.build_all_zip('2026-12')))
    assert sorted(z.namelist()) == ['업무분장_26년12월_AI플랫폼.xlsx', '업무분장_26년12월_소재_연구.xlsx']


def test_auto_send_with_generated_forms_only(forms, monkeypatch):
    import pipeline.mailer as mailer
    sent = []
    monkeypatch.setattr(mailer, 'send_html_email', lambda to, s, b, a=None, sender_email=None, sender_user_id=None,
                        cc=None, bcc=None: sent.append((to, [n for n, _ in a])))
    with auth.acting_as(ADMIN):
        with pytest.raises(ValueError):
            wa.save_auto(True, 9, hom.SHARED_SENDER)
        forms.save_settings(True)
        wa.save_auto(True, 9, hom.SHARED_SENDER)
    wa._update_settings(auto={**wa._settings()['auto'], 'set_at': '2026-11-01T00:00:00'})
    r = wa.run_auto_if_due(datetime(2026, 11, 25, 9, 5))
    assert r['target'] == '2026-12' and all(x['ok'] for x in r['results'])
    assert sorted(sent) == [(['a@x.com'], ['업무분장_26년12월_AI플랫폼.xlsx']),
                            (['b@x.com'], ['업무분장_26년12월_소재_연구.xlsx'])]


def test_full_list_file_for_review(forms):
    name, content = forms.build_form('2026-12', None)
    assert name == '업무분장_26년12월_전체.xlsx'
    rows = _sheet(content)
    assert [r[0] for r in rows[2:]] == ['cl4.park', 'gd.hong', 'new.one', 'mat.kim']   # 전 플랫폼, 조직 순서
