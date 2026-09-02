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
    if is_blank(s):
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


_BLANK_STRINGS = ('nan', 'none', 'nat', '<na>')


def is_blank(val) -> bool:
    """엑셀 셀 값이 사실상 비어 있는지 판정(None/빈 문자열/nan·None·NaT류 문자열,
    대소문자 무관)."""
    if val is None:
        return True
    return str(val).strip().lower() in ('',) + _BLANK_STRINGS


def clean_str(val) -> str:
    """엑셀 셀 값을 정리된 문자열로 변환. 비어 있으면(is_blank) 빈 문자열,
    아니면 앞뒤 공백만 제거한 원본 문자열(대소문자는 유지)."""
    if val is None:
        return ''
    s = str(val).strip()
    return '' if s.lower() in _BLANK_STRINGS else s


def parse_yyyymmdd(val) -> str:
    """YYYYMMDD(숫자 또는 문자열) 또는 이미 YYYY-MM-DD 형식인 값 → 'YYYY-MM-DD'.
    변환 불가/빈 값이면 빈 문자열. (실수형으로 읽힌 20230101.0 도 처리)"""
    if val is None:
        return ''
    s = str(val).strip().split('.')[0]
    if is_blank(s):
        return ''
    if len(s) == 8 and s.isdigit():
        return f'{s[:4]}-{s[4:6]}-{s[6:]}'
    if len(s) >= 10 and s[4] == '-':
        return s[:10]
    return s


