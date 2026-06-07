# P3 사전조사 — 취소 자동 전파 (SPLIT_CANCEL_MODE 플래그, 기본 OFF)

> 부모 계획: naver_split 근본 해결 (수정판 안 A). 선행: [P1](./split-group-step-01-column-and-record.md) ✅ [P2](./split-group-step-02-backfill-alerts.md) ✅
> 분류: 🔴 동작 추가 — 단 **기본값 `alert` 로 배포 시 P2 와 100% 동일 동작** (auto 전환은 별도 운영 결정)
> 변경 규모: config 1필드 + split_group_guard 전파 함수군 + naver_sync 2지점 + 통합테스트 + 활성화 절차서(본 문서 §7)

---

## 1. 목적

`SPLIT_CANCEL_MODE=auto` 일 때: 네이버발 취소(`incoming naver_status=='cancelled'`)가 확인된
분할 primary 의 **비보호** CONFIRMED sibling 을 자동 취소 (status + cancelled_at +
`on_status_cancelled` lifecycle + 수동 stay_group unlink). `alert`(기본) 일 때는 P2 와 동일.

**전파 트리거는 naver_sync 경로만** — 네이버의 취소 상태를 손에 들고 있는 유일한 지점.
DELETE/PATCH(운영자가 현장에 있음)/sweep(윈도우 밖 추정)은 경보 유지. 부활(취소→확정)은
**경보만** (lifecycle 에 칩/배정 복구 이벤트가 없어 자동 부활 전파 금지 — red-team).

## 2. red-team 검증 제약 (위반 금지)

| 제약 | 반영 |
|---|---|
| 전파 트리거 = 술어식 (트랜지션 금지 — 운영자 선취소 mef 핀 사각) | P2 의 `split_cancel_candidates` 수집 술어 그대로 재사용 |
| **재전파 금지** — 운영자가 sibling 을 의도적으로 복구(부분취소)했는데 다음 sync 가 또 취소하면 안 됨 | **그룹당 1회 ledger**: ActivityLog(type=`split_cancel_propagated`) 존재 시 전파 skip → 경보로 강등. 술어식+멱등 양립 |
| cancelled_at 누락 금지 (CancelledZone 비노출 + paired-state invariant 위반) | `sibling.cancelled_at = primary.cancelled_at or now(KST)` 명시 복사 |
| 보호신호 풀셋 검사 (mef name/phone 만으론 부족) | **mef 핀 전체(any key)** + check_in/out_pinned + manually_extended_until + gender_manual + 수동 RA(assigned_by='manual') + 미발송 보호 칩(PROTECTED_ASSIGNED_BY=manual/excluded/failed + **레거시 send_status='failed'**, chip_store.py:40-45) — 하나라도 있으면 skip+경보 강등 (과보호가 안전 방향). **의도적 비포함**: notes/section/highlight_color/ReservationDailyInfo/PartyCheckin — 표시·운영 메모성 필드로 '이 sibling 에 실투숙 의도가 있다'는 신호가 아님 (리뷰 검토 후 경계 확정) |
| primary 실제 취소 상태 가드 — mef status 핀 '진짜 모순' 상태(핀+CONFIRMED+네이버 cancelled)에서 전파 금지 | propagate_cancel 진입부에서 `primary.status != CANCELLED` 면 경보 강등 (naver_sync 모순 분기의 '자동 보정 위험, 경보만' 선언과 일관 — 리뷰 HIGH finding) |
| sibling별 SAVEPOINT 격리 (1멤버 실패가 sync 전체 rollback 금지) | `db.begin_nested()` (room_assignment.py:373 전례) — 실패 멤버는 rollback+기록 후 계속 |
| same_day 는 멤버 자신의 check_in 기준 | `str(sibling.check_in_date) == today_kst()` |
| sent 칩 보존 | `on_status_cancelled` 가 미발송(sent_at IS NULL)만 삭제 (lifecycle 기존 정책) |
| stay_group unlink + peer 칩은 **caller 책임** (lifecycle docstring :143) | naver_sync :828-846 패턴을 sibling 에 동일 적용 |
| 경보 관찰 기간 고아는 auto 전환 후에도 영구 미전파 (ledger 아님 — 술어는 fetch 윈도우 의존) | §7 활성화 절차에 **P0 정리 재실행** 명문화 |

## 3. 변경 지점

### 3-1. `app/config.py` — Settings 에 1필드
```python
SPLIT_CANCEL_MODE: str = "alert"   # 'alert'(기본, P2 동작) | 'auto'(비보호 sibling 자동 취소)
```

### 3-2. `services/split_group_guard.py` — 전파 함수군 추가 (기존 함수 무수정)
- `TYPE_CANCEL_PROPAGATED = "split_cancel_propagated"` (ledger 겸용)
- `_propagated_before(db, gid)` — **전기간** ledger 조회 (일일 dedup 아님)
- `_protection_signals(db, sibling) -> list[str]` — §2 풀셋
- `propagate_cancel(db, primary, source) -> dict` — ledger hit 시 `alert_cancel_orphan(dedup=True)` 로 강등.
  전파 성공/skip/실패 무관하게 **그룹당 ledger 1회 기록** (부분 skip 그룹의 잔존 sibling 은
  이후 매일 경보 경로가 담당 — 재전파로 운영자와 싸우지 않음)
