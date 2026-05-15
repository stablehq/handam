# event 스케줄 — 오늘 체크인 예약자 제외

> 분류: 🔵 정책 변경 (마케팅 안내 효율)
> 변경 규모: 1 줄 + 주석 + 단위 테스트

---

## 1. 목적

`schedule_category='event'` 스케줄은 "체크인 N일 전 미리 안내" 목적의
마케팅 SMS (예: 여성 이벤트 안내, 후킹 SMS 등). 당일 체크인 예약자에게는
이미 늦었으므로 발송 효과가 낮음 → 제외.

---

## 2. 변경 대상 코드

### `app/scheduler/template_scheduler.py:700-703`

**Before**:
```python
# 1) 안전장치: 과거 체크인 (이미 체크아웃했거나 mid-stay) 무조건 제외.
#    max_checkin_days 가 비어있어도 항상 적용 — 운영자가 실수로 빈 값
#    저장해도 과거 예약자에게 발송되는 사고 방지.
query = query.filter(Reservation.check_in_date >= today_str)
```

**After**:
```python
# 1) 안전장치: 오늘 + 과거 체크인 (이미 체크아웃했거나 mid-stay, 당일은 안내
#    효과 없음) 무조건 제외. max_checkin_days 가 비어있어도 항상 적용 —
#    운영자가 실수로 빈 값 저장해도 무의미한 발송 사고 방지.
query = query.filter(Reservation.check_in_date > today_str)
```

---

## 3. 동작 동등성

| 체크인 날짜 | Before | After |
|-----------|--------|-------|
| 어제 (mid-stay) | ❌ 제외 | ❌ 제외 |
| **오늘 (당일 체크인)** | ✅ 발송 | **❌ 제외** |
| 내일 | ✅ 발송 | ✅ 발송 |
| 모레+ | ✅ 발송 | ✅ 발송 |

---

## 4. 영향 범위

- **모든 `schedule_category='event'` 스케줄**: female_event, 후킹 SMS 등
- standard / custom_schedule / daily 카테고리: 영향 0 (별도 함수)
- naver_sync 즉시 발송 훅 (`event_sms_hook`): `_get_targets_event` 공유 → 동일 적용

---

## 5. 회귀 위험

| 위험 | 평가 |
|---|---|
| 과거 호환 | 운영 효과 낮은 발송 차단 — 회귀 아님 |
| 다른 event 스케줄에 영향 | ✅ 의도된 변경 (당일은 마케팅 효과 없음) |
| 당일 체크인 안내가 필요한 케이스 | event 카테고리 부적합 — daily / custom_schedule 로 분리 권장 |
