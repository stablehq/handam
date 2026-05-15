# sync_sms_tags 통합 — 단계 분해 계획

> 작성일: 2026-05-15
> 상태: 사전조사 (OQ 결정 대기)
> 부모 설계: 이 문서 §1 "현황 진단"
> 관련 마이그레이션: [chip-store-migration-plan.md](./chip-store-migration-plan.md) (완료)
> 사상: chip-store 가 CRUD 메커니즘 통합. 본 작업은 caller 가 어느 reconcile 진입점을 호출하는지 통합.

---

## 원칙 (chip-store 와 동일)

1. **기존 기능 변화 금지** — 의도된 변화 (4종 칩 누락 정상화) 만 허용
2. **각 단계는 별도 PR + 별도 사전조사 문서** — `sync-sms-tags-step-NN-*.md`
3. **각 호출처별 라인 단위 검증**
4. **각 단계는 직전 단계와 독립** — 롤백 시 시스템 동작
5. **diag-golden 정답지 영향 사전 확인**

---

## 1. 현황 진단

### 1-1. `sync_sms_tags` vs `reconcile_all_chips`

```python
# sync_sms_tags (room_assignment.py:198) — 1종 칩만
def sync_sms_tags(db, reservation_id, schedules=None):
    reconcile_chips_for_reservation(db, reservation_id, schedules)
    # 효과: 기본 SMS 칩 (체크인안내 등) 만 reconcile

# reconcile_all_chips (reconcile.py:23) — 5종 칩 통합
def reconcile_all_chips(db, reservation_id, *, dates=None, room_id=None):
    sync_sms_tags(db, reservation_id)                        # ① 기본
    for d in target_dates:
        reconcile_surcharge(db, reservation_id, d, room_id)  # ② 추가요금
        reconcile_party3_mms_for_reservation(db, res_id, d)  # ③ 파티3
        reconcile_room_upgrade_promise(db, res_id, d)        # ④ 업그레이드 약속
        reconcile_room_upgrade_review(db, res_id, d)         # ⑤ 업그레이드 후기
```

### 1-2. 9 호출처 분류

#### Group A — 의도된 부분 호출 (변경 안 함, 3건)

| 위치 | 이유 |
|------|------|
| `reconcile.py:62` | `reconcile_all_chips` 의 1번째 단계 — 정의상 의도됨 |
| `room_auto_assign.py:109` | 직후 113~ 에서 `reconcile_surcharge_batch` + `reconcile_room_upgrade_*_batch` 별도 호출. **배치 최적화** (N건 res × 5종 → 5종 batch × N건). |
| `room_assignment.py:435` | dorm push-out peer. 직후 `surcharge` + `upgrade_review` 별도 처리 (435~ 코멘트). |

#### Group B — 4종 누락 위험 (이주 후보, 6건)

| 위치 | 시나리오 | 누락 가능성 |
|------|---------|----------|
| `reservations.py:370` | unlink_stay_group 후 peer | 연박 끊긴 peer 의 surcharge/upgrade 칩 stale 가능 |
| `reservations_room.py:69` | 수동 unassign 후 | RA 변경 → surcharge 칩 stale (정원 재계산 필요) |
| `reservations_stay.py:101` | link_stay_group 후 linked | 연박 묶인 후 surcharge 합산 변동 가능 |
| `reservations_stay.py:141` | unlink_stay_group 후 affected | 동일 |
| `naver_sync.py:790` | peer unlink 후 | 동일 |
| `naver_sync.py:843` | sms field (party_type 등) 변경 후 | party3 칩 stale 가능 |

→ **6 곳에서 4종 칩 (surcharge / party3 / upgrade_promise / upgrade_review) 이 stale 될 수 있음**.

### 1-3. 정확한 위험 평가

| 누락 칩 | 운영 사고 시나리오 |
|---------|-----------------|
| surcharge | 정원초과 손님 → 추가요금 안내 SMS 누락 → 매출 손실 / 컴플레인 |
| party3 | party_type 변경 후 → 파티 안내 MMS 누락 |
| upgrade_promise | 객실 업그레이드 약속 칩 stale → "그날 받기로 한 안내" 안 감 |
| upgrade_review | 업그레이드 후기 요청 stale |

운영 영향 큼 — 정확성 우선.

---

## 2. 의도된 동작 변화

| # | 누락 패턴 | 발생 위치 | 해결 |
|---|---|---|---|
| 1 | unlink_stay_group 후 peer 의 4종 칩 stale | reservations.py:370, naver_sync.py:790 | reconcile_all_chips 로 교체 |
| 2 | link_stay_group 후 4종 칩 stale | reservations_stay.py:101 | 동일 |
| 3 | unlink_stay_group 후 affected 의 4종 칩 stale | reservations_stay.py:141 | 동일 |
| 4 | 수동 unassign 후 surcharge 칩 stale | reservations_room.py:69 | 동일 |
| 5 | naver sms field 변경 후 party3 stale | naver_sync.py:843 | 동일 |

---

## 3. Non-goals

- Group A (배치 최적화 의도) 는 변경 안 함
- `sync_sms_tags` 함수 자체 제거 — `reconcile_all_chips` 의 1단계로 계속 사용
- `reconcile_all_chips` 의 다른 chip 함수 시그니처 변경
- 성능 최적화 (배치 vs 단건) — 별도 작업

