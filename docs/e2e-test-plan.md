# E2E 테스트 계획서

SMS 예약 시스템 핵심 기능 E2E 테스트 항목.
Playwright MCP를 사용하여 로컬 서버에서 실행하며, 테스트 후 DB를 원복한다.

## 핵심 검증 목표

1. 네이버 예약을 통해 들어오는 예약자들이 잘 분리되고 저장되는지
2. 각 예약자에 알맞은 문자 발송 로직이 이행되는지

---

## A. 네이버 예약 동기화

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| A-1 | 신규 예약 동기화 | DB에 예약 생성, 필드 정확성 (이름, 전화, 체크인/아웃, 인원수) |
| A-2 | 기존 예약 업데이트 | 상태/날짜/인원 변경 시 DB 반영 |
| A-3 | 취소된 예약 동기화 | status=CANCELLED 반영 |
| A-4 | 중복 동기화 방지 | 같은 external_id 두 번 동기화 → 1건만 존재 |
| A-5 | reconcile 모드 (당일 포함) | 당일 예약도 재동기화, reconcile_date 파라미터 지정 시 해당 날짜 기준, USEDATE 필터링으로 체류 중인 예약도 포함 |

## B. 예약자 분류 (1박/연박/연장)

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| B-1 | 1박자 판별 | check_out - check_in == 1일 → is_long_stay=false |
| B-2 | 연박자 판별 (2박+) | check_out - check_in > 1일 → is_long_stay=true |
| B-3 | 연장자 감지 (동명+동번호+연속날짜) | A.checkout == B.checkin → 같은 stay_group_id |
| B-4 | 연장자 감지 (visitor_name 매칭) | visitor_name + phone 조합으로도 연결 |
| B-5 | 연장자 감지 (visitor_phone 매칭) | customer_name + visitor_phone 조합으로도 연결 |
| B-6 | 연장자 3건 이상 체인 | A→B→C 연속 → 모두 같은 group_id, order=0,1,2 |
| B-7 | is_last_in_group 정확성 | 마지막 예약만 true |
| B-8 | 연장자 해제 (중간 예약 취소) | B 취소 → A,C 그룹 해제, is_long_stay 재계산 |
| B-9 | 연박자+연장자 통합 변수 | 둘 다 is_long_stay=true로 통합 |
| B-10 | 1박 연장자 (1박×3건 연속) | 개별은 1박이지만 연결 후 is_long_stay=true |

## C. 객실 자동 배정

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| C-1 | biz_item 매핑 기반 자동 배정 | naver_biz_item_id → 매핑된 Room에 배정 |
| C-2 | 일반실 중복 배정 방지 | 같은 날짜 같은 방에 2명 배정 불가 |
| C-3 | 도미토리 용량 체크 | bed_capacity 초과 시 배정 실패 |
| C-4 | 도미토리 성별 잠금 | 남자 있는 방에 여자 배정 차단 |
| C-5 | 연박자 전 날짜 배정 | 3박 → 3일 모두 같은 방 배정 |
| C-6 | 연장자 같은 방 유지 | stay_group 멤버 → 이전 멤버와 같은 방 |
| C-7 | 성별 우선순위 정렬 | male_priority/female_priority에 따른 방 순서 |
| C-8 | 수동 배정 보호 | assigned_by='manual' → 자동 배정이 덮어쓰지 않음 |
| C-9 | party 섹션 제외 | section='party' → 자동 배정 대상 아님 |
| C-10 | 배정 후 denormalized 필드 | reservation.room_number, room_password 정확성 |
| C-11 | 다중 날짜 배정 denormalization | 4박 배정 시 모든 reservation record에 room_number/room_password 정확 반영 |
| C-12 | 도미토리 bed_order 연박 일관성 | 3박 도미토리 배정 시 3일 모두 같은 bed_order 값 |
| C-13 | 도미토리 bed_order 연장자 유지 | stay_group 멤버가 이전 멤버와 같은 bed_order 유지 |
| C-14 | 도미토리 bed_order 충돌 처리 | bed_order 1,2,3 사용 중 → 새 배정은 4번 슬롯 |

