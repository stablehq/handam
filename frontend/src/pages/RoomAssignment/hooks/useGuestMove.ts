import { useCallback, useState } from 'react';
import type { Dayjs } from 'dayjs';
import dayjs from 'dayjs';
import { toast } from 'sonner';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { reservationsAPI } from '../../../services/api';
import { queryKeys } from '@/lib/queryKeys';
import type { Reservation, SmsAssignment } from '../types';
import type { UndoEntry } from './useUndoStack';
import type { RoomEntry } from '../components/RoomRow';

declare global {
  interface Window {
    __diagAction?: string;
  }
}

// Multi-night detection: covers both naver-detected groups (stay_group_id) and
// single-record stays extended via the new model (end_date - check_in_date > 1).
function isMultiNight(res: { stay_group_id?: string | null; check_in_date?: string | null; check_out_date?: string | null }): boolean {
  if (res.stay_group_id) return true;
  if (res.check_in_date && res.check_out_date) {
    return dayjs(res.check_out_date).diff(dayjs(res.check_in_date), 'day') > 1;
  }
  return false;
}

type SectionOverrides = Record<number, 'party' | 'unassigned'>;
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

// ── Cache helpers ────────────────────────────────────────────────────────────

/** 두 캐시(당일 + 익일)에서 특정 예약을 immutable 갱신 */
function updateReservationInCaches(
  qc: ReturnType<typeof useQueryClient>,
  dateStr: string,
  nextDateStr: string,
  resId: number,
  updater: (r: Reservation) => Reservation,
) {
  for (const key of [
    queryKeys.reservations.list(dateStr),
    queryKeys.reservations.list(nextDateStr),
  ]) {
    qc.setQueryData<Reservation[]>(key, (prev) =>
      prev?.map((r) => (r.id === resId ? updater(r) : r)),
    );
  }
}

/** 두 캐시 모두 스냅샷 후 cancelQueries */
async function snapshotAndCancel(
  qc: ReturnType<typeof useQueryClient>,
  dateStr: string,
  nextDateStr: string,
) {
  await Promise.all([
    qc.cancelQueries({ queryKey: queryKeys.reservations.list(dateStr) }),
    qc.cancelQueries({ queryKey: queryKeys.reservations.list(nextDateStr) }),
  ]);
  return {
    prevToday: qc.getQueryData<Reservation[]>(queryKeys.reservations.list(dateStr)),
    prevNext: qc.getQueryData<Reservation[]>(queryKeys.reservations.list(nextDateStr)),
  };
}

function restoreSnapshots(
  qc: ReturnType<typeof useQueryClient>,
  ctx: { prevToday?: Reservation[]; prevNext?: Reservation[]; dateStr: string; nextDateStr: string } | undefined,
) {
  if (!ctx) return;
  if (ctx.prevToday)
    qc.setQueryData(queryKeys.reservations.list(ctx.dateStr), ctx.prevToday);
  if (ctx.prevNext)
    qc.setQueryData(queryKeys.reservations.list(ctx.nextDateStr), ctx.prevNext);
}

function invalidateBoth(
  qc: ReturnType<typeof useQueryClient>,
  dateStr: string,
  nextDateStr: string,
) {
  qc.invalidateQueries({ queryKey: queryKeys.reservations.list(dateStr) });
  qc.invalidateQueries({ queryKey: queryKeys.reservations.list(nextDateStr) });
}

/**
 * 게스트 이동 통합 — 객실 배정 / 미배정 / 파티만 + 연박 처리 + push_out + undo 푸시.
 *
 * Phase 3a: useMutation + onMutate/onError/onSettled 패턴으로 전환.
 * 외부 인터페이스(handleDropOnRoom/Pool/Party, onDropZoneClick) 유지.
 */
