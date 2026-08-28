"""
어학자격 처리 모듈

원천: source_reader.read_source('language_qualification')
  → DB language_qualification_stg 테이블 또는 data/raw_csv/language_qualification.csv
  (1단계 xlsx_to_raw_csv.py가 data/raw/어학자격 *.xlsx를 DRM 제거해 만든 사본)
출력 파일: data/processed/language_qualification.csv

원본 컬럼 구조(2026-08-29 사용자 확인): A열=사번, B~Y열은 이 기능과 무관한
컬럼, Z열부터 언어별로 6컬럼씩 반복된다 — "{언어} 회화", 발급일, 만료일,
"{언어} 필기", 발급일, 만료일, 다음 언어... 언어 종류는 고정돼 있지 않고
새 언어를 취득한 사람이 생기면 그 언어의 6컬럼 블록이 파일에 새로 추가된다.
"필기" 관련 값은 이번 기능에서 쓰지 않는다(사용자 확정).

"발급일"/"만료일" 헤더 자체는 모든 언어 블록에서 똑같은 문자열이라(엑셀이
파일을 읽을 때 자동으로 뒤에 .1/.2 등을 붙여 구분하긴 하지만) 이름만으로는
어느 언어의 만료일인지 알 수 없다 — 그래서 이 모듈은 "{언어} 회화" 컬럼을
이름으로 찾은 뒤, 그 컬럼의 위치(인덱스) + 2번째 컬럼을 그 언어의 만료일로
읽는다(사용자 확정 — 회화, 발급일, 만료일 순서가 고정이라는 전제).
이 위치 오프셋 규칙이 실제 파일과 어긋나면(예: 만료일 앞뒤로 컬럼이
추가/삭제되면) 엉뚱한 값이 그 언어의 만료일로 잘못 저장될 수 있으니, 원본
파일 구조가 바뀌면 이 모듈의 _EXPIRATION_OFFSET을 함께 확인할 것.

출력 스키마(long, 사람당 보유 언어 수만큼 여러 행):
  researcher_id, language, speak_grade, expiration_date
  speak_grade는 원본 "{언어} 회화" 셀 값을 그대로 저장한다(예: "2등급" —
  등급 문자가 이미 포함돼 있어 이 모듈이 따로 가공하지 않는다, 사용자 확정).

── 누적하지 않음(사용자 확정) ────────────────────────────────────────────────
다른 대부분의 process_*.py는 이번 파일에 없는 사람의 기존 데이터를 보존하는
업서트(merge_utils.write_merged)를 쓰지만, 어학자격은 "현재 재직자 기준으로만
의미가 있는 자료"라 매번 파일 전체로 통째로 교체한다 — 이번 업로드에 없는
사람(예: 원본에서 빠진 사람)의 기존 어학 데이터는 다음 실행 후 사라진다
(의도된 동작, 다른 대부분 테이블의 "이번 파일에 없어도 보존" 원칙과 다름).
그래서 evaluations/tech_ownership처럼 valid_year/valid_month 시점 보호나
_history.csv도 두지 않는다.

컬럼명이 다를 경우 파일 상단의 COL_ID/_EXPIRATION_OFFSET/_HEADER_ROW를
실제 헤더에 맞게 수정하세요.
"""

import csv
import os
import sys

import pandas as pd

LANG_PATTERN = '어학자격 *.xlsx'
_HEADER_ROW = 6  # 사용자 확인(2026-08-29) — 실제 헤더는 7번째 행(1~6행 무시)

COL_ID = '사번'
_SPEAK_SUFFIX = ' 회화'
_EXPIRATION_OFFSET = 2  # "{언어} 회화" 컬럼 기준 몇 번째 뒤 컬럼이 만료일인지

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import clean_str, norm_id, parse_flexible_date, read_xlsx  # noqa: E402
from source_files import find_latest  # noqa: E402
from source_reader import read_source  # noqa: E402


