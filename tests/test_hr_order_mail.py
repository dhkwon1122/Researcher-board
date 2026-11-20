"""업무 시나리오 > 인사발령 — 부서별 담당자 양식 메일(2026-11-19)."""
import json
from datetime import date

import pandas as pd
import pytest

from services import auth
from services import hr_order_mail as hom

ADMIN = {'user_id': 'adm', 'display_name': '관리자', 'email': '', 'role': 'executive_org', 'is_admin': True, 'permissions': {}}
HR = {'user_id': 'hong.gildong', 'display_name': '홍길동', 'email': 'hong@samsung.com', 'role': 'workforce_mng',
      'is_admin': False, 'permissions': {}}


@pytest.fixture
def paths(tmp_path, monkeypatch):
    for name in ('CONTACTS_PATH', 'SETTINGS_PATH', 'LOG_PATH'):
        monkeypatch.setattr(hom, name, str(tmp_path / name))
    monkeypatch.setenv('MAIL_FROM', 'people.sait@samsung.com')
    monkeypatch.setattr(auth, 'list_users', lambda: [ADMIN, HR])
    return tmp_path


def test_permission_admin_and_allowed_roles(paths):
    with auth.acting_as(HR):
        assert not hom.can_use()
        with pytest.raises(PermissionError):
            hom.set_allowed_roles(['workforce_mng'])
    with auth.acting_as(ADMIN):
        assert hom.can_use() and hom.set_allowed_roles(['workforce_mng', '없는역할']) == ['workforce_mng']
    with auth.acting_as(HR):
        assert hom.can_use()


def test_contacts_clean_and_excel(paths):
    with auth.acting_as(ADMIN):
        saved, errors = hom.save_contacts([{'dept': 'AI플랫폼', 'name': '김', 'email': 'a@x.com'}, {'dept': '', 'email': ''},
                                           {'dept': '소재', 'email': '잘못된주소'}])
        assert errors and not hom.load_contacts()                       # 오류가 있으면 저장 안 함
        saved, errors = hom.save_contacts([{'dept': 'AI플랫폼', 'name': '김', 'email': 'a@x.com'}])
        assert not errors and hom.load_contacts() == saved
    rows = hom.contacts_from_table(pd.DataFrame({'부서': ['A'], '담당자': ['이'], '이메일': ['b@x.com']}))
    assert rows == [{'dept': 'A', 'name': '이', 'email': 'b@x.com'}]
    with pytest.raises(ValueError):
        hom.contacts_from_table(pd.DataFrame({'이름': ['x']}))


def test_next_order_date():
    assert hom.next_order_date(date(2026, 11, 19)) == date(2026, 12, 1)
    assert hom.next_order_date(date(2026, 11, 3)) == date(2026, 11, 16)
    assert hom.next_order_date(date(2026, 12, 20)) == date(2027, 1, 1)


def test_send_as_logged_in_user_one_mail_each(paths, monkeypatch):
    import pipeline.mailer as mailer
    sent = []

    def fake(to, subject, body, attachments=None, sender_email=None, sender_user_id=None, cc=None, bcc=None):
        if to == ['bad@x.com']:
            raise mailer.MailError('수신 거부')
        sent.append((to, subject, body, attachments, sender_email, sender_user_id))
    monkeypatch.setattr(mailer, 'send_html_email', fake)
    contacts = [{'dept': 'A', 'name': '김', 'email': 'a@x.com'}, {'dept': 'B', 'name': '이', 'email': 'bad@x.com'}]
    with auth.acting_as(ADMIN):
        hom.set_allowed_roles(['workforce_mng'])
    with auth.acting_as(HR):
        assert [o['value'] for o in hom.sender_options()] == ['hong.gildong', hom.SHARED_SENDER]   # 관리자 아니면 본인·공용만
        with pytest.raises(PermissionError):
            hom.send(contacts, '제목', '본문', [('양식.xlsx', b'x')], 'adm')                      # 남의 계정은 관리자만
        res = hom.send(contacts, '[인사발령] 12.01', '줄1\n<b>줄2</b>', [('양식.xlsx', b'xyz')], 'hong.gildong')
    assert [r['ok'] for r in res] == [True, False]
    to, subject, body, att, s_email, s_uid = sent[0]
    assert to == ['a@x.com'] and att == [('양식.xlsx', b'xyz')]
    assert (s_email, s_uid) == ('hong@samsung.com', 'hong.gildong')                               # 본인 계정으로 발신
    assert '줄1<br>&lt;b&gt;줄2' in body                                                          # 본문 이스케이프
    log = hom.read_log()[0]
    assert log['sender'] == 'hong@samsung.com' and log['files'] == [{'name': '양식.xlsx', 'size': 3}]
    assert 'xyz' not in json.dumps(log)                                                           # 파일 내용은 기록 안 함
    with auth.acting_as(HR):
        hom.send(contacts[:1], '제목', '본문', [('a.xlsx', b'1')], hom.SHARED_SENDER)
    assert sent[-1][4:] == (None, None)                                                           # 팀 공용 = .env 값


