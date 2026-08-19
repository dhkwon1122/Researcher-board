# 내부 DB: CSV ↔ PostgreSQL

이 대시보드는 데이터를 **CSV(기본)** 또는 **PostgreSQL**에서 읽고 쓸 수 있다.
`DATABASE_URL` 환경변수의 유무로 자동 전환된다.

- `DATABASE_URL` **설정 O** → PostgreSQL 사용
- `DATABASE_URL` **설정 X** (또는 `.env` 없음) → 기존 CSV(`data/processed/*.csv`)로 폴백

코드상 단일 진입점:
- 읽기: `services/data_store.py` → `read_processed(name)`, `read_profile_tables()`
- 쓰기: `services/comments.py` → `upsert_comment(...)`

화면(`pages/*.py`)·컴포넌트는 항상 pandas `DataFrame`을 주고받으므로
백엔드가 바뀌어도 영향이 없다.

---

## 1. PostgreSQL 기동

### 방법 A — Docker Compose (권장)
```bash
docker compose --profile bundled-db up -d   # postgres:16 컨테이너 기동 (DB: researcher_board, 호스트 포트 5433)
```
호스트 포트를 5432가 아닌 5433으로 노출한다(`docker-compose.yml`의 `db` 서비스
`ports` 참고) — 운영 서버에 이미 5432로 떠 있는 기존 PostgreSQL(아래 방법 B,
손대지 않음)과 충돌하지 않기 위함이다.

비밀번호는 기본값이 `postgres`다(개발용) — 실제로 쓸 때는 `.env`(2번 참고)에
`POSTGRES_PASSWORD=원하는_비밀번호`를 채운 뒤 위 명령을 실행할 것. 이 값이
컨테이너의 실제 슈퍼유저 비밀번호가 되므로, 아래 `DATABASE_URL`의 비밀번호도
반드시 똑같이 맞춰야 한다.

### 방법 B — 기존/사내 PostgreSQL 사용
이미 운영 중인 인스턴스가 있으면 DB만 하나 생성한다. (이 프로젝트는 운영
서버의 기존 PostgreSQL을 그대로 쓰지 않고 방법 A/C로 별도 5433 포트 인스턴스를
띄우는 것을 기본으로 한다 — 기존 DB를 건드리기 어려운 경우를 위한 참고용.)
```sql
CREATE DATABASE researcher_board;
```

### 방법 C — Windows 네이티브 설치 (사내 PC 권장)
사내 PC에 Docker 사용이 어려우면 설치 관리자로 직접 설치한다.

1. https://www.postgresql.org/download/windows/ → **"Download the installer"**
   (EDB 배포판) 다운로드 후 실행.
2. 설치 마법사 주요 선택:
   - **Components**: PostgreSQL Server, **Command Line Tools**(psql), pgAdmin 4 체크.
     Stack Builder는 해제 가능.
   - **Password**: `postgres` 슈퍼유저 비밀번호 설정 → 꼭 기억 (예: `postgres`).
   - **Port**: `5433` 으로 변경(기본 `5432`가 아님) — 같은 서버에 이미 떠 있는
     기존 PostgreSQL(손대지 않음)과 충돌하지 않기 위함.
   - **Locale**: 기본값.
3. 설치 후 PostgreSQL이 Windows 서비스로 자동 등록·실행된다(재부팅 시 자동 시작).
4. **DB 생성** — 함께 설치된 **SQL Shell (psql)** 실행 → 접속 프롬프트는
   전부 Enter(기본값), 비밀번호만 입력 후:
   ```sql
   CREATE DATABASE researcher_board;
   \q
   ```
   (또는 pgAdmin 4에서 Databases 우클릭 → Create → Database)

> **psql이 명령어로 안 먹힐 때**: 설치 시 PATH 미등록이 원인.
> `C:\Program Files\PostgreSQL\16\bin` 을 시스템 환경변수 PATH에 추가하거나
> "SQL Shell (psql)" 바로가기를 사용한다.

이후 적재·실행은 아래 2~4단계를 그대로 따른다. PowerShell/CMD에서는
경로 구분자만 역슬래시를 쓴다: `python pipeline\load_to_db.py`.

---

## 2. 접속 설정

```bash
cp .env.example .env
# 필요 시 사용자/비밀번호/호스트 수정
```

`.env` 내용 (docker-compose 기본값과 일치, 포트 5433 — 위 1번 참고):
```
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5433/researcher_board
```

> `.env` 는 `.gitignore` 에 포함돼 커밋되지 않는다.
> 비밀번호에 `@ : / ?` 등 특수문자가 있으면 URL 인코딩이 필요하다
> (예: `@` → `%40`).

---

## 3. 데이터 적재

### 3-0. (선택) DRM 원본 → raw CSV → DB 스테이징

DRM xlsx를 직접 다루는 경우 아래 2단계를 먼저 거친다 — 자세한 구조는
`docs/data_pipeline.md` 참고.

```bash
# ① Windows(Excel 설치 PC)에서: DRM xlsx → data/raw_csv/*.csv (전 컬럼, DRM 제거)
python pipeline\xlsx_to_raw_csv.py

# data/raw_csv/ 를 리눅스 서버로 복사한 뒤

# ② 리눅스 서버에서: raw CSV → Postgres {name}_stg 스테이징 테이블
python pipeline/load_raw_to_db.py
```

