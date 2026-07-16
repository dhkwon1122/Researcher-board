# 데이터 파이프라인 점검표 (source → goal → logic)

원천 Excel(`data/raw/`) → 처리기(`pipeline/`) → 결과 CSV(`data/processed/`) →
(선택) PostgreSQL 적재. 오케스트레이터: `pipeline/run_pipeline.py`.

## 공통 규칙
- **읽기**: `excel_reader.read_xlsx()` — 사내 DRM xlsx는 **xlwings(Excel COM)**,
  그 외/리눅스는 **openpyxl(pandas) 폴백**. `.xlsb`는 pyxlsb.
- **사번 정규화**: 전 처리기 공통 `norm_id()` → **8자리 제로패딩 문자열**
  (`12345.0` → `'00012345'`), 빈 사번 행 제거.
- **출력**: `data/processed/*.csv`, `utf-8-sig`.
- **이중 소스(폴백)**: 전용 처리기가 원본 파일을 못 찾으면(`return False`)
  run_pipeline이 `{table}_raw.xlsx/csv`를 **변환 없이 통과** 저장.
- **LLM**: `process_comments`(종합요약, `--llm` 옵션)에서만 사용.

## 처리 순서 (run_pipeline.run)
researchers → evaluations(T&P) → patents → nurturing → awards → education →
leadership → incentive → **publications** → (passthrough: technology_transfer,
transfers, certifications, succession) → comments → (DATABASE_URL 있으면 DB 적재)

---

## 1. researchers ← `인력현황.xlsx` (`process_researchers.py`)

| 원본 컬럼 | 출력 컬럼 | 계산 |
|---|---|---|
| 사원번호 | researcher_id | `norm_id` 8자리 |
| 성명 | name | strip |
| 현소속부서명 | department | strip |
| 비공식소속부서명 | org_code | strip |
| CL | position | strip |
| 직무 | job_function | strip |
| 국적 | nationality | strip |
| 성별 | gender | strip |
| 법적생년월일성별 | birth_year | **앞 2자리(yy) → yy≥26이면 19yy, <26이면 20yy** |
| 근속기준일_그룹입사일 | hire_date | 다포맷(`%Y-%m-%d`,`/`,`.`,`%Y%m%d`) → `YYYY-MM-DD` |
| 승격산정기준일자 | promotion_date | 위와 동일 파싱 |
| Knox ID | knox_id | strip |

- **필수**: 사원번호·성명 (없으면 `[ERROR]` 후 return False → researchers_raw 폴백).
- age/tenure/근속연수 등은 화면 표시 전용이며 **CSV에 저장 안 함**.
- 정렬: researcher_id.

## 2. evaluations ← `T&P_기본_인사_정보.xlsx` (`process_tp_evaluation.py`)

| 원본 | 출력 | 계산 |
|---|---|---|
| 사번 | researcher_id | `norm_id` |
| 2024/2025/2026 연봉등급 | year, grade | **와이드→롱**(연도별 1행), 유효등급(가~마)만 |
| (grade 파생) | score | **등급→점수: 가95·나85·다75·라65·마55** |

- **부가 산출물**: `(성공여부, researcher_updates)` 튜플 반환 — 이름/성별/
  생년(생년월일 앞 4자리, 1900<y≤2010)을 담은 DF로 **researchers 보강용**.
- 유효하지 않은 등급은 카운트 후 `[WARN]` 제외. 연도별 등급 분포 로그 출력.
- **특이**: 사번 컬럼 없으면 **ValueError raise**(다른 처리기는 return False).
- 정렬: (researcher_id, year).

## 3. patents ← `특허 리스트.xlsx` (`process_patents.py`)

| 원본 | 출력 | 계산 |
|---|---|---|
| 사번 | researcher_id | `norm_id` |
| 접수ID | application_id | strip |
| 발명명칭 - 영문 / 발명명칭 | title / title_ko | strip |
| 진행상태 | status | **원문 그대로**(73종) |
| 지분율 | share_ratio | strip |
| 대표발명자여부 | is_lead_inventor | strip |
| 현재등급 / 현재등급 - A급구분 | patent_grade / patent_grade_a_sub | strip |
| (선택) 출원·등록 번호/일자, 국가/국가명 | application_no, application_date, registration_no, registration_date, country | 있으면 매핑, 없으면 빈칸 |

