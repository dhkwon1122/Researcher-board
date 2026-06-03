"""
xlwings 기반 Excel 읽기 유틸리티

사내 DRM이 걸린 xlsx 파일을 읽기 위해 xlwings를 사용합니다.
xlwings는 실제 Excel 애플리케이션(COM 자동화)을 통해 파일을 열기 때문에
DRM 보호 파일도 정상적으로 읽을 수 있습니다.

사전 조건:
  - Windows PC에 Microsoft Excel이 설치되어 있어야 합니다.
  - `pip install xlwings` 가 완료되어 있어야 합니다.
"""

import pandas as pd


def read_xlsx(file_path: str, sheet: int | str = 0) -> pd.DataFrame:
    """
    xlwings를 사용하여 xlsx 파일을 DataFrame으로 읽습니다.

    DRM이 걸린 파일은 xlwings(Excel COM)로만 읽을 수 있습니다.
    xlwings를 import할 수 없는 환경(Linux 개발 서버 등)에서는
    자동으로 openpyxl(pandas) 방식으로 폴백합니다.

    Args:
        file_path: xlsx 파일 경로
        sheet: 시트 인덱스(0-based int) 또는 시트 이름(str)

    Returns:
        pandas DataFrame (첫 행을 헤더로 사용)
    """
    try:
        import xlwings as xw
    except ImportError:
        # xlwings 미설치 환경 — pandas fallback
        return _read_with_pandas(file_path, sheet)

    app = None
    wb = None
    try:
        # visible=False: 백그라운드 실행, add_book=False: 빈 통합 문서 자동 생성 방지
        app = xw.App(visible=False, add_book=False)
        wb = app.books.open(str(file_path))

        if isinstance(sheet, int):
            ws = wb.sheets[sheet]
        else:
            ws = wb.sheets[sheet]

        data = ws.used_range.value

        if not data:
            return pd.DataFrame()

        # 단일 행인 경우 리스트로 감싸기
        if not isinstance(data[0], list):
            data = [data]

        headers = data[0]
        rows = data[1:]

        # 헤더가 None인 열 제거
        valid_cols = [(i, h) for i, h in enumerate(headers) if h is not None]
        clean_headers = [h for _, h in valid_cols]
        clean_rows = [[row[i] if i < len(row) else None for i, _ in valid_cols]
                      for row in rows]

        return pd.DataFrame(clean_rows, columns=clean_headers)

    except Exception as exc:
        # xlwings 실패 시 pandas fallback (DRM이 없는 일반 파일이라면 정상 동작)
        print(f'[xlwings 실패 → pandas fallback] {file_path}: {exc}')
        return _read_with_pandas(file_path, sheet)

    finally:
        if wb is not None:
            try:
                wb.close()
            except Exception:
                pass
        if app is not None:
            try:
                app.quit()
            except Exception:
                pass


def _read_with_pandas(file_path: str, sheet: int | str = 0) -> pd.DataFrame:
    """xlwings 없이 pandas(openpyxl)로 읽는 폴백."""
    return pd.read_excel(file_path, sheet_name=sheet)
