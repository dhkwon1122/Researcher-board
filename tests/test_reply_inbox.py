"""회신 메일 자동 취합(비실명 계정 POP3, 2026-11-23)."""
import io
from datetime import date
from email.message import EmailMessage

import pandas as pd
import pytest

from services import auth
from services import hr_order_mail as hom
from services import reply_inbox as ri
from services import work_assign as wa

ADMIN = {'user_id': 'adm', 'display_name': '관리자', 'email': '', 'role': 'executive_org', 'is_admin': True, 'permissions': {}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ('CONTACTS_PATH', 'SETTINGS_PATH', 'LOG_PATH', 'REPLIES_PATH'):
        monkeypatch.setattr(hom, name, str(tmp_path / f'hr_{name}'))
    monkeypatch.setattr(hom, 'REPLIES_DIR', str(tmp_path / 'hr_replies'))
    for name in ('SETTINGS_PATH', 'LOG_PATH', 'SUBMISSIONS_PATH', 'CONTACTS_PATH'):
        monkeypatch.setattr(wa, name, str(tmp_path / f'wa_{name}'))
    monkeypatch.setattr(wa, 'SUBMIT_DIR', str(tmp_path / 'wa_sub'))
    for name in ('INDEX_PATH', 'STATUS_PATH', 'FETCH_LOCK'):
        monkeypatch.setattr(ri, name, str(tmp_path / f'ri_{name}'))
    monkeypatch.setattr(ri, 'FILES_DIR', str(tmp_path / 'ri_files'))
    for k, v in {'MAIL_POP3_HOST': 'pop.example', 'MAIL_POP3_USER': 'people.sait', 'MAIL_SINCE_DAYS': '30'}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(auth, 'list_users', lambda: [ADMIN])
    with auth.acting_as(ADMIN):
        hom.save_contacts([{'dept': 'A플랫폼', 'name': '김', 'email': 'kim@samsung.com'},
                           {'dept': 'B플랫폼', 'name': '이', 'email': 'lee@samsung.com'}])
        wa.save_contacts([{'dept': 'A플랫폼', 'name': '김', 'email': 'kim@samsung.com'},
                          {'dept': 'C플랫폼', 'name': '김', 'email': 'kim@samsung.com'},       # 겸직
                          {'dept': 'B플랫폼', 'name': '이', 'email': 'lee@samsung.com'}])
    # 보낸 메일 이력(제목 대조용)
    with open(wa.LOG_PATH, 'w', encoding='utf-8') as f:
        f.write('{"target": "2026-12", "subject": "[업무분장] 2026년 12월 업무분장표 작성 요청 (11.25 발송)"}\n')
    with open(hom.LOG_PATH, 'w', encoding='utf-8') as f:
        f.write('{"order_date": "2026-12-16", "subject": "인사발령 대상 작성 요청"}\n')
    return tmp_path


def _xlsx(rows) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    return buf.getvalue()


def _mail(subject, sender, files=(), when='Mon, 23 Nov 2026 10:00:00 +0900') -> bytes:
    m = EmailMessage()
    m['Subject'], m['From'], m['To'], m['Date'] = subject, sender, 'people.sait@samsung.com', when
    m.set_content('회신드립니다.')
    for name, content in files:
        m.add_attachment(content, maintype='application', subtype='octet-stream', filename=name)
    m.add_attachment(b'\x89PNG', maintype='image', subtype='png', filename='sign.png', disposition='inline', cid='<s1>')
    return m.as_bytes()


class FakePop:
    def __init__(self, mails):
        self.mails = mails            # [(uidl, bytes)]
        self.retrieved = []

    def uidl(self):
        return b'+OK', [f'{i + 1} {u}'.encode() for i, (u, _) in enumerate(self.mails)], 0

    def retr(self, num):
        self.retrieved.append(num)
        return b'+OK', self.mails[num - 1][1].split(b'\n'), 0

    def quit(self):
        pass


def test_parse_korean_subject_and_attachments():
    p = ri.parse(_mail('회신: [업무분장] 12월', '김 <Kim@samsung.com>', [('업무분장_A플랫폼.xlsx', b'123')]))
    assert p['subject'] == '회신: [업무분장] 12월' and p['sender_email'] == 'kim@samsung.com'
    assert p['mail_date'] == '2026-11-23 10:00'
    assert [n for n, _ in p['attachments']] == ['업무분장_A플랫폼.xlsx']                   # 본문 속 그림은 뺌


def test_guess_scenario_from_sent_log_and_keywords(env):
    assert ri.guess_scenario('RE: 회신: [업무분장] 2026년 12월 업무분장표 작성 요청 (11.25 발송)')[:2] == ('work_assign', '2026-12')
    assert ri.guess_scenario('Re: 인사발령 대상 작성 요청')[:2] == ('hr_order', '2026-12-16')
    assert ri.guess_scenario("회신 - '27년 1월 업무분장 제출")[:2] == ('work_assign', '2027-01')
    assert ri.guess_scenario('[인사발령] 2027.01.01자 회신')[:2] == ('hr_order', '2027-01-01')
    assert ri.guess_scenario('점심 메뉴')[0] == ''


def test_fetch_registers_work_assign_and_hr_replies(env):
    table = _xlsx([{'성명': '김', '담당업무': '기획'}])
    pop = FakePop([
        ('u1', _mail('RE: [업무분장] 2026년 12월 업무분장표 작성 요청 (11.25 발송)', 'lee@samsung.com', [('회신.xlsx', table)])),
        ('u2', _mail('RE: [업무분장] 2026년 12월 업무분장표 작성 요청 (11.25 발송)', 'kim@samsung.com',
                     [('업무분장_26년12월_A플랫폼.xlsx', table), ('업무분장_26년12월_C플랫폼.xlsx', table)])),   # 겸직
        ('u3', _mail('RE: 인사발령 대상 작성 요청', 'lee@samsung.com', [('B플랫폼 발령.xlsx', b'x'), ('메모.pdf', b'y')])),
        ('u4', _mail('질문 있습니다', 'park@samsung.com', [('a.xlsx', table)])),
        ('u5', _mail('RE: 인사발령 대상 작성 요청', 'lee@samsung.com', [('old.xlsx', b'x')],
                     when='Mon, 01 Jun 2026 10:00:00 +0900')),                                      # 30일보다 오래됨
    ])
    st = ri.run_once(connect=lambda cfg: pop)
    assert st['ok'] and (st['new'], st['skipped'], st['registered'], st['review']) == (4, 1, 3, 1)
    assert sorted(wa.submissions('2026-12')) == ['A플랫폼', 'B플랫폼', 'C플랫폼']
    assert wa.submissions('2026-12')['B플랫폼']['source'] == 'mail'
    rep = hom.replies('2026-12-16')['B플랫폼']
    assert [f['name'] for f in rep['files']] == ['B플랫폼 발령.xlsx', '메모.pdf'] and rep['source'] == 'mail'
    assert hom.reply_file('2026-12-16', 'B플랫폼', '메모.pdf') == ('메모.pdf', b'y')
    review = [m for m in ri.list_mails() if m['status'] == 'review']
    assert [m['sender_email'] for m in review] == ['park@samsung.com']
    # 같은 메일은 두 번 읽지 않음
    pop.retrieved.clear()
    assert ri.run_once(connect=lambda cfg: pop)['new'] == 0 and pop.retrieved == []
    # 확인 필요 메일 직접 지정
    with auth.acting_as(ADMIN):
        r = ri.assign(review[0]['id'], 'work_assign', '2026-11', 'A플랫폼')
        assert r['status'] == 'registered' and 'A플랫폼' in wa.submissions('2026-11')
        ri.ignore(review[0]['id'])
    assert ri.get_mail(review[0]['id'])['status'] == 'ignored'
    status = {r['dept']: r for r in hom.reply_status('2026-12-16')}
    assert status['B플랫폼']['replied'] and not status['A플랫폼']['replied']


def test_not_configured_and_permission(env, monkeypatch):
    monkeypatch.delenv('MAIL_POP3_HOST')
    assert not ri.is_configured() and ri.run_once()['ok'] is False
    with pytest.raises(PermissionError):
        with auth.acting_as({'user_id': 'x', 'role': 'viewer', 'is_admin': False, 'permissions': {}}):
            ri.assign(1, 'work_assign', '2026-12', 'A플랫폼')