## D. 수동 객실 배정

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| D-1 | 단일 날짜 배정 | 특정 날짜만 방 배정 |
| D-2 | apply_subsequent (이후 전체) | 체크아웃까지 모든 날짜에 배정 |
| D-3 | apply_group (그룹 전체) | stay_group 전체 멤버에게 같은 방 |
| D-4 | 비도미토리 **자동** 배정 중복 차단 | assigned_by='auto'이면 에러. 수동 배정은 중복 허용 (D-8 참조) |
| D-5 | 방 이동 로그 | 이전 방 → 새 방 ActivityLog 기록 |
| D-6 | 배정 해제 | room_id=null → RoomAssignment 삭제 |
| D-7 | 배정 후 SMS 칩 동기화 | sync_sms_tags 호출 → 칩 생성/삭제 |
| D-8 | 비도미토리 수동 중복 배정 허용 | assigned_by='manual'이면 이미 점유된 비도미토리 방에도 추가 배정 가능 | - |

## E. SMS 템플릿 스케줄 — schedule_type별

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| E-1 | daily 스케줄 | 매일 지정 시간에 트리거 |
| E-2 | weekly 스케줄 | 지정 요일에만 트리거 |
| E-3 | hourly 스케줄 | 매시 지정 분에 트리거 |
| E-4 | interval 스케줄 | N분 간격 트리거 |
| E-5 | interval + active_hours | 활성 시간대 내에서만 트리거 |
| E-6 | event 스케줄 (예약 시점) | hours_since_booking 내 예약에만 발송 |
| E-7 | event + expires_after_days | 만료일 이후 자동 비활성화 |

## F. SMS 스케줄 — target_mode별

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| F-1 | once + 1박자 | 체크인 당일 1회만 |
| F-2 | once + 연박자 (3박) | 체크인 당일 1회만 (중복 없음) |
| F-3 | once + 연장자 | 그룹 전체에서 1회만 (once_per_stay) |
| F-4 | daily + 1박자 | 체크인 당일 1회 (=once와 동일) |
| F-5 | daily + 연박자 (3박) | 3일 각각 칩 생성 + 발송 |
| F-6 | daily + 연장자 (1박×3) | 각 멤버의 체류일마다 칩 |
| F-7 | last_day + 1박자 | 체크아웃 전날 = 체크인일에 발송 |
| F-8 | last_day + 연박자 (3박) | 체크아웃 전날(3일차)에만 발송 |
| F-9 | last_day + 연장자 | is_last_in_group=true인 멤버만, 마지막 날에만 |

## G. SMS 스케줄 — date_target별

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| G-1 | today (오늘 체크인) | 오늘 체크인 예약만 대상 |
| G-2 | tomorrow (내일 체크인) | 내일 체크인 예약만 대상 |
| G-3 | today_checkout (오늘 체크아웃) | 오늘 체크아웃 예약만 대상 |
| G-4 | tomorrow_checkout (내일 체크아웃) | 내일 체크아웃 예약만 대상 |

## H. SMS 스케줄 — 구조적 필터별

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| H-1 | assignment=room | section='room'인 예약만 |
| H-2 | assignment=party | section='party'인 예약만 |
| H-3 | assignment=unassigned | section='unassigned'인 예약만 |
| H-4 | building 필터 | 해당 건물에 배정된 예약만 |
| H-5 | room 필터 | 해당 방에 배정된 예약만 |
| H-6 | building + unassigned 혼합 | 미배정자도 포함되는지 |
| H-7 | column_match: contains | party_type에 "1차" 포함 |
| H-8 | column_match: not_contains | party_type에 "1차" 미포함 |
| H-9 | column_match: is_empty | notes가 비어있는 예약 |
| H-10 | column_match: is_not_empty | notes가 있는 예약 |
| H-11 | 복합 필터 (AND) | building=1 AND assignment=room |
| H-12 | 동일 타입 복수 (OR) | building=1 OR building=2 |
| H-13 | column_match AND 로직 | party_type contains "1차" AND notes is_not_empty → 둘 다 충족하는 예약만 칩 생성 |
| H-14 | party_type 일별 오버라이드 | ReservationDailyInfo 우선 적용 |
| H-15 | assignment=unstable 필터 | section='unstable' OR 해당 날짜에 unstable_party=true인 예약만 대상 | - |

