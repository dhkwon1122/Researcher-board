# 데이터 파이프라인 점검표 (source → goal → logic)

원천 Excel(`data/raw/`) → 처리기(`pipeline/`) → 결과 CSV(`data/processed/`) →
(선택) PostgreSQL 적재. 오케스트레이터는 `pipeline/run_pipeline.py`.

## 공통 규칙
- **읽기**: `excel_reader.read_xlsx()` — 사내 DRM xlsx는 **xlwings(Excel COM)** 로,
  그 외/리눅스는 **openpyxl(pandas) 폴백**. `.xlsb`는 pyxlsb.
- **사번 정규화**: 전 처리기 공통 `norm_id()` → **8자리 제로패딩 문자열**
  (`12345.0` → `'00012345'`), 빈 사번 행 제거.
- **출력**: 모두 `data/processed/*.csv`, `utf-8-sig`. (대부분 `QUOTE_NONNUMERIC`)
- **이중 소스(폴백)**: 전용 처리기가 실패(원본 파일 없음)하면 run_pipeline이
  `{table}_raw.xlsx/csv` 를 **변환 없이 통과** 저장.
- **LLM 사용**: `process_comments`(종합요약, 옵션) 한 곳뿐. 나머지는 순수 규칙 변환.

---

## 요약 표

| 결과 CSV | 소스 파일 (data/raw) | 처리기 | 핵심 처리 |
|---|---|---|---|
| researchers | 인력현황.xlsx | process_researchers | 컬럼 매핑, 생년/입사/승격일 파생 |
| evaluations | T&P_기본_인사_정보.xlsx | process_tp_evaluation | 연도별 등급 롱포맷 + 등급→점수 |
| education | 임직원_학력.xlsx | process_education | 학위 표준화 + **최종학력만** 필터 |
| incentive_selection | 핵심이력.xlsx | process_incentive | 연도 와이드→롱, 선정여부 파생 |
| leadership | 리더십진단.xlsx | process_leadership | 문항→6역량 평균 + **타인평균 파생행** |
| leadership_comments | 리더십진단.xlsx | process_leadership | 평가자별 강점/개선점 분리 |
| tasks | 개인별과제투입기간데이터_260114.xlsb | process_tasks | 날짜/투입률 파싱 + **연속기간 병합** |
| nurturing | 양성_인력_현황.xlsx | process_nurturing | 컬럼 매핑, 날짜/연도 파생 |
| awards | 시상 세부사항.xlsx | process_awards | 컬럼 매핑, 최신순 정렬 |
| patents | 특허 리스트.xlsx | process_patents | 컬럼 매핑만(변환·dedup 없음) |
| comments | comments_raw.xlsx + leadership_comments.csv | process_comments | 통합 + **LLM 종합요약(옵션)** |
| publications | 개인별논문현황_2016_2026.xlsx *(주의)* | process_publications *(주의)* | 기여도 파싱 등 — **⚠ 아래 점검①** |
| technology_transfer | technology_transfer_raw.* | (전용 처리기 없음) | raw 패스스루 or 샘플생성 |
| transfers | transfers_raw.* | (전용 처리기 없음) | raw 패스스루 or 샘플생성 |
| certifications | certifications_raw.* | (전용 처리기 없음) | raw 패스스루 or 샘플생성 |
| succession | succession_raw.* | (전용 처리기 없음) | raw 패스스루 or 샘플생성 |

---

## 처리기별 상세

### researchers ← 인력현황.xlsx (`process_researchers.py`)
- 원본컬럼: 사원번호/성명/현소속부서명/CL/비공식소속부서명/직무/국적/근속기준일/
  법적생년월일성별/성별/승격산정기준일/Knox ID
- 출력: researcher_id, name, department, org_code, position, job_function,
  nationality, gender, birth_year, hire_date, promotion_date, knox_id
- 로직: `법적생년월일성별` 앞 2자리로 birth_year 산출(yy≥26→19xx, <26→20xx);
  hire/promotion_date 다포맷 파싱→`YYYY-MM-DD`; 필수=사원번호·성명.
- 참고: age/tenure 등은 표시 전용, CSV 미저장.

### evaluations ← T&P_기본_인사_정보.xlsx (`process_tp_evaluation.py`)
- 원본: 사번/이름/성별/생년월일 + `2024·2025·2026 연봉등급`
- 출력: researcher_id, year, grade, score  (**등급→점수** 가95/나85/다75/라65/마55)
- 로직: 등급 컬럼 롱포맷, 유효등급만; 부수적으로 **researcher 기본정보(name/gender/
  birth_year) 업데이트 DataFrame도 반환**(researchers 보강용).
- 특이: 사번 컬럼 없으면 **ValueError**(다른 처리기는 return False).

### education ← 임직원_학력.xlsx (`process_education.py`)
- 출력: researcher_id, degree, school, major, graduation_year
- 로직: 학위 표준화(박사>석사>학사>전문대>고교); **연구원별 최종학력만 남김**
  (학사↑ 있으면 고교·전문대 제거 등); 연도는 취득연도 우선, 없으면 졸업일에서.

