import { useCallback, useState } from 'react';
import type { Dayjs } from 'dayjs';
import { toast } from 'sonner';
import { reservationsAPI } from '../../../services/api';
import type { Reservation, SmsAssignment } from '../types';
import type { UndoEntry } from './useUndoStack';
import type { RoomEntry } from '../components/RoomRow';

declare global {
  interface Window {
    __diagAction?: string;
  }
}

type SectionOverrides = Record<number, 'party' | 'unassigned'>;
type ReservationsSetter = React.Dispatch<React.SetStateAction<Reservation[]>>;
type SectionOverridesSetter = React.Dispatch<React.SetStateAction<SectionOverrides>>;

interface MultiNightConfirmShape {
  open: boolean;
  resId: number;
  resName: string;
  roomId: number;
  roomNumber: string;
  onConfirm: (applySubsequent: boolean) => void;
}

interface UseGuestMoveProps {
  reservations: Reservation[];
  nextDayReservations: Reservation[];
  selectedDate: Dayjs;
  fetchReservations: (date: Dayjs) => void;
  setReservations: ReservationsSetter;
  setNextDayReservations: ReservationsSetter;
  sectionOverrides: SectionOverrides;
  setSectionOverrides: SectionOverridesSetter;
  findReservation: (resId: number) => { res: Reservation; isNextDay: boolean } | null;
  nextDayRoomMap: Map<number, Reservation[]>;
  assignedRooms: Map<number, Reservation[]>;
  activeRoomEntries: RoomEntry[];
  pushUndo: (entry: UndoEntry) => void;
  setMultiNightConfirm: (state: MultiNightConfirmShape | null) => void;
  // I-3: onDropZoneClick 흡수
  selectedGuestIds: Set<number>;
  setSelectedGuestIds: React.Dispatch<React.SetStateAction<Set<number>>>;
  showConfirm: (title: string, content: string, onOk: () => void) => void;
}

/**
 * 게스트 이동 통합 — 객실 배정 / 미배정 / 파티만 + 연박 처리 + push_out + undo 푸시.
 *
 * Phase I-2: handleDropOnRoom/Pool/Party + doAssignRoom + recentlyMovedId 통합.
 * 가장 큰 단일 추출 — 게스트 상태 전환의 중심.
 */
