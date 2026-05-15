import { useCallback, useMemo, useState } from 'react';
import type { Dayjs } from 'dayjs';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { reservationsAPI, roomsAPI, templatesAPI } from '../../../services/api';
import { queryKeys } from '@/lib/queryKeys';
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
 * Phase 2–5: rooms / reservations / nextDayReservations / templateLabels / roomGroups
 *            → useQuery. setter/fetch shims 제거 완료.
 */
export function useReservationsData(selectedDate: Dayjs) {
  const qc = useQueryClient();

  const dateStr = selectedDate.format('YYYY-MM-DD');
  const nextDateStr = selectedDate.add(1, 'day').format('YYYY-MM-DD');

  // ===== useQuery: 당일 예약 =====
  const reservationsQuery = useQuery<Reservation[]>({
    queryKey: queryKeys.reservations.list(dateStr),
    queryFn: () =>
      reservationsAPI
        .getAll({ date: dateStr, limit: 200 })
        .then((res) => filterActive(res.data.items ?? res.data, dateStr)),
    staleTime: 30_000,
  });

  // ===== useQuery: 익일 예약 =====
  const nextDayQuery = useQuery<Reservation[]>({
    queryKey: queryKeys.reservations.list(nextDateStr),
    queryFn: () =>
      reservationsAPI
        .getAll({ date: nextDateStr, limit: 200 })
        .then((res) => filterActive(res.data.items ?? res.data, nextDateStr)),
    staleTime: 30_000,
  });

  // ===== useQuery: 객실 목록 (비활성 포함 — 배정 페이지에서 오버레이로 표시) =====
  const roomsQuery = useQuery<any[]>({
    queryKey: queryKeys.rooms.list(),
    queryFn: () => roomsAPI.getAll({ include_inactive: true }).then((res) => res.data),
    staleTime: 300_000,
  });

  // ===== useQuery: 객실 그룹 =====
  const roomGroupsQuery = useQuery<RoomGroup[]>({
    queryKey: queryKeys.rooms.groups(),
    queryFn: () => roomsAPI.getGroups().then((res) => res.data),
    staleTime: 300_000,
  });

  // ===== useQuery: 템플릿 라벨 =====
  const templateLabelsQuery = useQuery<TemplateLabel[]>({
    queryKey: queryKeys.templates.labels(),
    queryFn: () => templatesAPI.getLabels().then((res) => res.data),
    staleTime: 300_000,
  });

  // Unwrap query data with safe defaults
  const reservations: Reservation[] = reservationsQuery.data ?? [];
  const nextDayReservations: Reservation[] = nextDayQuery.data ?? [];
  const rooms: any[] = roomsQuery.data ?? [];
  const roomGroups: RoomGroup[] = roomGroupsQuery.data ?? [];
  const templateLabels: TemplateLabel[] = templateLabelsQuery.data ?? [];

  // loading: mirrors original behavior (true while reservation fetch in-flight)
  const loading = reservationsQuery.isFetching;

  // ===== sectionOverrides: purely client-side, stays useState =====
  const [sectionOverrides, setSectionOverrides] = useState<Record<number, 'party' | 'unassigned'>>({});

  // ===== 파생 상태 (inputs come from useQuery) =====

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

  const saveRoomMemoMutation = useMutation({
    mutationFn: ({ roomId, memo }: { roomId: number; memo: string }) =>
      roomsAPI.update(roomId, { room_memo: memo }),
    onMutate: async ({ roomId, memo }) => {
      await qc.cancelQueries({ queryKey: queryKeys.rooms.list() });
      const previous = qc.getQueryData<any[]>(queryKeys.rooms.list());
      qc.setQueryData<any[]>(queryKeys.rooms.list(), (prev) =>
        (prev ?? []).map((r) => (r.id === roomId ? { ...r, room_memo: memo } : r))
      );
      return { previous };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous !== undefined) {
        qc.setQueryData(queryKeys.rooms.list(), ctx.previous);
      }
      toast.error('메모 저장 실패');
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: queryKeys.rooms.list() });
    },
  });

  const saveRoomMemo = useCallback(
    (roomId: number, memo: string): Promise<void> =>
      saveRoomMemoMutation.mutateAsync({ roomId, memo }).then(() => undefined),
    [saveRoomMemoMutation],
  );

  const activeRoomEntries = useMemo(() => {
    return rooms.map((room) => ({
      room_id: room.id as number,
      room_number: room.room_number as string,
      isDormitory: room.dormitory || false,
      bed_capacity: room.bed_capacity || 1,
      building_id: room.building_id as number | null,
      building_name: room.building_name as string | null,
      isActive: room.active !== false,
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
    reservations,
    sectionOverrides, setSectionOverrides,
    nextDayReservations,
    rooms,
    templateLabels,
    roomGroups,
    loading,
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
