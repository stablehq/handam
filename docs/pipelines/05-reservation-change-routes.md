# 5. 예약 변경 전체 경로 — 입력 6개 → Reconcile → SMS 발송

> 🔴 버그·보호 없음 &nbsp;|&nbsp; ⚠️ 일부만 처리 &nbsp;|&nbsp; 🛡 보호 로직 있음 &nbsp;|&nbsp; ✅ 정상

---

## 전체 개요 다이어그램

```mermaid
flowchart TB
    classDef entry  fill:#FFE8CC,stroke:#FF9F00,color:#191F28,font-weight:bold
    classDef ok     fill:#E8F3FF,stroke:#3182F6,color:#191F28
    classDef warn   fill:#FFFBE6,stroke:#FF9F00,color:#191F28
    classDef bug    fill:#FFE4E1,stroke:#F04452,color:#191F28
    classDef shield fill:#E8FAF5,stroke:#00C9A7,color:#191F28
    classDef db     fill:#F0E8FF,stroke:#8B5CF6,color:#191F28
    classDef sms    fill:#dcfce7,stroke:#16a34a,color:#191F28

    %% ════════════════════════════════════════
    %% 입력 6개 경로
    %% ════════════════════════════════════════

    N(["① 네이버 싱크\n5분마다 자동 실행"]):::entry
    C(["② 수동 생성\n직원이 직접 입력"]):::entry
    U(["③ 수동 수정 PUT\n날짜·인원·구역 변경"]):::entry
    E(["④ 연박 연장\n체크아웃 +1일"]):::entry
    R(["⑤ 연박 축소\n체크아웃 -1일"]):::entry
    D(["⑥ 드래그 이동\n다른 날짜 열로 끌기"]):::entry

    %% ── ① 네이버 싱크 경로 ──────────────────
    n1["_update_reservation\n네이버 값으로 예약 정보 덮어쓰기\nnaver_sync.py:646"]:::ok
    n2["🔴 check_in_date 무조건 덮어씌움\n보호 로직 없음\nnaver_sync.py:672"]:::bug
    n3["check_out_date 덮어쓰기\n🛡 수동 연장됐으면 무시\nnaver_sync.py:676"]:::shield

    %% ── ② 수동 생성 경로 ───────────────────
    c1["create_reservation\n예약 레코드 신규 생성\nreservations.py:199"]:::ok

    %% ── ③ 수동 수정 경로 ───────────────────
    u1["update_reservation\n요청받은 필드 업데이트\nreservations.py:261"]:::ok
    u2["🔴 보호 플래그 미설정\ncheck_in_date 바꿔도\n5분 후 네이버가 다시 덮어씌움"]:::bug

    %% ── ④ 연박 연장 경로 ───────────────────
    e1["extend_stay\ncheck_out_date +1일\nreservations_stay.py:156"]:::ok
    e2["manually_extended_until 설정\n🛡 체크아웃만 보호\n체크인은 여전히 무방비\nreservations_stay.py:223"]:::shield

    %% ── ⑤ 연박 축소 경로 ───────────────────
    r1["reduce_extension\ncheck_out_date -1일\nreservations_stay.py:316"]:::ok
    r2["RoomAssignment 삭제\n줄어든 날짜의 방 배정 제거\nreservations_stay.py:365"]:::ok

    %% ── ⑥ 드래그 이동 경로 ─────────────────
    d1["update check_in/out_date\n예약 날짜 자체를 변경\n③ PUT 경로로 진입\nuseGuestMove.ts"]:::ok
    d2["assign_room\n새 날짜에 방 배정\nreservations_room.py:44"]:::ok
    d3["🔴 보호 플래그 없음\n날짜 변경 후 5분 뒤\ncheck_in_date 원복"]:::bug

    %% ════════════════════════════════════════
    %% 공유 Reconcile 함수들
    %% ════════════════════════════════════════

    SHIFT["shift_daily_records\n날짜 바뀌면 파티체크인·일별메모를\n새 날짜로 평행이동\nroom_assignment.py:741"]:::ok

    RDATES["reconcile_dates\n배정표에서 범위 밖 삭제\n누락 날짜 자동 생성\nroom_assignment.py:826"]:::ok

    RALL["reconcile_all_chips  ✅\n5종 칩 전부 재계산\n기본 · 추가요금 · 파티MMS · 객실업그레이드\nreconcile.py:23"]:::ok

    RBASIC["reconcile_chips_for_reservation  ⚠️\n기본 칩만 재계산 구버전\n추가요금·파티MMS·업그레이드 누락\nchip_reconciler.py:41"]:::warn

    %% ════════════════════════════════════════
    %% DB
    %% ════════════════════════════════════════

    DB_ROOM[("RoomAssignment\n날짜별 방 배정 기록")]:::db
    DB_CHIP[("ReservationSmsAssignment\nSMS 칩 · 발송 예정 목록")]:::db

    %% ════════════════════════════════════════
    %% SMS 발송 파이프라인
    %% ════════════════════════════════════════

    SCHED(["APScheduler\n설정 시간 도달 시 자동 실행"]):::entry

    FILTER["_get_targets_standard\n발송 대상 예약 필터링\n날짜·배정 여부·구역·성별 조건 체크\ntemplate_scheduler.py:419"]:::ok

    RENDER["calculate_template_variables\n+ TemplateRenderer.render\n{{방번호·비밀번호·인원}} 치환\nvariables.py / renderer.py"]:::ok

    SEND["sms_provider.send_sms\nAligo API 실제 전송\nreal/sms.py"]:::sms

    TRACK["record_sms_sent\nsent_at 기록 → 중복 발송 차단\nsms_tracking.py"]:::ok

    %% ════════════════════════════════════════
    %% 연결
    %% ════════════════════════════════════════

    %% ① 네이버 싱크
    N --> n1 --> n2 --> n3

    %% ② 수동 생성
    C --> c1

    %% ③ 수동 수정
    U --> u1
    u1 -. "날짜 직접 수정 시" .-> u2

    %% ④ 연박 연장
    E --> e1 --> e2

    %% ⑤ 연박 축소
    R --> r1 --> r2

    %% ⑥ 드래그
    D --> d1 --> d2
    d1 -. "날짜 변경 후" .-> d3

    %% → shift_daily_records (날짜 변경 발생한 경로들)
    n3  --> SHIFT
    u1  --> SHIFT
    d1  --> SHIFT
    SHIFT --> RDATES

    %% → reconcile_all_chips (완전한 재계산 경로들)
    c1     --> RALL
    u1     --> RALL
    d2     --> RALL
    RDATES --> RALL

    %% → reconcile_chips_for_reservation (구버전, 일부 경로들)
    n2 --> RBASIC
    e2 --> RBASIC
    r2 --> RBASIC

    %% → DB
    RDATES --> DB_ROOM
    RALL   --> DB_CHIP
    RBASIC --> DB_CHIP

    %% SMS 파이프라인
    DB_CHIP -->|"미발송 칩 조회\nsent_at IS NULL"| SCHED
    SCHED   --> FILTER --> RENDER --> SEND --> TRACK
    TRACK   -->|"sent_at = 지금시간\n발송 완료 표시"| DB_CHIP
```

