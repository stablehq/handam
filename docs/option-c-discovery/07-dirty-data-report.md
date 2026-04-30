# Phase 0 산출물 #7: 더티 데이터 보고서 + 정리 SQL

> 생성: 2026-04-30 / 옵션 C 마이그레이션 사전 클린업

## Executive Summary

오늘 사고로 만들어진 cross-tenant 더티 row 가 **두 가지 패턴**으로 존재:

| 패턴 | 의미 | 건수 | 발송 여부 |
|--|--|--|--|
| **A** | `chip.tenant_id=2` + `schedule.tenant_id=1` (STABLE 칩이 HANDAM 스케줄 가리킴) | **34건** | 5건 sent |
| **B** | `chip.tenant_id=1` + `reservation.tenant_id=2` (HANDAM 칩이 STABLE 예약 가리킴) | **20건** | 20건 sent |
| **합계** | | **54건** (일부 겹침 가능) | **25건** |

다른 8개 FK 관계 (room_assignments / template_schedules / party_checkins / reservation_daily_info / room_biz_item_links / rooms.building_id / rooms.room_group_id) 는 **누수 0건** — 안전.

## 패턴 A: chip vs schedule 누수 (34건)

### 메커니즘
STABLE (tid=2) 컨텍스트에서 `naver_sync` Phase 6 의 `reconcile_chips_for_reservation` 또는 `room_auto_assign`의 `sync_sms_tags` 가 HANDAM (tid=1) 스케줄까지 끌고 들어와 STABLE 예약에 칩을 만든 케이스. 칩 자체는 STABLE 테넌트 (`chip.tenant_id=2`) 로 박혔지만 `schedule_id` 가 HANDAM 스케줄.

### 데이터 (chip_id 일부)
```
3031~3040, 3059~3060, 3062~3067, 3078~3083, 3087~3092, 3096~3099
schedule_id IN (1=HANDAM party_info, 7=HANDAM party_alert)
```

### 발송 여부
- `sent_at IS NOT NULL`: **5건** (3062, 3063, 3066, 3067, 3090)
- `sent_at IS NULL`: 29건 (미발송, 자동 정리 대상)

## 패턴 B: chip vs reservation 누수 (20건) — **신규 발견**

### 메커니즘
HANDAM (tid=1) 스케줄러가 fire 할 때 `_get_targets_standard` 가 cross-tenant Reservation 까지 픽업 → SMS 실발송 → `record_sms_sent` 가 새 칩 INSERT → before_flush 가 `current_tenant_id=1` 주입해서 chip.tenant_id=1 로 박힘. 그러나 reservation_id 가 가리키는 행은 tid=2.

### 데이터 (전수)
```
chip_id  | chip_tid | reservation_id | res_tid | template_key | sent_at
---------+----------+----------------+---------+--------------+-------
3047     | 1        | 4706           | 2       | party_info   | 03:00:01
3048     | 1        | 3454           | 2       | party_info   | 03:00:03
3049     | 1        | 3882           | 2       | party_info   | 03:00:05
3050     | 1        | 3684           | 2       | party_info   | 03:00:05
3051     | 1        | 3712           | 2       | party_info   | 03:00:07
3052     | 1        | 3745           | 2       | party_info   | 03:00:07
3053     | 1        | 4069           | 2       | party_info   | 03:00:08
3054     | 1        | 3564           | 2       | party_info   | 03:00:09
3055     | 1        | 4627           | 2       | party_info   | 03:00:10
3056     | 1        | 4662           | 2       | party_info   | 03:00:10
3068     | 1        | 4706           | 2       | party_alert  | 07:00:00
3069     | 1        | 3454           | 2       | party_alert  | 07:00:01
3070     | 1        | 3882           | 2       | party_alert  | 07:00:05
3071     | 1        | 3684           | 2       | party_alert  | 07:00:05
3072     | 1        | 3712           | 2       | party_alert  | 07:00:06
3073     | 1        | 3745           | 2       | party_alert  | 07:00:06
3074     | 1        | 4069           | 2       | party_alert  | 07:00:06
3075     | 1        | 3564           | 2       | party_alert  | 07:00:07
3076     | 1        | 4627           | 2       | party_alert  | 07:00:07
3077     | 1        | 4662           | 2       | party_alert  | 07:00:07
```

### 발송 여부
- 20건 모두 `sent_at IS NOT NULL` — 전부 실발송됨
- 03:00 17건 (party_info) + 07:00 12건 (party_alert) 사고와 매칭

## 패턴 A ∩ B: 잠재적 동일 사고

같은 reservation_id 에 대해 패턴 A 와 B 가 동시에 만들어졌는지 확인 필요 (UNIQUE 제약 `(reservation_id, template_key, date)` 때문에 한 쪽만 존재해야 함).

```sql
SELECT reservation_id, template_key, date, COUNT(*) AS chip_count
FROM reservation_sms_assignments
WHERE reservation_id IN (
  SELECT DISTINCT reservation_id FROM reservation_sms_assignments rsa
  JOIN reservations r ON r.id = rsa.reservation_id
  WHERE rsa.tenant_id != r.tenant_id
)
GROUP BY reservation_id, template_key, date
HAVING COUNT(*) > 1;
```

## 운영자 영향

### STABLE 운영자 화면
- 패턴 A 의 5 sent 칩 → STABLE 화면에 "발송완료" 표시 (HANDAM 본문이 발송됐음)
- 패턴 A 의 29 unsent 칩 → STABLE 화면에 "발송 대기" 잘못된 칩 표시
- 패턴 B 의 20 sent 칩 → **STABLE 화면에선 안 보임** (chip.tenant_id=1 이라 STABLE 쿼리 결과에 없음)

