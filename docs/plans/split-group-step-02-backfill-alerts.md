# P2 사전조사 — backfill + 취소고아 경보 3경로 + bc drift 감지 + 일일 sweep

> 부모 계획: naver_split 근본 해결 (수정판 안 A). 선행: [P1 — 컬럼+기록](./split-group-step-01-column-and-record.md) ✅
> 분류: 🟡 관측 추가 — 예약 데이터 무변경 (경보/diag/ActivityLog 기록만). backfill 만 split_group_id 컬럼에 기록 (다른 컬럼 무접촉)
> 변경 규모: 신규 서비스 모듈 1 + naver_sync 2지점 + reservations 2지점 + jobs 1 + 스크립트 1 + diag-golden 2 + 통합테스트 1
> 후속: P3(자동 전파 — 이 모듈이 실행자로 확장), P4(freeze OR-강화)

---

## 1. 목적

P1 이 심은 `split_group_id` 의 첫 소비자. **alert-only** — 어떤 예약 데이터도 자동 변경하지 않는다.

1. **취소 고아 경보**: primary 취소 시 CONFIRMED 잔존 sibling 을 3경로(naver sync / DELETE / PATCH)에서 탐지·경보
2. **bc drift 감지**: 네이버 booking_count ↔ 그룹 총 row 수 불일치 + 비분할 일반실 bc 1→N 변경 (현재 이중 침묵 → 가시화)
3. **일일 sweep**: sync fetch 윈도우(REGDATE 1일+USEDATE 오늘~내일)를 벗어난 취소를 잡는 마지막 그물
4. **backfill**: 기존 split 그룹(소급분할 52건 포함)에 그룹 키 소급 부여

## 2. red-team 검증에서 확정된 설계 제약 (위반 금지)

| 제약 | 근거 |
|---|---|
| 경보 트리거는 status **트랜지션 금지** → "incoming naver_status=='cancelled' AND CONFIRMED sibling 존재" 술어식 | 운영자 선취소 시 mef status 핀(naver_sync.py:761-766)으로 트랜지션이 영원히 안 일어남 |
| 경보 발화는 Phase 2 **db.commit()(naver_sync.py:230) 이후** 격리 phase | log_activity 의 명시적 db.flush()(activity_logger.py:56)가 루프 중 세션 오염(PendingRollbackError) 유발 — 칩 phase(:324-343) 패턴 준용 |
| drift 비교식 = incoming_bc vs **그룹 총 row 수(취소 포함)** + primary CONFIRMED 가드 | 네이버는 취소건도 fetch 윈도우 동안 매번 재전송 — "alive 수 비교"는 전파/정리 직후부터 5분마다 영구 오탐 |
| 경보 일 1회 dedup (naver_sync/sweep 경로) | 5분 cron 스팸 + ooo-log-validation 오탐 방지. DELETE/PATCH(운영자 직접 행동)는 dedup 없이 즉시 |
| backfill 휴리스틱에 **created_at 사용 금지** | 소급분할 52건은 sibling created_at=스크립트 실행시각(2026-04-26)이라 구조적 무효 |
| backfill ambiguous(후보 0/2+) **자동 기록 금지** | 동일 손님 동일날짜 별도 booking 2건 오연결 → P3 에서 엉뚱한 예약 자동취소 위험 |
| sweep 시각: ~~09:50~~ → **09:45 KST** | 09:50 은 refresh_snapshots_morning_late 가 선점(jobs.py:511-513). 09:45 → 09:50 스냅샷 → 09:55 reconcile → 10:01 배정 순서 유지 |

## 3. 신규 모듈 — `app/services/split_group_guard.py`

공유 헬퍼 (naver_sync / reservations / jobs 3호출처). 파일 상단 docstring 에 책임+단계 명시 (프로젝트 관례).

- `find_confirmed_siblings(db, split_group_id, exclude_id, min_checkout=None)` — defense-in-depth 명시 tenant 필터 (naver_sync.py:328-336 패턴)
- `alert_cancel_orphan(db, primary, source, dedup=True) -> list[int]` — diag `split_guard.cancel_orphan`(critical) + ActivityLog(type=`split_cancel_orphan`, status="failed", detail 에 split_group_id/sibling_ids/발송칩 수). 반환: 경보된 sibling ids
- `alert_bc_drift(db, reservation_id, split_group_id, incoming_bc, source)` — 그룹 총 row 수 비교, primary CONFIRMED 가드, 일 1회 dedup. diag `split_guard.bc_drift`
- `alert_unsplit_multi(db, reservation_id, incoming_bc, source)` — 비분할 매핑 일반실 bc 1→N (freeze 가 덮어쓰기를 막아 stored=1 유지 — 매 sync 재탐지되므로 dedup 필수). diag `split_guard.unsplit_multi_bc`
- `sweep_orphan_groups(db, today_str) -> dict` — 취소 primary(키 보유) × CONFIRMED sibling(check_out>=today) join → alert_cancel_orphan(dedup=True) 재사용. diag `split_guard.sweep`(verbose 요약)
- `_alerted_today(db, activity_type, marker)` — ActivityLog created_at(UTC naive) >= KST 자정 + detail LIKE marker

## 4. 변경 지점 (Before/After)

### 4-1. `naver_sync.py` Phase 2 루프 (L212-228) — 후보 수집 (DB 무접촉, 리스트 append 만)