## I. SMS 스케줄 — stay_filter / once_per_stay

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| I-1 | stay_filter=null (전체) | 1박+연박+연장 모두 대상 |
| I-2 | stay_filter=exclude | 1박자만 대상, 연박/연장 제외 |
| I-3 | once_per_stay=false | 그룹 멤버 각각 발송 |
| I-4 | once_per_stay=true + 연장자 | 그룹 중 earliest만 발송 |
| I-5 | once_per_stay=true + 연박자 | 중복 발송 방지 |
| I-6 | stay_filter=exclude + once_per_stay | 1박자만 + 중복 방지 |

## J. SMS 스케줄 — send_condition (성비 조건)

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| J-1 | 조건 충족 (gte) | male/female >= threshold → 발송 |
| J-2 | 조건 미충족 (gte) | male/female < threshold → 미발송 |
| J-3 | 조건 충족 (lte) | male/female <= threshold → 발송 |
| J-4 | female=0 처리 | ratio=∞ → gte는 항상 true |
| J-5 | 양쪽 0명 | 발송 안 함 |
| J-6 | send_condition_date=today vs tomorrow | 각각 해당 날짜 기준 |

## K. SMS 스케줄 — event 카테고리 전용

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| K-1 | hours_since_booking 내 예약 | 시간 내 확정 예약 → 발송 |
| K-2 | hours_since_booking 초과 | 시간 초과 → 미발송 |
| K-3 | gender_filter=female | 여성 예약만 대상 |
| K-4 | gender_filter=male | 남성 예약만 대상 |
| K-5 | max_checkin_days | 체크인 N일 이내만 대상 |
| K-6 | event + stay_filter=exclude | 이벤트 + 1박자만 |

## L. 칩 (ReservationSmsAssignment) 생성/삭제

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| L-1 | 스케줄 생성 → 칩 자동 생성 | 대상자에게 칩 즉시 생성 |
| L-2 | 스케줄 수정 → 칩 재조정 | chip_reconciler가 미발송 칩 삭제 + 새 칩 생성, 발송 완료 칩은 보호 |
| L-3 | 스케줄 비활성화 → 칩 삭제 | 미발송 칩만 삭제 |
| L-4 | 발송 완료 칩 보호 | sent_at 있는 칩 절대 삭제 안 됨 |
| L-5 | 수동 배정 칩 보호 | assigned_by='manual' 칩 삭제 안 됨 |
| L-6 | 수동 제외 칩 보호 | assigned_by='excluded' 칩은 필터 재매칭/스케줄 수정/배정 변경 후에도 재생성 안 됨 |
| L-7 | 객실 배정 변경 → 칩 재동기화 | 방 변경 시 building/room 필터 반영 |
| L-8 | 예약 취소 → 칩 처리 | CANCELLED 예약의 칩 |
| L-9 | once 모드 칩 (체크인일만) | 1개 날짜에만 칩 |
| L-10 | daily 모드 칩 (전체 체류일) | 체류일 수만큼 칩 |
| L-11 | last_day 모드 칩 | 마지막 날에만 칩 |
| L-12 | exclude_sent (이중발송 방지) | 이미 sent된 템플릿+날짜 → 재대상 안 됨 |

## M. 칩 → UI 표시 (객실 배정 페이지)

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| M-1 | 대상자에게 칩 표시 | 칩 있는 예약자에게 해당 템플릿 칩 렌더링 |
| M-2 | 비대상자 칩 없음 | 필터에 안 맞는 예약자에게 칩 없음 |
| M-3 | 발송 완료 칩 상태 표시 | sent_at 있으면 발송완료 스타일 |
| M-4 | 미발송 칩 상태 표시 | sent_at 없으면 대기 스타일 |
| M-5 | 제외 칩 상태 표시 | excluded 상태 표시 |
| M-6 | 객실 배정 → 칩 추가 | room 필터 스케줄: 배정하면 칩 생김 |
| M-7 | 객실 해제 → 칩 제거 | room 필터 스케줄: 해제하면 칩 사라짐 |
| M-8 | building 변경 → 칩 변경 | 다른 건물로 이동 → 칩 재조정 |
| M-9 | section 변경 → 칩 변경 | party→room 변경 시 칩 재조정 |
| M-10 | 연박자 daily 칩 날짜별 표시 | 3박이면 각 날짜에 칩 1개씩 (총 3개 분산) |

