# Phase 0 후속 #20: 데이터 정리 + 운영자 통보 스크립트

> 더티 데이터 54건 정리 SQL + 잘못 발송 26건 STABLE 고객 정정 안내. **운영자 승인 필요**.

## 1단계: 백업 (선행 필수)

```sql
-- 백업 테이블 생성
CREATE TABLE IF NOT EXISTS reservation_sms_assignments_leaked_archive (
    id INTEGER,
    reservation_id INTEGER,
    template_key VARCHAR(100),
    assigned_at TIMESTAMP,
    sent_at TIMESTAMP,
    assigned_by VARCHAR(20),
    date VARCHAR(20),
    tenant_id INTEGER,
    schedule_id INTEGER,
    send_status VARCHAR(10),
    send_error VARCHAR(500),
    archived_at TIMESTAMP DEFAULT NOW(),
    archive_reason VARCHAR(50)
);

-- 더티 칩 백업 (54건)
INSERT INTO reservation_sms_assignments_leaked_archive
  (id, reservation_id, template_key, assigned_at, sent_at, assigned_by, date,
   tenant_id, schedule_id, send_status, send_error, archive_reason)
SELECT rsa.id, rsa.reservation_id, rsa.template_key, rsa.assigned_at, rsa.sent_at,
       rsa.assigned_by, rsa.date, rsa.tenant_id, rsa.schedule_id,
       rsa.send_status, rsa.send_error,
       'pattern_a_chip_vs_schedule' AS archive_reason
FROM reservation_sms_assignments rsa
JOIN template_schedules ts ON ts.id = rsa.schedule_id
WHERE rsa.tenant_id != ts.tenant_id;

INSERT INTO reservation_sms_assignments_leaked_archive
  (id, reservation_id, template_key, assigned_at, sent_at, assigned_by, date,
   tenant_id, schedule_id, send_status, send_error, archive_reason)
SELECT rsa.id, rsa.reservation_id, rsa.template_key, rsa.assigned_at, rsa.sent_at,
       rsa.assigned_by, rsa.date, rsa.tenant_id, rsa.schedule_id,
       rsa.send_status, rsa.send_error,
       'pattern_b_chip_vs_reservation' AS archive_reason
FROM reservation_sms_assignments rsa
JOIN reservations r ON r.id = rsa.reservation_id
WHERE rsa.tenant_id != r.tenant_id;

-- 백업 카운트 검증
SELECT archive_reason, COUNT(*) FROM reservation_sms_assignments_leaked_archive
GROUP BY archive_reason;
-- 예상:
-- pattern_a_chip_vs_schedule    : 34
-- pattern_b_chip_vs_reservation : 20
```

## 2단계: 잘못 발송 고객 명단 추출

```sql
-- 패턴 B (HANDAM 본문이 STABLE 고객에게 발송된 케이스)
SELECT 
    r.customer_name,
    r.phone,
    r.tenant_id AS actual_tenant,
    rsa.template_key,
    rsa.sent_at AS wrong_send_at,
    rsa.id AS chip_id
FROM reservation_sms_assignments rsa
JOIN reservations r ON r.id = rsa.reservation_id
WHERE rsa.tenant_id != r.tenant_id
  AND rsa.sent_at IS NOT NULL
ORDER BY rsa.sent_at;
-- 예상: 20건 (모두 03:00 / 07:00 시각, party_info / party_alert)

-- 패턴 A 발송분 (STABLE 고객에 sent 박힌 칩)
SELECT 
    r.customer_name,
    r.phone,
    rsa.template_key,
    rsa.sent_at,
    rsa.id AS chip_id
FROM reservation_sms_assignments rsa
JOIN reservations r ON r.id = rsa.reservation_id
JOIN template_schedules ts ON ts.id = rsa.schedule_id
WHERE rsa.tenant_id = r.tenant_id  -- 패턴 B 와 다른 조건
  AND rsa.tenant_id != ts.tenant_id
  AND rsa.sent_at IS NOT NULL
ORDER BY rsa.sent_at;
-- 예상: 5건 (3062, 3063, 3066, 3067, 3090 — 김락훈, 이현수, 김승환)

-- 중복 제거된 영향 고객 (전화번호 기준)
SELECT DISTINCT r.customer_name, r.phone, MIN(rsa.sent_at) AS first_wrong_send
FROM reservation_sms_assignments rsa
JOIN reservations r ON r.id = rsa.reservation_id
WHERE rsa.sent_at IS NOT NULL
  AND (rsa.tenant_id != r.tenant_id
       OR rsa.id IN (SELECT rsa2.id FROM reservation_sms_assignments rsa2
                     JOIN template_schedules ts ON ts.id = rsa2.schedule_id
                     WHERE rsa2.tenant_id != ts.tenant_id AND rsa2.sent_at IS NOT NULL))
GROUP BY r.customer_name, r.phone
ORDER BY first_wrong_send;
```

