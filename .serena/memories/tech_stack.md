# Tech Stack

## Backend (Python 3, `backend/`)
- **Framework**: FastAPI 0.109, Uvicorn
- **ORM**: SQLAlchemy 2.0, Alembic 마이그레이션
- **DB**: SQLite(데모) / PostgreSQL(운영, psycopg2-binary)
- **Cache/Queue**: Redis 5.0
- **Validation**: Pydantic 2.x + pydantic-settings
- **Scheduler**: APScheduler 3.10
- **Auth**: PyJWT, bcrypt
- **Rate limit**: slowapi
- **HTTP client**: httpx 0.26
- **LLM**: anthropic SDK (Claude API; 운영 모드)
- **Monitoring**: sentry-sdk[fastapi]
- **외부 SMS**: Aligo HTTP API (`real/sms.py`)
- **외부 예약**: 네이버 스마트플레이스 (쿠키 인증, `real/reservation.py`)

## Frontend (`frontend/`)
- **Build**: Vite 5 + TypeScript 5.3
- **UI**: React 18 + React Router 6
- **Style system**: Tailwind CSS 4 + Flowbite React + (shadcn 설치되어 있음)
- **Toss Invest 디자인 시스템** (CLAUDE.md 의 Frontend Design Guidelines 절 참조)
- **State**: Zustand
- **HTTP**: Axios (자동 토큰 갱신, X-Tenant-Id 헤더 주입 — `src/services/api.ts`)
- **Forms**: react-hook-form + zod
- **DnD**: @dnd-kit (객실 배정 드래그앤드롭)
- **Charts**: recharts
- **Icons**: lucide-react
- **Date**: dayjs
- **Toast**: sonner
- **Monitoring**: @sentry/react

## Infra
- Docker Compose (postgres, redis, chromadb)
- Nginx (production: `frontend/nginx*.conf`)
- 타임존: Asia/Seoul (KST)
