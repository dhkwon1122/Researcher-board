import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pipeline'))

import process_tasks  # noqa: E402


def _touch(path, mtime):
    path.write_bytes(b'x')
    os.utime(path, (mtime, mtime))


def test_finds_named_file_any_suffix_and_extension(tmp_path):
    now = time.time()
    _touch(tmp_path / '개인별과제투입기간데이터_260114.xlsb', now - 100)
    _touch(tmp_path / '개인별과제투입기간데이터.xlsx', now)
    _touch(tmp_path / '~$개인별과제투입기간데이터.xlsx', now + 50)
    _touch(tmp_path / '다른파일.xlsx', now + 100)
    assert process_tasks._find_source_file(str(tmp_path)).endswith('개인별과제투입기간데이터.xlsx')


def test_falls_back_to_single_excel_file(tmp_path):
    _touch(tmp_path / 'upload.xlsb', time.time())
    assert process_tasks._find_source_file(str(tmp_path)).endswith('upload.xlsb')


def test_ambiguous_or_missing_returns_none(tmp_path):
    assert process_tasks._find_source_file(str(tmp_path)) is None
    _touch(tmp_path / 'a.xlsx', time.time())
    _touch(tmp_path / 'b.xlsb', time.time())
    assert process_tasks._find_source_file(str(tmp_path)) is None