def parse_flexible_date(val) -> str:
    """다양한 날짜 표기(YYYYMMDD, YYYY-MM-DD, YYYY/MM/DD 등)를 pandas가 인식하는
    한 자유롭게 파싱해 'YYYY-MM-DD'로 반환. 빈 값이면 빈 문자열, 파싱 실패 시
    원본 문자열(strip만 적용)을 그대로 반환."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ''
    s = str(val).strip()
    if is_blank(s):
        return ''
    try:
        return pd.to_datetime(s).strftime('%Y-%m-%d')
    except Exception:
        return s


_FORMULA_TRIGGER_CHARS = ('=', '+', '-', '@', '\t', '\r')


def excel_safe_text(val) -> str:
    """CSV 텍스트가 '-', '=', '+', '@'로 시작하면 Excel이 수식으로 오인해
    #NAME? 등의 오류를 낸다(예: '- 대사공학 역량...' → #NAME?). 이런 값 앞에
    작은따옴표(')를 붙여 Excel이 텍스트로 인식하게 한다 — Excel은 화면에는
    이 작은따옴표를 표시하지 않는다.
    """
    s = str(val) if val is not None else ''
    if s and s[0] in _FORMULA_TRIGGER_CHARS:
        return "'" + s
    return s


def _is_blank_cell(value) -> bool:
    return is_blank(value)


def _first_nonblank_row(rows: list[list]) -> int:
    """행 리스트(list of list) 중 하나라도 값이 있는 첫 행의 인덱스. 못 찾으면 0."""
    for i, row in enumerate(rows):
        if any(not _is_blank_cell(cell) for cell in row):
            return i
    return 0


def read_xlsx(file_path: str, sheet: int | str = 0, header_row: int | str = 0,
              visible: bool = False) -> pd.DataFrame:
    """
    xlwings를 사용하여 xlsx 파일을 DataFrame으로 읽습니다.

    DRM이 걸린 파일은 xlwings(Excel COM)로만 읽을 수 있습니다.
    xlwings를 import할 수 없는 환경(Linux 개발 서버 등)에서는
    자동으로 openpyxl(pandas) 방식으로 폴백합니다.

    Args:
        file_path: xlsx 파일 경로
        sheet: 시트 인덱스(0-based int) 또는 시트 이름(str)
        header_row: 헤더 행 인덱스(0-based). 기본값 0 = 첫 번째 행.
                    'auto' 를 넘기면 앞쪽 공란 행을 건너뛰고 실제 값이 있는
                    첫 행을 헤더로 자동 인식합니다 (엑셀 절대 행 기준).
        visible: True면 xlwings가 Excel 창을 화면에 띄운 채로 연다(기본값
                 False = 백그라운드/숨김). DRM 파일 중 일부는 Protected
                 View 등 상호작용이 필요한 팝업이 자동화(headless)로는
                 렌더링/해제되지 않아 COM 예외(예: -2146827284,
                 -2147352567 계열, "예외가 발생했습니다")로 열기 자체가
                 실패하는 경우가 있다(scripts/build_past_team_refer.py,
                 2026-09-02 실사용 확인) — 이럴 때 visible=True로 창을
                 보이게 하면 그런 팝업이 뜨더라도(필요시 사용자가 직접
                 닫아줄 수 있어) 자동화가 막히지 않을 수 있다. 기본값은
                 기존 호출부(대부분 서버에서 무인 배치 실행) 동작을 그대로
                 유지하기 위해 False로 둔다.

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
        app = xw.App(visible=visible, add_book=False)
        wb = app.books.open(str(file_path))

        if isinstance(sheet, int):
            ws = wb.sheets[sheet]
        else:
            ws = wb.sheets[sheet]

        # xlwings는 used_range가 실제로는 여러 열이어도 시트 상태에 따라 1행/1열로
        # 판단되면 .value가 중첩 리스트가 아닌 평평한(flat) 1차원 리스트를 반환한다.
        # 이 경우 아래의 "행 하나로 감싸기" 처리가 열 전체를 하나의 헤더/행으로
        # 잘못 취급해, 모든 데이터가 첫 번째 컬럼에 뭉쳐 들어가는 원인이 된다.
        # options(ndim=2)로 항상 중첩 리스트(2차원)를 강제해 이 문제를 근본적으로
        # 없앤다.
        used_range = ws.used_range
        data = used_range.options(ndim=2).value

        if not data:
            return pd.DataFrame()

        if not isinstance(data[0], list):
            data = [data]

        # used_range는 시트에서 값이 있는 첫 행/열부터 시작하고, 그 시작 위치가
        # 항상 A1(1행 1열)이라는 보장이 없다 — 예를 들어 1행이 완전히 비어 있으면
        # used_range가 2행부터 시작해 data[0]이 물리적 2행이 된다. header_row는
        # "엑셀 절대 행 기준"(위 docstring)으로 문서화돼 있으므로, used_range의
        # 실제 시작 행/열(1-based)만큼 빈 행/열을 앞에 채워 data[0][0]이 항상
        # 물리적 A1이 되도록 맞춘다 — 이 보정이 없으면 앞쪽 행/열이 비어 있는
        # 파일에서 header_row가 가리키는 것보다 한 행(또는 그 이상) 아래를
        # 헤더로 잘못 읽는다.
        row_offset = used_range.row - 1
        col_offset = used_range.column - 1
        if row_offset or col_offset:
            width = len(data[0]) + col_offset
            data = [[None] * width for _ in range(row_offset)] + [
                [None] * col_offset + list(row) for row in data
            ]

        resolved_header_row = _first_nonblank_row(data) if header_row == 'auto' else header_row

        headers = data[resolved_header_row]
        rows = data[resolved_header_row + 1:]

        # 헤더 셀이 비어 있어도(None) 그 컬럼의 데이터는 버리지 않고 보존한다.
        # (엑셀에서 헤더 없이 값만 채워진 컬럼이 있을 수 있음 — "전체 컬럼 보존"이 목표)
        n_cols = len(headers)
        clean_headers = [str(h).strip() if h is not None else f'Unnamed_{i}'
                          for i, h in enumerate(headers)]
        clean_rows = [[row[i] if i < len(row) else None for i in range(n_cols)]
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


def read_xlsx_matrix(file_path: str, sheet: int | str = 0) -> list[list]:
    """엑셀 시트 전체를 헤더 적용 없이 원본 행렬(list of list)로 반환한다.
    read_xlsx()와 같은 xlwings 경로/오프셋 보정(위 docstring 참고)을 쓰되,
    특정 행을 헤더로 잘라내지 않고 물리적 A1 기준 행렬을 그대로 돌려준다.

    헤더 위치를 아직 모르는 채로 원본 레이아웃(머리말 행 포함)을 보존해야
    할 때 쓴다 — 예: merge_job_profile_source.py가 "내 리포트 *.xlsx"의
    앞쪽 안내 행을 그대로 유지한 채 데이터만 이어붙여 저장해야 하는 경우.
    """
    try:
        import xlwings as xw
    except BaseException:
        return _read_matrix_with_pandas(file_path, sheet)

    app = None
    wb = None
    try:
        app = xw.App(visible=False, add_book=False)
        wb = app.books.open(str(file_path))
        ws = wb.sheets[sheet]

        used_range = ws.used_range
        data = used_range.options(ndim=2).value
        if not data:
            return []
        if not isinstance(data[0], list):
            data = [data]

        row_offset = used_range.row - 1
        col_offset = used_range.column - 1
        if row_offset or col_offset:
            width = len(data[0]) + col_offset
            data = [[None] * width for _ in range(row_offset)] + [
                [None] * col_offset + list(row) for row in data
            ]
        return data

    except Exception as exc:
        print(f'[xlwings 실패 → pandas fallback] {file_path}: {exc}')
        return _read_matrix_with_pandas(file_path, sheet)

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


def _read_matrix_with_pandas(file_path: str, sheet: int | str = 0) -> list[list]:
    engine = 'pyxlsb' if str(file_path).lower().endswith('.xlsb') else None
    raw = pd.read_excel(file_path, sheet_name=sheet, header=None, engine=engine)
    return raw.values.tolist()


def _read_with_pandas(file_path: str, sheet: int | str = 0, header_row: int | str = 0) -> pd.DataFrame:
    """xlwings 없이 pandas로 읽는 폴백. xlsb는 pyxlsb 엔진 사용."""
    engine = 'pyxlsb' if str(file_path).lower().endswith('.xlsb') else None
    try:
        if header_row == 'auto':
            raw = pd.read_excel(file_path, sheet_name=sheet, header=None, engine=engine)
            rows = raw.values.tolist()
            resolved_header_row = _first_nonblank_row(rows)
            df = pd.read_excel(file_path, sheet_name=sheet, header=resolved_header_row, engine=engine)
        else:
            df = pd.read_excel(file_path, sheet_name=sheet, header=header_row, engine=engine)
    except Exception:
        if engine == 'pyxlsb':
            raise ImportError(
                '.xlsb 파일 읽기에 pyxlsb 패키지가 필요합니다: pip install pyxlsb'
            )
        raise
    df.columns = [str(c).strip() for c in df.columns]
    return df
