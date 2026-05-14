# 5. 예약 변경 전체 경로 — 6개 입력 → Reconcile → SMS 발송

예약 데이터가 바뀌는 모든 경로와, 그 후에 Reconcile·SMS 발송까지 이어지는 전체 흐름입니다.

> 🔴 버그 / 보호 없음 &nbsp;|&nbsp; ⚠️ 일부만 처리 &nbsp;|&nbsp; 🛡 보호 로직 있음 &nbsp;|&nbsp; ✅ 정상

---

## 6개 입력 경로

```mermaid
flowchart TB
    classDef entry  fill:#FFE8CC,stroke:#FF9F00,color:#191F28,font-weight:bold
    classDef ok     fill:#E8F3FF,stroke:#3182F6,color:#191F28
    classDef warn   fill:#FFFBE6,stroke:#FF9F00,color:#191F28
    classDef bug    fill:#FFE4E1,stroke:#F04452,color:#191F28
    classDef shield fill:#E8FAF5,stroke:#00C9A7,color:#191F28
    classDef db     fill:#F0E8FF,stroke:#8B5CF6,color:#191F28

    %% ── ① 네이버 싱크 ──────────────────────────────────────────
    subgraph N["① 네이버 싱크 — 5분마다 자동"]
        direction TB
        n1["_update_reservation\n네이버에서 받은 예약 정보로 DB 갱신"]:::ok
        n2["check_in_date 덮어쓰기\n🔴 아무 조건 없이 네이버 값으로 덮어씀\nnaver_sync.py:672"]:::bug
        n3["check_out_date 덮어쓰기\n🛡 manually_extended_until 설정 시 무시\nnaver_sync.py:676"]:::shield
        n4["shift_daily_records\n날짜 바뀌면 파티체크인·일별메모를 새 날짜로 이동\nnaver_sync.py:852"]:::ok
        n5["reconcile_dates\n날짜 바뀌면 배정표 범위 다시 맞추기\nnaver_sync.py:853"]:::ok
        n6["reconcile_chips_for_reservation\n⚠️ 기본 칩만 재계산 (구버전)\nnaver_sync.py:340"]:::warn
        n7["reconcile_surcharge_batch\n추가요금 칩 별도로 재계산\nnaver_sync.py:348"]:::warn
        n1-->n2-->n3-->n4-->n5-->n6-->n7
    end

    %% ── ② 수동 생성 ──────────────────────────────────────────
    subgraph C["② 수동 예약 생성 — 직원이 직접 입력"]
        direction TB
        c1["create_reservation\n예약 레코드 새로 만들기\nreservations.py:199"]:::ok
        c2["reconcile_all_chips\n✅ 5종 칩 전부 재계산\nreservations.py:242"]:::ok
        c1-->c2
    end

    %% ── ③ 수동 수정 ──────────────────────────────────────────
    subgraph U["③ 예약 수정 PUT — 날짜·인원·구역 변경"]
        direction TB
        u1["update_reservation\n요청받은 필드 업데이트\nreservations.py:261"]:::ok
        u2["shift_daily_records\n날짜 바뀌면 일별 기록 이동\nreservations.py:393"]:::ok
        u3["reconcile_dates\n날짜 바뀌면 배정 범위 다시 맞추기\nreservations.py:396"]:::ok
        u4["reconcile_all_chips\n✅ 5종 칩 전부 재계산\nreservations.py:447"]:::ok
        u5["🔴 보호 플래그 미설정\n5분 후 네이버 싱크가 다시 덮어씌움"]:::bug
        u1-->u2-->u3-->u4
        u1-. "check_in_date 바꿔도" .->u5
    end

    %% ── ④ 연박 연장 ──────────────────────────────────────────
    subgraph E["④ 연박 연장 — 체크아웃 하루 늘리기"]
        direction TB
        e1["extend_stay\ncheck_out_date +1일\nreservations_stay.py:156"]:::ok
        e2["manually_extended_until 설정\n🛡 체크아웃만 보호 · 체크인은 무방비\nreservations_stay.py:223"]:::shield
        e3["reconcile_chips_for_reservation\n⚠️ 기본 칩만 · 추가요금·파티MMS·업그레이드 누락\nreservations_stay.py:246"]:::warn
        e1-->e2-->e3
    end

    %% ── ⑤ 연박 축소 ──────────────────────────────────────────
    subgraph R["⑤ 연박 축소 — 체크아웃 하루 줄이기"]
        direction TB
        r1["reduce_extension\ncheck_out_date -1일\nreservations_stay.py:316"]:::ok
        r2["RoomAssignment 삭제\n줄어든 날짜의 방 배정 제거\nreservations_stay.py:365"]:::ok
        r3["reconcile_chips_for_reservation\n⚠️ 기본 칩만 · 추가요금·파티MMS·업그레이드 누락\nreservations_stay.py:456"]:::warn
        r1-->r2-->r3
    end

    %% ── ⑥ 드래그 이동 ──────────────────────────────────────────
    subgraph D["⑥ 드래그 이동 — 다른 날짜 열로 끌어다 놓기"]
        direction TB
        d1["update check_in/out_date\n예약 날짜 자체를 변경 (③ PUT 경로 진입)\nuseGuestMove.ts → reservations.py"]:::ok
        d2["assign_room\n새 날짜에 방 배정\nreservations_room.py:44"]:::ok
        d3["🔴 보호 플래그 없음\n5분 후 check_in_date 네이버 값으로 원복"]:::bug
        d1-->d2
        d1-. "날짜 변경 후" .->d3
    end
```

