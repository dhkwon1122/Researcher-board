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


def norm_id(val) -> str:
    """사번 값을 8자리 제로패딩 문자열로 정규화.
    Excel이 숫자로 읽은 12345.0 → '00012345'
    """
    s = str(val).strip()
    if s in ('', 'nan', 'None', 'NaT'):
        return ''
    try:
        return str(int(float(s))).zfill(8)
    except (ValueError, OverflowError):
        return s.zfill(8)


def norm_researcher_id_col(df: pd.DataFrame) -> pd.DataFrame:
    """DataFrame에 researcher_id 컬럼이 있으면 8자리 텍스트로 정규화."""
    if 'researcher_id' in df.columns:
        df = df.copy()
        df['researcher_id'] = df['researcher_id'].apply(norm_id)
        df = df[df['researcher_id'] != '']   # 빈 ID 행 제거
    return df


def read_xlsx(file_path: str, sheet: int | str = 0, header_row: int = 0) -> pd.DataFrame:
    """
    xlwings를 사용하여 xlsx 파일을 DataFrame으로 읽습니다.

    DRM이 걸린 파일은 xlwings(Excel COM)로만 읽을 수 있습니다.
    xlwings를 import할 수 없는 환경(Linux 개발 서버 등)에서는
    자동으로 openpyxl(pandas) 방식으로 폴백합니다.

    Args:
        file_path: xlsx 파일 경로
        sheet: 시트 인덱스(0-based int) 또는 시트 이름(str)
        header_row: 헤더 행 인덱스(0-based). 기본값 0 = 첫 번째 행.

    Returns:
        pandas DataFrame
    """
    try:
        import xlwings as xw
    except BaseException:
        return _read_with_pandas(file_path, sheet, header_row)

    app = None
    wb = None
    try:
        app = xw.App(visible=False, add_book=False)
        wb = app.books.open(str(file_path))

        if isinstance(sheet, int):
            ws = wb.sheets[sheet]
        else:
            ws = wb.sheets[sheet]

        data = ws.used_range.value

        if not data:
            return pd.DataFrame()

        if not isinstance(data[0], list):
            data = [data]

        headers = data[header_row]
        rows = data[header_row + 1:]

        valid_cols = [(i, h) for i, h in enumerate(headers) if h is not None]
        clean_headers = [str(h).strip() for _, h in valid_cols]
        clean_rows = [[row[i] if i < len(row) else None for i, _ in valid_cols]
                      for row in rows]

        return pd.DataFrame(clean_rows, columns=clean_headers)

    except Exception as exc:
        print(f'[xlwings 실패 → pandas fallback] {file_path}: {exc}')
        return _read_with_pandas(file_path, sheet, header_row)

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


def _read_with_pandas(file_path: str, sheet: int | str = 0, header_row: int = 0) -> pd.DataFrame:
    """xlwings 없이 pandas로 읽는 폴백. xlsb는 pyxlsb 엔진 사용."""
    if str(file_path).lower().endswith('.xlsb'):
        try:
            df = pd.read_excel(file_path, sheet_name=sheet, header=header_row, engine='pyxlsb')
        except Exception:
            raise ImportError(
                '.xlsb 파일 읽기에 pyxlsb 패키지가 필요합니다: pip install pyxlsb'
            )
    else:
        df = pd.read_excel(file_path, sheet_name=sheet, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]
    return df
