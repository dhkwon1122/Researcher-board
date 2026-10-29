"""연구원 프로필 "최근 검색" — 계정별 구분, 로그아웃 시 브라우저 저장소 삭제(2026-10-29)."""
from services import auth


def _u(uid):
    return {'user_id': uid, 'display_name': uid, 'role': 'recruit', 'is_admin': False, 'permissions': {}}


def test_history_is_per_account():
    import app  # noqa: F401 — 페이지 모듈은 앱 생성 뒤에 불러와야 함
    from pages import researcher_profile as rp
    with auth.acting_as(_u('a')):
        data = rp._history_data([{'rid': '1', 'label': '홍길동'}])
        assert data['user'] == 'a' and rp._history_items(data) == [{'rid': '1', 'label': '홍길동'}]
    with auth.acting_as(_u('b')):
        assert rp._history_items(data) == []                                   # 다른 계정 이력은 안 보임
        assert rp._history_items([{'rid': '1', 'label': '예전 형식'}]) == []    # 계정 표시 없는 예전 이력도 숨김


def test_logout_clears_browser_storage():
    import app as appmod
    client = appmod.app.server.test_client()
    resp = client.get('/logout')
    assert resp.status_code == 200 and resp.headers['Clear-Site-Data'] == '"storage"'
    body = resp.get_data(as_text=True)
    assert 'localStorage.clear()' in body and '/login' in body