---

## 4. 미결정 사항 (OQ)

> 🚧 사용자 결정 필요. PR1 시작 전 확정.

### OQ-1 ⭐ 이주 범위 — 6곳 모두 vs 선별?

| 옵션 | 내용 | 영향 |
|------|------|------|
| A | **Group B 6곳 모두** reconcile_all_chips 로 교체 | 정확성 최대. 일부 경로 성능 저하 (단건 reconcile × 5종) |
| B | **선별** — 정말 4종 누락 위험 있는 곳만 (예: link/unlink, naver field 변경). RA 변경만 있는 곳은 sync_sms_tags 유지 | 균형. 위치별 분석 필요 |
| C | **호출 자체 변경 안 하고**, sync_sms_tags 가 5종 모두 호출하게 변경 | API 단순. 그러나 모든 호출처에 5종 부담 (Group A 의 배치 최적화 의도 깨짐) |

### OQ-2 ⭐ 성능 영향 허용 범위

각 호출처 빈도:
- `link_stay_group`: 운영자 수동, 하루 0~수회
- `unlink_stay_group`: 동일
- `reservations_room.py:69` (수동 unassign): 하루 수회~수십회
- `reservations_stay.py:141`: 운영자 수동
- `naver_sync.py:790, 843`: 5분 cron, 변경 시만 발화

→ 빈도 모두 작음. 5종 reconcile 부담 미미. **OQ-1 옵션 A 선호 시 성능 안전**.

### OQ-3 ⭐ `sync_sms_tags` 함수 향후 운명

본 마이그레이션 후 `sync_sms_tags` 의 외부 호출이:
- Group A (3곳): 유지 — 배치 최적화 의도
- Group B (6곳): 제거됨 → reconcile_all_chips 사용

**남은 외부 호출 3곳 + 내부 (chip_reconciler 위임)**. 함수 자체는 유지.

향후 추가 정리 가능:
- `sync_sms_tags` 를 private 화 (`_sync_sms_tags`)?
- Group A 의 배치 최적화도 통합 함수 (`reconcile_all_chips_batch`) 로?

→ 본 PR 범위 외. **현재 sync_sms_tags 는 그대로 유지 + caller 만 변경**.

### OQ-4 ⭐ `reconcile_all_chips` 의 dates 인자

현재 시그니처: `reconcile_all_chips(db, reservation_id, *, dates=None, room_id=None)`

- `dates=None` → 예약의 stay 전체 (check_in ~ check_out)
- `dates=[...]` → 특정 날짜만

각 caller 의 적절한 dates:
- link/unlink stay: 전체 stay (dates=None)
- 수동 unassign with date: 그 날짜만 (dates=[that_date])?
- naver field 변경: 전체 stay
- peer sync: 전체 stay

→ 대부분 None 이 적절. 일부만 명시. **호출처별 사전조사에서 결정**.

---

## 5. 단계 분해 (6 PR)

각 PR 의 동작 변화:
- 🔵 의도된 변화 (4종 칩 누락 해결)

### A. caller 별 이주 (1 PR per file)

| # | 작업 | 변경 파일 | 이슈 |
|---|---|---|---|
| 1 | `reservations_stay.py` 2건 (link/unlink) → reconcile_all_chips | `app/api/reservations_stay.py` | linked_ids 각자 |
| 2 | `reservations.py:370` → 동일 | `app/api/reservations.py` | peer_ids 각자 |
| 3 | `reservations_room.py:69` → 동일 | `app/api/reservations_room.py` | RA 변경된 res |
| 4 | `naver_sync.py` 2건 → 동일 | `app/services/naver_sync.py` | peer + sms field |

### B. 회귀 차단

| # | 작업 | 변경 파일 |
|---|---|---|
| 5 | (선택) `sync_sms_tags` 직접 호출 lint 추가 — Group A 외 차단 | `backend/scripts/check_sync_sms_tags_lint.sh` |

→ Group A (3곳) 만 화이트리스트로 허용.

---

## 6. PR 분할

```
PR1   reservations_stay.py 2건 (link/unlink 후 4종 칩 보장)
PR2   reservations.py:370 (unlink peer 4종)
PR3   reservations_room.py:69 (수동 unassign 후 4종)
PR4   naver_sync.py 2건 (peer + sms field)
PR5   (선택) lint 추가
```

각 PR 후 diag-golden 검증 회차에서 4종 칩 발화 빈도 확인.

---

## 7. 진행 상태 (체크리스트)

- [x] OQ-1 결정 (이주 범위) — **전수 교체** (Group B 6곳 모두)
- [x] OQ-2 결정 (성능 허용) — 빈도 분석상 안전 (운영자 수동 + 5분 cron 변경 시만)
- [x] OQ-3 결정 (sms_tags 운명) — **유지** (Group A 3곳이 계속 사용, 본 PR 범위 외)
- [x] OQ-4 결정 (dates 인자) — 호출처별 사전조사에서 결정 (기본 None=전체 stay)
- [ ] PR1 reservations_stay
- [ ] PR2 reservations.py
- [ ] PR3 reservations_room
- [ ] PR4 naver_sync
- [ ] PR5 lint (선택)
