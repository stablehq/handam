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

    m_N(["① 네이버 싱크\n5분마다 자동 실행"]):::entry
    m_C(["② 수동 생성\n직원이 직접 입력"]):::entry
    m_U(["③ 수동 수정 PUT\n날짜·인원·구역 변경"]):::entry
    m_E(["④ 연박 연장\n체크아웃 +1일"]):::entry
    m_R(["⑤ 연박 축소\n체크아웃 -1일"]):::entry
    m_D(["⑥ 드래그 이동\n다른 날짜 열로 끌기"]):::entry
    m_A_AUTO(["⑦ 자동 배정\nAPScheduler 매일 실행"]):::entry
    m_DEL(["⑩ 예약 삭제\nDELETE /reservations/{id}"]):::entry
    m_CC_IN(["⑨ 예약 취소\n네이버 싱크에서 감지"]):::entry

    %% ── 1단계: Mutator (필드 변경 권한) ──
    subgraph GATE1["1단계: Mutator (필드 변경 권한 게이트)"]
        m_MUTATOR["ReservationMutator.apply_changes(source, fields)\nreservation_mutator.py"]:::gate
        m_PERM["🛡 FIELD_PERMISSIONS + Pin 검사\nNAVER → pinned 필드 skip + catch-up\nMANUAL → pin 자동 설정\nSYSTEM → 제한 없음"]:::shield
        m_MUTATOR --> m_PERM
    end

    %% ── 2단계: Lifecycle (사건별 후처리 매뉴얼 5장) ──
    subgraph GATE2["2단계: Lifecycle (사건별 후처리 게이트)"]
        m_LC_DATES["on_dates_changed\n날짜 변경 시\nreservation_lifecycle.py"]:::gate
        m_LC_CONST["on_constraints_changed\n인원/성별 변경 시\nreservation_lifecycle.py"]:::gate
        m_LC_CANCEL["on_status_cancelled\nstatus=CANCELLED 시\nreservation_lifecycle.py"]:::gate
        m_LC_ROOM["on_room_assigned\n방 배정 직후\nreservation_lifecycle.py"]:::gate
        m_LC_DEL["on_reservation_deleted\n예약 삭제 시\nreservation_lifecycle.py"]:::gate
    end

    %% ── 후처리 함수 (lifecycle 이 내부 호출, private 화됨) ──
    subgraph PROC["후처리 함수 (lifecycle 내부에서만 호출)"]
        m_SHIFT["_shift_daily_records\n파티·메모 평행이동\nroom_assignment.py:809 (private)"]:::ok
        m_RDATES["_reconcile_dates\n범위 밖 RA 삭제 + 누락 INSERT\nroom_assignment.py:894 (private)"]:::ok
        m_INVCHK["check_assignment_validity\ninvariant 검사 + unassign_room\nroom_assignment_invariants.py"]:::ok
        m_UNASSIGN_DATES["unassign_dates\n특정 날짜 RA 삭제 + bed_order + chip cleanup\nroom_assignment.py:668 (단계 #1 신규)"]:::shield
        m_CLEAR_ALL["clear_all_for_reservation\n전체 RA 삭제 + denormalized 필드\nroom_assignment.py"]:::ok
        m_CORE["assign_room\n비밀번호·침대 순서 계산 + push-out\nroom_assignment.py:213"]:::ok
    end

    m_RALL["reconcile_all_chips\n✅ 항상 5종 전부\nreconcile.py:23"]:::ok
    m_chip1["① sync_sms_tags\n기본 칩  reconcile.py:62"]:::ok
    m_chip2["② reconcile_surcharge_batch\n추가요금 칩  reconcile.py:70"]:::ok
    m_chip3["③ reconcile_party3_mms\n파티MMS 칩  reconcile.py:76"]:::ok
    m_chip4["④ reconcile_room_upgrade_promise\n업그레이드 약속  reconcile.py:85"]:::ok
    m_chip5["⑤ reconcile_room_upgrade_review\n업그레이드 후기  reconcile.py:91"]:::ok
    m_GUARD["🛡 삭제 보호 검사\nchip_reconciler.py:335\nsent_at · manual · excluded · failed"]:::shield
    m_DB_ROOM[("RoomAssignment\n날짜별 방 배정")]:::db
    m_DB_CHIP[("ReservationSmsAssignment\nSMS 칩 목록")]:::db

    m_LINT["🔒 CI Lint (단계 #22)\nRA 직접 조작 차단 +\nnon-_ private 함수 차단\nscripts/check_lifecycle_lint.sh"]:::shield

    m_SCHED(["APScheduler\n설정 시간 도달"]):::entry
    m_f1["① 테넌트 필터\n:451"]:::ok
    m_f2["② 칩 사전 필터\n:460"]:::ok
    m_f3["🛡 ③ 안전 가드 ±7일\n:483"]:::shield
    m_f4["④ 날짜 타겟\n:492"]:::ok
    m_f5["⑤ 타겟 모드\n:499"]:::ok
    m_f6["⑥ 구조 필터\n:506"]:::ok
    m_f7["🛡 ⑦ 발송 이력 제외\n:509"]:::shield
    m_f8["⑧ 숙박 필터\n:539"]:::ok
    m_RENDER["템플릿 렌더링\nvariables.py / renderer.py"]:::ok
    m_SEND["sms_provider.send_sms\nAligo API\nreal/sms.py"]:::sms
    m_TRACK["record_sms_sent\nsms_tracking.py"]:::ok

    %% 진입점 → Mutator (필드 변경)
    m_N & m_U & m_E & m_R & m_D --> m_MUTATOR
    m_C -.->|"신규 INSERT (Mutator 미경유)"| m_DB_ROOM

    %% Mutator 통과 후 → Lifecycle 분기
    m_PERM -->|"날짜 변경"| m_LC_DATES
    m_PERM -->|"인원/성별 변경"| m_LC_CONST
    m_CC_IN -->|"status=CANCELLED"| m_LC_CANCEL
    m_A_AUTO --> m_CORE
    m_CORE -.->|"assign 직후"| m_LC_ROOM
    m_DEL --> m_LC_DEL

    %% Lifecycle → 내부 후처리 호출
    m_LC_DATES --> m_SHIFT
    m_SHIFT --> m_RDATES
    m_RDATES --> m_RALL
    m_LC_CONST --> m_INVCHK
    m_INVCHK --> m_RALL
    m_LC_CANCEL -->|"same_day=True"| m_UNASSIGN_DATES
    m_LC_CANCEL -->|"same_day=False"| m_CLEAR_ALL
    m_LC_CANCEL --> m_RALL
    m_LC_ROOM --> m_RALL
    m_LC_DEL --> m_CLEAR_ALL

    %% 후처리 함수 → DB
    m_UNASSIGN_DATES --> m_DB_ROOM
    m_CLEAR_ALL --> m_DB_ROOM
    m_CORE --> m_DB_ROOM

    %% 칩 재계산 → SmsAssignment DB
    m_RALL --> m_chip1 --> m_chip2 --> m_chip3 --> m_chip4 --> m_chip5 --> m_GUARD --> m_DB_CHIP

    %% Lint 차단 (정적)
    m_LINT -.->|"PR 자동검사"| m_DB_ROOM

    %% SMS 발송 파이프라인
    m_DB_CHIP -->|"sent_at IS NULL"| m_SCHED
    m_SCHED --> m_f1 --> m_f2 --> m_f3 --> m_f4 --> m_f5 --> m_f6 --> m_f7 --> m_f8 --> m_RENDER --> m_SEND --> m_TRACK
    m_TRACK -->|"sent_at 기록"| m_DB_CHIP
```

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
