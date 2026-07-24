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
# 과제/연구원 전문성 분석·매칭 결과(json/html)의 실행 시각별 누적 아카이브 위치.
# data/processed의 '현재본'(파이프라인 체인용, 매번 덮어씀)과는 별개로,
# result_archive.py가 실행마다 타임스탬프를 붙여 이 아래에 사본을 계속 쌓는다.
RESULT_DIR = os.path.join(RAW_DIR, 'result')
