import { useCallback, useState } from 'react';
import type { Dayjs } from 'dayjs';
import dayjs from 'dayjs';
import { toast } from 'sonner';
import { reservationsAPI } from '../../../services/api';
import type { Reservation } from '../types';

interface UseReservationFormProps {
  reservations: Reservation[];
  selectedDate: Dayjs;
  fetchReservations: (date: Dayjs) => void;
  findReservation: (resId: number) => { res: Reservation; isNextDay: boolean } | null;
  showConfirm: (title: string, content: string, onOk: () => void) => void;
  /** 빠른 추가 시 새 ID 마킹 — 셀이 자동 포커스되어 인라인 편집 진입. */
  setQuickAddedId: (id: number | null) => void;
}

const DEFAULT_FORM_VALUES = {
  guest_type: 'party_only',
  customer_name: '',
  phone: '',
  date: '',
  time: '18:00',
  gender: '',
  party_size: 1,
  naver_room_type: '',
  notes: '',
  status: 'confirmed',
  booking_source: 'manual',
};

/**
 * 예약 폼 모달 (추가/수정/삭제/빠른추가) 흐름 통합.
 *
 * Phase H: RoomAssignment.tsx 의 modalVisible / formValues / 5개 핸들러 묶음.
 * 폼-백엔드 스키마 변환 로직은 그대로 보존 (DELETE.md `[리팩토링]` 메모).
 */
export function useReservationForm({
  reservations,
  selectedDate,
  fetchReservations,
  findReservation,
  showConfirm,
  setQuickAddedId,
}: UseReservationFormProps) {
  const [modalVisible, setModalVisible] = useState(false);
  const [savingReservation, setSavingReservation] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formValues, setFormValues] = useState<any>({ ...DEFAULT_FORM_VALUES });

  const closeModal = useCallback(() => setModalVisible(false), []);

  // 새 파티 게스트 모달 열기 — 빈 폼 + 기본값
  const handleAddPartyGuest = useCallback(() => {
    setEditingId(null);
    setFormValues({
      ...DEFAULT_FORM_VALUES,
      date: selectedDate.format('YYYY-MM-DD'),
    });
    setModalVisible(true);
  }, [selectedDate]);

  // QuickMenuBar 의 즉시 추가 — 모달 없이 빈 게스트 생성 + 마킹
  const handleQuickAddParty = useCallback(async () => {
    try {
      const res = await reservationsAPI.create({
        customer_name: '',
        phone: '',
        check_in_date: selectedDate.format('YYYY-MM-DD'),
        check_in_time: '18:00',
        naver_room_type: '파티만',
        section: 'party',
        status: 'confirmed',
        booking_source: 'manual',
      });
      const newId = res.data?.id;
      if (newId) setQuickAddedId(newId);
      await fetchReservations(selectedDate);
      toast.success('파티 게스트 추가됨');
    } catch {
      toast.error('추가 실패');
    }
  }, [selectedDate, fetchReservations, setQuickAddedId]);

  // 기존 게스트 수정 모달 열기 (다음날 게스트는 차단)
  const handleEditGuest = useCallback((id: number) => {
    const found = findReservation(id);
    if (found?.isNextDay) {
      toast.info('해당 날짜로 이동 후 편집해주세요');
      return;
    }
    const guest = reservations.find((r) => r.id === id);
    if (guest) {
      setEditingId(id);
      setFormValues({
        ...guest,
        guest_type: undefined,
      });
      setModalVisible(true);
    }
  }, [findReservation, reservations]);

  // 게스트 삭제 (확인 다이얼로그 → API → 새로고침)
  const handleDeleteGuest = useCallback((id: number) => {
    showConfirm('게스트 삭제', '정말 삭제하시겠습니까?', async () => {
      try {
        await reservationsAPI.delete(id);
        toast.success('삭제 완료');
        fetchReservations(selectedDate);
      } catch {
        toast.error('삭제 실패');
      }
    });
  }, [showConfirm, fetchReservations, selectedDate]);

  // 폼 저장 — 입력 검증 + 변환 + API 호출
  const handleSubmit = useCallback(async () => {
    if (savingReservation) return;
    const values = { ...formValues };

    if (!values.customer_name) { toast.error('이름을 입력하세요'); return; }
    if (!values.phone) { toast.error('전화번호를 입력하세요'); return; }
    if (!values.date) { toast.error('날짜를 입력하세요'); return; }

    // male_count/female_count → gender 문자열 + party_size
    const maleCount = values.male_count ? Number(values.male_count) : 0;
    const femaleCount = values.female_count ? Number(values.female_count) : 0;
    const genderParts = [];
    if (maleCount > 0) genderParts.push(`남${maleCount}`);
    if (femaleCount > 0) genderParts.push(`여${femaleCount}`);
    values.gender = genderParts.join('') || null;
    values.party_size = (maleCount + femaleCount) || null;
    values.male_count = maleCount || null;
    values.female_count = femaleCount || null;

    // 연박: check_out_date 계산
    if (values.multi_night && values.nights && values.nights >= 2 && values.date) {
      const checkIn = dayjs(values.date);
      values.check_out_date = checkIn.add(values.nights, 'day').format('YYYY-MM-DD');
    } else if (values.date) {
      // 1박: co=null 로 보내야 _filter_last_day 가 당일 케이스로 인식해
      // last_night 스케줄(연박유도/후기 등)에 정상 포함됨.
      // 연박→단일 전환 시 백엔드 exclude_unset 회피 위해 명시 null 전송.
      values.check_out_date = null;
    }
    delete values.multi_night;
    delete values.nights;

    // 필드명 매핑
    values.check_in_date = values.date;
    values.check_in_time = values.time || '00:00';
    delete values.date;
    delete values.time;

    if (!editingId && values.guest_type) {
      if (values.guest_type === 'party_only') {
        values.naver_room_type = '파티만';
        values.section = 'party';
      } else {
        // 수동 추가 - 미배정: naver_room_type을 '수동추가'로 설정
        if (!values.naver_room_type) {
          values.naver_room_type = '수동추가';
        }
      }
      delete values.guest_type;
    }

    setSavingReservation(true);
    try {
      if (editingId) {
        await reservationsAPI.update(editingId, values);
        toast.success('수정 완료');
      } else {
        await reservationsAPI.create(values);
        toast.success('추가 완료');
      }
      setModalVisible(false);
      fetchReservations(selectedDate);
    } catch {
      toast.error('저장 실패');
    } finally {
      setSavingReservation(false);
    }
  }, [savingReservation, formValues, editingId, fetchReservations, selectedDate]);

  return {
    modalVisible,
    closeModal,
    savingReservation,
    editingId,
    formValues,
    setFormValues,
    handleAddPartyGuest,
    handleQuickAddParty,
    handleEditGuest,
    handleDeleteGuest,
    handleSubmit,
  };
}
