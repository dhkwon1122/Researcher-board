"""
사진 파일 탐색 경로 진단 스크립트
실행: python debug_photo.py [사번]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.data_store import ASSETS_DIR, RAW_DIR

rid_input = sys.argv[1] if len(sys.argv) > 1 else '00000001'
rid = str(rid_input).zfill(8)
rid_stripped = str(int(rid)) if rid.isdigit() else rid
rid_variants = list(dict.fromkeys([rid, rid_stripped]))

print(f'=== 사번: {rid_input}  →  탐색 ID 목록: {rid_variants}')
print(f'RAW_DIR : {RAW_DIR}')
print(f'ASSETS  : {os.path.join(ASSETS_DIR, "photos")}')
print()

found = False
for r in rid_variants:
    for ext in ('png', 'jpg', 'jpeg', 'PNG', 'JPG', 'JPEG'):
        for label, base in [('assets/photos', os.path.join(ASSETS_DIR, 'photos')),
                             ('data/raw',      RAW_DIR)]:
            path = os.path.join(base, f'{r}.{ext}')
            exists = os.path.exists(path)
            marker = '✓ 발견' if exists else '✗'
            print(f'  {marker}  {path}')
            if exists:
                found = True

if not found:
    print('\n[결과] 사진 파일을 찾지 못했습니다.')
    print(f'  → assets/photos/{rid}.jpg  또는  data/raw/{rid}.jpg 에 파일을 놓으세요.')
else:
    print('\n[결과] 위 ✓ 경로의 파일이 사용됩니다.')
