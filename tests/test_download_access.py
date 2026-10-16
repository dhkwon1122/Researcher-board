"""엑셀 다운로드 권한 + 1회성 요청/승인(2026-10-15)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services import download_access as da  # noqa: E402

USER = {'user_id': 'u1', 'display_name': '홍길동', 'email': '', 'role': 'talent_dev', 'is_admin': False,
        'permissions': {'download_excel': False}, 'eval_excluded_dep_ids': []}
ADMIN = {'user_id': 'adm', 'display_name': '관리자', 'email': '', 'role': 'talent_mng', 'is_admin': True,
         'permissions': {}, 'eval_excluded_dep_ids': []}


def test_request_approve_ack_use_once(tmp_path, monkeypatch):
    from services import auth
    monkeypatch.setattr(da, 'REQUESTS_PATH', str(tmp_path / 'r.json'))
    with auth.acting_as(USER):
        assert not da.has_permission()
        ok, msg, _ = da.check('report_builder')
        assert not ok and '다운로드 요청' in msg
        with pytest.raises(ValueError):
            da.create_request('report_builder', '대상', '')
        req = da.create_request('report_builder', 'AI플랫폼 6명', '재배치 검토')
        assert '승인 대기' in da.check('report_builder')[1]
        with pytest.raises(PermissionError):
            da.decide(req['id'], True)
    with auth.acting_as(ADMIN):
        assert da.decide(req['id'], True, '회의용')['status'] == 'approved'
        with pytest.raises(ValueError):
            da.decide(req['id'], False)                      # 이미 처리됨
    with auth.acting_as(USER):
        assert [n['id'] for n in da.notices('u1')] == [req['id']]
        ok, msg, _ = da.check('report_builder')
        assert not ok and '안내를 확인' in msg                # 책임 안내 확인 전에는 사용 불가
        da.acknowledge([req['id']], 'u1')
        assert da.notices('u1') == []
        assert not da.check('job_market')[0]                 # 다른 화면에는 쓸 수 없음
        ok, _msg, grant = da.check('report_builder')
        assert ok and grant == req['id']
        da.consume(grant)
        assert not da.check('report_builder')[0]             # 1회만


def test_permission_holder_skips_gate(tmp_path, monkeypatch):
    from services import auth
    monkeypatch.setattr(da, 'REQUESTS_PATH', str(tmp_path / 'r.json'))
    with auth.acting_as({**USER, 'permissions': {}}):        # 역할 기본값(허용)
        assert da.check('researcher_list') == (True, '', None)
