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

    def fake(to, subject, body, attachments=None, sender_email=None, sender_user_id=None):
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