- `alert_reactivated_orphan(db, primary, source)` — 부활 경보 (일일 dedup, type=`split_reactivated_orphan`)

### 3-3. `services/naver_sync.py` — 2지점
(a) Phase 2 루프: `old_status` 스냅샷 추가 → CANCELLED→CONFIRMED 전이 + 그룹 키 보유 시
`split_reactivated_candidates` 수집 (부활은 **전이 기반** — 의도적 부분취소 상태가
매일 경보로 오인되지 않게. 술어식이면 '운영자가 sibling 만 취소한 정상 상태'를 영구 경보)
(b) Phase 2.8: `settings.SPLIT_CANCEL_MODE == 'auto'` 분기 — auto 면 `propagate_cancel`,
아니면 기존 `alert_cancel_orphan`. reactivated 후보는 모드 무관 경보.

## 4. 동작 동등성 (alert 모드 = P2 와 100% 동일)

| 경로 | alert(기본) | auto |
|---|---|---|
| naver 취소 + 잔존 sibling | P2 경보 (변경 없음) | 비보호 sibling 취소 + lifecycle / 보호·기전파 그룹은 경보 강등 |
| DELETE/PATCH/sweep | P2 그대로 | P2 그대로 (전파 안 함) |
| 부활 전이 | 경보 (신규 — alert 모드에도 추가, 관측 가치) | 경보 (자동 복구 금지) |
| bc drift / unsplit | P2 그대로 | P2 그대로 |

유일한 alert-모드 변화: 부활 전이 경보 추가 (alert-only, 데이터 무변경 — P2 계약 유지).

## 5. 실패 시나리오 대응

- 전파 중 1 sibling 예외 → SAVEPOINT rollback, failed 기록, 나머지 계속. Phase 2.8 외곽 try 가 최종 방어
- 네이버 글리치 오취소 → primary 부활 시 reactivated 경보 (sibling 자동 복구는 금지 — 수동). ledger 가 재전파도 차단
- 운영자 부분취소(한 방만 살림) → ledger 로 재전파 차단. 잔존 CONFIRMED sibling 일일 경보는 지속 (의도된 노출 — '그룹 분리' 액션은 후속 검토)
- propagated ledger ActivityLog 가 운영자에 의해 삭제되면 재전파 위험 → ActivityLog 는 삭제 UI 없음 (조회 전용) — 허용 리스크
- auto 켠 직후 과거 고아 일괄 취소 기대 → 일어나지 않음 (술어는 fetch 윈도우 내 incoming 필요) — §7 P0 재실행이 담당
- ledger check-then-act race (이중 전파) → **단일 워커 전제** (entrypoint.sh `GUNICORN_WORKERS:-1` 기본 + Phase 2.8 은 await 없는 동기 블록이라 단일 이벤트 루프에서 직렬). 워커 수 늘리면 ledger 를 유니크 제약 전용 행으로 옮겨야 함 — config 주석에 전제 기록
- 부활 경보 one-shot 유실 창: 전이 사이클에서 Phase 2.8 예외 시 부활 경보 1회 유실 가능 (전이 기반 수집의 본질적 한계 — 발생 확률 극히 낮아 **수용**). 운영자 PATCH 복구 경로는 reservations.py 에 별도 경보 추가로 커버

## 6. 검증 계획

기존 P2 테스트 15건 무수정 통과(alert 기본값 회귀 증명) + 신규: 전파/cancelled_at/sent 칩 보존/
보호신호 skip(핀·수동RA·보호칩)/ledger 재전파 금지(부분복구)/수동 stay_group unlink/부활 경보.

## 7. ⚠️ auto 전환 절차 (스위치 켜기 전 체크리스트 — 순서 엄수)

1. P2 경보 1~2주 관찰: 오매칭 0건 + 글리치 오취소 빈도 확인
2. backfill `--apply` 완료 + `naver_split sibling 존재 AND split_group_id NULL` 0건 확인
3. **P0 정리 스크립트 재실행**: `python -m scripts.cleanup_orphan_split_siblings` dry-run → `--apply`
   (경보 기간 누적 고아 소급 — 트리거 멱등성 공백 보완)
4. **정답지 승격**: naver-sync-sub-events.yaml 의 forbidden_events 에서
   `split_guard.cancel_propagated` 제거 → CONDITIONAL 로 재등재 (forbidden 항목의 reason 에
   필드 명세 보관됨). alert 운영 중엔 forbidden 이 설정 사고(의도치 않은 auto)를 일일 검증에서 잡아줌
5. 단일 워커 확인: `GUNICORN_WORKERS` 미설정(기본 1) 또는 =1
6. `.env` 에 `SPLIT_CANCEL_MODE=auto` + 재시작 (오타는 Literal 타입이 기동 거부)
7. 첫 전파 발생 시 diag `split_guard.cancel_propagated` + ActivityLog 확인
롤백: `SPLIT_CANCEL_MODE=alert` 복귀 (재배포 불요) + 정답지 forbidden 원복. 전파분 복원은 ActivityLog 원장 + PATCH confirmed
