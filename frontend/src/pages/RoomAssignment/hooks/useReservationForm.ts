import { useCallback, useState } from 'react';
import type { Dayjs } from 'dayjs';
import dayjs from 'dayjs';
import { toast } from 'sonner';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { reservationsAPI } from '../../../services/api';
import { queryKeys } from '@/lib/queryKeys';
import type { Reservation } from '../types';

interface UseReservationFormProps {
  reservations: Reservation[];
  selectedDate: Dayjs;
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
 * Phase 3b: create/update/delete → useMutation.
 */
export function useReservationForm({
  reservations,
  selectedDate,
  findReservation,
  showConfirm,
  setQuickAddedId,
}: UseReservationFormProps) {
  const qc = useQueryClient();
  const [modalVisible, setModalVisible] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formValues, setFormValues] = useState<any>({ ...DEFAULT_FORM_VALUES });

  const dateStr = selectedDate.format('YYYY-MM-DD');
  const nextDateStr = selectedDate.add(1, 'day').format('YYYY-MM-DD');

  const invalidateReservations = useCallback(() => {
    qc.invalidateQueries({ queryKey: queryKeys.reservations.list(dateStr) });
    qc.invalidateQueries({ queryKey: queryKeys.reservations.list(nextDateStr) });
  }, [qc, dateStr, nextDateStr]);

  const closeModal = useCallback(() => setModalVisible(false), []);

  // ===== Create mutation =====
  const createMutation = useMutation({
    mutationFn: (values: any) => reservationsAPI.create(values),
    onSuccess: () => {
      toast.success('추가 완료');
      setModalVisible(false);
      invalidateReservations();
    },
    onError: () => toast.error('저장 실패'),
  });

  // ===== Update mutation =====
  const updateMutation = useMutation({
    mutationFn: ({ id, values }: { id: number; values: any }) =>
      reservationsAPI.update(id, values),
    onSuccess: () => {
      toast.success('수정 완료');
      setModalVisible(false);
      invalidateReservations();
    },
    onError: () => toast.error('저장 실패'),
  });

  // ===== Delete mutation =====
  const deleteMutation = useMutation({
    mutationFn: (id: number) => reservationsAPI.delete(id),
    onSuccess: () => {
      toast.success('삭제 완료');
      invalidateReservations();
    },
    onError: () => toast.error('삭제 실패'),
  });

  // Quick-add mutation (no modal)
  const quickAddMutation = useMutation({
    mutationFn: (values: any) => reservationsAPI.create(values),
    onSuccess: (res) => {
      const newId = res.data?.id;
      if (newId) setQuickAddedId(newId);
      toast.success('파티 게스트 추가됨');
      invalidateReservations();
    },
    onError: () => toast.error('추가 실패'),
  });

  const savingReservation = createMutation.isPending || updateMutation.isPending;

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
  const handleQuickAddParty = useCallback(() => {
    quickAddMutation.mutate({
      customer_name: '',
      phone: '',
      check_in_date: selectedDate.format('YYYY-MM-DD'),
      check_in_time: '18:00',
      naver_room_type: '파티만',
      section: 'party',
      status: 'confirmed',
      booking_source: 'manual',
    });
  }, [selectedDate, quickAddMutation]);

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

  // 게스트 삭제 (확인 다이얼로그 → mutation)
  const handleDeleteGuest = useCallback((id: number) => {
    showConfirm('게스트 삭제', '정말 삭제하시겠습니까?', () => {
      deleteMutation.mutate(id);
    });
  }, [showConfirm, deleteMutation]);

  // 폼 저장 — 입력 검증 + 변환 + mutation 호출
  const handleSubmit = useCallback(() => {
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
        if (!values.naver_room_type) {
          values.naver_room_type = '수동추가';
        }
      }
      delete values.guest_type;
    }

    if (editingId) {
      updateMutation.mutate({ id: editingId, values });
    } else {
      createMutation.mutate(values);
    }
  }, [savingReservation, formValues, editingId, createMutation, updateMutation]);

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