`DATABASE_URL` 이 설정돼 있으면 `run_pipeline.py`가 시작할 때 ②를 자동으로
호출하므로, 보통은 `data/raw_csv/`만 서버에 올려두고 아래 3-1을 실행하면 된다.
DB 없이 CSV만으로 개발할 때는 이 단계를 건너뛰어도 된다 — process_*.py가
`data/raw_csv/*.csv`를 직접 읽는다.

### 3-1. 최종 테이블 적재

```bash
pip install -r requirements.txt          # sqlalchemy, psycopg2-binary, python-dotenv 포함
python pipeline/load_to_db.py            # schema.sql 적용 + CSV 15개 → DB 적재
```

`load_to_db.py` 는 `pipeline/schema.sql` 을 먼저 실행(테이블·제약·인덱스 생성)한 뒤
각 테이블을 `TRUNCATE` 하고 해당 CSV를 적재한다. 반복 실행해도 안전(멱등).

전체 파이프라인 실행 시에도 `DATABASE_URL` 이 감지되면 raw 스테이징 적재(3-0-②)와
최종 적재(3-1)가 모두 자동으로 실행된다.
```bash
python pipeline/run_pipeline.py
```

---

## 4. 실행

```bash
python app.py        # http://<사내IP>:8050
```

`DATABASE_URL` 이 설정돼 있으면 세 화면 모두 PostgreSQL에서 데이터를 읽는다.
프로필 화면의 코멘트 입력은 `INSERT ... ON CONFLICT` 로 upsert 된다
(`comments` 테이블의 `(researcher_id, year, commenter_type)` UNIQUE 제약 사용).

---

## 5. 스키마

`pipeline/schema.sql` 에 15개 테이블이 정의돼 있다. 모든 컬럼은 `TEXT` 로,
8자리 zero-pad 사번 등 문자열 보존을 위해 기존 CSV(`dtype=str`) 동작과 일치시켰다.

| 테이블 | 비고 |
|--------|------|
| researchers, evaluations, education, incentive_selection, leadership, transfers, tasks, nurturing, awards, publications, patents, technology_transfer, certifications, succession | 조회용 |

이와 별개로 `load_raw_to_db.py`가 만드는 `{name}_stg` 스테이징 테이블(예:
`researchers_stg`, `publications_stg` 등, 총 10개 — 목록은 `pipeline/sources.py`)
이 있다. 원본 xlsx 헤더를 그대로 보존한 전 컬럼 TEXT 테이블로, `process_*.py`가
읽어서 위 최종 테이블로 가공하는 중간 산출물이다. 화면 코드는 이 테이블을
직접 조회하지 않는다.
| comments | upsert (UNIQUE: researcher_id, year, commenter_type) |

---

## 6. CSV로 되돌리기

`.env` 를 지우거나 `DATABASE_URL` 을 비우면 자동으로 CSV 폴백으로 돌아간다.
```bash
unset DATABASE_URL
python app.py
```

---

## 7. 운영 서버 배포 시 — 원천/가공 CSV·JSON 파일 권한

화면(`pages/*.py`)의 역할별 접근 제어(`services/auth.py`의 `ROLE_PERMISSIONS`)는
Dash/Flask 화면을 거칠 때만 적용되는 **애플리케이션 레벨** 제어다. `data/raw*`,
`data/raw_csv/*.csv`, `data/processed/*.csv`(및 LLM 파생 JSON)는 서버
파일시스템에 그대로 남아 있고, `pandas.to_csv()`가 만드는 파일은 보통 서버
기본 umask(흔히 644 — 소유자 외에도 읽기 가능)로 생성되므로, **서버에 셸
계정이 있는 사람이면 화면의 권한 설정과 무관하게 파일을 그냥 열어볼 수
있다.** 개발/CSV 전용 환경에서는 크게 문제되지 않지만, 운영 서버에 올릴
때는 반드시 잠가야 한다.

- `pipeline/load_to_db.py`는 각 CSV를 DB에 성공적으로 적재한 직후 그 파일을
  `chmod 600`(소유자만 읽기/쓰기)으로 자동으로 좁힌다 — 배포 스크립트
  실행을 깜빡해도 최소한의 보호가 남는다.
- 그와 별개로, `data/` 디렉터리 전체(raw/raw_csv/processed, 파이프라인이 아직
  건드리지 않은 파일 포함)를 한 번에 잠그려면:
  ```bash
  scripts/secure_data_permissions.sh          # 기본: <저장소>/data
  scripts/secure_data_permissions.sh /path/to/data   # 경로 직접 지정
  ```
  배포 때마다(또는 파이프라인 실행 후) 다시 실행하는 것을 권장한다 — 소유권
  (chown)은 배포 환경마다 실행 계정이 달라 이 스크립트가 바꾸지 않으므로,
  `data/`가 앱을 구동하는 계정 소유인지는 별도로 확인할 것.
- **DB 자체 접근도 같은 기준으로 좁혀야 의미가 있다** — CSV를 다 잠가도
  `psql` 접속 계정을 아무나 쓸 수 있거나 DB 포트(5433)가 불필요하게 넓은
  네트워크에 노출돼 있으면, 구멍이 파일에서 DB 크리덴셜로 옮겨갈 뿐이다.