export function useGuestMove({
  reservations,
  nextDayReservations,
  selectedDate,
  fetchReservations,
  setReservations,
  setNextDayReservations,
  sectionOverrides,
  setSectionOverrides,
  findReservation,
  nextDayRoomMap,
  assignedRooms,
  activeRoomEntries,
  pushUndo,
  setMultiNightConfirm,
  selectedGuestIds,
  setSelectedGuestIds,
  showConfirm,
}: UseGuestMoveProps) {
  const [recentlyMovedId, setRecentlyMovedId] = useState<number | null>(null);

  /** 실제 객실 배정 — 낙관적 업데이트 + API + push_out + undo 푸시. handleDropOnRoom 내부 호출용. */
  const doAssignRoom = useCallback(async (
    resId: number,
    roomId: number,
    roomNumber: string,
    applySubsequent: boolean,
    applyGroup: boolean = false,
    targetDate?: Dayjs,
  ) => {
    const effectiveDate = targetDate || selectedDate;
    const isNextDay = targetDate != null && !targetDate.isSame(selectedDate, 'day');
    const setter = isNextDay ? setNextDayReservations : setReservations;
    const source = isNextDay ? nextDayReservations : reservations;
    const prev = source.find(r => r.id === resId);
    // 낙관적 업데이트: 새 방으로 이동 + room_info SMS 자동 할당
    setter((list) =>
      list.map((r) => {
        if (r.id !== resId) return r;
        const hasRoomInfo = r.sms_assignments?.some((a) => a.template_key === 'room_info');
        const updatedAssignments = hasRoomInfo
          ? r.sms_assignments
          : [...(r.sms_assignments || []), { id: 0, reservation_id: r.id, template_key: 'room_info', assigned_at: new Date().toISOString(), sent_at: null, assigned_by: 'auto', date: effectiveDate.format('YYYY-MM-DD') } as SmsAssignment];
        return { ...r, room_id: roomId, room_number: roomNumber, sms_assignments: updatedAssignments };
      })
    );
    if (!isNextDay) setSectionOverrides((p) => { const next = { ...p }; delete next[resId]; return next; });

    try {
      window.__diagAction = `drag_guest_to_room:res=${resId},room=${roomNumber}`;
      const { data: result } = await reservationsAPI.assignRoom(resId, {
        room_id: roomId,
        date: effectiveDate.format('YYYY-MM-DD'),
        apply_subsequent: applySubsequent,
        apply_group: applyGroup,
      });
      toast.success(`${roomNumber} 배정 완료`);
      // 성공 시에만 undo 스택에 푸시
      if (prev) {
        // prevSection 정합성 보정: room_id 가 null 이면 'room' 절대 안 됨.
        // sectionOverrides (당일 컨텍스트만) 우선, 그 다음 DB section, 마지막 fallback 'unassigned'.
        const overrideSec = !isNextDay ? sectionOverrides[resId] : undefined;
        const computedPrevSection = prev.room_id
          ? 'room'
          : (overrideSec ?? (prev.section && prev.section !== 'room' ? prev.section : 'unassigned'));
        pushUndo({
          resId,
          prevRoomId: prev.room_id ?? null,
          prevRoomNumber: (prev as any).room_number ?? null,
          prevSection: computedPrevSection,
          date: effectiveDate.format('YYYY-MM-DD'),
          customerName: prev.customer_name,
          applySubsequent,
          applyGroup,
          movedToRoomId: roomId,
          pushedOut: result.pushed_out ?? [],
        });
      }
      if (result.warnings?.length) {
        result.warnings.forEach((w: string) => toast.warning(w));
      }
      fetchReservations(selectedDate);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || '객실 배정에 실패했습니다.');
      await fetchReservations(selectedDate);
    }
  }, [
    reservations, nextDayReservations, selectedDate,
    setReservations, setNextDayReservations, setSectionOverrides,
    fetchReservations, pushUndo,
  ]);

  /** 객실 영역 드롭 — 날짜 이동 / 연박자 / 일반 분기 처리. */
  const handleDropOnRoom = useCallback((resId: number, roomId: number, dropTargetDate?: Dayjs) => {
    const found = findReservation(resId);
    if (!found) return;
    const { res, isNextDay: sourceIsNextDay } = found;
    const targetDate = dropTargetDate || selectedDate;
    const dropIsNextDay = !targetDate.isSame(selectedDate, 'day');

    // 중복 체크
    const currentList = dropIsNextDay
      ? (nextDayRoomMap.get(roomId) || [])
      : (assignedRooms.get(roomId) || []);
    if (currentList.some((r) => r.id === resId)) return;

    const entry = activeRoomEntries.find((e) => e.room_id === roomId);

    // 날짜 이동: 예약 날짜 + 객실 변경
    if (sourceIsNextDay !== dropIsNextDay) {
      if (res.stay_group_id) {
        toast.warning('연박 그룹에 속한 게스트는 날짜 이동이 불가합니다. 연박 해제 후 이동하세요.');
        return;
      }

      const destDate = dropIsNextDay ? selectedDate.add(1, 'day') : selectedDate;
      const destDateStr = destDate.format('YYYY-MM-DD');
      const destCheckout = destDate.add(1, 'day').format('YYYY-MM-DD');
      const roomNumber = entry?.room_number || '';

      const sourceSetter = sourceIsNextDay ? setNextDayReservations : setReservations;
      const targetSetter = dropIsNextDay ? setNextDayReservations : setReservations;
      sourceSetter((prev) => prev.filter((r) => r.id !== resId));
      targetSetter((prev) => [...prev, { ...res, room_id: roomId, room_number: roomNumber, check_in_date: destDateStr, check_out_date: destCheckout, section: 'room' }]);

      (async () => {
        try {
          await reservationsAPI.update(resId, {
            check_in_date: destDateStr,
            check_out_date: destCheckout,
          });
          await reservationsAPI.assignRoom(resId, {
            room_id: roomId,
            date: destDateStr,
            apply_subsequent: false,
          });
          toast.success(`${res.customer_name} → ${roomNumber} (${destDateStr})`);
          fetchReservations(selectedDate);
        } catch (err: any) {
          toast.error(err?.response?.data?.detail || '날짜 이동 실패');
          fetchReservations(selectedDate);
        }
      })();
      return;
    }

    const roomNumber = entry?.room_number || '';

    // 연박자: 적용 범위 (single/subsequent) 모달 띄움
    if (res.is_long_stay) {
      setMultiNightConfirm({
        open: true, resId, resName: res.customer_name, roomId, roomNumber,
        onConfirm: (applySubsequent) => {
          setMultiNightConfirm(null);
          doAssignRoom(resId, roomId, roomNumber, applySubsequent, !!res.stay_group_id && applySubsequent, targetDate);
        },
      });
      return;
    }

    doAssignRoom(resId, roomId, roomNumber, true, false, targetDate);
  }, [
    findReservation, selectedDate, nextDayRoomMap, assignedRooms, activeRoomEntries,
    setReservations, setNextDayReservations, fetchReservations,
    setMultiNightConfirm, doAssignRoom,
  ]);

  /** 미배정으로 이동 (객실 배정 해제 또는 파티→미배정). */
  const handleDropOnPool = useCallback(async (resId: number, targetDate?: Dayjs) => {
    const found = findReservation(resId);
    if (!found) return;
    const { res, isNextDay } = found;

    const effectiveDate = targetDate || (isNextDay ? selectedDate.add(1, 'day') : selectedDate);
    const setter = isNextDay ? setNextDayReservations : setReservations;
    setRecentlyMovedId(resId);
    const effectiveSection = sectionOverrides[resId] ?? res.section;
    if (!res.room_id && effectiveSection === 'unassigned') return;

    if (res.room_id) {
      setter((prev) => prev.map((r) => {
        if (r.id !== resId) return r;
        const filtered = r.sms_assignments?.filter((a) => !(a.template_key === 'room_info' && !a.sent_at)) || [];
        return { ...r, room_id: null, room_number: null, section: 'unassigned', sms_assignments: filtered };
      }));
      if (!isNextDay) setSectionOverrides((prev) => ({ ...prev, [resId]: 'unassigned' }));
      try {
        if (!window.__diagAction) window.__diagAction = 'drop_on_pool';
        await reservationsAPI.assignRoom(resId, { room_id: null, date: effectiveDate.format('YYYY-MM-DD'), apply_subsequent: true });
        await reservationsAPI.update(resId, { section: 'unassigned' });
        toast.success('미배정으로 이동');
        pushUndo({
          resId,
          prevRoomId: res.room_id,
          prevRoomNumber: res.room_number ?? null,
          prevSection: 'room',
          date: effectiveDate.format('YYYY-MM-DD'),
          customerName: res.customer_name,
          applySubsequent: true,
          applyGroup: false,
        });
        fetchReservations(selectedDate);
      } catch {
        toast.error('배정 해제에 실패했습니다.');
        await fetchReservations(selectedDate);
      }
    } else {
      if (isNextDay) {
        setter((prev) => prev.map((r) => r.id === resId ? { ...r, section: 'unassigned' } : r));
      } else {
        setSectionOverrides((prev) => ({ ...prev, [resId]: 'unassigned' }));
      }
      toast.success('미배정으로 이동');
      try {
        await reservationsAPI.update(resId, { section: 'unassigned' });
        pushUndo({
          resId,
          prevRoomId: null,
          prevRoomNumber: null,
          prevSection: effectiveSection ?? 'party',
          date: effectiveDate.format('YYYY-MM-DD'),
          customerName: res.customer_name,
          applySubsequent: false,
          applyGroup: false,
        });
        fetchReservations(selectedDate);
      } catch {
        if (!isNextDay) setSectionOverrides((prev) => { const next = { ...prev }; delete next[resId]; return next; });
        toast.error('이동 실패');
      }
    }
  }, [
    findReservation, selectedDate, sectionOverrides,
    setReservations, setNextDayReservations, setSectionOverrides, fetchReservations,
    pushUndo,
  ]);

  /** 파티만으로 이동 (객실 배정 해제 또는 미배정→파티). */
  const handleDropOnParty = useCallback(async (resId: number, targetDate?: Dayjs) => {
    const found = findReservation(resId);
    if (!found) return;
    const { res: guest, isNextDay } = found;

    const effectiveDate = targetDate || (isNextDay ? selectedDate.add(1, 'day') : selectedDate);
    const setter = isNextDay ? setNextDayReservations : setReservations;
    setRecentlyMovedId(resId);
    const effectiveSection = sectionOverrides[resId] ?? guest.section;
    if (!guest.room_id && effectiveSection === 'party') return;

    if (guest.room_id) {
      setter((prev) => prev.map((r) => {
        if (r.id !== resId) return r;
        const filtered = r.sms_assignments?.filter((a) => !(a.template_key === 'room_info' && !a.sent_at)) || [];
        return { ...r, room_id: null, room_number: null, section: 'party', sms_assignments: filtered };
      }));
      if (!isNextDay) setSectionOverrides((prev) => ({ ...prev, [resId]: 'party' }));
      try {
        if (!window.__diagAction) window.__diagAction = 'drop_on_party';
        await reservationsAPI.assignRoom(resId, { room_id: null, date: effectiveDate.format('YYYY-MM-DD'), apply_subsequent: true });
        await reservationsAPI.update(resId, { section: 'party' });
        toast.success('파티만으로 이동');
        pushUndo({
          resId,
          prevRoomId: guest.room_id,
          prevRoomNumber: guest.room_number ?? null,
          prevSection: 'room',
          date: effectiveDate.format('YYYY-MM-DD'),
          customerName: guest.customer_name,
          applySubsequent: true,
          applyGroup: false,
        });
        fetchReservations(selectedDate);
      } catch {
        toast.error('이동 실패');
        await fetchReservations(selectedDate);
      }
    } else {
      if (isNextDay) {
        setter((prev) => prev.map((r) => r.id === resId ? { ...r, section: 'party' } : r));
      } else {
        setSectionOverrides((prev) => ({ ...prev, [resId]: 'party' }));
      }
      toast.success('파티만으로 이동');
      try {
        await reservationsAPI.update(resId, { section: 'party' });
        pushUndo({
          resId,
          prevRoomId: null,
          prevRoomNumber: null,
          prevSection: effectiveSection ?? 'unassigned',
          date: effectiveDate.format('YYYY-MM-DD'),
          customerName: guest.customer_name,
          applySubsequent: false,
          applyGroup: false,
        });
        fetchReservations(selectedDate);
      } catch {
        if (!isNextDay) setSectionOverrides((prev) => { const next = { ...prev }; delete next[resId]; return next; });
        toast.error('이동 실패');
      }
    }
  }, [
    findReservation, selectedDate, sectionOverrides,
    setReservations, setNextDayReservations, setSectionOverrides, fetchReservations,
    pushUndo,
  ]);

  /** 드롭존 클릭 — 선택된 게스트들을 적절한 zone 으로 이동. */
  const onDropZoneClick = useCallback((e: React.MouseEvent) => {
    if (selectedGuestIds.size === 0) return;

    const interactive = (e.target as HTMLElement).closest('button, a, input, select, textarea, [role="button"], [data-interactive]');
    if (interactive) return;

    const target = (e.target as HTMLElement).closest<HTMLElement>('[data-drop-zone]');
    if (!target) return;
    const zoneId = target.dataset.dropZone || '';

    const ids = [...selectedGuestIds];
    setSelectedGuestIds(new Set());

    if (zoneId.startsWith('next-room-')) {
      const roomId = Number(zoneId.replace('next-room-', ''));
      const targetDate = selectedDate.add(1, 'day');
      const hasCrossDay = ids.some(id => {
        const f = findReservation(id);
        return f && !f.isNextDay;
      });
      if (hasCrossDay) {
        showConfirm('날짜 이동 확인', '오늘 체크인 게스트를 내일 방에 배정하시겠습니까?\n예약 날짜가 내일로 변경됩니다.', () => {
          ids.forEach(id => handleDropOnRoom(id, roomId, targetDate));
        });
        return;
      }
      ids.forEach(id => handleDropOnRoom(id, roomId, targetDate));
    } else if (zoneId.startsWith('room-')) {
      const roomId = Number(zoneId.replace('room-', ''));
      const hasCrossDay = ids.some(id => {
        const f = findReservation(id);
        return f && f.isNextDay;
      });
      if (hasCrossDay) {
        showConfirm('날짜 이동 확인', '내일 체크인 게스트를 오늘 방에 배정하시겠습니까?\n예약 날짜가 오늘로 변경됩니다.', () => {
          ids.forEach(id => handleDropOnRoom(id, roomId));
        });
        return;
      }
      ids.forEach(id => handleDropOnRoom(id, roomId));
    } else if (zoneId === 'next-pool') {
      ids.forEach(id => handleDropOnPool(id, selectedDate.add(1, 'day')));
    } else if (zoneId === 'next-party') {
      ids.forEach(id => handleDropOnParty(id, selectedDate.add(1, 'day')));
    } else if (zoneId === 'pool') {
      ids.forEach(id => handleDropOnPool(id));
    } else if (zoneId === 'party') {
      ids.forEach(id => handleDropOnParty(id));
    }
  }, [
    selectedGuestIds, setSelectedGuestIds, selectedDate,
    findReservation, showConfirm,
    handleDropOnRoom, handleDropOnPool, handleDropOnParty,
  ]);

  return {
    recentlyMovedId,
    handleDropOnRoom,
    handleDropOnPool,
    handleDropOnParty,
    onDropZoneClick,
  };
}