**예상 영향 고객 (산출물 #7 기준)**:
- 임용섭, 김범진, 김준형, 최용우, 최예진, 이지원, 한동민, 노환일, 윤정희, 김응규, 강민구
- 김락훈, 이현수, 김승환
- (개별 추출 시 SQL 결과로 확정)

## 3단계: 정정 SMS 본문 초안

운영자 검토 후 발송. 두 가지 옵션:

### 옵션 1: 짧은 사과 메시지
```
[STABLE] 안녕하세요. 시스템 오류로 다른 호스텔의 안내가 잘못 발송됐습니다. 
무시해 주세요. 정확한 안내는 곧 다시 전송드립니다. 
불편을 드려 죄송합니다.
```

### 옵션 2: 상세 안내 + 정확한 정보 동봉
```
[STABLE] 안녕하세요. 

조금 전 발송된 파티 안내는 시스템 오류로 다른 호스텔(한담누리)의 내용이 잘못 전달된 것입니다.

정확한 STABLE 파티 안내:
- 시간: [STABLE 정확한 시간]
- 장소: [STABLE 정확한 위치]
- 입금 계좌: [STABLE 정확한 계좌]

불편을 드려 죄송합니다. 추가 문의는 이 번호로 연락 주세요.
```

→ **운영자 결정**: 옵션 1 (간단) vs 옵션 2 (상세). STABLE 의 실제 파티 안내 내용을 알아야 옵션 2 작성 가능.

## 4단계: 미발송 누수 칩 삭제 (안전)

```sql
BEGIN;

-- 패턴 A 미발송 (29건)
DELETE FROM reservation_sms_assignments
WHERE id IN (
    SELECT rsa.id FROM reservation_sms_assignments rsa
    JOIN template_schedules ts ON ts.id = rsa.schedule_id
    WHERE rsa.tenant_id != ts.tenant_id
      AND rsa.sent_at IS NULL
);

-- 패턴 B 미발송 (0건 예상 — B 는 모두 sent)
DELETE FROM reservation_sms_assignments
WHERE id IN (
    SELECT rsa.id FROM reservation_sms_assignments rsa
    JOIN reservations r ON r.id = rsa.reservation_id
    WHERE rsa.tenant_id != r.tenant_id
      AND rsa.sent_at IS NULL
);

-- 검증
SELECT COUNT(*) AS remaining_unsent_pattern_a
FROM reservation_sms_assignments rsa
JOIN template_schedules ts ON ts.id = rsa.schedule_id
WHERE rsa.tenant_id != ts.tenant_id AND rsa.sent_at IS NULL;
-- 0 이어야 함

SELECT COUNT(*) AS remaining_unsent_pattern_b
FROM reservation_sms_assignments rsa
JOIN reservations r ON r.id = rsa.reservation_id
WHERE rsa.tenant_id != r.tenant_id AND rsa.sent_at IS NULL;
-- 0 이어야 함

COMMIT;
```

## 5단계: 발송완료 누수 칩 처리 — 운영자 결정

**옵션 1: 보존 + 마킹** (권장 시작점)
```sql
-- assigned_by 를 'leaked_legacy' 로 변경 → 운영 추적 가능 + 화면 정상 표시 유지
UPDATE reservation_sms_assignments rsa
SET assigned_by = 'leaked_legacy'
WHERE id IN (
    SELECT rsa2.id FROM reservation_sms_assignments rsa2
    JOIN template_schedules ts ON ts.id = rsa2.schedule_id
    WHERE rsa2.tenant_id != ts.tenant_id AND rsa2.sent_at IS NOT NULL
)
OR id IN (
    SELECT rsa2.id FROM reservation_sms_assignments rsa2
    JOIN reservations r ON r.id = rsa2.reservation_id
    WHERE rsa2.tenant_id != r.tenant_id AND rsa2.sent_at IS NOT NULL
);
-- 영향: 25건
```

**옵션 2: 백업 후 삭제** (운영 화면 정리)
```sql
BEGIN;

DELETE FROM reservation_sms_assignments rsa
USING template_schedules ts
WHERE rsa.schedule_id = ts.id
  AND rsa.tenant_id != ts.tenant_id
  AND rsa.sent_at IS NOT NULL;

DELETE FROM reservation_sms_assignments rsa
USING reservations r
WHERE rsa.reservation_id = r.id
  AND rsa.tenant_id != r.tenant_id
  AND rsa.sent_at IS NOT NULL;

-- 백업 테이블에 이미 있음 (1단계에서 보존)
COMMIT;
```

**비교**:
| 옵션 | 화면 영향 | 감사 추적 | 운영 결정 |
|--|--|--|--|
| 옵션 1: leaked_legacy 마킹 | 칩 그대로 표시 (오해 가능) | ✅ 직접 보임 | "투명성" 우선 |
| 옵션 2: 백업 후 삭제 | 칩 사라짐 (깨끗) | ✅ archive 테이블 | "정상화" 우선 |

→ **권장**: 옵션 2. 운영 화면이 깨끗해지고 archive 에서 언제든 추적 가능.

## 6단계: 최종 검증

```sql
-- 모든 cross-tenant 잔여 0 검증
SELECT COUNT(*) AS pattern_a_remaining
FROM reservation_sms_assignments rsa
JOIN template_schedules ts ON ts.id = rsa.schedule_id
WHERE rsa.tenant_id != ts.tenant_id;

SELECT COUNT(*) AS pattern_b_remaining
FROM reservation_sms_assignments rsa
JOIN reservations r ON r.id = rsa.reservation_id
WHERE rsa.tenant_id != r.tenant_id;
-- 양쪽 모두 0 이어야 함

-- 백업 테이블 카운트 (54건 보존 확인)
SELECT archive_reason, COUNT(*) FROM reservation_sms_assignments_leaked_archive
GROUP BY archive_reason;
-- pattern_a_chip_vs_schedule : 34
-- pattern_b_chip_vs_reservation : 20
```

## 운영자 승인 체크리스트

다음 결정 후 실행:
- [ ] 1단계 백업 SQL 실행 (운영자 승인)
- [ ] 2단계 영향 고객 명단 추출 + 검토
- [ ] 3단계 정정 SMS 본문 결정 (옵션 1 vs 2)
- [ ] STABLE 운영자에게 정정 SMS 발송 (수동 또는 시스템 통해)
- [ ] 4단계 미발송 칩 삭제 SQL 실행
- [ ] 5단계 발송완료 칩 처리 결정 (옵션 1 vs 2) + SQL 실행
- [ ] 6단계 검증 쿼리 실행 → 0 확인

## 실행 스크립트 (자동화)

```bash
#!/bin/bash
# scripts/cleanup_dirty_data.sh
# 운영자 승인 후 단계별 실행

set -e
PSQL='psql "postgresql://postgres.cdrfkxvqezwtejzrtzip:oljSu7PqD4oEItZn@aws-1-ap-northeast-2.pooler.supabase.com:6543/postgres?sslmode=require"'

case "$1" in
    "backup")
        echo "Creating archive table + backing up dirty rows..."
        $PSQL -f docs/option-c-discovery/sql/backup_dirty_data.sql
        ;;
    "list_customers")
        echo "Extracting affected customer list..."
        $PSQL -f docs/option-c-discovery/sql/list_affected_customers.sql
        ;;
    "delete_unsent")
        echo "Deleting unsent dirty chips..."
        $PSQL -f docs/option-c-discovery/sql/delete_unsent.sql
        ;;
    "delete_sent")
        echo "Deleting sent dirty chips (option 2)..."
        $PSQL -f docs/option-c-discovery/sql/delete_sent.sql
        ;;
    "verify")
        echo "Running final verification..."
        $PSQL -f docs/option-c-discovery/sql/verify_cleanup.sql
        ;;
    *)
        echo "Usage: $0 {backup|list_customers|delete_unsent|delete_sent|verify}"
        exit 1
        ;;
esac
```

## 사고 보고서 템플릿

운영자에게 전달할 사고 요약 (Phase 0 마무리 후 추가 작성 권장):

```
사고 발생: 2026-04-30
원인: APScheduler ContextVar 누수 → HANDAM 스케줄이 STABLE 고객에게 SMS 발송
영향:
  - 잘못 발송: 26건 (STABLE 고객 14명에게 HANDAM 본문)
  - 더티 칩: 54건 (DB)
조치:
  - 즉시: 6 패치 + Layer 4 가드 적용 (완료)
  - 단기: 더티 데이터 정리 + STABLE 고객 정정 안내
  - 중기: 옵션 C (Session-bound tenant) 마이그레이션 — root cause 차단
  - 장기: 회귀 테스트 보강 + 운영 모니터링 강화
```

## 결론

**Phase 0 데이터 정리는 운영자 승인 필요한 단계** — 자동 실행 안 함. 백업 → 명단 추출 → 정정 SMS → 미발송 삭제 → 발송완료 처리 결정 → 검증의 6 단계 sequence.

운영자 승인 후 단계별 실행 가능. 모든 단계 atomic — 각 단계 개별 commit/rollback 가능.

**Phase 1 진입 영향**: 데이터 정리는 Phase 1 진입과 독립. 동시 진행 가능 또는 Phase 1 후 실행 가능. 단, Phase 5 (보강 단계) 전에는 정리 완료 권장.
