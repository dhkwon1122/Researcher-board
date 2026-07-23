"""
과제별 MPR(Monthly Report) PDF 텍스트 추출 유틸리티

Confluence 주소(confl_address)가 비어 있는 과제에 한해, project_summary.py가
Confluence 조회 대신 이 모듈로 폴백한다. data/raw/conflue_MPR/{과제명}.pdf
파일을 찾아 본문 텍스트를 추출해, 이후 요약(_summarize)·전문성 분석 과정은
Confluence 원문을 썼을 때와 동일하게 진행된다.

파일명은 project_confl_address.csv의 과제명(project_name)과 정확히 일치해야
한다(예: 과제명이 "지능형 물류 시스템"이면 data/raw/conflue_MPR/지능형 물류 시스템.pdf).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR  # noqa: E402

PDF_DIR = os.path.join(RAW_DIR, 'conflue_MPR')


class PdfNotFoundError(RuntimeError):
    """과제명에 해당하는 PDF 파일을 찾지 못했거나 텍스트 추출에 실패했을 때."""


def fetch_pdf_text(project_name: str) -> str:
    """data/raw/conflue_MPR/{project_name}.pdf 의 제목+본문 텍스트를 반환.
    실패(파일 없음/추출 실패/추출 결과 공백) 시 PdfNotFoundError."""
    path = os.path.join(PDF_DIR, f'{project_name}.pdf')
    if not os.path.exists(path):
        raise PdfNotFoundError(f'PDF 파일 없음: {path}')

    try:
        from pypdf import PdfReader
    except ModuleNotFoundError as exc:
        raise PdfNotFoundError('pypdf 패키지가 없습니다: pip install pypdf') from exc

    try:
        reader = PdfReader(path)
        pages_text = [(page.extract_text() or '') for page in reader.pages]
    except Exception as exc:  # noqa: BLE001
        raise PdfNotFoundError(f'PDF 텍스트 추출 실패({path}): {type(exc).__name__}: {exc}') from exc

    body_text = '\n'.join(t for t in pages_text if t.strip())
    if not body_text.strip():
        raise PdfNotFoundError(f'PDF에서 추출된 텍스트가 없습니다(스캔 이미지 PDF일 수 있음): {path}')

    return f'{project_name}\n\n{body_text}'.strip()