**Before** (L216-222):
```python
        if existing:
            old_dates = (existing.check_in_date, existing.check_out_date)
            _update_reservation(db, existing, res_data)
            ...
            updated_count += 1
```
**After**: `updated_count += 1` 다음에 수집 블록 추가 —
```python
            # split-group P2: 그룹 정합 경보 후보 수집 (Phase 2.8 일괄 평가 —
            # 루프 내 DB 쓰기/flush 금지, 파이썬 리스트만. 세션 오염 방지)
            if existing.booking_source != "naver_split":
                _incoming_bc = res_data.get("booking_count") or 1
                if existing.split_group_id:
                    if res_data.get("status") == "cancelled":
                        split_cancel_candidates.append(existing.id)
                    split_drift_candidates.append(
                        (existing.id, existing.split_group_id, _incoming_bc))
                elif (_incoming_bc > 1 and (existing.booking_count or 1) == 1
                      and not res_data.get("_is_dormitory")
                      and res_data.get("_has_room_link")):
                    unsplit_multi_candidates.append((existing.id, _incoming_bc))
```
(L210 카운터 선언부에 빈 리스트 3개 추가)

### 4-2. `naver_sync.py` Phase 2.8 신설 — db.commit()(L230) 직후, Phase 3 주석(L232) 앞

try/except + rollback 격리 (칩 phase :341-343 패턴). 후보를 split_group_guard 헬퍼로 평가·발화 후 자체 commit. 실패 시 sync 본 흐름 무영향.

### 4-3. `reservations.py` DELETE (L461-544) — soft-cancel 후 경보 + 응답 메시지

본 commit(L529) **이후** try/except 격리 블록: primary(split_group_id 보유, 비sibling) soft-cancel 시 `alert_cancel_orphan(dedup=False)` + 자체 commit. 응답 message 에 `" — 분할 동반 객실 N건이 아직 확정 상태입니다 (res=...). 함께 취소할지 확인하세요."` 부가. 실패해도 삭제 응답은 정상 반환.

### 4-4. `reservations.py` PATCH — CANCELLED stay_group 블록(L389-405) 다음

`status==CANCELLED AND split_group_id AND booking_source!='naver_split'` 이면 `alert_cancel_orphan(dedup=False)` (endpoint 단일 트랜잭션 내 — 루프 아님, flush 안전). try/except 로 본 PATCH 흐름 보호.

### 4-5. `scheduler/jobs.py` — sweep job (09:45 KST)

`split_orphan_sweep_job` (sync def — refresh_snapshots_job 패턴) + `_for_each_tenant`. 등록: `CronTrigger(hour=9, minute=45, timezone='Asia/Seoul')`, id='split_orphan_sweep'.

### 4-6. `scripts/backfill_split_group_id.py` (신규)

- dry-run 기본 / `--apply`. 테넌트별 `session_for_tenant` 루프 (bypass 는 테넌트 목록 조회만 — jobs._for_each_tenant 패턴)
- sibling(booking_source='naver_split' AND split_group_id IS NULL) 별 primary 후보: 동일 (customer_name, phone, check_in_date, check_out_date, naver_biz_item_id) + booking_source!='naver_split' + naver_booking_id IS NOT NULL — **6-필드, created_at 금지, status 무필터**(취소 그룹도 연결해야 sweep dedup 동작)
- 정확히 1후보 → 양쪽에 `nsplit-{naver_booking_id}` 기록. 0/2+ → ambiguous 리포트만 ([tid=N] res=XXX 규약)
- 멱등 (키 있으면 skip). 운영 실행은 P2 코드 배포 후

### 4-7. diag-golden

- `naver-sync-sub-events.yaml`: CONDITIONAL 로 `naver_sync.split_multi_room`/`split_summary`(기존 미등재 갭 해소, P1 의 split_group_id 필드 포함) + `split_guard.cancel_orphan`/`bc_drift`/`unsplit_multi_bc` 등재
- 신규 `job-split-orphan-sweep.yaml`: 09:45 sweep 정답지

## 5. 동작 동등성

| 경로 | 변화 |
|---|---|
| 예약 row 데이터 | **무변경** (backfill 의 split_group_id 기록 제외 — P1 무동작 컬럼) |
| sync 본 흐름 | 루프 내 리스트 append 만. Phase 2.8 실패는 rollback+suppress — Phase 3~6 정상 진행 |
| DELETE/PATCH 응답 | DELETE message 에 경고 부가만. 실패 시 기존 메시지 그대로 |
| 발송/배정/칩 | **무접촉** |
| 기존 split 가드 (existing_map/연박/booking_source) | **무수정** — 기존 회귀 테스트 무수정 통과가 합격 기준 |

## 6. 실패 시나리오 대응

- 경보 폭주 → 일 1회 dedup (ActivityLog 존재 검사). 운영자 행동 경로(DELETE/PATCH)만 즉시
- Phase 2.8 예외 → rollback + warning 로그, sync 본 흐름 무영향 (5분 후 재시도 자연 발생)
- backfill 오매칭 → ambiguous 자동기록 금지로 원천 차단. dry-run 리포트 수동 검토 후 apply
- sweep 과 sync 경보 같은 날 중복 → 동일 dedup 키(type+split_group_id) 공유로 자동 억제
- 운영자가 sibling 의도적 잔존(부분취소 후 1방 투숙) → 매일 1회 경보 지속이 의도된 동작 (P3 에서 '그룹 분리' 액션 검토)

## 7. 검증 계획

1. 신규 통합테스트 `tests/integration/test_split_group_guard.py` (db fixture): orphan 탐지/dedup/bc drift/unsplit/sweep 날짜경계
2. 기존 split 테스트 19건 무수정 통과
3. 전체 스위트 회귀 0건 (기존 실패 7+2 제외)
4. backfill dry-run 을 운영 DB 에 실행해 리포트 검수 (apply 는 운영자 승인 후)
