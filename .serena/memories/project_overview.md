# Project Overview

**sms-system** — 숙소(게스트하우스) 예약 관리 + SMS 자동 발송 시스템.

## Purpose
- 네이버 스마트플레이스 예약 동기화
- 객실 배정 (도미토리 성별 잠금 등 포함)
- 템플릿 기반 SMS 자동 발송 스케줄링
- 파티 체크인, 자동응답, 활동 로그, 대시보드
- 멀티 테넌트 (여러 게스트하우스 동시 운영) 지원

## High-level Architecture
1. **Provider Factory + Hot-Swap** — `DEMO_MODE` 환경변수로 Mock/Real 구현 즉시 전환 (`backend/app/factory.py`)
2. **Multi-Tenant Isolation** — ContextVar 기반 자동 테넌트 격리. SQLAlchemy `before_compile` / `before_flush` 이벤트로 SELECT/INSERT 자동 필터/주입 (`backend/app/db/tenant_context.py`)
3. **Template Schedule System** — APScheduler + DB 기반 SMS 자동 발송 스케줄링 (`backend/app/scheduler/`)
4. **Auto-Response Pipeline** — DB Rules → YAML Rules → LLM → Review Queue (confidence ≥ 0.6 자동 발송)

## Top-level Layout
```
sms-system/
├── backend/        # FastAPI + SQLAlchemy + APScheduler
│   ├── app/        # 메인 애플리케이션 코드
│   ├── alembic/    # DB 마이그레이션
│   ├── tests/      # unit + integration
│   ├── scripts/    # 운영 스크립트
│   └── requirements.txt
├── frontend/       # React + Vite + TypeScript + Tailwind
│   └── src/
├── docker-compose.yml          # dev: postgres, redis, chromadb
├── docker-compose.prod.yml
├── docs/
├── tests/                      # 추가 통합 테스트(필요 시)
└── CLAUDE.md       # 상세 프로젝트 가이드 (반드시 참조)
```

## CLAUDE.md
프로젝트 루트의 `CLAUDE.md` 파일이 가장 권위 있는 가이드. 라우터·서비스·모델·디자인 토큰까지 광범위하게 다룸. 아키텍처 결정·디자인 시스템·DB 스키마 질문은 우선 그 파일 참조.
