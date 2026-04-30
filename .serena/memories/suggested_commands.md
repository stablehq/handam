# Suggested Commands

## Backend
```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# DB 초기화 (스키마 변경 후 필수)
rm -f sms.db
python -m app.db.seed

# 개발 서버
uvicorn app.main:app --reload                 # http://localhost:8000
uvicorn app.main:app --reload --port 8001     # 다른 포트

# Swagger UI: http://localhost:8000/docs

# 마이그레이션
alembic revision --autogenerate -m "Description"
alembic upgrade head
alembic downgrade -1
```

## Backend Tests (pytest)
```bash
cd backend
source venv/bin/activate
pytest                          # 전체
pytest tests/unit               # 유닛만
pytest tests/integration        # 통합만
pytest tests/integration/test_send_pipeline.py -v
pytest -k "room_assign"         # 키워드 매칭
```
린트/포맷팅 도구는 명시적으로 설정되어 있지 않음 (pyproject.toml 없음). 새로 도입 시 사용자 확인 필요.

## Frontend
```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
npm run build        # tsc + vite build (타입체크 포함)
npm run preview
```

## Docker (선택, 보통 SQLite 로 충분)
```bash
docker compose up -d                 # postgres, redis, chromadb
docker compose up -d postgres
docker compose down
docker compose logs -f
```

## 시스템(Linux/WSL2)
일반 Linux 명령 그대로 사용 가능: `ls`, `cd`, `grep`, `find`, `git`, `rg`. 별도 특이사항 없음.

## 자주 쓰는 git 흐름
```bash
git status
git log --oneline -20
git diff
git diff --stat HEAD~5
```