def test_mailer_sender_override(monkeypatch):
    import pipeline.mailer as mailer
    for k, v in {'MAIL_API_URL': 'https://m.example', 'MAIL_TOKEN': 't', 'MAIL_SYSTEM_ID': 's',
                 'MAIL_FROM': 'people.sait@samsung.com', 'MAIL_USER_ID': 'people.sait'}.items():
        monkeypatch.setenv(k, v)
    calls = []

    class R:
        def raise_for_status(self):
            pass
    monkeypatch.setattr(mailer.requests, 'post', lambda url, **kw: calls.append((url, kw)) or R())
    mailer.send_html_email(['a@x.com'], 's', 'b', [('f.xlsx', b'1')], sender_email='hong@samsung.com',
                           sender_user_id='hong.gildong')
    url, kw = calls[0]
    assert url.endswith('/mails/send?userId=hong.gildong')
    assert json.loads(kw['data'][0][1][1])['sender'] == {'emailAddress': 'hong@samsung.com'}
    mailer.send_html_email(['a@x.com'], 's', 'b')
    assert calls[1][0].endswith('userId=people.sait') and '"people.sait@samsung.com"' in calls[1][1]['data']


def test_workdays_reply_and_auto_dates(paths):
    assert hom.reply_due(date(2026, 12, 16)) == date(2026, 12, 10)          # 사용자 예시: 12.16 → 12.10
    assert hom.auto_send_date(date(2026, 12, 16)) == date(2026, 12, 7)
    assert hom.reply_due(date(2026, 10, 1)) == date(2026, 9, 23)            # 추석 연휴(9.24~26) 제외
    with auth.acting_as(ADMIN):
        hom.set_company_holidays('2026-12-14')
        with pytest.raises(ValueError):
            hom.set_company_holidays('12/09')
    assert hom.reply_due(date(2026, 12, 16)) == date(2026, 12, 9)           # 회사 휴무일(12.14)도 제외 → 12.9


def test_template_render_and_save(paths):
    d = date(2026, 12, 16)
    assert hom.render('{발령일}자, 회신 {회신일_월일}, {기타}', d) == '2026.12.16자, 회신 12월 10일(목), {기타}'
    with auth.acting_as(ADMIN):
        hom.save_template('[발령] {발령일_월일}', '본문 {회신일}')
    assert hom.template() == ('[발령] {발령일_월일}', '본문 {회신일}')


def test_admin_sender_only_self_or_shared(paths):
    with auth.acting_as(ADMIN):
        assert [o['value'] for o in hom.sender_options()] == ['adm', hom.SHARED_SENDER]
        with pytest.raises(PermissionError):
            hom.send([{'dept': 'A', 'name': '', 'email': 'a@x.com'}], 's', 'b', [('f', b'1')], 'hong.gildong')


def test_contact_for_person_uses_knox_id(paths, monkeypatch):
    df = pd.DataFrame([{'researcher_id': '00000001', 'name': '홍길동', 'org_code': 'X', 'department': '원본부서',
                        'knox_id': 'gd.hong'},
                       {'researcher_id': '00000002', 'name': '무녹스', 'org_code': 'X', 'department': '원본부서',
                        'knox_id': float('nan')}])
    monkeypatch.setattr(hom.data_store, 'read_processed', lambda name: df)
    import services.similarity_map as sm
    monkeypatch.setattr(sm, 'dep_name_for_org_code', lambda oc: 'AI플랫폼')
    assert hom.contact_for_person('00000001') == {'dept': 'AI플랫폼', 'name': '홍길동', 'email': 'gd.hong@samsung.com'}
    assert hom.contact_for_person('00000002')['email'] == ''