## N. SMS 실제 발송

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| N-1 | 스케줄 트리거 → 발송 | 시간 도달 시 대상자에게 SMS 발송 |
| N-2 | 템플릿 변수 치환 | {{customer_name}}, {{room_num}} 등 정확 치환 |
| N-3 | 객실 비밀번호 생성 | room_password 자동 생성 또는 고정값 |
| N-4 | 인원수 버퍼 적용 | participant_buffer, gender_ratio_buffers 정확 계산 |
| N-5 | 반올림 (ceil/round/floor) | round_unit + round_mode 정확 적용 |
| N-6 | SMS/LMS 자동 감지 | 90바이트 이하→SMS, 초과→LMS |
| N-7 | 발송 후 칩 sent_at 업데이트 | 발송 성공 → timestamp 기록 |
| N-8 | 발송 실패 처리 | API 에러 시 칩 sent_at 그대로 null |
| N-9 | ActivityLog 기록 | 발송 결과 로그 (success/failed count) |
| N-10 | SSE 이벤트 발행 | 발송 후 실시간 이벤트 전파 |

## P. 인증/권한

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| P-1 | 로그인 성공 | JWT access + refresh 토큰 발급 |
| P-2 | 토큰 갱신 | refresh 토큰으로 access 재발급 |
| P-3 | SUPERADMIN 전체 접근 | 모든 API 접근 가능 |
| P-4 | STAFF 제한 접근 | 파티 체크인만 접근 |
| P-5 | 만료 토큰 거부 | 401 반환 |

## Q. 멀티테넌트 격리

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| Q-1 | 예약 데이터 격리 | 테넌트A 예약이 테넌트B에서 조회 안 됨 |
| Q-2 | 객실/건물 격리 | 테넌트A 방/건물이 테넌트B에 안 보임 |
| Q-3 | 템플릿 격리 | 테넌트A 템플릿이 테넌트B에 안 보임 |
| Q-4 | 스케줄 격리 | 테넌트A 스케줄이 테넌트B에 안 보임 |
| Q-5 | SMS 이력 격리 | 테넌트A 발송 이력이 테넌트B에 안 보임 |
| Q-6 | 칩(SmsAssignment) 격리 | 테넌트A 칩이 테넌트B에 안 보임 |
| Q-7 | ActivityLog 격리 | 테넌트A 로그가 테넌트B에 안 보임 |
| Q-8 | 파티 체크인 격리 | 테넌트A 체크인이 테넌트B에 안 보임 |
| Q-10 | INSERT 자동 tenant_id 주입 | 어떤 모델이든 생성 시 현재 테넌트 자동 부여 |
| Q-11 | 스케줄 실행 시 격리 | 테넌트A 스케줄이 테넌트B 예약에 발송 안 함 |
| Q-12 | 동기화 시 격리 | 테넌트A 네이버 동기화가 테넌트B에 영향 없음 |
| Q-13 | 자동 배정 시 격리 | 테넌트A 자동배정이 테넌트B 방 사용 안 함 |
| Q-14 | SSE 이벤트 격리 | 테넌트A 이벤트가 테넌트B 구독자에게 안 감 |

## R. 파티 체크인

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| R-1 | 체크인 토글 ON | PartyCheckin 레코드 생성 |
| R-2 | 체크인 토글 OFF | 레코드 삭제 |
| R-3 | 날짜별 체크인 현황 | 특정 날짜의 체크인 목록 |
| R-4 | 전화번호 컬럼 표시 | 예약자 phone 필드 그대로 표시 |
| R-5 | 메모 컬럼 표시 | 예약자 notes 필드 표시 |

## S. 대시보드

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| S-1 | 통계 카드 정확성 | 예약수, 발송수, 체크인수, 네이버 동기화 상태(정상/오류) |
| S-2 | 성별 통계 | male_count/female_count 정확 |
| S-3 | 날짜별 필터링 | 날짜 변경 시 통계 갱신 |
| S-4 | 동기화 실패 시 에러 표시 | 마지막 naver_sync 로그가 failed면 에러 메시지 표시 |
| S-5 | 쿠키 만료 에러 메시지 | 쿠키 관련 에러면 "쿠키 만료" 안내 표시 |

## T. 객실 그룹

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| T-1 | 객실 그룹 생성 | POST /api/rooms/groups → 그룹 생성, room.room_group_id 설정 |
| T-2 | 객실 그룹 수정 | PUT → 이전 방 해제 + 새 방 연결 |
| T-3 | 객실 그룹 삭제 | DELETE → room_group_id NULL 복원 |

