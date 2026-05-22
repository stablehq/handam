/**
 * RoomAssignment 페이지에서 공유되는 데이터 shape 타입.
 *
 * Phase 1 단순 분리: RoomAssignment.tsx 내 인라인 정의를 그대로 옮김.
 * 동작/필드 변경 없음. 컴포넌트 props 타입(RoomMemoEditorProps, SmsCellProps 등)은
 * 해당 컴포넌트 추출 시 함께 이동 예정이라 여기 포함하지 않음.
 *
 * NOTE: pages/Reservations.tsx 가 동명 `Reservation` 인터페이스를 자체 정의하지만
 * 두 파일이 직접 공유하지 않으므로 충돌 없음. 추후 통합 시 별도 작업.
 */

export interface SmsAssignment {
  id: number;
  reservation_id: number;
  template_key: string;
  assigned_at: string;
  sent_at: string | null;
  assigned_by: string;
  date: string;
  send_status?: string | null;
  send_error?: string | null;
  surcharge_total_text?: string | null;  // 'add_standard'/'add_double' 칩 툴팁용 ("추가요금 8만원")
}

export interface Reservation {
  id: number;
  customer_name: string;
  phone: string;
  visitor_name?: string | null;
  visitor_phone?: string | null;
  check_in_date: string;
  check_in_time: string;
  status: string;
  room_id: number | null;
  room_number: string | null;
  room_password: string | null;
  room_assigned_by: string | null;
  naver_room_type: string | null;
  section: string;  // 'room', 'unassigned', 'party', 'unstable'
  unstable_party?: boolean;
  gender: string | null;
  age_group?: string | null;
  visit_count?: number | null;
  male_count: number | null;
  female_count: number | null;
  party_size: number | null;
  party_type: string | null;  // '1'=1차만, '2'=1+2차, '2차만'
  notes: string | null;
  check_out_date: string | null;
  booking_source?: string;
  sms_assignments: SmsAssignment[];
  stay_group_id?: string | null;
  stay_group_order?: number | null;
  stay_group_total_nights?: number | null;  // 그룹 전체 박수 (경로 B 지원)
  stay_group_night_offset?: number | null;  // 이 record 시작 전까지 누적 박수
  is_long_stay?: boolean;
  manually_extended_until?: string | null;
  bed_order?: number;
  highlight_color?: string | null;
  has_unstable_booking?: boolean;
  cancelled_at?: string | null;
  created_at?: string;
}

export interface ConfirmState {
  open: boolean;
  title: string;
  content: string;
  onOk: () => void;
}

/**
 * RoomAssignment 페이지의 상단 SummaryCards 가 표시하는 통계.
 * RoomAssignment.tsx 의 summary useMemo (line 801-861) 반환 타입을 명시.
 * DesktopLayout / SummaryCards 가 동일한 prop 타입으로 받는다.
 */
export interface Summary {
  // 객실 게스트 통계 (복사본 제외)
  roomTotal: number;
  roomMale: number;
  roomFemale: number;
  // 파티 전체
  partyTotal: number;
  partyMale: number;
  partyFemale: number;
  // 파티 1차 (1차만 + 1,2차)
  firstTotal: number;
  firstMale: number;
  firstFemale: number;
  // 파티 2차만
  secondOnlyTotal: number;
  secondOnlyMale: number;
  secondOnlyFemale: number;
  // 2차 전환율 (1차 중 2차 참여 비율, %)
  conversionRate: number;
  // 1차 남:여 비율 ("1.5:1" 또는 "-")
  genderRatio: string;
  // unstable (순수 unstable + 복사본)
  unstableTotal: number;
  unstableMale: number;
  unstableFemale: number;
}