def test_auto_send_once_at_due_time(paths, monkeypatch, tmp_path):
    from datetime import datetime
    import pipeline.mailer as mailer
    monkeypatch.setattr(hom, 'FILES_DIR', str(tmp_path / 'files'))
    monkeypatch.setattr(hom, 'AUTO_SENT_PATH', str(tmp_path / 'sent.json'))
    monkeypatch.setattr(hom, 'AUTO_LOCK_PATH', str(tmp_path / 'lock'))
    sent = []
    monkeypatch.setattr(mailer, 'send_html_email',
                        lambda to, subject, body, attachments=None, sender_email=None, sender_user_id=None, cc=None, bcc=None:
                        sent.append((to, subject, body, sender_email, cc)))
    with auth.acting_as(HR | {'is_admin': True}):
        hom.save_contacts([{'dept': 'A', 'name': '김', 'email': 'a@x.com'}, {'dept': 'B', 'name': '이', 'email': 'b@x.com'}])
        hom.save_template('[발령] {발령일}', '회신 {회신일_월일}까지')
        with pytest.raises(ValueError):
            hom.save_auto(True, 9, 'hong.gildong')                     # 첨부 없으면 켤 수 없음
        hom.save_auto_files([('양식.xlsx', b'x')])
        hom.save_auto(True, 9, 'hong.gildong')
    assert hom.next_auto_send(datetime(2026, 12, 2, 10))[0:2] == (date(2026, 12, 16), datetime(2026, 12, 7, 9))
    assert hom.run_auto_if_due(datetime(2026, 12, 7, 8, 50)) is None                      # 아직 시각 전
    r = hom.run_auto_if_due(datetime(2026, 12, 7, 9, 5))
    assert r['order_date'] == date(2026, 12, 16) and len(sent) == 2
    assert sent[0][1] == '[발령] 2026.12.16' and '12월 10일(목)까지' in sent[0][2] and sent[0][3] == 'hong@samsung.com'
    assert hom.run_auto_if_due(datetime(2026, 12, 7, 9, 20)) is None and len(sent) == 2   # 같은 발령일은 한 번만
    assert hom.next_auto_send(datetime(2026, 12, 7, 9, 20))[0] == date(2027, 1, 1)       # 다음 발령일로
    assert hom.read_log()[0]['kind'] == 'auto'


def test_mailer_cc_bcc_recipient_types(monkeypatch):
    import pipeline.mailer as mailer
    for k, v in {'MAIL_API_URL': 'https://m.example', 'MAIL_TOKEN': 't', 'MAIL_SYSTEM_ID': 's',
                 'MAIL_FROM': 'people.sait@samsung.com'}.items():
        monkeypatch.setenv(k, v)
    calls = []

    class R:
        def raise_for_status(self):
            pass
    monkeypatch.setattr(mailer.requests, 'post', lambda url, **kw: calls.append(kw) or R())
    mailer.send_html_email(['a@x.com'], 's', 'b', cc=['c@x.com', 'A@x.com'], bcc=['d@x.com', 'c@x.com'])
    assert json.loads(calls[0]['data'])['recipients'] == [
        {'emailAddress': 'a@x.com', 'recipientType': 'TO'}, {'emailAddress': 'c@x.com', 'recipientType': 'CC'},
        {'emailAddress': 'd@x.com', 'recipientType': 'BCC'}]                     # 중복 주소는 앞 구분만


def test_send_with_cc_each_and_single(paths, monkeypatch):
    import pipeline.mailer as mailer
    df = pd.DataFrame([{'researcher_id': '00000009', 'name': '동료', 'org_code': 'X', 'department': '인사',
                        'knox_id': 'mate'}, {'researcher_id': '00000008', 'name': '팀장', 'org_code': 'X',
                                             'department': '인사', 'knox_id': 'boss'}])
    monkeypatch.setattr(hom.data_store, 'read_processed', lambda name: df)
    import services.similarity_map as sm
    monkeypatch.setattr(sm, 'dep_name_for_org_code', lambda oc: '인사팀')
    sent = []
    monkeypatch.setattr(mailer, 'send_html_email',
                        lambda to, subject, body, attachments=None, sender_email=None, sender_user_id=None, cc=None,
                        bcc=None: sent.append((to, cc, bcc)))
    contacts = [{'dept': 'A', 'name': '김', 'email': 'a@x.com'}, {'dept': 'B', 'name': '이', 'email': 'b@x.com'}]
    with auth.acting_as(ADMIN):
        rcp = hom.save_recipient_settings(['00000009'], ['00000008', '00000009'], 'single')
        assert [p['email'] for p in rcp['cc']] == ['mate@samsung.com']
        assert [p['email'] for p in rcp['bcc']] == ['boss@samsung.com']       # CC와 겹치면 BCC에서 뺌
        assert rcp['mode'] == 'single'
        hom.send(contacts, '제목', '본문', [('a.xlsx', b'1')], hom.SHARED_SENDER, cc=rcp['cc'], bcc=rcp['bcc'])
        assert sorted(sent) == [(['a@x.com'], ['mate@samsung.com'], ['boss@samsung.com']),
                                (['b@x.com'], ['mate@samsung.com'], ['boss@samsung.com'])]   # 담당자별 따로 + 매번 참조
        sent.clear()
        res = hom.send(contacts, '제목', '본문', [('a.xlsx', b'1')], hom.SHARED_SENDER, cc=rcp['cc'], mode='single')
        assert sent == [(['a@x.com', 'b@x.com'], ['mate@samsung.com'], [])] and all(r['ok'] for r in res)
        with pytest.raises(ValueError):
            hom.save_recipient_settings([], [], 'weird')
    log = hom.read_log()[0]
    assert log['mode'] == 'single' and log['cc'] == [{'name': '동료', 'email': 'mate@samsung.com'}]