---

## Frontend (UI) 테스트

### FA. 객실배정 테이블 인터랙션

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| FA-5 | 건물 접기/펼치기 북마크 | 좌측 탭 클릭 → 건물 방 목록 접기/펼치기 토글 |
| FA-6 | 접힌 건물 요약 표시 | "건물명 — X/Y" 형태로 배정/전체 현황 표시 |
| FA-7 | 그룹 구분선 추가 | 방 사이 클릭 → 파란 구분선 생성 (+ 아이콘) |
| FA-8 | 그룹 구분선 제거 | 구분선 클릭 → 점선으로 복원 (× 아이콘) |
| FA-9 | 그룹 저장 → API 반영 | 구분선 기반 그룹이 정확한 room_ids로 저장 |

### FB. 로그인 & 레이아웃

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| FB-1 | 로그인 기억하기 체크박스 | "아이디/비밀번호 저장" 체크 후 새로고침 → 입력값 유지 (localStorage) |
| FB-2 | 모바일 테이블 스크롤 | 핀치줌 코드 미존재, 브라우저 네이티브 스크롤 동작 |

### FC. 연박 연결 UI

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| FC-1 | 연박 연결 모달 | 컨텍스트 메뉴에서 기준 예약자 자동 선택되어 열림 (1단계 스킵) |
| FC-2 | 연박 연결 모달 양방향 체인 | 좌(이전)/우(이후) 방향 선택 + 예약자 추가, 체인 미리보기에 체크인~체크아웃 날짜 표시 |

### FD. 게스트 컨텍스트 메뉴

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| FD-1 | 우클릭 메뉴 표시 | 게스트 행 우클릭 → 커스텀 메뉴 표시, 브라우저 기본 메뉴 안 뜸 |
| FD-2 | 메뉴 항목 조건부 비활성 | 미배정 풀 게스트 → "미배정으로 이동" 비활성(회색), 파티 게스트 → "파티만으로 이동" 비활성 |
| FD-3 | 미배정으로 이동 액션 | 방 배정된 게스트 → 메뉴에서 "미배정으로 이동" → 미배정 풀로 이동, 토스트 표시 |
| FD-4 | 파티만으로 이동 액션 | 미배정/방 게스트 → 메뉴에서 "파티만으로 이동" → 파티 섹션으로 이동, 토스트 표시 |
| FD-5 | 게스트 삭제 액션 | 메뉴에서 "게스트 삭제" → 확인 모달 → 확인 → 삭제 완료 |
| FD-6 | 연박 묶기 액션 | 메뉴에서 "연박 묶기" → 연박 연결 모달 열림 |
| FD-7 | 복수 선택 + 우클릭 | 선택 모드에서 3명 선택 → 우클릭 → 메뉴에 "(3명)" 표시, 액션 시 3명 모두 적용 |
| FD-8 | 메뉴 닫기 동작 | 메뉴 열린 상태 → 외부 클릭/Escape/스크롤 → 메뉴 닫힘 |
| FD-10 | 하이라이트 색상 지정 액션 | 메뉴에서 색상 선택 → 게스트 행 배경색 변경, DB에 highlight_color 저장 | - |
| FD-11 | 하이라이트 색상 해제 | 색상 해제 → highlight_color=null, 배경색 초기화 | - |
| FD-12 | 예약 날짜 변경 액션 | 메뉴에서 "예약 날짜 변경" → 모달에서 check_in/check_out 수정 | - |
| FD-13 | 내일 연박추가 액션 | "내일 연박추가" → 다음날 예약 생성 + stay_group 연결 + 방 배정 | - |
| FD-14 | 수동연박 취소 액션 | "수동연박 취소" → booking_source='extend' 예약 삭제 + 그룹 해제 + 원본 복원 | - |

### FE. 활동 로그

| # | 테스트 항목 | 검증 포인트 |
|---|-----------|-----------|
| FE-1 | 제목 검색 필터 | 검색어 입력 → 제목에 포함된 로그만 표시 |

### FG. 일별 메모 오버라이드

