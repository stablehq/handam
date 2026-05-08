import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Dayjs } from 'dayjs';
import { toast } from 'sonner';
import { reservationsAPI, roomsAPI, templatesAPI } from '../../../services/api';
import type { Reservation } from '../types';

interface TemplateLabel {
  template_key: string;
  name: string;
  short_label: string | null;
}

interface RoomGroup {
  id: number;
  name: string;
  sort_order: number;
  color?: string;
  room_ids: number[];
}

/**
 * 활성 예약만 통과 + 당일 취소도 시각 확인용으로 유지.
 * 본체의 navigateDate 최적화 로직에서도 사용하므로 export.
 * 추후 utils/ 로 이동 가능.
 */
export const filterActive = (data: any[], dateStr: string): Reservation[] => {
  return data.filter((r: Reservation) => {
    if (r.status !== 'cancelled') return true;
    if (r.check_in_date !== dateStr) return false;
    if (!r.cancelled_at) return false;
    return r.cancelled_at.startsWith(dateStr);
  });
};

/**
 * 객실 배정 페이지의 모든 데이터 페칭과 상태를 통합.
 *
 * Phase C-1: rooms / reservations / nextDayReservations / templateLabels / roomGroups + fetch + effects.
 * 파생 상태(assignedRooms, buildingGroups 등)는 Phase C-2 에서 흡수 예정.
 *
 * setter 일부 노출(setReservations 등): Phase D/I 진행 후 정리 예정.
 */
