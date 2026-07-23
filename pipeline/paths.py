"""
공용 경로 상수

pipeline/*.py 모듈 대부분이 반복 계산하던 BASE_DIR/RAW_DIR/OUT_DIR을 한 곳에서
정의한다. 필요한 이름만 골라서 임포트하면 된다:

    from paths import RAW_DIR, OUT_DIR
"""

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, 'data', 'raw')
OUT_DIR = os.path.join(BASE_DIR, 'data', 'processed')
