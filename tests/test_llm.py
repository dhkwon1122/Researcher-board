import pytest

from services.llm import LLMError, embed


def test_embed_rejects_non_ascii_api_key(monkeypatch):
    """EMBED_API_KEY에 한글 등이 섞이면(흔한 실수: .env.example의 placeholder를
    실제 값으로 안 바꾸고 그대로 씀) requests가 헤더 인코딩 중에 던지는
    UnicodeEncodeError 대신, 원인을 바로 알 수 있는 LLMError가 나야 한다."""
    monkeypatch.setenv('EMBED_API_KEY', '여기_긴_랜덤값')
    with pytest.raises(LLMError, match='EMBED_API_KEY'):
        embed(['테스트'])


def test_embed_accepts_ascii_api_key_and_reaches_network(monkeypatch):
    """ASCII 키는 헤더 인코딩 단계를 통과해, 다음 단계인 실제 네트워크 호출까지
    가야 한다(여기서는 서버가 없으니 연결 실패 LLMError로 끝나는 것으로
    "헤더 검증에서 막히지 않았다"만 확인한다)."""
    monkeypatch.setenv('EMBED_API_KEY', 'a' * 32)
    monkeypatch.setenv('EMBED_BASE_URL', 'http://127.0.0.1:1')  # 아무도 안 듣는 포트
    with pytest.raises(LLMError, match='연결할 수 없습니다'):
        embed(['테스트'])
