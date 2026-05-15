# 5. 예약 변경 전체 경로 — Mutator + Lifecycle 두 단계 게이트웨이

> 🔴 버그·보호 없음 &nbsp;|&nbsp; ⚠️ 일부만 처리 &nbsp;|&nbsp; 🛡 보호 로직 있음 &nbsp;|&nbsp; ✅ 정상

```mermaid
flowchart TB
    classDef entry  fill:#FFE8CC,stroke:#FF9F00,color:#191F28,font-weight:bold
    classDef ok     fill:#E8F3FF,stroke:#3182F6,color:#191F28
    classDef warn   fill:#FFFBE6,stroke:#FF9F00,color:#191F28
    classDef bug    fill:#FFE4E1,stroke:#F04452,color:#191F28
    classDef shield fill:#E8FAF5,stroke:#00C9A7,color:#191F28
    classDef db     fill:#F0E8FF,stroke:#8B5CF6,color:#191F28
    classDef sms    fill:#dcfce7,stroke:#16a34a,color:#191F28
    classDef gate   fill:#FFF0FF,stroke:#9B59B6,color:#191F28,font-weight:bold
    classDef group  fill:#FAFAFA,stroke:#B0B8C1,color:#4E5968

    %% ═══════════════════════════════════════════════════════════════
    %% 📥 진입점 9종 (시스템이 예약을 건드리기 시작하는 모든 트리거)
    %% ═══════════════════════════════════════════════════════════════
    subgraph ENTRY["📥 진입점 — 시스템이 예약을 건드리는 모든 트리거"]
        direction TB

        subgraph AUTO["⚙️ 자동 (스케줄러/외부 동기화)"]
            direction TB
            m_N(["① 네이버 동기화\n5분 cron · 신규/변경/취소 감지\n📁 jobs.sync_naver_reservations_job"]):::entry
            m_A_AUTO(["⑦ 자동 객실 배정\n10:01 cron · 미배정 예약에 룸 매칭\n📁 jobs.daily_room_assign_job"]):::entry
            m_CC_IN(["⑨ 예약 취소\n네이버 응답 status=cancelled 감지\n📁 naver_sync._update_reservation"]):::entry
        end

        subgraph MANUAL["👤 운영자 수동 (직원이 화면에서 클릭)"]
            direction TB
            m_C(["② 수동 예약 생성\n운영자가 직접 입력 (POST)\n📁 reservations.create_reservation"]):::entry
            m_U(["③ 수동 필드 수정\n예약 카드에서 필드 편집 (PUT)\n📁 reservations.update_reservation"]):::entry
            m_E(["④ 연박 연장\n[+1일] 클릭 · check_out +1 + pin\n📁 reservations_stay.extend_stay"]):::entry
            m_R(["⑤ 연박 축소\n[-1일] 클릭 · 마지막날 RA 삭제\n📁 reservations_stay.reduce_extension"]):::entry
            m_D(["⑥ 드래그 이동\n게스트 카드를 다른 날짜 열로\n📁 reservations.update_reservation 경유"]):::entry
            m_DEL(["⑩ 예약 삭제\n휴지통 클릭 (DELETE)\n📁 reservations.delete_reservation"]):::entry
        end
    end

    %% ═══════════════════════════════════════════════════════════════
    %% 1단계: Mutator — "누가 어떤 필드 바꿀 수 있나" 권한 게이트
    %% ═══════════════════════════════════════════════════════════════
    subgraph GATE1["1단계 · Mutator — 필드 변경 권한 게이트"]
        direction TB
        m_MUTATOR["⭐ ReservationMutator.apply_changes(source, fields)\n수정 시도를 권한표로 검사 → 통과한 필드만 적용\n📁 reservation_mutator.py:78"]:::gate
        m_PERM["🛡 권한 평가 규칙 (15필드 × 3소스)\n• NAVER + pinned=True → 덮어쓰기 차단 (수동수정 보호)\n• MANUAL + 날짜변경 → pin 자동 ON\n• SYSTEM → name/phone 등 변경 불가 (never)"]:::shield
        m_MUTATOR --> m_PERM
    end

    %% ═══════════════════════════════════════════════════════════════
    %% 2단계: Lifecycle — 사건별 후처리 매뉴얼 5장
    %% ═══════════════════════════════════════════════════════════════
    subgraph GATE2["2단계 · Lifecycle — 사건별 후처리 매뉴얼 5장"]
        direction TB
        m_LC_DATES["on_dates_changed\n📌 날짜 변경 후처리\n파티/메모 이동 → RA 정리 → 칩 재계산"]:::gate
        m_LC_CONST["on_constraints_changed\n📌 인원/성별 변경 후처리\ninvariant 검사 → 위반 RA 해제 → 칩 재계산"]:::gate
        m_LC_CANCEL["on_status_cancelled(same_day)\n📌 취소 후처리\nTrue=오늘이후만 / False=전체 + 미발송칩 삭제"]:::gate
        m_LC_ROOM["on_room_assigned(pushed_out)\n📌 방 배정 직후\n본인 + 밀려난 예약 각자 칩 재계산"]:::gate
        m_LC_DEL["on_reservation_deleted\n📌 삭제 후처리\n모든 RA + 미발송 칩 cascade 삭제"]:::gate
    end

    %% ═══════════════════════════════════════════════════════════════
    %% 후처리 함수 (lifecycle 내부에서만 호출, private 화됨)
    %% ═══════════════════════════════════════════════════════════════
    subgraph PROC["🛠 후처리 함수 (lifecycle 내부 전용)"]
        direction TB
        m_SHIFT["_shift_daily_records\n파티 체크인·메모 등 부수 데이터를 새 날짜로 평행이동\n📁 room_assignment.py:809 (private)"]:::ok
        m_RDATES["_reconcile_dates\n범위 밖 RA 삭제 + 누락 날짜 INSERT (push-out 처리)\n📁 room_assignment.py:894 (private)"]:::ok
        m_INVCHK["check_assignment_validity\n도미토리 성별·정원·연속성 invariant 검사 → 위반 dates 추출\n📁 room_assignment_invariants.py"]:::ok
        m_UNASSIGN_DATES["unassign_dates\n비연속 날짜 list 의 RA 삭제 + bed_order 재정렬 + 칩 cleanup\n📁 room_assignment.py:668 (ded670f 신규)"]:::shield
        m_CLEAR_ALL["clear_all_for_reservation\n예약의 모든 일자 RA + denormalized 필드 통째 삭제\n📁 room_assignment.py"]:::ok
        m_CORE["⭐ assign_room\n객실 배정 메인 — 비밀번호 prefix + bed_order 계산 + push-out 발생 가능\n📁 room_assignment.py:213"]:::ok
    end

    %% ═══════════════════════════════════════════════════════════════
    %% 수동 생성용 inline 후처리 (lifecycle 우회 경로)
    %% ═══════════════════════════════════════════════════════════════
    m_INLINE["📌 inline 후처리 (수동 생성 전용)\ncompute_is_long_stay + reconcile_all_chips\n📁 reservations.create_reservation 내부\n⚠️ Mutator/Lifecycle 미경유 — 새 row 라 변경 게이트 불필요"]:::ok

    %% ═══════════════════════════════════════════════════════════════
    %% 칩 재계산 5종 (reconcile_all_chips 진입점 → 5 함수 순차 호출)
    %% ═══════════════════════════════════════════════════════════════
    m_RALL["⭐ reconcile_all_chips\n예약·스케줄 변경 시 5종 칩을 항상 전부 재평가\n📁 reconcile.py:23"]:::ok
    m_chip1["① sync_sms_tags<br/>기본 SMS 칩 (체크인안내·체크아웃알림 등)"]:::ok
    m_chip2["② reconcile_surcharge_batch<br/>추가요금 칩 (정원 초과 시 자동 안내)"]:::ok
    m_chip3["③ reconcile_party3_mms<br/>파티3 MMS 칩 (이벤트 안내 이미지)"]:::ok
    m_chip4["④ reconcile_room_upgrade_promise<br/>객실 업그레이드 약속 칩"]:::ok
    m_chip5["⑤ reconcile_room_upgrade_review<br/>업그레이드 후기 요청 칩"]:::ok
    m_GUARD["🛡 삭제 보호 검사\n이미 발송(sent_at) · 운영자수동(manual) · 제외(excluded) · 실패(failed) 칩은 보존\n📁 chip_reconciler.py:335"]:::shield

    %% ═══════════════════════════════════════════════════════════════
    %% DB 테이블 (3 종)
    %% ═══════════════════════════════════════════════════════════════
    m_DB_RES[("Reservation\n예약 마스터 레코드")]:::db
    m_DB_ROOM[("RoomAssignment\n날짜별 객실 배정 (bed_order 포함)")]:::db
    m_DB_CHIP[("ReservationSmsAssignment\nSMS 발송 예정 목록 (=칩)")]:::db

    %% ═══════════════════════════════════════════════════════════════
    %% CI Lint — 회귀 차단 (정적 검사)
    %% ═══════════════════════════════════════════════════════════════
    m_LINT["🔒 CI Lint — 회귀 차단 (마이그레이션 단계 #22)\n① RoomAssignment 를 services/room_assignment.py 외부에서 직접 조작 시 fail\n② shift_daily_records / reconcile_dates 외부 호출 시 fail (private 우회)\n📁 scripts/check_lifecycle_lint.sh"]:::shield

    %% ═══════════════════════════════════════════════════════════════
    %% SMS 발송 파이프라인 (Template Schedule 8 필터 → 실제 발송)
    %% ═══════════════════════════════════════════════════════════════
    m_SCHED(["⏰ APScheduler 트리거\n설정된 시간(또는 cron) 도달 → 발송 사이클 시작\n📁 scheduler/template_scheduler.py"]):::entry

    subgraph FILTER["🔍 칩 → 실제 발송 대상 추리는 8단계 필터"]
        direction TB
        m_f1["① 테넌트 필터 (line 451)"]:::ok
        m_f2["② 칩 사전 필터 (line 460)"]:::ok
        m_f3["🛡 ③ 안전 가드 ±7일 (line 483)"]:::shield
        m_f4["④ 날짜 타겟 (line 492)"]:::ok
        m_f5["⑤ 타겟 모드 (line 499)"]:::ok
        m_f6["⑥ 구조 필터 (line 506)"]:::ok
        m_f7["🛡 ⑦ 발송 이력 제외 (line 509)"]:::shield
        m_f8["⑧ 숙박 필터 (line 539)"]:::ok
        m_f1 --> m_f2 --> m_f3 --> m_f4 --> m_f5 --> m_f6 --> m_f7 --> m_f8
    end

    m_RENDER["✉️ 템플릿 렌더링\n변수 치환 + 객실 비밀번호 prefix 등\n📁 templates/variables.py · renderer.py"]:::ok
    m_SEND["📨 Aligo SMS API 호출\n실제 SMS/LMS 발송 (90B 기준 자동 감지)\n📁 real/sms.py · sms_provider.send_sms"]:::sms
    m_TRACK["✅ record_sms_sent\n발송 결과를 칩의 sent_at 컬럼에 기록 (중복 발송 차단)\n📁 services/sms_tracking.py"]:::ok

    %% ════════════════════════════════════════════════════════════════
    %% 엣지 — 진입점에서 게이트로
    %% ════════════════════════════════════════════════════════════════

    %% 5 운영자 수정 경로 → Mutator
    m_U & m_E & m_R & m_D --> m_MUTATOR

    %% 네이버 sync 도 Mutator 통과 (NAVER source)
    m_N --> m_MUTATOR

    %% 수동 생성: Mutator/Lifecycle 우회 — inline 후처리
    m_C --> m_DB_RES
    m_C --> m_INLINE
    m_INLINE --> m_RALL

    %% Mutator 통과 후 → Lifecycle 분기
    m_PERM -->|"날짜 변경 시"| m_LC_DATES
    m_PERM -->|"인원·성별 변경 시"| m_LC_CONST

    %% 직접 lifecycle 호출 (Mutator 미경유 — 변경이 아님)
    m_CC_IN -->|"status 전환"| m_LC_CANCEL
    m_A_AUTO -->|"신규 배정"| m_CORE
    m_CORE -.->|"assign 직후"| m_LC_ROOM
    m_DEL -->|"row 삭제"| m_LC_DEL

    %% Lifecycle → 후처리 함수
    m_LC_DATES --> m_SHIFT --> m_RDATES --> m_RALL
    m_LC_CONST --> m_INVCHK --> m_RALL
    m_LC_CANCEL -->|"same_day=True (당일)"| m_UNASSIGN_DATES
    m_LC_CANCEL -->|"same_day=False (사전)"| m_CLEAR_ALL
    m_LC_CANCEL --> m_RALL
    m_LC_ROOM --> m_RALL
    m_LC_DEL --> m_CLEAR_ALL

    %% 후처리 함수 → DB
    m_UNASSIGN_DATES --> m_DB_ROOM
    m_CLEAR_ALL --> m_DB_ROOM
    m_CORE --> m_DB_ROOM

    %% reconcile_all_chips → 5 칩 → 보호검사 → DB
    m_RALL --> m_chip1 --> m_chip2 --> m_chip3 --> m_chip4 --> m_chip5 --> m_GUARD --> m_DB_CHIP

    %% Lint (정적 검사) — 점선
    m_LINT -.->|"PR 머지 전 검사"| m_DB_ROOM

    %% SMS 발송 사이클
    m_DB_CHIP -->|"sent_at IS NULL 인 칩"| m_SCHED
    m_SCHED --> m_f1
    m_f8 --> m_RENDER --> m_SEND --> m_TRACK
    m_TRACK -->|"sent_at 갱신"| m_DB_CHIP

    %% 스타일 적용
    class ENTRY,AUTO,MANUAL,GATE1,GATE2,PROC,FILTER group
```