### HANDAM 운영자 화면
- 패턴 B 의 20 sent 칩 → **HANDAM 화면에 "발송완료" 표시** (실제로는 STABLE 고객에게 보냄)
- 활동로그 에 그대로 남음 (이미 확인된 26건 발송 로그)

## 정리 SQL

### 단계 1: 미발송 누수 칩 즉시 정리 (안전)

```sql
BEGIN;

-- 패턴 A: chip.tenant=2 + schedule.tenant=1 + sent_at IS NULL
DELETE FROM reservation_sms_assignments
WHERE id IN (
  SELECT rsa.id FROM reservation_sms_assignments rsa
  JOIN template_schedules ts ON ts.id = rsa.schedule_id
  WHERE rsa.tenant_id != ts.tenant_id
    AND rsa.sent_at IS NULL
);
-- 예상: 29건 삭제

-- 패턴 B 미발송: chip.tenant != reservation.tenant + sent_at IS NULL
DELETE FROM reservation_sms_assignments
WHERE id IN (
  SELECT rsa.id FROM reservation_sms_assignments rsa
  JOIN reservations r ON r.id = rsa.reservation_id
  WHERE rsa.tenant_id != r.tenant_id
    AND rsa.sent_at IS NULL
);
-- 예상: 0건 삭제 (B 는 모두 sent)

COMMIT;
```

### 단계 2: 발송완료 누수 칩 — 운영 결정 필요

**옵션 1: 보존 (운영 추적용)**
sent 칩 25건은 그대로 두고 `assigned_by='leaked_legacy'` 로 마킹해 향후 추적.

```sql
UPDATE reservation_sms_assignments rsa
SET assigned_by = 'leaked_legacy'
FROM template_schedules ts
WHERE rsa.schedule_id = ts.id
  AND rsa.tenant_id != ts.tenant_id
  AND rsa.sent_at IS NOT NULL;

UPDATE reservation_sms_assignments rsa
SET assigned_by = 'leaked_legacy'
FROM reservations r
WHERE rsa.reservation_id = r.id
  AND rsa.tenant_id != r.tenant_id
  AND rsa.sent_at IS NOT NULL;
```

**옵션 2: 백업 후 삭제**
별도 테이블 `reservation_sms_assignments_leaked_archive` 생성 → 25건 이관 → 원본 삭제. 화면 노이즈 제거 + 감사 추적 양립.

```sql
-- 백업 테이블 생성
CREATE TABLE reservation_sms_assignments_leaked_archive AS
SELECT *, NOW() AS archived_at FROM reservation_sms_assignments WHERE 1=0;

-- 25건 이관
INSERT INTO reservation_sms_assignments_leaked_archive
SELECT rsa.*, NOW() FROM reservation_sms_assignments rsa
LEFT JOIN template_schedules ts ON ts.id = rsa.schedule_id
LEFT JOIN reservations r ON r.id = rsa.reservation_id
WHERE rsa.sent_at IS NOT NULL
  AND ((ts.id IS NOT NULL AND rsa.tenant_id != ts.tenant_id)
       OR (r.id IS NOT NULL AND rsa.tenant_id != r.tenant_id));

-- 원본 삭제
DELETE FROM reservation_sms_assignments rsa
USING template_schedules ts
WHERE rsa.schedule_id = ts.id AND rsa.tenant_id != ts.tenant_id AND rsa.sent_at IS NOT NULL;

DELETE FROM reservation_sms_assignments rsa
USING reservations r
WHERE rsa.reservation_id = r.id AND rsa.tenant_id != r.tenant_id AND rsa.sent_at IS NOT NULL;
```

### 단계 3: STABLE 잘못 발송된 고객에게 정정 안내 (운영 결정)

26명 STABLE 고객에게 잘못된 HANDAM 본문 (계좌·메뉴·시간) 발송됨. 파티 입금 사고 방지를 위해 정정 SMS 권장:

> "[STABLE] 안녕하세요, 시스템 오류로 다른 호스텔의 파티 안내가 잘못 발송됐습니다. 무시해 주시고 정확한 안내는 [STABLE 본문] 입니다."

전화번호 + 이름 + 발송 시각 추출:

```sql
SELECT DISTINCT r.customer_name, r.phone, MIN(rsa.sent_at) AS first_leak_at
FROM reservation_sms_assignments rsa
JOIN reservations r ON r.id = rsa.reservation_id
WHERE rsa.sent_at IS NOT NULL
  AND rsa.tenant_id != r.tenant_id
GROUP BY r.customer_name, r.phone
ORDER BY first_leak_at;
```

## 마이그레이션 영향 (단계 2C 복합 FK)

**현 상태로 단계 2C 복합 FK 추가 시도 시**: 25건 sent 칩이 새 FK 제약 위반 → ALTER TABLE 실패. **복합 FK 마이그레이션 전 단계 1 + 단계 2 (옵션 1 또는 2) 선행 필수**.

## 검증 쿼리 (정리 후 0건 확인용)

```sql
-- 모든 cross-tenant 잔여 검증
SELECT COUNT(*) AS remaining_pattern_a FROM reservation_sms_assignments rsa
JOIN template_schedules ts ON ts.id = rsa.schedule_id
WHERE rsa.tenant_id != ts.tenant_id;

SELECT COUNT(*) AS remaining_pattern_b FROM reservation_sms_assignments rsa
JOIN reservations r ON r.id = rsa.reservation_id
WHERE rsa.tenant_id != r.tenant_id;

-- 양쪽 모두 0 이어야 함 (옵션 2 선택 시) 또는 'leaked_legacy' 마킹만 잔존 (옵션 1)
```
