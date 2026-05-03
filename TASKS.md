# Pending Tasks (2026-05-03 9회차 검증 발견)

발단: 5/1 김수민(res_id=4761, ci=co=2026-05-01 단일날짜) 연박/날짜변경 시도 케이스에서 발견된 항목들.

---

## 🔴 HIGH — 단일날짜 예약 연박묶기 봉쇄 버그

**파일**: `frontend/src/pages/RoomAssignment.tsx`
**증상**: 단일날짜 예약(`ci=co`, 수동/파티만/데이유) 을 시작점으로 한 연박묶기 모달에서 다음날(체크아웃 다음) 후보가 절대 노출되지 않음. 사용자 시나리오: "4761(5/1 단일) 연박묶기 모달에서 5/2 예약(4825)이 안 보임" 의 직접 원인.

**원인**: next-day 계산이 `co || ci` fallback 으로만 되어있어 `ci===co` 일 때 같은 날짜로 폴백.

### 수정 위치 4곳

| 라인 | 함수 | 현재 |
|---|---|---|
| 1469 | `openStayGroupModalForRes` 모달 오픈 | `const nextDate = res.check_out_date \|\| res.check_in_date;` |
| 1509 | `handleStayGroupAddMore` (right 분기) | `const nextDate = selected.check_out_date \|\| selected.check_in_date;` |
| 1526 | `handleStayGroupDirectionChange` (right) | `loadReservationsForDate(last.check_out_date \|\| last.check_in_date);` |
| 1501 | `handleStayGroupAddMore` 검증 | `if (lastInChain && selected.check_in_date !== lastInChain.check_out_date) { ... 거부 }` |

### 제안 수정안 (헬퍼 1개로 통일)

```typescript
const nextDateOf = (r: { check_in_date: string; check_out_date?: string | null }) =>
  (r.check_out_date && r.check_out_date !== r.check_in_date)
    ? r.check_out_date
    : dayjs(r.check_in_date).add(1, 'day').format('YYYY-MM-DD');

// 1469, 1509, 1526 → loadReservationsForDate(nextDateOf(res|selected|last))
// 1501 검증 → selected.check_in_date !== nextDateOf(lastInChain)
```

### 비고
- prev 방향(1497, 1520)은 이미 `dayjs(...).subtract(1,'day')` 패턴이 있어 정상.
- next 방향만 비대칭으로 fallback 만 있던 상태 → 헬퍼 도입으로 양방향 대칭화.
- 검증/QA: 4761 (ci=co=5/1) 로 모달 열고 5/2 후보(4825) 가 보이는지, 검증 거부 없이 추가 가능한지 확인.

---

## 🟡 MED — "예약 수정" 폼의 check_out_date payload 누락

**파일**: `frontend/src/pages/RoomAssignment.tsx:1850-1909` (editingId 모달 onSubmit)

**현재 동작** (`1867-1875`):
```typescript
if (values.multi_night && values.nights && values.nights >= 2 && values.date) {
  const checkIn = dayjs(values.date);
  values.check_out_date = checkIn.add(values.nights, 'day').format('YYYY-MM-DD');
}
// ...
values.check_in_date = values.date;  // ci 는 항상 set
// ↑ multi_night 미체크 시 values.check_out_date 키 자체가 payload 에 없음
```

**문제**:
- 백엔드 `update_reservation` 은 `exclude_unset=True` 라 ci 만 갱신
- 단일날짜 → 연박 전환을 이 폼으로 시도하면 ci 만 변경되고 co 는 그대로 → ci > co 가 되거나 변경이 무효화됨
- 백엔드 로그의 `changed_fields=['check_in_date']` 단독 흔적 5건과 부합

**결정 필요**:
- (A) 폼이 단일날짜 → 연박 전환을 지원해야 함 → multi_night 미체크 시에도 co 를 적절히 보내거나(예: co=ci), 폼에 체크아웃 칸 추가
- (B) 폼은 그대로 두고, 날짜 변경은 컨텍스트 메뉴 "예약 날짜 변경" 모달만 사용하게 안내 → ci 단독 PUT 이 의도된 동작

---

## ⏸ 보류 — Q1 4761 PUT ci 단독 PUT 3건의 출처 미스터리

**상황**:
- 사용자: 컨텍스트 메뉴 → "예약 날짜 변경" 클릭, 모달에서 co 만 5/2 로 변경
- 모달 코드(`3914-3925`)는 ci+co 둘 다 보냄, 가드(`3919 checkOut > checkIn`)도 통과해야 정상
- 하지만 백엔드 로그에 ci+co 둘 다 든 PUT 흔적 없음, ci 단독 PUT 3건만 존재 (14:19:09, 14:19:32, 14:49:54)
- 배포된 frontend 번들(`2026-05-01 11:09 빌드`)에는 ci+co 둘 다 보내는 코드가 정확히 박혀있음 확인

**유력 가설**: 사용자 브라우저가 옛 JS 번들 캐시 (4/3 이전 버전은 ci 만 보냈을 가능성).

**검증 방법**:
1. 브라우저 hard refresh (Ctrl+Shift+R / Cmd+Shift+R)
2. 4761 컨텍스트 메뉴 → "예약 날짜 변경" → 두 번째 칸(체크아웃)을 5/2 로 변경 → "변경" 클릭
3. 백엔드 로그에서 `changed_fields=['check_in_date', 'check_out_date']` 둘 다 든 PUT 이 찍히는지 확인

**대안 가설** (캐시 아니면): 사용자가 본 모달이 dateChangeModal 이 아니라 다른 모달이었을 가능성. 모달 헤더가 "예약 날짜 변경 — 김수민" 이었는지 확인 필요.

---

## (참고) Q2 정책 결정 필요 — 방문자명 노출

**파일**: `frontend/src/pages/RoomAssignment.tsx:154,2175` (카드/테이블 표시)

**현재**: 백엔드는 `customer_name`(예약자) 와 `visitor_name`(방문자) 를 별도 컬럼으로 저장하지만 프론트는 `customer_name` 만 표시. visitor 우선/병기 fallback 없음.

**결정 필요**: 방문자 정보를 화면에 노출할 것인지, 의도된 동작으로 둘 것인지.

수정 시: visitor_name 이 customer_name 과 다를 때 카드에 보조 표기 (`(방문자: ...)` 등) 추가.
