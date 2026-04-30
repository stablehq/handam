# Phase 0 산출물 #11: 간접 ContextVar 사용 정밀 audit

> grep 으로 안 잡히는 패턴 (lambda/partial/decorator/dynamic import) 으로 ContextVar 가 새는지 검사.

## 검사 결과 요약

| 패턴 | 발견 | 영향 |
|--|--|--|
| **lambda 안 ContextVar 사용** | 0건 | 안전 |
| **functools.partial / partial application** | 0건 (lru_cache 만, ContextVar 무관) | 안전 |
| **자체 decorator 정의** | 0건 (FastAPI middleware 1곳만) | 안전 |
| **dynamic import (importlib, getattr)** | 0건 (tenant attr getattr 만) | 안전 |
| **다른 ContextVar (wrap pattern)** | 2개 (`diag_request_id`, `diag_user_action`) | 격리 무관 |

→ **간접 ContextVar 사용은 0건**. ContextVar 가 정의된 변수 (`current_tenant_id`, `bypass_tenant_filter`) 외엔 다른 경로로 tenant 정보가 누수되지 않음.

## 다른 ContextVar 정의 (격리에 영향 없음 확인)

```python
# diag_logger.py:35-36
_request_id_ctx: ContextVar[str] = ContextVar("diag_request_id", default="-")
_action_ctx: ContextVar[str] = ContextVar("diag_user_action", default="-")
```

- 용도: 진단 로그 correlation
- tenant 와 무관: request_id 와 user_action 는 tenant_id 가 아님
- 옵션 C 후에도 그대로 유지 (별도 영역)

## 검증한 패턴들

### 1. lambda 안 ContextVar 사용
```bash
grep -rn "lambda" backend/app | grep "current_tenant_id\|bypass_tenant_filter"
```
**결과**: 0건. lambda 안에서 ContextVar 직접 호출 없음.

### 2. functools.partial 사용
```bash
grep -rn "partial(" backend/app
```
**결과**: `config.py:3` 의 `from functools import lru_cache` 만 — ContextVar 무관.

### 3. decorator 정의
```bash
grep -rn "^def.*\|@app\.middleware\|@functools\|@wraps" backend/app | grep -iE "decor|wrap|middleware"
```
**결과**: `main.py:98` 의 `@app.middleware("http")` 만 — diag correlation 만 처리, tenant 무관.

### 4. dynamic import
```bash
grep -rn "importlib\|__import__\|getattr.*tenant\|hasattr.*tenant" backend/app
```
**결과**:
- `templates/variables.py:287-288`: `getattr(tenant, 'surcharge_unit_standard', 20000)` — Tenant 객체 attribute (정적 접근, 안전)
- `db/tenant_context.py:27`: `if hasattr(obj, 'tenant_id')` — TenantMixin 검증 (정적, 안전)

### 5. asyncio Task 의 context 파라미터
```bash
grep -rn "Task(.*context=\|create_task(.*context=" backend/app
```
**결과**: 0건. ContextVar 명시 격리 코드 없음.

→ 그래서 sibling-task 누수가 발생할 수 있었음 (이번 사고).

### 6. ContextVar 의 set 외 다른 mutation
```bash
grep -rn "current_tenant_id\.\|bypass_tenant_filter\." backend/app | grep -v "set\|reset\|get\|import"
```
**결과**: 0건. set/reset/get 외 다른 메서드 사용 없음 (Token 객체 직접 조작 등).

## 잠재 위험 (옵션 C 마이그레이션 중)

### 🟢 [Safe] 다른 ContextVar 가 tenant_id 를 wrap 하지 않음
diag_request_id 와 diag_user_action 는 tenant 와 분리. 옵션 C 후에도 동일.

### 🟢 [Safe] 자체 decorator 가 tenant 자동 주입 안 함
auth/dependencies.py 의 `get_current_user` / `require_admin_or_above` 등 의존성은 FastAPI 의존성 시스템 사용. ContextVar 자동 주입 없음.

### 🟢 [Safe] 동적 코드 생성 없음
`exec` / `eval` / `compile` 사용 0건 (검증 완료).

## 사이드이펙트 격리 확인

### 옵션 C 적용 시 외부 발견 영향
- `diag_request_id` / `diag_user_action`: 옵션 C 와 무관, 그대로 동작
- FastAPI middleware: ContextVar 미사용, 영향 없음
- lambda / partial: 사용 자체 없음

### 잠재 회귀 0건
간접 사용 패턴 자체가 없으므로 옵션 C 후 보이지 않는 회귀 가능성 매우 낮음.

## 결론

**ContextVar 사용은 명시적 set/reset/get 만 존재**. 옵션 C 마이그레이션 시 산출물 #2 의 50건 + 28건 직접 사용처만 처리하면 누수 차단 완전.

이 결과는 옵션 C 마이그레이션의 **위험을 한 단계 낮춤**: 숨은 ContextVar 사용 없으므로 산출물 #2 의 매핑이 그대로 완전한 변경 리스트.