---

## A. `reconcile_all_chips` 내부 — 5종 칩 상세

`reconcile_all_chips`(`reconcile.py:23`)는 5개 함수를 순서대로 호출합니다.  
각 칩은 이미 발송됐거나 수동으로 지정된 경우 **삭제 보호**를 받습니다.

```mermaid
flowchart TB
    classDef entry  fill:#FFE8CC,stroke:#FF9F00,color:#191F28,font-weight:bold
    classDef ok     fill:#E8F3FF,stroke:#3182F6,color:#191F28
    classDef shield fill:#E8FAF5,stroke:#00C9A7,color:#191F28
    classDef db     fill:#F0E8FF,stroke:#8B5CF6,color:#191F28
    classDef guard  fill:#FFF3CD,stroke:#FF9F00,color:#191F28

    RALL(["reconcile_all_chips\nreconcile.py:23"]):::entry

    %% 5종 칩 함수
    C1["① sync_sms_tags\n기본 칩 생성·삭제\ncolumn_match 조건 평가\nroom_assignment.py:198\nreconcile.py:62"]:::ok
    C2["② reconcile_surcharge_batch\n초과 인원 추가요금 칩\n(정원 초과 시 생성)\nsurcharge.py\nreconcile.py:70"]:::ok
    C3["③ reconcile_party3_mms_for_reservation\n파티 당일 2차 참여자 MMS 칩\n(파티 구역 예약 한정)\nparty3_mms.py\nreconcile.py:76"]:::ok
    C4["④ reconcile_room_upgrade_promise\n첫날 밤 업그레이드 약속 칩\n(체크인 당일 발송)\nroom_upgrade.py\nreconcile.py:85"]:::ok
    C5["⑤ reconcile_room_upgrade_review\n마지막 날 밤 후기 요청 칩\n(체크아웃 전날 발송)\nroom_upgrade.py\nreconcile.py:91"]:::ok

    %% 삭제 보호 게이트
    GUARD["🛡 삭제 보호 검사\nchip_reconciler.py:335\n\n① sent_at IS NOT NULL  → 이미 발송됨\n② assigned_by = 'manual' → 수동 지정\n③ assigned_by = 'excluded' → 발송 제외\n④ send_status = 'failed' → 실패 재시도 대기"]:::guard

    DB[("ReservationSmsAssignment\n칩 목록 갱신")]:::db

    RALL --> C1 --> C2 --> C3 --> C4 --> C5
    C1 & C2 & C3 & C4 & C5 --> GUARD
    GUARD -->|"보호 조건 없음 → 삭제/교체"| DB
    GUARD -->|"보호 조건 해당 → 유지"| DB
```