export function useReservationsData(selectedDate: Dayjs) {
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [sectionOverrides, setSectionOverrides] = useState<Record<number, 'party' | 'unassigned'>>({});
  const [nextDayReservations, setNextDayReservations] = useState<Reservation[]>([]);
  const [rooms, setRooms] = useState<any[]>([]);
  const [templateLabels, setTemplateLabels] = useState<TemplateLabel[]>([]);
  const [roomGroups, setRoomGroups] = useState<RoomGroup[]>([]);
  const [loading, setLoading] = useState(false);

  // 날짜 이동 방향 추적 (프리페치/애니메이션용)
  const prevDateRef = useRef<Dayjs>(selectedDate);
  const reservationsRef = useRef<Reservation[]>([]);
  const nextDayRef = useRef<Reservation[]>([]);

  const fetchRoomGroups = useCallback(async () => {
    try {
      const res = await roomsAPI.getGroups();
      setRoomGroups(res.data);
    } catch {
      // silently ignore group fetch failures
    }
  }, []);

  const fetchRooms = useCallback(async () => {
    try {
      const res = await roomsAPI.getAll();
      setRooms(res.data);
    } catch {
      toast.error('객실 목록을 불러오지 못했습니다.');
    }
  }, []);

  const fetchReservations = useCallback(async (date: Dayjs) => {
    setLoading(true);
    try {
      const dateStr = date.format('YYYY-MM-DD');

      // 당일 먼저 로딩
      const current = await reservationsAPI.getAll({ date: dateStr, limit: 200 });
      const curr = filterActive(current.data.items ?? current.data, dateStr);
      setReservations(curr);
      reservationsRef.current = curr;
      prevDateRef.current = date;
      setLoading(false);

      // 다음날 백그라운드 fetch
      const nextDateStr = date.add(1, 'day').format('YYYY-MM-DD');
      reservationsAPI.getAll({ date: nextDateStr, limit: 200 })
        .then(res => { const d = filterActive(res.data.items ?? res.data, nextDateStr); setNextDayReservations(d); nextDayRef.current = d; })
        .catch(() => { setNextDayReservations([]); nextDayRef.current = []; });
    } catch {
      toast.error('예약 목록을 불러오지 못했습니다.');
      setLoading(false);
    }
  }, []);

  // 마운트: 객실/그룹 로드
  useEffect(() => {
    fetchRooms();
    fetchRoomGroups();
  }, [fetchRooms, fetchRoomGroups]);

  // 마운트: 템플릿 라벨 로드 (한 번만)
  useEffect(() => {
    templatesAPI.getLabels().then(res => setTemplateLabels(res.data)).catch(() => {});
  }, []);

  // 날짜 변경 시 예약 새로고침
  useEffect(() => {
    fetchReservations(selectedDate);
  }, [selectedDate, fetchReservations]);

  // ===== 파생 상태 =====

  const roomInfoMap = useMemo(() => {
    const map: Record<string, string> = {};
    rooms.forEach((room) => {
      map[room.room_number] = room.room_type;
    });
    return map;
  }, [rooms]);

  const roomMemoMap = useMemo(() => {
    const map: Record<number, string> = {};
    rooms.forEach((room) => {
      map[room.id] = room.room_memo || '';
    });
    return map;
  }, [rooms]);

  const saveRoomMemo = useCallback(async (roomId: number, memo: string) => {
    try {
      await roomsAPI.update(roomId, { room_memo: memo });
      setRooms((prev) => prev.map((r) => (r.id === roomId ? { ...r, room_memo: memo } : r)));
    } catch {
      toast.error('메모 저장 실패');
      throw new Error('save failed');
    }
  }, []);

  const activeRoomEntries = useMemo(() => {
    return rooms.filter((room) => room.active).map((room) => ({
      room_id: room.id as number,
      room_number: room.room_number as string,
      isDormitory: room.dormitory || false,
      bed_capacity: room.bed_capacity || 1,
      building_id: room.building_id as number | null,
      building_name: room.building_name as string | null,
    }));
  }, [rooms]);

  const nextDayRoomMap = useMemo(() => {
    const map = new Map<number, Reservation[]>();
    nextDayReservations.forEach((r) => {
      if (r.room_id) {
        const existing = map.get(r.room_id) || [];
        existing.push(r);
        map.set(r.room_id, existing);
      }
    });
    return map;
  }, [nextDayReservations]);

  const roomGroupMap = useMemo(() => {
    const map = new Map<number, { group_id: number; groupIndex: number; isFirst: boolean; isLast: boolean }>();
    for (let gi = 0; gi < roomGroups.length; gi++) {
      const group = roomGroups[gi];
      const orderedIds = activeRoomEntries
        .map((e) => e.room_id)
        .filter((id) => group.room_ids.includes(id));
      orderedIds.forEach((roomId, idx) => {
        map.set(roomId, {
          group_id: group.id,
          groupIndex: gi,
          isFirst: idx === 0,
          isLast: idx === orderedIds.length - 1,
        });
      });
    }
    return map;
  }, [roomGroups, activeRoomEntries]);

  // 예약을 5개 카테고리로 분류 — bumping(recentlyMovedId)은 본체 책임이라 raw 만 반환.
  const { assignedRooms, unassigned, partyOnly, unstableGuests, cancelledGuests } = useMemo(() => {
    const assigned = new Map<number, Reservation[]>();
    const unassignedList: Reservation[] = [];
    const partyOnlyList: Reservation[] = [];
    const unstableList: Reservation[] = [];
    const cancelledList: Reservation[] = [];

    reservations.forEach((res) => {
      if (res.status === 'cancelled') {
        cancelledList.push(res);
        return;
      }
      if (res.room_id) {
        const list = assigned.get(res.room_id) || [];
        list.push(res);
        assigned.set(res.room_id, list);
      } else if (sectionOverrides[res.id] === 'party' || (sectionOverrides[res.id] === undefined && res.section === 'party')) {
        partyOnlyList.push(res);
      } else if (res.section === 'unstable') {
        unstableList.push(res);
      } else {
        unassignedList.push(res);
      }
    });

    // 스테이블 예약자 중 unstable_party=true인 경우 → 언스테이블 행에 복사본 추가
    reservations.forEach((res) => {
      if (res.section !== 'unstable' && res.unstable_party) {
        unstableList.push({ ...res, _isCopied: true } as Reservation & { _isCopied?: boolean });
      }
    });

    // 파티만 행: 예약 생성 시각 오래된 순 (최신이 맨 아래)
    partyOnlyList.sort((a, b) =>
      new Date(a.created_at ?? 0).getTime() - new Date(b.created_at ?? 0).getTime()
    );

    return {
      assignedRooms: assigned,
      unassigned: unassignedList,
      partyOnly: partyOnlyList,
      unstableGuests: unstableList,
      cancelledGuests: cancelledList,
    };
  }, [reservations, sectionOverrides]);

  const nextDayUnassigned = useMemo(() =>
    nextDayReservations.filter(r => !r.room_id && (r.section === 'unassigned' || !r.section)),
    [nextDayReservations]
  );

  const nextDayPartyOnly = useMemo(() =>
    nextDayReservations.filter(r => !r.room_id && r.section === 'party'),
    [nextDayReservations]
  );

  const findReservation = useCallback(
    (resId: number): { res: Reservation; isNextDay: boolean } | null => {
      const today = reservations.find((r) => r.id === resId);
      if (today) return { res: today, isNextDay: false };
      const tomorrow = nextDayReservations.find((r) => r.id === resId);
      if (tomorrow) return { res: tomorrow, isNextDay: true };
      return null;
    },
    [reservations, nextDayReservations]
  );

  const buildingGroups = useMemo(() => {
    const groups: { building_id: number | null; building_name: string | null; entries: typeof activeRoomEntries; assignedCount: number; totalCount: number }[] = [];
    let currentBuildingId: number | null | undefined = undefined;
    let currentGroup: typeof groups[0] | null = null;

    activeRoomEntries.forEach((entry) => {
      if (entry.building_id !== currentBuildingId) {
        currentBuildingId = entry.building_id;
        currentGroup = {
          building_id: entry.building_id,
          building_name: entry.building_name,
          entries: [],
          assignedCount: 0,
          totalCount: 0,
        };
        groups.push(currentGroup);
      }
      currentGroup!.entries.push(entry);
      currentGroup!.totalCount++;
      if ((assignedRooms.get(entry.room_id) || []).length > 0) {
        currentGroup!.assignedCount++;
      }
    });

    return groups;
  }, [activeRoomEntries, assignedRooms]);

  return {
    reservations, setReservations,
    sectionOverrides, setSectionOverrides,
    nextDayReservations, setNextDayReservations,
    rooms, setRooms,
    templateLabels,
    roomGroups, setRoomGroups,
    loading,
    fetchReservations,
    fetchRooms,
    fetchRoomGroups,
    // 본체의 navigateDate 최적화 로직에서 직접 조작하는 ref. Phase D/I 이후 정리 가능.
    prevDateRef,
    reservationsRef,
    nextDayRef,
    // C-2: 파생 상태
    roomInfoMap,
    roomMemoMap,
    saveRoomMemo,
    activeRoomEntries,
    nextDayRoomMap,
    roomGroupMap,
    assignedRooms,
    unassigned,
    partyOnly,
    unstableGuests,
    cancelledGuests,
    nextDayUnassigned,
    nextDayPartyOnly,
    findReservation,
    buildingGroups,
  };
}