export function useGuestMove({
  reservations,
  nextDayReservations,
  selectedDate,
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
  const qc = useQueryClient();
  const [recentlyMovedId, setRecentlyMovedId] = useState<number | null>(null);

  // ── Flow A: assignRoom ────────────────────────────────────────────────────

  const assignRoomMutation = useMutation({
    mutationFn: (vars: {
      resId: number;
      roomId: number;
      roomNumber: string;
      applySubsequent: boolean;
      applyGroup: boolean;
      effectiveDateStr: string;
      isNextDay: boolean;
      dateStr: string;
      nextDateStr: string;
    }) =>
      reservationsAPI
        .assignRoom(vars.resId, {
          room_id: vars.roomId,
          date: vars.effectiveDateStr,
          apply_subsequent: vars.applySubsequent,
          apply_group: vars.applyGroup,
        })
        .then((r) => r.data),

    onMutate: async (vars) => {
      const { prevToday, prevNext } = await snapshotAndCancel(
        qc,
        vars.dateStr,
        vars.nextDateStr,
      );

      // Optimistic: move to new room + auto-add room_info SMS assignment
      const targetKey = queryKeys.reservations.list(
        vars.isNextDay ? vars.nextDateStr : vars.dateStr,
      );
      qc.setQueryData<Reservation[]>(targetKey, (prev) =>
        prev?.map((r) => {
          if (r.id !== vars.resId) return r;
          const hasRoomInfo = r.sms_assignments?.some(
            (a) => a.template_key === 'room_info',
          );
          const updatedAssignments = hasRoomInfo
            ? r.sms_assignments
            : [
                ...(r.sms_assignments || []),
                {
                  id: 0,
                  reservation_id: r.id,
                  template_key: 'room_info',
                  assigned_at: new Date().toISOString(),
                  sent_at: null,
                  assigned_by: 'auto',
                  date: vars.effectiveDateStr,
                } as SmsAssignment,
              ];
          return {
            ...r,
            room_id: vars.roomId,
            room_number: vars.roomNumber,
            sms_assignments: updatedAssignments,
          };
        }),
      );

      return { prevToday, prevNext, dateStr: vars.dateStr, nextDateStr: vars.nextDateStr };
    },

    onError: (err: any, _vars, ctx) => {
      restoreSnapshots(qc, ctx);
      toast.error(err?.response?.data?.detail || '객실 배정에 실패했습니다.');
    },

    onSettled: (_data, _err, vars, ctx) => {
      if (!ctx) return;
      invalidateBoth(qc, vars.dateStr, vars.nextDateStr);
    },
  });

  /** 실제 객실 배정 — 낙관적 업데이트 + API + push_out + undo 푸시 */
  const doAssignRoom = useCallback(
    async (
      resId: number,
      roomId: number,
      roomNumber: string,
      applySubsequent: boolean,
      applyGroup: boolean = false,
      targetDate?: Dayjs,
    ) => {
      const effectiveDate = targetDate || selectedDate;
      const isNextDay =
        targetDate != null && !targetDate.isSame(selectedDate, 'day');
      const dateStr = selectedDate.format('YYYY-MM-DD');
      const nextDateStr = selectedDate.add(1, 'day').format('YYYY-MM-DD');

      // Snapshot prev state for undo (from cache, before mutation fires)
      const source = isNextDay ? nextDayReservations : reservations;
      const prev = source.find((r) => r.id === resId);

      if (!isNextDay) {
        setSectionOverrides((p) => {
          const next = { ...p };
          delete next[resId];
          return next;
        });
      }

      window.__diagAction = `drag_guest_to_room:res=${resId},room=${roomNumber}`;

      try {
        const result = await assignRoomMutation.mutateAsync({
          resId,
          roomId,
          roomNumber,
          applySubsequent,
          applyGroup,
          effectiveDateStr: effectiveDate.format('YYYY-MM-DD'),
          isNextDay,
          dateStr,
          nextDateStr,
        });

        toast.success(`${roomNumber} 배정 완료`);

        if (prev) {
          const overrideSec = !isNextDay ? sectionOverrides[resId] : undefined;
          const computedPrevSection = prev.room_id
            ? 'room'
            : (overrideSec ??
                (prev.section && prev.section !== 'room'
                  ? prev.section
                  : 'unassigned'));
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
      } catch {
        // onError already handled toast + rollback
      }
    },
    [
      reservations,
      nextDayReservations,
      selectedDate,
      setSectionOverrides,
      sectionOverrides,
      pushUndo,
      assignRoomMutation,
    ],
  );

  // ── Flow B: date-cross drop ───────────────────────────────────────────────

  const dateCrossMutation = useMutation({
    mutationFn: async (vars: {
      resId: number;
      roomId: number;
      roomNumber: string;
      destDateStr: string;
      destCheckout: string;
      dateStr: string;
      nextDateStr: string;
    }) => {
      await reservationsAPI.update(vars.resId, {
        check_in_date: vars.destDateStr,
        check_out_date: vars.destCheckout,
      });
      await reservationsAPI.assignRoom(vars.resId, {
        room_id: vars.roomId,
        date: vars.destDateStr,
        apply_subsequent: false,
      });
    },

    onMutate: async (vars) => {
      const { prevToday, prevNext } = await snapshotAndCancel(
        qc,
        vars.dateStr,
        vars.nextDateStr,
      );
      return { prevToday, prevNext, dateStr: vars.dateStr, nextDateStr: vars.nextDateStr };
    },

    onError: (_err: any, vars, ctx) => {
      restoreSnapshots(qc, ctx);
      toast.error(_err?.response?.data?.detail || '날짜 이동 실패');
    },

    onSettled: (_data, _err, vars) => {
      invalidateBoth(qc, vars.dateStr, vars.nextDateStr);
    },
  });

  // ── Flow B-2: date-cross drop to pool/party (no room target) ──────────────
  // dnd-kit cross-day 시나리오: 오늘 객실 → 내일 미배정/파티만 (또는 그 반대).
  // 1) reservation.update(check_in_date, check_out_date) → backend on_dates_changed
  //    → _reconcile_dates 가 범위 밖 RA 자동 삭제 (assignRoom(null) 별도 불필요).
  // 2) reservation.update(section)
  const dateCrossPoolPartyMutation = useMutation({
    mutationFn: async (vars: {
      resId: number;
      destDateStr: string;
      destCheckout: string;
      targetSection: 'unassigned' | 'party';
      dateStr: string;
      nextDateStr: string;
    }) => {
      window.__diagAction =
        vars.targetSection === 'party'
          ? 'drag_cross_day_to_party'
          : 'drag_cross_day_to_pool';
      // 1. 체크인/아웃 변경 — backend lifecycle 이 범위 밖 RA 자동 삭제
      await reservationsAPI.update(vars.resId, {
        check_in_date: vars.destDateStr,
        check_out_date: vars.destCheckout,
      });
      // 2. section 변경
      await reservationsAPI.update(vars.resId, { section: vars.targetSection });
    },

    onMutate: async (vars) => {
      const { prevToday, prevNext } = await snapshotAndCancel(
        qc,
        vars.dateStr,
        vars.nextDateStr,
      );
      return { prevToday, prevNext, dateStr: vars.dateStr, nextDateStr: vars.nextDateStr };
    },

    onError: (_err: any, _vars, ctx) => {
      restoreSnapshots(qc, ctx);
      toast.error(_err?.response?.data?.detail || '날짜 + 섹션 이동 실패');
    },

    onSettled: (_data, _err, vars) => {
      invalidateBoth(qc, vars.dateStr, vars.nextDateStr);
    },
  });

  // ── Flow C+D: pool/party drop (with existing room assignment) ─────────────

  const unassignRoomMutation = useMutation({
    mutationFn: async (vars: {
      resId: number;
      effectiveDateStr: string;
      targetSection: 'unassigned' | 'party';
      dateStr: string;
      nextDateStr: string;
    }) => {
      window.__diagAction =
        vars.targetSection === 'party' ? 'drop_on_party' : 'drop_on_pool';
      await reservationsAPI.assignRoom(vars.resId, {
        room_id: null,
        date: vars.effectiveDateStr,
        apply_subsequent: true,
      });
      await reservationsAPI.update(vars.resId, { section: vars.targetSection });
    },

    onMutate: async (vars) => {
      const { prevToday, prevNext } = await snapshotAndCancel(
        qc,
        vars.dateStr,
        vars.nextDateStr,
      );

      updateReservationInCaches(
        qc,
        vars.dateStr,
        vars.nextDateStr,
        vars.resId,
        (r) => {
          const filtered =
            r.sms_assignments?.filter(
              (a) => !(a.template_key === 'room_info' && !a.sent_at),
            ) || [];
          return {
            ...r,
            room_id: null,
            room_number: null,
            section: vars.targetSection,
            sms_assignments: filtered,
          };
        },
      );

      return { prevToday, prevNext, dateStr: vars.dateStr, nextDateStr: vars.nextDateStr };
    },

    onError: (_err: any, _vars, ctx) => {
      restoreSnapshots(qc, ctx);
      toast.error('이동 실패');
    },

    onSettled: (_data, _err, vars) => {
      invalidateBoth(qc, vars.dateStr, vars.nextDateStr);
    },
  });

  // ── Flow C+D part 2: section-only update (no room assignment to clear) ────

  const sectionUpdateMutation = useMutation({
    mutationFn: (vars: {
      resId: number;
      targetSection: 'unassigned' | 'party';
      dateStr: string;
      nextDateStr: string;
    }) => reservationsAPI.update(vars.resId, { section: vars.targetSection }),

    onMutate: async (vars) => {
      const { prevToday, prevNext } = await snapshotAndCancel(
        qc,
        vars.dateStr,
        vars.nextDateStr,
      );
      return { prevToday, prevNext, dateStr: vars.dateStr, nextDateStr: vars.nextDateStr };
    },

    onError: (_err, vars, ctx) => {
      restoreSnapshots(qc, ctx);
      // Revert sectionOverrides on error (non-nextDay path)
      setSectionOverrides((prev) => {
        const next = { ...prev };
        delete next[vars.resId];
        return next;
      });
      toast.error('이동 실패');
    },

    onSettled: (_data, _err, vars) => {
      invalidateBoth(qc, vars.dateStr, vars.nextDateStr);
    },
  });

  // ── handleDropOnRoom ──────────────────────────────────────────────────────

  const handleDropOnRoom = useCallback(
    (resId: number, roomId: number, dropTargetDate?: Dayjs) => {
      const found = findReservation(resId);
      if (!found) return;
      const { res, isNextDay: sourceIsNextDay } = found;
      const targetDate = dropTargetDate || selectedDate;
      const dropIsNextDay = !targetDate.isSame(selectedDate, 'day');

      // 중복 체크
      const currentList = dropIsNextDay
        ? nextDayRoomMap.get(roomId) || []
        : assignedRooms.get(roomId) || [];
      if (currentList.some((r) => r.id === resId)) return;

      const entry = activeRoomEntries.find((e) => e.room_id === roomId);

      // 날짜 이동: 예약 날짜 + 객실 변경
      if (sourceIsNextDay !== dropIsNextDay) {
        if (isMultiNight(res)) {
          toast.warning(
            '연박 그룹에 속한 게스트는 날짜 이동이 불가합니다. 연박 해제 후 이동하세요.',
          );
          return;
        }

        const dateStr = selectedDate.format('YYYY-MM-DD');
        const nextDateStr = selectedDate.add(1, 'day').format('YYYY-MM-DD');
        const destDate = dropIsNextDay ? selectedDate.add(1, 'day') : selectedDate;
        const destDateStr = destDate.format('YYYY-MM-DD');
        const destCheckout = destDate.add(1, 'day').format('YYYY-MM-DD');
        const roomNumber = entry?.room_number || '';

        // Optimistic: move across lists immediately (UI feedback)
        const sourceKey = queryKeys.reservations.list(sourceIsNextDay ? nextDateStr : dateStr);
        const targetKey = queryKeys.reservations.list(dropIsNextDay ? nextDateStr : dateStr);
        qc.setQueryData<Reservation[]>(sourceKey, (prev) => prev?.filter((r) => r.id !== resId));
        qc.setQueryData<Reservation[]>(targetKey, (prev) => [
          ...(prev ?? []),
          {
            ...res,
            room_id: roomId,
            room_number: roomNumber,
            check_in_date: destDateStr,
            check_out_date: destCheckout,
            section: 'room',
          },
        ]);

        dateCrossMutation.mutate(
          {
            resId,
            roomId,
            roomNumber,
            destDateStr,
            destCheckout,
            dateStr,
            nextDateStr,
          },
          {
            onSuccess: () => {
              toast.success(`${res.customer_name} → ${roomNumber} (${destDateStr})`);
            },
          },
        );
        return;
      }

      const roomNumber = entry?.room_number || '';

      // 연박자: 적용 범위 (single/subsequent) 모달 띄움
      if (res.is_long_stay) {
        setMultiNightConfirm({
          open: true,
          resId,
          resName: res.customer_name,
          roomId,
          roomNumber,
          onConfirm: (applySubsequent) => {
            setMultiNightConfirm(null);
            doAssignRoom(
              resId,
              roomId,
              roomNumber,
              applySubsequent,
              !!res.stay_group_id && applySubsequent, // applyGroup: only for naver-detected groups
              targetDate,
            );
          },
        });
        return;
      }

      doAssignRoom(resId, roomId, roomNumber, true, false, targetDate);
    },
    [
      findReservation,
      selectedDate,
      nextDayRoomMap,
      assignedRooms,
      activeRoomEntries,
      qc,
      dateCrossMutation,
      setMultiNightConfirm,
      doAssignRoom,
    ],
  );

  // ── handleDropOnZoneCrossDay ──────────────────────────────────────────────
  // cross-day + zone 이동: 오늘 객실 → 내일 미배정/파티만 (또는 그 반대).
  // 1) reservation.update(check_in_date, check_out_date) — backend가 범위 밖 RA 자동 삭제
  // 2) reservation.update(section) — section 변경
  const handleDropOnZoneCrossDay = useCallback(
    (resId: number, destDate: Dayjs, targetSection: 'unassigned' | 'party') => {
      const found = findReservation(resId);
      if (!found) return;
      if (isMultiNight(found.res)) {
        toast.warning(
          '연박 그룹에 속한 게스트는 날짜 이동이 불가합니다. 연박 해제 후 이동하세요.',
        );
        return;
      }
      const destDateStr = destDate.format('YYYY-MM-DD');
      const destCheckout = destDate.add(1, 'day').format('YYYY-MM-DD');
      const dateStr = selectedDate.format('YYYY-MM-DD');
      const nextDateStr = selectedDate.add(1, 'day').format('YYYY-MM-DD');
      setRecentlyMovedId(resId);

      dateCrossPoolPartyMutation.mutate(
        {
          resId,
          destDateStr,
          destCheckout,
          targetSection,
          dateStr,
          nextDateStr,
        },
        {
          onSuccess: () => {
            toast.success(
              targetSection === 'party'
                ? `${found.res.customer_name} → 파티만 (${destDateStr})`
                : `${found.res.customer_name} → 미배정 (${destDateStr})`,
            );
          },
        },
      );
    },
    [findReservation, selectedDate, dateCrossPoolPartyMutation],
  );

  // ── handleDropOnPool ──────────────────────────────────────────────────────

  const handleDropOnPool = useCallback(
    async (resId: number, targetDate?: Dayjs) => {
      const found = findReservation(resId);
      if (!found) return;
      const { res, isNextDay } = found;

      const effectiveDate =
        targetDate || (isNextDay ? selectedDate.add(1, 'day') : selectedDate);
      setRecentlyMovedId(resId);
      const effectiveSection = sectionOverrides[resId] ?? res.section;
      if (!res.room_id && effectiveSection === 'unassigned') return;

      const dateStr = selectedDate.format('YYYY-MM-DD');
      const nextDateStr = selectedDate.add(1, 'day').format('YYYY-MM-DD');

      if (res.room_id) {
        if (!isNextDay)
          setSectionOverrides((prev) => ({ ...prev, [resId]: 'unassigned' }));

        try {
          await unassignRoomMutation.mutateAsync({
            resId,
            effectiveDateStr: effectiveDate.format('YYYY-MM-DD'),
            targetSection: 'unassigned',
            dateStr,
            nextDateStr,
          });
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
        } catch {
          // onError already handled rollback + toast
          if (!isNextDay)
            setSectionOverrides((prev) => {
              const next = { ...prev };
              delete next[resId];
              return next;
            });
        }
      } else {
        // No room assigned — just update section
        if (isNextDay) {
          qc.setQueryData<Reservation[]>(queryKeys.reservations.list(nextDateStr), (prev) =>
            prev?.map((r) => (r.id === resId ? { ...r, section: 'unassigned' } : r)),
          );
        } else {
          setSectionOverrides((prev) => ({ ...prev, [resId]: 'unassigned' }));
        }
        toast.success('미배정으로 이동');

        try {
          await sectionUpdateMutation.mutateAsync({
            resId,
            targetSection: 'unassigned',
            dateStr,
            nextDateStr,
          });
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
        } catch {
          // onError already handled rollback + toast
        }
      }
    },
    [
      findReservation,
      selectedDate,
      sectionOverrides,
      qc,
      setSectionOverrides,
      unassignRoomMutation,
      sectionUpdateMutation,
      pushUndo,
    ],
  );

  // ── handleDropOnParty ─────────────────────────────────────────────────────

  const handleDropOnParty = useCallback(
    async (resId: number, targetDate?: Dayjs) => {
      const found = findReservation(resId);
      if (!found) return;
      const { res: guest, isNextDay } = found;

      const effectiveDate =
        targetDate || (isNextDay ? selectedDate.add(1, 'day') : selectedDate);
      setRecentlyMovedId(resId);
      const effectiveSection = sectionOverrides[resId] ?? guest.section;
      if (!guest.room_id && effectiveSection === 'party') return;

      const dateStr = selectedDate.format('YYYY-MM-DD');
      const nextDateStr = selectedDate.add(1, 'day').format('YYYY-MM-DD');

      if (guest.room_id) {
        if (!isNextDay)
          setSectionOverrides((prev) => ({ ...prev, [resId]: 'party' }));

        try {
          await unassignRoomMutation.mutateAsync({
            resId,
            effectiveDateStr: effectiveDate.format('YYYY-MM-DD'),
            targetSection: 'party',
            dateStr,
            nextDateStr,
          });
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
        } catch {
          // onError already handled rollback + toast
          if (!isNextDay)
            setSectionOverrides((prev) => {
              const next = { ...prev };
              delete next[resId];
              return next;
            });
        }
      } else {
        // No room assigned — just update section
        if (isNextDay) {
          qc.setQueryData<Reservation[]>(queryKeys.reservations.list(nextDateStr), (prev) =>
            prev?.map((r) => (r.id === resId ? { ...r, section: 'party' } : r)),
          );
        } else {
          setSectionOverrides((prev) => ({ ...prev, [resId]: 'party' }));
        }
        toast.success('파티만으로 이동');

        try {
          await sectionUpdateMutation.mutateAsync({
            resId,
            targetSection: 'party',
            dateStr,
            nextDateStr,
          });
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
        } catch {
          // onError already handled rollback + toast
        }
      }
    },
    [
      findReservation,
      selectedDate,
      sectionOverrides,
      qc,
      setSectionOverrides,
      unassignRoomMutation,
      sectionUpdateMutation,
      pushUndo,
    ],
  );

  // ── onDropZoneClick ───────────────────────────────────────────────────────

  const onDropZoneClick = useCallback(
    (e: React.MouseEvent) => {
      if (selectedGuestIds.size === 0) return;

      const interactive = (e.target as HTMLElement).closest(
        'button, a, input, select, textarea, [role="button"], [data-interactive]',
      );
      if (interactive) return;

      const target = (e.target as HTMLElement).closest<HTMLElement>('[data-drop-zone]');
      if (!target) return;
      const zoneId = target.dataset.dropZone || '';

      const ids = [...selectedGuestIds];
      setSelectedGuestIds(new Set());

      if (zoneId.startsWith('next-room-')) {
        const roomId = Number(zoneId.replace('next-room-', ''));
        const targetDate = selectedDate.add(1, 'day');
        const hasCrossDay = ids.some((id) => {
          const f = findReservation(id);
          return f && !f.isNextDay;
        });
        if (hasCrossDay) {
          showConfirm(
            '날짜 이동 확인',
            '오늘 체크인 게스트를 내일 방에 배정하시겠습니까?\n예약 날짜가 내일로 변경됩니다.',
            () => {
              ids.forEach((id) => handleDropOnRoom(id, roomId, targetDate));
            },
          );
          return;
        }
        ids.forEach((id) => handleDropOnRoom(id, roomId, targetDate));
      } else if (zoneId.startsWith('room-')) {
        const roomId = Number(zoneId.replace('room-', ''));
        const hasCrossDay = ids.some((id) => {
          const f = findReservation(id);
          return f && f.isNextDay;
        });
        if (hasCrossDay) {
          showConfirm(
            '날짜 이동 확인',
            '내일 체크인 게스트를 오늘 방에 배정하시겠습니까?\n예약 날짜가 오늘로 변경됩니다.',
            () => {
              ids.forEach((id) => handleDropOnRoom(id, roomId));
            },
          );
          return;
        }
        ids.forEach((id) => handleDropOnRoom(id, roomId));
      } else if (zoneId === 'next-pool') {
        ids.forEach((id) => handleDropOnPool(id, selectedDate.add(1, 'day')));
      } else if (zoneId === 'next-party') {
        ids.forEach((id) => handleDropOnParty(id, selectedDate.add(1, 'day')));
      } else if (zoneId === 'pool') {
        ids.forEach((id) => handleDropOnPool(id));
      } else if (zoneId === 'party') {
        ids.forEach((id) => handleDropOnParty(id));
      }
    },
    [
      selectedGuestIds,
      setSelectedGuestIds,
      selectedDate,
      findReservation,
      showConfirm,
      handleDropOnRoom,
      handleDropOnPool,
      handleDropOnParty,
    ],
  );

  return {
    recentlyMovedId,
    handleDropOnRoom,
    handleDropOnPool,
    handleDropOnParty,
    handleDropOnZoneCrossDay,
    onDropZoneClick,
  };
}