### 칩 종류 요약

| # | 칩 키 예시 | 생성 조건 | 보호 조건 |
|---|-----------|----------|----------|
| ① | `column_match` 기반 | 예약이 템플릿 스케줄 조건 충족 | sent_at, manual, excluded, failed |
| ② | 추가요금 | 배정 인원 > 객실 정원 | 동일 |
| ③ | 파티3차MMS | 파티 구역 예약 + 당일 | 동일 |
| ④ | 업그레이드약속 | 첫날 밤 배정 완료 | 동일 |
| ⑤ | 업그레이드후기 | 마지막 밤 배정 완료 | 동일 |

---

## B. RoomAssignment 변경 경로 — 5가지 진입점

`RoomAssignment` 테이블(날짜별 방 배정 기록)은 다음 5가지 경로에서 생성·수정·삭제됩니다.

```mermaid
flowchart TB
    classDef entry  fill:#FFE8CC,stroke:#FF9F00,color:#191F28,font-weight:bold
    classDef ok     fill:#E8F3FF,stroke:#3182F6,color:#191F28
    classDef warn   fill:#FFFBE6,stroke:#FF9F00,color:#191F28
    classDef shield fill:#E8FAF5,stroke:#00C9A7,color:#191F28
    classDef db     fill:#F0E8FF,stroke:#8B5CF6,color:#191F28
    classDef bug    fill:#FFE4E1,stroke:#F04452,color:#191F28

    %% ── 5가지 진입점 ──────────────────────
    M(["① 수동 배정\n드래그앤드롭 → API 호출"]):::entry
    A(["② 자동 배정\nAPScheduler 매일 실행"]):::entry
    RD(["③ reconcile_dates 자동 생성\n날짜 범위 바뀔 때 누락 채움"]):::entry
    PO(["④ 밀어내기(Push-out)\n도미토리 성별 충돌 시"]):::entry
    CC(["⑤ 취소 연쇄 삭제\n예약 취소 시"]):::entry

    %% ── ① 수동 배정 ────────────────────────
    m1["PUT /reservations/{id}/room\nreservations_room.py:44"]:::ok
    m2["assign_room\nSELECT FOR UPDATE → 중복 방지\nroom_assignment.py:213"]:::ok

    %% ── ② 자동 배정 ────────────────────────
    a1["daily_room_assign_job\n미래 날짜 미배정 예약 일괄 처리\njobs.py:350"]:::ok
    a2["auto_assign_rooms\n도미토리 성별 잠금 체크\nroom_auto_assign.py:32"]:::ok
    a3["_assign_all_rooms\n용량·성별 조건 확인 후 배정\nroom_auto_assign.py:272"]:::ok

    %% ── ③ reconcile_dates 자동 생성 ─────────
    rd1["reconcile_dates\n예약 날짜 범위 vs 실제 배정 비교\nroom_assignment.py:826"]:::ok
    rd2["🛡 안전장치: 기존 배정 없으면 생성 안 함\nmissing AND existing 조건\nroom_assignment.py:895"]:::shield

    %% ── ④ 밀어내기 ──────────────────────────
    po1["_push_out_reservation\n도미토리 성별 충돌 예약 강제 이동\nroom_auto_assign.py:305"]:::ok
    po2["기존 RoomAssignment 삭제\n→ assign_room으로 재배정 시도\nroom_auto_assign.py:458"]:::ok

    %% ── ⑤ 취소 연쇄 삭제 ────────────────────
    cc1{"당일 취소?\nis_same_day_cancel\nnaver_sync.py:761"}
    cc2["오늘 이후 배정만 삭제\n지난 날짜 기록 보존\nnaver_sync.py:768"]:::ok
    cc3["전체 배정 삭제\nclear_all_for_reservation\nnaver_sync.py:813"]:::ok

    %% ── 공통 후처리 ─────────────────────────
    CORE["assign_room 공통 처리\n비밀번호 생성 · 침대 순서 계산\nroom_assignment.py:213"]:::ok
    RALL["reconcile_all_chips\n5종 칩 재계산\nreconcile.py:23"]:::ok
    DB_ROOM[("RoomAssignment\n날짜별 방 배정 기록")]:::db
    DB_CHIP[("ReservationSmsAssignment\nSMS 칩 갱신")]:::db

    %% ── 연결 ────────────────────────────────
    M  --> m1 --> m2
    A  --> a1 --> a2 --> a3
    RD --> rd1 --> rd2
    PO --> po1 --> po2
    CC --> cc1
    cc1 -->|"당일"| cc2
    cc1 -->|"사전"| cc3

    m2  --> CORE
    a3  --> CORE
    rd2 -->|"누락 날짜 자동 생성"| CORE
    po2 --> CORE

    CORE --> DB_ROOM
    CORE --> RALL
    cc2 & cc3 --> DB_ROOM

    RALL --> DB_CHIP
```

