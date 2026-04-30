# Phase 0 산출물 #10: 회귀 baseline 캡처

> Phase 별 배포 후 회귀 비교용 — 현재 운영 동작의 정량/정성 baseline.

## 캡처 대상

### A. API endpoint 응답 스펙
모든 endpoint 의 정상 응답 형태를 OpenAPI / 실제 호출 결과로 캡처.

**캡처 방법**:
```bash
# OpenAPI schema dump
curl http://localhost:8000/openapi.json > docs/option-c-discovery/baseline/openapi-baseline.json

# 주요 endpoint 실제 응답 샘플 (Authorization + X-Tenant-Id 포함)
curl -H "Authorization: Bearer $TOKEN" -H "X-Tenant-Id: 1" http://localhost:8000/api/reservations \
  > docs/option-c-discovery/baseline/api-reservations-list.json
# ... 약 20개 핵심 endpoint 반복
```

**비교 시점**: Phase 2 배포 후 동일 호출 → diff 0 이어야 함.

### B. 활동 로그 패턴
ActivityLog 의 type / title / detail 구조.

**캡처 SQL**:
```sql
-- type 별 최근 30일 활동 로그 샘플
SELECT type, title, status, created_by, COUNT(*) AS n
FROM activity_logs
WHERE created_at >= NOW() - INTERVAL '30 days'
GROUP BY type, title, status, created_by
ORDER BY n DESC
LIMIT 100;

-- detail JSON 키 분포 (type 별)
SELECT type,
  jsonb_object_keys(detail::jsonb) AS detail_key,
  COUNT(*) AS n
FROM activity_logs
WHERE detail IS NOT NULL AND detail != ''
  AND created_at >= NOW() - INTERVAL '30 days'
GROUP BY type, detail_key
ORDER BY type, n DESC;
```

**비교 시점**: Phase 5 배포 후 동일 통계 → 패턴 동일해야 함.

### C. 스케줄러 발화 빈도 / 평균 처리량

**캡처 SQL**:
```sql
-- 잡별 발화 횟수 (최근 7일)
SELECT type, title,
  COUNT(*) AS fires,
  AVG(target_count) AS avg_target,
  AVG(success_count) AS avg_success,
  AVG(failed_count) AS avg_failed
FROM activity_logs
WHERE type IN ('sms_send', 'naver_sync', 'room_assign', 'naver_reconcile')
  AND created_at >= NOW() - INTERVAL '7 days'
GROUP BY type, title
ORDER BY fires DESC;
```

**비교 시점**: Phase 3 배포 후 잡 발화 빈도 비교 → 잡당 ±10% 이내.

### D. SMS 발송 양상

**캡처 SQL**:
```sql
-- 시간대별 발송 분포
SELECT date_trunc('hour', sent_at) AS hour,
  COUNT(*) AS sent,
  COUNT(*) FILTER (WHERE send_status = 'failed') AS failed
FROM reservation_sms_assignments
WHERE sent_at >= NOW() - INTERVAL '7 days'
GROUP BY hour
ORDER BY hour;

-- template_key 별 발송 빈도
SELECT template_key, tenant_id,
  COUNT(*) AS sent,
  COUNT(*) FILTER (WHERE send_status = 'sent') AS success,
  COUNT(*) FILTER (WHERE send_status = 'failed') AS failed
FROM reservation_sms_assignments
WHERE sent_at >= NOW() - INTERVAL '7 days'
GROUP BY template_key, tenant_id;
```

**비교 시점**: Phase 3 배포 후 발송 양상 → 패턴 일관 유지.

### E. 평균 응답 시간 (성능 baseline)

**캡처 도구**:
- nginx / FastAPI 미들웨어 access log
- Sentry performance tracing (있다면)

**측정 endpoint** (가장 자주 호출):
- `GET /api/reservations`
- `GET /api/dashboard/stats`
- `POST /api/reservations` (생성)
- `GET /api/rooms`
- `GET /api/templates`

**baseline 표**:
```
endpoint                              | p50 (ms) | p95 (ms) | p99 (ms) | RPS
--------------------------------------+----------+----------+----------+-----
GET /api/reservations                 | TBD      | TBD      | TBD      | TBD
GET /api/dashboard/stats              | TBD      | TBD      | TBD      | TBD
...
```

**비교 시점**: Phase 2 후 +20% 이내 허용. +20% 초과 시 회귀 의심.

### F. 에러율 / 패턴

**캡처 SQL**:
```sql
SELECT date_trunc('day', created_at) AS day,
  type,
  status,
  COUNT(*) AS n
FROM activity_logs
WHERE created_at >= NOW() - INTERVAL '7 days'
  AND status IN ('failed', 'error')
GROUP BY day, type, status
ORDER BY day, n DESC;
```

**baseline 에러 패턴**: 평소 발생하는 에러 종류 + 빈도 기록.