## 노드 색상 가이드

| 색 | 의미 | 예시 |
|----|------|------|
| 🟧 주황 | 진입점 / 트리거 | 네이버 sync, 운영자 클릭, APScheduler |
| 🟪 보라 | 게이트웨이 (핵심 진입 함수) | `apply_changes`, `on_dates_changed` 5장 |
| 🟦 파랑 | 일반 함수 (정상 동작) | `assign_room`, `reconcile_all_chips`, 칩 5종 |
| 🟩 초록 | 🛡 보호 로직 | 권한 평가, 삭제 보호, CI Lint, 발송 이력 가드 |
| 🟪 진보라 | 🗄 DB 테이블 | Reservation, RoomAssignment, ReservationSmsAssignment |
| 🟢 연두 | 📨 외부 API | Aligo SMS |

## 구조 요약

| 영역 | 현재 구조 |
|------|----------|
| **네이버 덮어쓰기 보호** | Mutator pin (`check_in_pinned`, `check_out_pinned`) |
| **후처리 일관성** | Lifecycle 5장 매뉴얼 (`on_dates_changed` / `on_constraints_changed` / `on_status_cancelled` / `on_room_assigned` / `on_reservation_deleted`) |
| **보호 방식** | `check_in/out_pinned` (동기화 보호) + `manually_extended_until` (UI "수동 연박" 표시) — 책임 분리 |
| **칩 재계산** | `reconcile_all_chips` 5종 단일 진입점 |
| **RA 직접 조작** | 0건 — `unassign_dates` 단일 헬퍼로 통합 |
| **`_shift_daily_records` / `_reconcile_dates`** | private (`_` prefix) + lifecycle 내부 호출만 |
| **회귀 차단** | `scripts/check_lifecycle_lint.sh` (RA 직접 조작 + non-_ 호출 차단) |
| **신규 caller 추가 시** | 사건 종류만 결정 → Lifecycle 매뉴얼이 처리 + lint 가 우회 차단 |
| **새 경로 추가 시** | Mutator 1곳만 수정 |