### incentive_selection ← 핵심이력.xlsx (`process_incentive.py`)
- 원본: 사번 + `22/23/24/25/26` 연도 컬럼
- 출력: researcher_id, year, selected, category, note
- 로직: 와이드→롱; 값 있으면 selected=True·category=값, 없으면 False; note는 공란.

### leadership / leadership_comments ← 리더십진단.xlsx (`process_leadership.py`)
- 문항 1~28을 6역량으로 그룹(미래통찰1-4/성과창출5-8/몰입촉진9-12/인재육성13-16/
  자기관리17-20/저해행동21-26).
- **leadership.csv**: (researcher_id, year, evaluator_group) 별 문항평균→역량평균.
  추가로 동료+상사+부서원을 평균낸 **`evaluator_group='타인평균'` 파생행**.
- **leadership_comments.csv**: 평가자 1인 1행, `commenter_type='리더십_{그룹}'`,
  강점/개선점. → 이후 process_comments가 comments.csv로 병합.

### tasks ← 개인별과제투입기간데이터_260114.xlsb (`process_tasks.py`)
- 원본: KNOXID/과제명/시작일/해제일/투입률
- 출력: researcher_id, task_name, start_date, end_date, input_rate
- 로직: 날짜 8자리→`YYYY-MM-DD`; 투입률 0<v≤1이면 ×100(%);
  **같은 (연구원,과제) 연속 기간 병합**(이전 종료==다음 시작), 투입률은 최신값.

### nurturing ← 양성_인력_현황.xlsx (`process_nurturing.py`)
- 출력: researcher_id, category, subcategory, start_date, end_date, country, city,
  institution, major, service_end_date, year
- 로직: 컬럼 매핑 + 날짜 파싱 + year=start_date 앞 4자리. 필수=사번만.

### awards ← 시상 세부사항.xlsx (`process_awards.py`)
- 출력: researcher_id, award_date, award_type, award_name, awarding_org,
  description, year
- 로직: 매핑 + year 파생; **award_date 내림차순(최신 우선)**.

### patents ← 특허 리스트.xlsx (`process_patents.py`)
- 원본: 사번/접수ID/발명명칭(영·국문)/**진행상태**/지분율/대표발명자여부/현재등급/
  A급구분 (+선택: 출원·등록 번호/일자, 국가)
- 출력: researcher_id, application_id, title, title_ko, status, share_ratio,
  is_lead_inventor, patent_grade, patent_grade_a_sub, (+선택 컬럼)
- 로직: **컬럼 매핑만**. dedup/집계/파생 **없음** → 발명자 N명이면 특허 1건이 N행,
  `진행상태` 원문 그대로(73종). *(집계·등록판정은 앱 화면단에서 수행 — 최근 수정)*

### comments ← comments_raw.xlsx + leadership_comments.csv (`process_comments.py`)
- 출력: researcher_id, year, commenter_type, comment_raw, comment_summary,
  strengths, improvements
- 로직: 부서장 코멘트 + 리더십 강점/개선점 통합. `--llm` 옵션 시 연구원별
  **LLM 종합요약**(`commenter_type='종합요약'`) 사내 API로 생성.

---

## ⚠ 점검 포인트 (확인 필요)

1. **publications 처리기 미연결** — `run_pipeline.py`는 `process_publications`를
   **호출하지 않는다.** 실서비스 경로에선 publications가 "나머지 테이블" 루프의
   **패스스루**(원본 `publications_raw`를 변환 없이 저장) 대상이다. 정교한
   `process_publications.py`(개인별논문현황 파싱: 기여도·교신저자·pub_year 파생)는
   **`generate_sample_data.py`에서만** 호출된다.
   → 실제 논문 원본을 process_publications로 처리하려면 run_pipeline에 배선 필요.

2. **전용 변환기 없는 4개 테이블** — transfers, technology_transfer,
   certifications, succession 은 `{name}_raw` 파일을 **정규화만 하고 통과**하거나,
   없으면 `generate_sample_data.py`가 **랜덤 더미**를 만든다. 실데이터 스키마가
   raw 그대로여야 함(컬럼 매핑 로직 없음).

3. **특허 진행상태 원문 유지** — `status`는 73종 원문 그대로 저장. "출원/등록"
   집계·판정은 파이프라인이 아니라 **앱 화면(`components/detail_tabs._is_registered`
   등)** 에서 수행. (등록 판정 규칙은 최근 보정: `등록전 종료` 등 제외)

4. **DRM/xlwings 의존** — 원본이 DRM xlsx면 **Windows + Excel + xlwings** 필요.
   리눅스/CI는 pandas 폴백이라 DRM 파일은 못 읽음.

5. **파일명·컬럼명 하드코딩** — 각 처리기 상단 상수(파일명, `COL_*`)가 실제
   원본 헤더와 정확히 일치해야 함. 불일치 시 `[ERROR]`(중단) 또는 폴백.

6. **evaluations = researcher 보강 소스** — 이름/성별/생년이 T&P에서도 나와
   researchers를 덮을 수 있음(두 원본 간 정합성 확인 권장).