def _find_language_specs(columns: list) -> list[tuple[str, int, int]]:
    """"{언어} 회화" 컬럼을 전부 찾아 (언어명, 회화 컬럼 위치, 만료일 컬럼
    위치) 리스트로 반환한다. 만료일 컬럼이 실제로 "만료일"이라는 이름이
    아니면(위치 오프셋 가정이 어긋났을 가능성) 경고만 남기고 그래도 그
    위치를 그대로 쓴다(사용자가 확정한 규칙이므로 값 자체는 신뢰)."""
    specs = []
    for idx, col in enumerate(columns):
        if not col.endswith(_SPEAK_SUFFIX):
            continue
        language = col[:-len(_SPEAK_SUFFIX)].strip()
        if not language:
            continue
        exp_idx = idx + _EXPIRATION_OFFSET
        if exp_idx >= len(columns):
            print(f'  [WARN] "{col}" 뒤에 만료일 컬럼이 없어(파일 끝) 이 언어는 건너뜀')
            continue
        if not str(columns[exp_idx]).strip().startswith('만료일'):
            print(f'  [WARN] "{col}"의 {_EXPIRATION_OFFSET}번째 뒤 컬럼("{columns[exp_idx]}")이 '
                  f'"만료일"이 아닙니다 — 그래도 그 위치 값을 만료일로 사용합니다. '
                  f'원본 파일 구조를 확인해주세요.')
        specs.append((language, idx, exp_idx))
    return specs


def process(raw_dir: str = RAW_DIR) -> bool:
    if raw_dir == RAW_DIR:
        df = read_source('language_qualification')
        if df is None:
            print('[SKIP] language_qualification 원천 데이터 없음 '
                  '(DB language_qualification_stg 또는 data/raw_csv/language_qualification.csv)')
    else:
        raw_path = find_latest(raw_dir, LANG_PATTERN)
        if raw_path is not None:
            df = read_xlsx(raw_path, header_row=_HEADER_ROW)
        else:
            df = None
            print(f'[SKIP] {LANG_PATTERN} 파일 없음({raw_dir})')

    if df is None:
        return False
    if df.empty:
        print('[SKIP] 파일 읽기 결과가 비어 있습니다.')
        return False

    df.columns = [str(c).strip() for c in df.columns]
    columns = list(df.columns)

    if COL_ID not in columns:
        sample = ', '.join(f'"{c}"' for c in columns[:15])
        print(
            f'[ERROR] 필수 컬럼 없음: [{COL_ID}]\n'
            f'  파일의 컬럼(앞 15개): {sample}\n'
            f'  process_language_qualification.py 상단의 COL_ID를 실제 헤더에 맞게 수정하세요.'
        )
        return False

    language_specs = _find_language_specs(columns)
    if not language_specs:
        print(f'[SKIP] "{{언어}}{_SPEAK_SUFFIX}" 형태의 컬럼을 찾지 못했습니다 — 헤더: '
              f'{", ".join(columns[:15])}...')
        return False

    rid_series = df[COL_ID].apply(norm_id)

    records = []
    for language, speak_idx, exp_idx in language_specs:
        speak_series = df.iloc[:, speak_idx].apply(clean_str)
        exp_series = df.iloc[:, exp_idx].apply(parse_flexible_date)
        for rid, grade, exp in zip(rid_series, speak_series, exp_series):
            if not rid or not grade:  # 사번 없거나(사용자 확정 — 제외) 회화 등급 없는 행은 건너뜀
                continue
            records.append({
                'researcher_id': rid, 'language': language,
                'speak_grade': grade, 'expiration_date': exp,
            })

    result = pd.DataFrame(records, columns=['researcher_id', 'language', 'speak_grade', 'expiration_date'])
    result = result.sort_values(['researcher_id', 'language']).reset_index(drop=True)

    # 누적하지 않음(사용자 확정) — merge_utils.write_merged() 업서트 대신
    # 매번 파일 전체를 통째로 교체한다.
    out_path = os.path.join(OUT_DIR, 'language_qualification.csv')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    result.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)

    n = result['researcher_id'].nunique() if not result.empty else 0
    langs = sorted({s[0] for s in language_specs})
    print(f'[OK]   language_qualification.csv 저장 (총 {len(result)}행, {n}명, '
          f'인식된 언어: {", ".join(langs)})')
    return True


if __name__ == '__main__':
    process()