- **매핑만** 수행 — dedup/집계/파생 **없음**. 발명자 N명이면 특허 1건이 **N행**.
- 출원/등록 **집계·등록판정은 앱 화면**(`components/detail_tabs._is_registered`:
  `status`에 '등록' 포함 && `등록전`·`등록료불납` 등 제외; 출원=특허 수(application_id
  중복 제거))에서 수행. 파이프라인은 원문만 보존.
- **필수**: 사번·접수ID. 정렬: (researcher_id, application_id).

## 4. nurturing ← `양성_인력_현황.xlsx` (`process_nurturing.py`)

| 원본 | 출력 | 계산 |
|---|---|---|
| 사번 | researcher_id | `norm_id` |
| 양성구분/세부양성구분 | category/subcategory | strip |
| 연수시작일/연수종료일/의무근무 종료일 | start_date/end_date/service_end_date | `to_datetime`→`%Y-%m-%d` |
| 국가/도시/교육기관/전공학과 | country/city/institution/major | strip |
| (start_date 파생) | year | start_date 앞 4자리 |

- **필수**: 사번만. 나머지 컬럼은 없어도 빈값. 정렬: (researcher_id, start_date).

## 5. awards ← `시상 세부사항.xlsx` (`process_awards.py`)

| 원본 | 출력 | 계산 |
|---|---|---|
| 사번 | researcher_id | `norm_id` |
| 수상일 | award_date | `to_datetime`→`%Y-%m-%d` |
| 수상 유형/수상명/수여기관/설명 | award_type/award_name/awarding_org/description | strip |
| (award_date 파생) | year | 앞 4자리 |

- **필수**: 사번만. 정렬: researcher_id ↑, **award_date ↓(최신 우선)**.

## 6. education ← `임직원_학력.xlsx` (`process_education.py`)

| 원본 | 출력 | 계산 |
|---|---|---|
| 사번 | researcher_id | `norm_id` |
| 학력 | degree | **학위 표준화**(DEGREE_MAP 키워드로 박사>석사>학사>전문대>고교) |
| 학교명/전공 | school/major | strip |
| 학위 취득 연도 / 졸업일 | graduation_year | 취득연도 우선, 없으면 졸업일에서 연도(1900~2100) |

- **최종학력 필터**: 연구원별로 학사↑ 있으면 고교·전문대 제거, 전문대 있으면 고교 제거.
- 정렬: (researcher_id, 학위순위 박사0..고교4).

## 7. incentive_selection ← `핵심이력.xlsx` (`process_incentive.py`)

| 원본 | 출력 | 계산 |
|---|---|---|
| 사번 | researcher_id | `norm_id` |
| 22/23/24/25/26 (연도 컬럼) | year | **와이드→롱**, 헤더 `'22.0'`→`'22'` 정규화 |
| (연도 셀 값) | selected, category | **값 있으면 selected=True·category=셀값, 없으면 False·''** |
| — | note | 항상 빈 문자열 |

- **필수**: 사번 + 연도 컬럼 ≥1개. 정렬: (researcher_id, year).

## 8. leadership / leadership_comments ← `리더십진단.xlsx` (`process_leadership.py`)

문항 1~28 (역량 분류: 미래통찰1-4·성과창출5-8·몰입촉진9-12·인재육성13-16·
자기관리17-20·저해행동21-26).

**leadership.csv** (역량 점수)

| 출력 컬럼 | 계산 |
|---|---|
| researcher_id | `진단대상자ID` → `norm_id` |
| year | `평가연도` 컬럼(있으면 숫자화, 실패/부재 시 현재연도) |
| evaluator_group | `평가자그룹명` |
| 미래통찰~저해행동(6개) | **(researcher_id, year, group)별 문항 평균 → 역량별 소속문항 평균**(round2). 문항값은 쉼표→소수점 후 숫자화 |
| (파생행) evaluator_group='타인평균' | 동료+상사+부서원 그룹 역량점수를 (researcher_id, year)로 평균 |