---

## Reconcile 레이어 — 예약 변경 후 데이터 정합성 맞추기

```mermaid
flowchart TB
    classDef ok     fill:#E8F3FF,stroke:#3182F6,color:#191F28
    classDef warn   fill:#FFFBE6,stroke:#FF9F00,color:#191F28
    classDef db     fill:#F0E8FF,stroke:#8B5CF6,color:#191F28

    subgraph REC["Reconcile 함수들"]
        direction TB
        rec1["shift_daily_records\n파티체크인·일별메모를 새 날짜로 평행이동\nroom_assignment.py:741"]:::ok
        rec2["reconcile_dates\n배정표에서 범위 밖 삭제 + 누락 날짜 자동 생성\nroom_assignment.py:826"]:::ok
        rec3["reconcile_all_chips  ✅\n5종 칩 전부 재계산\n기본·추가요금·파티MMS·객실업그레이드\nreconcile.py:23"]:::ok
        rec4["reconcile_chips_for_reservation  ⚠️\n기본 칩만 재계산 (구버전)\nchip_reconciler.py:41"]:::warn
        rec1-->rec2-->rec3
    end

    subgraph DB["DB 최종 상태"]
        direction LR
        db1["RoomAssignment\n날짜별 방 배정 기록"]:::db
        db2["ReservationSmsAssignment\nSMS 칩 — 발송 예정 목록"]:::db
    end

    네이버싱크["① 네이버 싱크"]-- "날짜 변경 시" -->rec1
    네이버싱크-- "배치" -->rec4
    수동생성["② 수동 생성"]-->rec3
    수동수정["③ 수동 수정"]-- "날짜 변경 시" -->rec1
    수동수정-->rec3
    연박연장["④ 연박 연장"]-->rec4
    연박축소["⑤ 연박 축소"]-->rec4
    드래그["⑥ 드래그"]-- "③ PUT 경유" -->rec1

    rec2-->db1
    rec3-->db2
    rec4-->db2
```

---

## SMS 발송 레이어 — APScheduler 시간 도달 시 자동 실행

```mermaid
flowchart TB
    classDef trigger fill:#FFE8CC,stroke:#FF9F00,color:#191F28,font-weight:bold
    classDef ok      fill:#E8F3FF,stroke:#3182F6,color:#191F28
    classDef db      fill:#F0E8FF,stroke:#8B5CF6,color:#191F28
    classDef sms     fill:#E8FAF5,stroke:#00C9A7,color:#191F28

    DB["ReservationSmsAssignment\n발송 예정 칩 (sent_at IS NULL)"]:::db

    DB-->|"미발송 칩 조회"| exec

    subgraph SEND["SMS 발송 파이프라인"]
        direction TB
        exec["execute_schedule\nDB의 TemplateSchedule 기준 트리거\ntemplate_scheduler.py:33"]:::trigger
        filter["_get_targets_standard\n발송 대상 예약 필터링\n날짜·배정 여부·구역·성별 등 조건 체크\ntemplate_scheduler.py:419"]:::ok
        render1["calculate_template_variables\n{{변수}} 값 계산\n방번호·비밀번호·인원 등\nvariables.py:312"]:::ok
        render2["TemplateRenderer.render\n템플릿 문자열에 변수 삽입\nrenderer.py:26"]:::ok
        send["sms_provider.send_sms\nAligo API로 실제 전송\nreal/sms.py"]:::sms
        track["record_sms_sent\nsent_at = 지금시간 기록\n→ 같은 칩 중복 발송 차단\nsms_tracking.py"]:::ok
        log["log_activity\n발송 결과 감사 로그 기록\nactivity_logger.py"]:::ok
        exec-->filter-->render1-->render2-->send-->track-->log
    end

    track-->|"sent_at 업데이트"| DB
```

---

## 전체 흐름 요약

```mermaid
flowchart LR
    classDef entry  fill:#FFE8CC,stroke:#FF9F00,color:#191F28
    classDef proc   fill:#E8F3FF,stroke:#3182F6,color:#191F28
    classDef db     fill:#F0E8FF,stroke:#8B5CF6,color:#191F28
    classDef out    fill:#E8FAF5,stroke:#00C9A7,color:#191F28

    subgraph IN["입력"]
        i1["① 네이버 싱크"]:::entry
        i2["② 수동 생성"]:::entry
        i3["③ 수동 수정"]:::entry
        i4["④ 연박 연장"]:::entry
        i5["⑤ 연박 축소"]:::entry
        i6["⑥ 드래그"]:::entry
    end

    subgraph REC["Reconcile"]
        r1["배정 범위\n맞추기"]:::proc
        r2["칩 재계산"]:::proc
    end

    subgraph DB["DB"]
        d1["Reservation"]:::db
        d2["RoomAssignment"]:::db
        d3["SmsAssignment"]:::db
    end

    subgraph OUT["출력"]
        o1["객실 배정 페이지\n표시"]:::out
        o2["SMS 자동 발송"]:::out
    end

    IN-->REC-->DB
    d2-->o1
    d3-->|"APScheduler\n시간 도달"| o2
```
