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
docker compose up -d        # postgres:16 컨테이너 기동 (DB: researcher_board, 포트 5432)
```

### 방법 B — 기존/사내 PostgreSQL 사용
이미 운영 중인 인스턴스가 있으면 DB만 하나 생성한다.
```sql
CREATE DATABASE researcher_board;
```

---

## 2. 접속 설정

```bash
cp .env.example .env
# 필요 시 사용자/비밀번호/호스트 수정
```

`.env` 내용 (docker-compose 기본값과 일치):
```
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/researcher_board
```

> `.env` 는 `.gitignore` 에 포함돼 커밋되지 않는다.

---

## 3. 데이터 적재

```bash
pip install -r requirements.txt          # sqlalchemy, psycopg2-binary, python-dotenv 포함
python pipeline/load_to_db.py            # schema.sql 적용 + CSV 15개 → DB 적재
```

`load_to_db.py` 는 `pipeline/schema.sql` 을 먼저 실행(테이블·제약·인덱스 생성)한 뒤
각 테이블을 `TRUNCATE` 하고 해당 CSV를 적재한다. 반복 실행해도 안전(멱등).

전체 파이프라인 실행 시에도 `DATABASE_URL` 이 감지되면 마지막에 자동 적재된다.
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
| comments | upsert (UNIQUE: researcher_id, year, commenter_type) |

---

## 6. CSV로 되돌리기

`.env` 를 지우거나 `DATABASE_URL` 을 비우면 자동으로 CSV 폴백으로 돌아간다.
```bash
unset DATABASE_URL
python app.py
```