**leadership_comments.csv** (주관식) — 평가자 1인 1행:
`commenter_type='리더십_{그룹}'`, `strengths=강점`, `improvements=개선점`,
comment_raw/summary는 빈칸. (강점·개선점 둘 다 비면 스킵) → **process_comments가 병합**.

- **필수**: 진단대상자ID·평가자그룹명. 정렬: (researcher_id, year, group).

## 9. publications ← `개인별논문현황_2016_2026.xlsx` (`process_publications.py`)
※ 헤더가 **3번째 행**(`header_row=2`). *(이번에 run_pipeline에 정식 배선)*

| 원본 | 출력 | 계산 |
|---|---|---|
| 사번 | researcher_id | `norm_id` |
| 저자구분 | author_type | strip |
| 교신저자여부 | is_corresponding | **y/yes/예/o/○/1/true/교신 → True** |
| 논문제목/게재·발표처/발표형태 | title/journal/pub_type | strip |
| 실적일 | pub_date | 8자리→`YYYY-MM-DD` |
| (pub_date 파생) | pub_year | 앞 4자리 |
| 저자순위/총저자수 | author_rank/total_authors | `.0` 제거 후 정수 |
| 전체 저자정보 | author_info | 끝의 `(기여도 : XX%)` **제거한 텍스트** |
| 전체 저자정보 | contribution | 끝의 `(기여도 : XX%)`에서 **숫자만 추출** |

- **필수**: 위 10개 원본 컬럼 전체. 없으면 return False → publications_raw 폴백.
- 정렬: researcher_id ↑, pub_date ↓.

## 10. comments ← `comments_raw.xlsx` + `leadership_comments.csv` (`process_comments.py`)

출력: researcher_id, year, commenter_type, comment_raw, comment_summary,
strengths, improvements

- **부서장 코멘트**(comments_raw): commenter_type 기본 '부서장'. `--llm` 시
  단건 요약(comment_summary/strengths/improvements), 아니면 원문/앞120자.
- **리더십 코멘트**: leadership_comments.csv를 concat.
- **LLM 종합요약**(`--llm`): 연구원별 부서장+리더십 코멘트를 취합→사내 API로
  통합 요약 JSON 생성→`commenter_type='종합요약'` 행 추가(year=최근연도).
- 정렬: (researcher_id, commenter_type, year).

## 11. 전용 변환기 없는 4개 테이블 — passthrough
**technology_transfer / transfers / certifications / succession**
- `run_pipeline`이 `{table}_raw.xlsx/csv`를 읽어 **researcher_id만 정규화 후 그대로 저장**
  (컬럼 매핑·파생·집계 없음). raw 없으면 `[SKIP]`.
- 개발용 더미는 `generate_sample_data.py`가 전용 generate 함수로 랜덤 생성
  (예: succession은 부서별 Ready Now/Later 선발, certifications는 TOEIC/OPIc/기술사 확률 생성).
- → **실데이터 raw의 컬럼명이 최종 스키마와 일치해야 함**(변환 로직 없음).

---

## ⚠ 점검 포인트

1. **publications 배선 완료** — (구) run_pipeline이 process_publications를 호출하지
   않아 논문이 raw 패스스루였음 → **이제 전용 처리기로 연결**(기여도·pub_year·교신
   파싱 적용, 실패 시 publications_raw 폴백).
2. **전용 변환기 없는 4개 테이블** — raw 스키마가 최종 컬럼과 정확히 일치해야 함.
3. **특허 진행상태 원문 유지** — 집계/등록판정은 앱 화면(`_is_registered`)에서.
   '등록'을 포함하나 미등록인 상태(`등록전 종료`,`등록료불납`)는 제외 처리됨.
4. **DRM/xlwings 의존** — DRM xlsx는 Windows+Excel+xlwings 필요(리눅스는 못 읽음).
5. **파일명·`COL_*` 하드코딩** — 각 처리기 상단 상수가 실제 헤더와 일치해야 함.
6. **evaluations가 researchers 보강** — 이름/성별/생년이 T&P에서도 나와 정합성 확인 권장.