| # | 테스트 항목 | 검증 포인트 | 상태 |
|---|-----------|-----------|------|
| FG-1 | 연박자 일별 메모 저장 | PUT /reservations/{id}/daily-info에 notes 전송 → ReservationDailyInfo 저장 | - |
| FG-2 | 일별 메모 조회 시 오버라이드 | GET /reservations?date=X → override_notes 적용, 기본 notes 대신 daily notes 반환 | - |
| FG-3 | 일별 메모 null로 초기화 | notes=null 전송 → daily notes 삭제, 기본 notes로 복원 | - |

### FH. 테이블 설정 모달

| # | 테스트 항목 | 검증 포인트 | 상태 |
|---|-----------|-----------|------|
| FH-1 | 테이블 설정 모달 열기/닫기 | 설정 버튼 → 3탭 모달 (하이라이트 색상, 구분선, 행 스타일) 표시 | - |
| FH-2 | 커스텀 하이라이트 색상 저장 | 색상 추가/삭제 → 저장 → 컨텍스트 메뉴 퀵컬러에 반영 | - |
| FH-3 | 행 스타일 변경 | 짝수/홀수 행 배경색 변경 → 테이블에 즉시 반영 | - |

### FI. 언스테이블 파티 설정

| # | 테스트 항목 | 검증 포인트 | 상태 |
|---|-----------|-----------|------|
| FI-1 | 언스테이블 설정 저장 | POST /settings/unstable/settings → business_id, cookie 저장 + 연결 검증 | - |
| FI-2 | 언스테이블 쿠키 상태 조회 | GET /settings/unstable/status → has_cookie, is_valid 반환 | - |
| FI-3 | 언스테이블 수동 동기화 | POST /settings/unstable/sync → 예약 동기화, section='unstable' 저장 | - |
| FI-4 | 메인 동기화 시 언스테이블 함께 실행 | POST /reservations/sync/naver → unstable_business_id 있으면 함께 동기화 | - |
| FI-5 | 테넌트별 언스테이블 UI 표시/숨김 | has_unstable=false → 언스테이블 관련 UI 전체 숨김 | - |

### FJ. 선택 모드 (탭 투 셀렉트)

| # | 테스트 항목 | 검증 포인트 | 상태 |
|---|-----------|-----------|------|
| FJ-1 | 게스트 행 탭 → 선택 | 행 클릭 → 파란 선택 표시 + 상단 토스트 "이동할 방을 클릭하세요" | - |
| FJ-2 | 방 클릭 → 배정 실행 | 선택 후 방 클릭 → 배정 API 호출 + 선택 해제 | - |
| FJ-3 | ESC/✕로 선택 해제 | ESC 키 또는 토스트 ✕ 버튼 → 선택 해제 + 토스트 닫힘 | - |
| FJ-4 | 복수 선택 후 일괄 배정 | Shift/Ctrl 클릭으로 여러 명 선택 → 방 클릭 → 전원 배정 | - |

### FK. Ctrl+Z 되돌리기

| # | 테스트 항목 | 검증 포인트 | 상태 |
|---|-----------|-----------|------|
| FK-1 | Ctrl+Z로 방 배정 되돌리기 | 배정 후 Ctrl+Z → 이전 상태 복원 + 토스트 "되돌리기: 이름 → 이전방" | - |
| FK-2 | 되돌리기 스택 순차 실행 | A→방1, B→방2 배정 후 Ctrl+Z 2번 → B 복원 → A 복원 | - |

### FL2. 연박추가/취소 API

| # | 테스트 항목 | 검증 포인트 | 상태 |
|---|-----------|-----------|------|
| FL2-1 | 연박추가 API (충돌 없음) | POST /reservations/{id}/extend-stay → 다음날 예약 + stay_group + 방 배정 | - |
| FL2-2 | 연박추가 API (방 충돌) | 다음날 방에 게스트 있으면 → conflict_guests 반환, 방 미배정 | - |
| FL2-3 | 충돌 해결 (기존 게스트 이동) | POST /extend-stay/assign-room + move_existing=true → 기존 미배정 + 새 배정 | - |
| FL2-4 | 연박취소 API | DELETE /extend-stay → extend 예약 삭제 + 그룹 해제 + SMS 재동기화 | - |

### FM. 다음날 테이블 & 크로스데이 이동

