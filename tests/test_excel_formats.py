import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'pipeline'))
sys.path.insert(0, ROOT)

import excel_reader  # noqa: E402
import source_files  # noqa: E402
from services import web_pipeline_runner as wpr  # noqa: E402


def test_find_matches_includes_xlsb_variant(tmp_path):
    (tmp_path / '시상 세부사항 2026.xlsb').write_bytes(b'x')
    (tmp_path / '특허 리스트.xlsb').write_bytes(b'x')
    assert source_files.find_matches(str(tmp_path), '시상 세부사항 *.xlsx')
    assert source_files.find_matches(str(tmp_path), '특허 리스트.xlsx')
    assert not source_files.find_matches(str(tmp_path), '없는파일.xlsx')


def test_resolve_excel_prefers_exact_then_other_extension(tmp_path):
    (tmp_path / 'a.xlsb').write_bytes(b'x')
    assert source_files.resolve_excel(str(tmp_path), 'a.xlsx').endswith('a.xlsb')
    (tmp_path / 'a.xlsx').write_bytes(b'x')
    assert source_files.resolve_excel(str(tmp_path), 'a.xlsx').endswith('a.xlsx')
    assert source_files.resolve_excel(str(tmp_path), 'zzz.xlsx').endswith('zzz.xlsx')  # 없으면 원래 경로


def test_exact_mode_upload_keeps_stem_and_uses_upload_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(wpr, 'WEB_UPDATES_DIR', str(tmp_path))
    monkeypatch.setattr(wpr, 'archive_raw_bytes', lambda *a, **k: None)
    for item in wpr.MANIFEST:
        if item['mode'] != 'exact' or not item.get('dest_filename', 'x').endswith('.xlsx'):
            continue
        wpr.save_upload(item['key'], '아무이름.xlsb', b'data')
        names = [os.path.basename(p) for p in wpr.uploaded_files(item['key'])]
        assert names == [item['dest_filename'][:-5] + '.xlsb'], item['key']
        wpr.save_upload(item['key'], 'again.xlsx', b'data')
        names = [os.path.basename(p) for p in wpr.uploaded_files(item['key'])]
        assert names == [item['dest_filename']], item['key']
        assert wpr.has_upload(item['key'])


def test_job_profile_dual_slots_accept_xlsb(tmp_path, monkeypatch):
    monkeypatch.setattr(wpr, 'WEB_UPDATES_DIR', str(tmp_path))
    monkeypatch.setattr(wpr, 'archive_raw_bytes', lambda *a, **k: None)
    wpr.save_upload('job_profile', 'legacy.xlsb', b'x', slot='legacy')
    assert not wpr.has_upload('job_profile')          # new 슬롯이 아직 없음
    wpr.save_upload('job_profile', '내 리포트 2026.xlsb', b'x', slot='new')
    assert wpr.has_upload('job_profile')
    wpr.save_upload('job_profile', 'legacy2.xlsx', b'x', slot='legacy')   # 확장자 바꿔 재업로드
    names = sorted(os.path.basename(p) for p in wpr.uploaded_files('job_profile'))
    assert len(names) == 2 and sum(n.endswith('.xlsb') for n in names) == 1


def test_excel_serial_dates_are_converted():
    assert excel_reader.parse_yyyymmdd('45678') == '2025-01-21'
    assert excel_reader.parse_yyyymmdd(45678.0) == '2025-01-21'
    assert excel_reader.parse_yyyymmdd('20240101') == '2024-01-01'
    assert excel_reader.parse_flexible_date(45678) == '2025-01-21'
    assert excel_reader.parse_flexible_date('2024/03/05') == '2024-03-05'


def test_confluence_float_page_id_is_treated_as_bare_id():
    import confluence_client as cc
    assert cc.extract_page_id('3957970224.0') == '3957970224'
    assert cc._is_bare_page_id(' 3957970224.00 ')
    assert not cc._is_bare_page_id('12.5')
    assert cc.extract_page_id('https://h.samsungds.net/pages/viewpage.action?pageId=123') == '123'
