"""임베딩 요청을 서버 한도(개수·항목 글자·총 글자) 안으로 나눔(2026-10-15, HTTP 413 수정)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services import llm  # noqa: E402


def test_chunks_respect_limits(monkeypatch):
    monkeypatch.setenv('EMBED_MAX_CHARS_PER_ITEM', '100')
    monkeypatch.setenv('EMBED_MAX_ITEMS', '3')
    monkeypatch.setenv('EMBED_MAX_TOTAL_CHARS', '250')
    texts = ['a' * 90, 'b' * 300, 'c' * 90, 'd' * 10, 'e', 'f', 'g']
    chunks = llm._embed_chunks(texts, 64)
    assert [t[0] for c in chunks for t in c] == list('abcdefg')          # 순서 유지
    assert all(len(c) <= 3 and sum(map(len, c)) <= 250 for c in chunks)
    assert max(len(t) for c in chunks for t in c) == 100                  # 긴 항목은 잘림