**비교 시점**: 각 Phase 후 새로운 에러 종류 발생 시 회귀.

### G. cross-tenant 누수 검증 (사고 후 baseline)

**캡처 SQL**: 산출물 #7 의 검증 쿼리. 마이그레이션 시작 시점 기준 cross-tenant row 0 (정리 후).

```sql
-- 정리 후 baseline (0이어야 함)
SELECT COUNT(*) AS pattern_a FROM reservation_sms_assignments rsa
JOIN template_schedules ts ON ts.id = rsa.schedule_id
WHERE rsa.tenant_id != ts.tenant_id;

SELECT COUNT(*) AS pattern_b FROM reservation_sms_assignments rsa
JOIN reservations r ON r.id = rsa.reservation_id
WHERE rsa.tenant_id != r.tenant_id;
```

**비교 시점**: 각 Phase 후 매일 자동 실행. 1 이상 발생 시 즉시 알람.

## baseline 저장 구조

```
docs/option-c-discovery/baseline/
├── openapi-baseline.json          # OpenAPI schema
├── api-responses/                 # 주요 endpoint 응답 샘플
│   ├── reservations-list.json
│   ├── dashboard-stats.json
│   └── ...
├── activity-log-stats.csv         # ActivityLog 통계
├── scheduler-firing-stats.csv     # 잡 발화 빈도
├── sms-send-distribution.csv      # SMS 발송 양상
├── performance-baseline.csv       # 응답 시간
├── error-baseline.csv             # 에러 패턴
└── cross-tenant-leak-baseline.txt # 누수 검증 0 baseline
```

## 자동화 스크립트

```bash
#!/bin/bash
# scripts/capture_baseline.sh
# Phase 0 적용 시점에 1회 실행

set -e
OUT=docs/option-c-discovery/baseline
mkdir -p $OUT $OUT/api-responses

# 1. OpenAPI
curl -s http://localhost:8000/openapi.json > $OUT/openapi-baseline.json

# 2. 주요 endpoint 응답 (인증 토큰 필요)
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -d '{"username":"admin","password":"..."}' | jq -r .access_token)

for ep in "reservations" "dashboard/stats" "rooms" "templates"; do
  curl -s -H "Authorization: Bearer $TOKEN" -H "X-Tenant-Id: 1" \
    http://localhost:8000/api/$ep > $OUT/api-responses/$(echo $ep | tr '/' '-').json
done

# 3. DB baseline SQL
psql ... -c "..." > $OUT/activity-log-stats.csv
# ... 반복

echo "Baseline captured at $(date) → $OUT"
```

## 비교 도구

```python
# scripts/compare_baseline.py
import json
from pathlib import Path

def diff_openapi(baseline, current):
    """OpenAPI schema 비교 — 누락/변경 endpoint 감지."""
    base = json.loads(baseline.read_text())
    cur = json.loads(current.read_text())
    base_paths = set(base['paths'].keys())
    cur_paths = set(cur['paths'].keys())
    missing = base_paths - cur_paths
    added = cur_paths - base_paths
    return {"missing": missing, "added": added}

def diff_response(baseline_file, current_file):
    """응답 JSON 비교 — 필드 누락/변경 감지."""
    base = json.loads(baseline_file.read_text())
    cur = json.loads(current_file.read_text())
    # 깊은 비교 (순서 무시)
    ...

# 각 Phase 배포 후 자동 실행
```

## 비교 임계 (회귀 트리거)

| 지표 | 정상 | 경고 | 회귀 (롤백 트리거) |
|--|--|--|--|
| API 응답 스키마 | 100% 일치 | 1 endpoint 차이 | 2+ endpoint 차이 |
| 응답 시간 p95 | baseline ±10% | +20% | +50% |
| 활동 로그 type | 100% 일치 | 새 type 추가 | 기존 type 누락 |
| 잡 발화 빈도 | baseline ±5% | ±15% | ±30% |
| SMS 발송 양상 | 일관 | 패턴 변화 | 누락/중복 |
| 에러율 | baseline | +10% | +50% |
| cross-tenant 누수 | 0건 | - | 1건 이상 |

## Phase 별 비교 시점

| Phase | 비교 대상 |
|--|--|
| Phase 1 | A (스키마), E (성능), F (에러) — 안전 검증 |
| Phase 2 | A + B + E + F — API 변환 검증 |
| Phase 3 | C + D + F — 스케줄러 검증 |
| Phase 4 | B + F — service 변환 검증 |
| Phase 5 | G — 누수 baseline 유지 |
| Phase 6 | A + E + F — 최종 검증 |

## 결론

baseline 캡처는 **마이그레이션 안전망의 핵심**. 정량 비교로 회귀 자동 감지 가능. Phase 0 마지막 단계로 baseline 캡처 실행 후 다음 Phase 진입.