### RoomAssignment 변경 요약

| # | 경로 | 트리거 | 삭제 | 생성 |
|---|------|--------|------|------|
| ① | 수동 배정 | 직원 드래그앤드롭 | 이전 배정 교체 | ✅ |
| ② | 자동 배정 | APScheduler 매일 | — | ✅ (미배정만) |
| ③ | reconcile_dates | 날짜 범위 변경 후 | 범위 밖 삭제 | ✅ (기존 있을 때만) |
| ④ | 밀어내기 | 도미토리 성별 충돌 | 기존 배정 강제 삭제 | ✅ (재배정 시도) |
| ⑤ | 취소 연쇄 | 예약 취소 | 당일: 오늘 이후만 / 사전: 전체 | — |

---

## C. SMS 발송 필터 체인 — 8단계 상세

`_get_targets_standard`(`template_scheduler.py:419`)는 8개 필터를 순서대로 통과해야 SMS가 발송됩니다.  
하나라도 걸리면 그 예약은 해당 스케줄에서 제외됩니다.

```mermaid
flowchart TB
    classDef entry  fill:#FFE8CC,stroke:#FF9F00,color:#191F28,font-weight:bold
    classDef ok     fill:#E8F3FF,stroke:#3182F6,color:#191F28
    classDef shield fill:#E8FAF5,stroke:#00C9A7,color:#191F28
    classDef skip   fill:#F5F5F5,stroke:#B0B8C1,color:#191F28
    classDef sms    fill:#dcfce7,stroke:#16a34a,color:#191F28

    START(["APScheduler 트리거\n설정된 스케줄 시간 도달"]):::entry

    %% 8단계 필터
    F1["① 테넌트 필터\n현재 테넌트 예약만 조회\ntemplate_scheduler.py:450"]:::ok
    F2["② 칩 사전 필터\n해당 template_key 칩이 있는 예약만\nassigned_by NOT IN excluded\ntemplate_scheduler.py:460"]:::ok
    F3["③ 안전 가드\n발송 기준일 ±7일 범위만 허용\n(오래된 예약 / 너무 미래 예약 제외)\ntemplate_scheduler.py:483"]:::shield
    F4["④ 날짜 타겟\n체크인일 또는 체크아웃일 기준\n오늘 날짜와 대조\ntemplate_scheduler.py:491"]:::ok
    F5["⑤ 타겟 모드 분기\nfirst_night → 체크인 당일만\nlast_night → 체크아웃 전날만\ndefault → 전체 날짜\ntemplate_scheduler.py:499"]:::ok
    F6["⑥ 구조 필터\n건물·객실·구역·성별 조건 평가\napply_structural_filters\nfilters.py\ntemplate_scheduler.py:505"]:::ok
    F7["⑦ 발송 이력 제외\nsent_at IS NOT NULL → 이미 발송됨\n중복 발송 방지\ntemplate_scheduler.py:508"]:::shield
    F8["⑧ 숙박 필터\n체크인~체크아웃 사이 날짜만\n(당일치기 vs 연박 구분)\ntemplate_scheduler.py:539"]:::ok

    PASS["✅ 필터 통과\n발송 대상 확정"]:::sms
    SKIP["발송 제외\n(해당 스케줄에서)"]:::skip

    SEND["send_single_sms\n템플릿 렌더링 → Aligo 전송\nsms_sender.py:31"]:::sms
    TRACK["record_sms_sent\nsent_at = 현재시각\nsms_tracking.py:202"]:::ok

    START --> F1 --> F2 --> F3 --> F4 --> F5 --> F6 --> F7 --> F8

    F1 & F2 & F3 & F4 & F5 & F6 & F7 & F8 -->|"조건 불충족"| SKIP
    F8 -->|"모두 통과"| PASS
    PASS --> SEND --> TRACK
```

### 8단계 필터 요약

| # | 필터 | 통과 조건 | 목적 |
|---|------|----------|------|
| ① | 테넌트 | 현재 테넌트 예약 | 멀티테넌트 격리 |
| ② | 칩 사전 | template_key 칩 보유 + 미제외 | 발송 대상 칩 존재 확인 |
| ③ | 안전 가드 | 기준일 ±7일 이내 | 과거/미래 오발송 방지 |
| ④ | 날짜 타겟 | 체크인 또는 체크아웃 = 오늘 | 발송 시점 맞추기 |
| ⑤ | 타겟 모드 | first/last_night 조건 일치 | 첫날·마지막날 분기 |
| ⑥ | 구조 필터 | 건물·구역·성별 설정 일치 | 템플릿 타겟 세분화 |
| ⑦ | 발송 이력 | sent_at IS NULL | 중복 발송 차단 |
| ⑧ | 숙박 필터 | 체크인 ≤ 기준일 < 체크아웃 | 재실 기간만 발송 |