| # | 테스트 항목 | 검증 포인트 | 상태 |
|---|-----------|-----------|------|
| FM-1 | 다음날 패널 기본 펼침 | 페이지 로드 시 다음날 패널이 펼쳐진 상태(기본값) → 예약자 목록 표시 | - |
| FM-2 | 다음날 패널 접기/펼치기 | ChevronsRight 클릭 → 접힘, ChevronsLeft 클릭 → 펼침 | - |
| FM-3 | 다음날 패널 상태 localStorage 저장 | 접기 → 새로고침 → 접힌 상태 유지, 펼치기 → 새로고침 → 펼친 상태 유지 | - |
| FM-4 | 다음날 헤더 1줄 레이아웃 | 펼침 시 접기 아이콘이 Circle 컬럼(w-8)에 위치, 날짜+서브헤더가 한 줄 | - |
| FM-5 | 다음날 패널 게스트 표시 | 펼침 → 다음날 예약자 방별/미배정/파티 InlineInput 표시 | - |
| FM-6 | 크로스데이 이동 (오늘→내일) | 오늘 게스트 → 내일 방 배정 → check_in_date 변경 + 방 배정 | - |
| FM-7 | 크로스데이 이동 (내일→오늘) | 내일 게스트 → 오늘 방 배정 → check_in_date 변경 + 방 배정 | - |
| FM-8 | 연박 그룹 크로스데이 차단 | stay_group 게스트 크로스데이 시 경고 토스트 + 차단 | - |
| FM-9 | 다음날 InlineInput 편집 | 다음날 필드 편집 → 다음날 날짜 기준 daily-info/reservation 저장 | - |

### FN. 예약 날짜 변경 모달

| # | 테스트 항목 | 검증 포인트 | 상태 |
|---|-----------|-----------|------|
| FN-1 | 날짜 변경 모달 | 컨텍스트 메뉴 → 모달에서 check_in/check_out 수정 → is_long_stay 재계산 + reconcile_dates | - |

### FO. 브라우저 컨텍스트 메뉴 차단

| # | 테스트 항목 | 검증 포인트 | 상태 |
|---|-----------|-----------|------|
| FO-1 | 테이블 영역 우클릭 차단 | 빈 행/영역 우클릭 → 브라우저 기본 메뉴 안 뜸 | - |

---

## 테스트 실행 환경

- **서버**: 로컬 (backend: uvicorn, frontend: npm run dev)
- **DB**: SQLite (DEMO_MODE=true)
- **SMS**: Aligo testmode=true (실제 발송 안 됨)
- **도구**: Playwright MCP (실제 브라우저 조작 + 스크린샷)
- **원복**: `rm sms.db && python -m app.db.seed`

## 총 테스트 항목 수

| 섹션 | 항목 수 |
|------|--------|
| A. 네이버 예약 동기화 | 5 |
| B. 예약자 분류 | 10 |
| C. 객실 자동 배정 | 14 |
| D. 수동 객실 배정 | 8 |
| E. 스케줄 type별 | 7 |
| F. 스케줄 target_mode별 | 9 |
| G. 스케줄 date_target별 | 4 |
| H. 스케줄 구조적 필터별 | 15 |
| I. 스케줄 stay_filter | 6 |
| J. 스케줄 send_condition | 6 |
| K. 스케줄 event | 6 |
| L. 칩 생성/삭제 | 12 |
| M. 칩 UI 표시 | 10 |
| N. SMS 실제 발송 | 10 |
| P. 인증/권한 | 5 |
| Q. 멀티테넌트 격리 | 13 |
| R. 파티 체크인 | 5 |
| S. 대시보드 | 5 |
| T. 객실 그룹 | 3 |
| FA. 객실배정 테이블 인터랙션 | 5 |
| FB. 로그인 & 레이아웃 | 2 |
| FC. 연박 연결 UI | 2 |
| FD. 게스트 컨텍스트 메뉴 | 13 |
| FE. 활동 로그 | 1 |
| FG. 일별 메모 오버라이드 | 3 |
| FH. 테이블 설정 모달 | 3 |
| FI. 언스테이블 파티 설정 | 5 |
| FJ. 선택 모드 (탭 투 셀렉트) | 4 |
| FK. Ctrl+Z 되돌리기 | 2 |
| FL2. 연박추가/취소 API | 4 |
| FM. 다음날 테이블 & 크로스데이 이동 | 9 |
| FN. 예약 날짜 변경 모달 | 1 |
| FO. 브라우저 컨텍스트 메뉴 차단 | 1 |
| **합계** | **208** |
