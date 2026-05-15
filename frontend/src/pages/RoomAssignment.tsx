import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { createPortal } from 'react-dom';
import api, { reservationsAPI, roomsAPI, templatesAPI, smsAssignmentsAPI, settingsAPI } from '../services/api';
import { normalizeUtcString } from '../lib/utils';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/queryKeys';
import { useTenantStore } from '@/stores/tenant-store';
import dayjs, { Dayjs } from 'dayjs';
import { toast } from 'sonner';
import { Tooltip } from '@/components/ui/tooltip';
import { Modal, ModalHeader, ModalBody, ModalFooter } from '@/components/ui/modal';
import { TextInput } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import {
  Trash2,
  ChevronLeft,
  ChevronRight,
  Plus,
  UserRoundPlus,
  Link2,
  Circle,
  Minus,
  ChevronsLeft,
  ChevronsRight,
  Menu,
  Phone,
  Undo2,
} from 'lucide-react';
import { useIsMobile } from '../hooks/use-mobile';
import GuestContextMenu from '../components/GuestContextMenu';
import TableSettingsModal from '../components/TableSettingsModal';
import type { SmsAssignment, Reservation } from './RoomAssignment/types';
import { formatGenderPeople, formatGuestSuffix } from './RoomAssignment/utils/reservationFormat';
import { useConfirmDialog } from './RoomAssignment/hooks/useConfirmDialog';
import { useHoverZone } from './RoomAssignment/hooks/useHoverZone';
import { useCollapsibleBuildings } from './RoomAssignment/hooks/useCollapsibleBuildings';
import { useAutoAssign } from './RoomAssignment/hooks/useAutoAssign';
import { useCampaignSend } from './RoomAssignment/hooks/useCampaignSend';
import { useHighlightColors } from './RoomAssignment/hooks/useHighlightColors';
import { useStayGroup } from './RoomAssignment/hooks/useStayGroup';
import { useReservationsData, filterActive } from './RoomAssignment/hooks/useReservationsData';
import { useColumnResize } from './RoomAssignment/hooks/useColumnResize';
import { useGuestSelection } from './RoomAssignment/hooks/useGuestSelection';
import { useContextMenu } from './RoomAssignment/hooks/useContextMenu';
import { useSmsAssignment } from './RoomAssignment/hooks/useSmsAssignment';
import { GuestRow } from './RoomAssignment/components/shared/GuestRow';
import { CompactGuestCell } from './RoomAssignment/components/shared/CompactGuestCell';
import { UnassignedZone } from './RoomAssignment/components/zones/UnassignedZone';
import { PartyZone } from './RoomAssignment/components/zones/PartyZone';
import { UnstableZone } from './RoomAssignment/components/zones/UnstableZone';
import { CancelledZone } from './RoomAssignment/components/zones/CancelledZone';
import { RoomRow, type RoomEntry } from './RoomAssignment/components/RoomRow';
import { BuildingGroup } from './RoomAssignment/components/BuildingGroup';
import { useReservationForm } from './RoomAssignment/hooks/useReservationForm';
import { useUndoStack } from './RoomAssignment/hooks/useUndoStack';
import { useSseInvalidator } from '../hooks/useSseInvalidator';
import { useGuestMove } from './RoomAssignment/hooks/useGuestMove';
import { PageHeader } from './RoomAssignment/components/PageHeader';
import { SummaryCards } from './RoomAssignment/components/SummaryCards';
import { CampaignToolbar } from './RoomAssignment/components/CampaignToolbar';
import { RoomMemoEditor } from './RoomAssignment/components/RoomMemoEditor';
import { SmsCell } from './RoomAssignment/components/SmsCell';
import { InlineInput } from './RoomAssignment/components/InlineInput';
import { ConfirmDialog } from './RoomAssignment/modals/ConfirmDialog';
import { MultiNightConfirmModal } from './RoomAssignment/modals/MultiNightConfirmModal';
import { AutoAssignConfirmModal } from './RoomAssignment/modals/AutoAssignConfirmModal';
import { DateChangeModal } from './RoomAssignment/modals/DateChangeModal';
import { StayGroupChainModal } from './RoomAssignment/modals/StayGroupChainModal';
import { SendConfirmModal } from './RoomAssignment/modals/SendConfirmModal';
import { ReservationFormModal } from './RoomAssignment/modals/ReservationFormModal';
import { ExtendStayConflictModal } from './RoomAssignment/modals/ExtendStayConflictModal';
import { QuickMenuBar } from './RoomAssignment/components/QuickMenuBar';

import {
  PRESET_HIGHLIGHT_STYLES,
  isCustomHexColor,
  getCustomBgStyle,
  getCustomTextClass,
} from '@/lib/highlight-colors';

// RoomMemoEditor 는 RoomAssignment/components/RoomMemoEditor.tsx 로 분리 (Phase 2).

// 데이터 shape 타입은 RoomAssignment/types.ts 로 분리 (Phase 1 단순 분리).
// SmsAssignment, Reservation, ConfirmState 는 파일 상단 import 참조.



// formatGenderPeople, formatGuestSuffix 는 RoomAssignment/utils/reservationFormat.ts 로 분리 (Phase A-1).

// SmsCell 은 RoomAssignment/components/SmsCell.tsx 로 분리 (Phase 2).

// ConfirmState 는 RoomAssignment/types.ts 로 이동 (Phase 1).

const RoomAssignment = () => {
  const { tenants, currentTenantId } = useTenantStore();
  const currentTenant = tenants.find(t => String(t.id) === currentTenantId);
  const hasUnstable = currentTenant?.has_unstable ?? false;

  const qc = useQueryClient();
  const [selectedDate, setSelectedDate] = useState<Dayjs>(dayjs());
  const {
    reservations,
    sectionOverrides, setSectionOverrides,
    nextDayReservations,
    rooms,
    templateLabels,
    roomGroups,
    loading,
    roomInfoMap, roomMemoMap, saveRoomMemo,
    activeRoomEntries, nextDayRoomMap, roomGroupMap,
    assignedRooms,
    unassigned: rawUnassigned,
    partyOnly: rawPartyOnly,
    unstableGuests, cancelledGuests,
    nextDayUnassigned, nextDayPartyOnly,
    findReservation,
    buildingGroups,
  } = useReservationsData(selectedDate);

  // ===== Inline mutations (Phase 3b) =====
  const _dateStr = selectedDate.format('YYYY-MM-DD');
  const _nextDateStr = selectedDate.add(1, 'day').format('YYYY-MM-DD');
  const _invalidateReservations = useCallback(() => {
    qc.invalidateQueries({ queryKey: queryKeys.reservations.list(_dateStr) });
    qc.invalidateQueries({ queryKey: queryKeys.reservations.list(_nextDateStr) });
  }, [qc, _dateStr, _nextDateStr]);

  // Color set: batch update highlight_color for selected ids
  const setColorMutation = useMutation({
    mutationFn: ({ ids, color }: { ids: number[]; color: string | null }) =>
      Promise.all(ids.map(id => reservationsAPI.update(id, { highlight_color: color }))),
    onError: () => toast.error('색상 저장 실패'),
    // Invalidation handled by caller after loop; onSettled omitted to avoid N invalidations.
  });

  // Copy to unstable: batch updateDailyInfo unstable_party=true
  const copyToUnstableMutation = useMutation({
    mutationFn: ({ ids, dateStr }: { ids: number[]; dateStr: string }) =>
      Promise.all(ids.map(id => reservationsAPI.updateDailyInfo(id, { date: dateStr, unstable_party: true }))),
    onError: () => toast.error('복사 실패'),
  });

  // Remove from unstable: batch updateDailyInfo unstable_party=false
  const removeFromUnstableMutation = useMutation({
    mutationFn: ({ ids, dateStr }: { ids: number[]; dateStr: string }) =>
      Promise.all(ids.map(id => reservationsAPI.updateDailyInfo(id, { date: dateStr, unstable_party: false }))),
    onError: () => toast.error('제거 실패'),
  });

  // Extend stay
  const extendStayMutation = useMutation({
    mutationFn: ({ resId, roomId }: { resId: number; roomId: number | null }) =>
      api.post(`/api/reservations/${resId}/extend-stay`, { room_id: roomId }),
    onError: (err: any) => toast.error(err?.response?.data?.detail || '연박추가 실패'),
    onSettled: () => _invalidateReservations(),
  });

  // Cancel extend stay
  const cancelExtendStayMutation = useMutation({
    mutationFn: (resId: number) => api.delete(`/api/reservations/${resId}/extend-stay`),
    onSuccess: () => toast.success('수동연박 취소 완료'),
    onError: (err: any) => toast.error(err?.response?.data?.detail || '연박취소 실패'),
    onSettled: () => _invalidateReservations(),
  });

  // Assign extend-stay room (수동 배정은 항상 공동 점유 허용)
  const assignExtendStayRoomMutation = useMutation({
    mutationFn: ({
      newResId, roomId, date,
    }: { newResId: number; roomId: number; date: string }) =>
      api.post(`/api/reservations/${newResId}/extend-stay/assign-room`, {
        new_reservation_id: newResId,
        room_id: roomId,
        date,
      }),
    onError: () => toast.error('배정 실패'),
    onSettled: () => _invalidateReservations(),
  });

  const [nextDayExpanded, setNextDayExpanded] = useState(() => {
    const saved = localStorage.getItem('roomAssignment_nextDayExpanded');
    if (saved !== null) return saved === 'true';
    // 첫 진입: 2xl(≥1536) 이상이면 펼침 default, 그 미만은 접힘 (좁은 화면 overflow 회피)
    return typeof window !== 'undefined' && window.innerWidth >= 1536;
  });
  const [animDirection, setAnimDirection] = useState<'none' | 'left' | 'right'>('none');
  const { hover, setHover, clearHover } = useHoverZone();

  const isMobile = useIsMobile();

  const {
    selectedGuestIds, setSelectedGuestIds, selectionActive,
    cancelDeselect, onGripClick,
  } = useGuestSelection({ selectedDate, reservations, nextDayReservations });

  // nextDayExpanded localStorage 저장
  useEffect(() => {
    localStorage.setItem('roomAssignment_nextDayExpanded', String(nextDayExpanded));
  }, [nextDayExpanded]);

  // Undo stack for room assignments
  const { canUndo, pushUndo, handleUndo } = useUndoStack({ selectedDate });

  const [processing] = useState(false);
  const [quickAddedId, setQuickAddedId] = useState<number | null>(null);
  const { collapsedBuildings, toggleBuildingCollapse } = useCollapsibleBuildings();

  const { confirmState, showConfirm, closeConfirm } = useConfirmDialog();

  const {
    modalVisible, closeModal,
    savingReservation, editingId, formValues, setFormValues,
    handleAddPartyGuest, handleQuickAddParty, handleEditGuest, handleDeleteGuest, handleSubmit,
  } = useReservationForm({
    reservations,
    selectedDate,
    findReservation,
    showConfirm,
    setQuickAddedId,
  });

  const [multiNightConfirm, setMultiNightConfirm] = useState<{
    open: boolean;
    resId: number;
    resName: string;
    roomId: number;
    roomNumber: string;
    onConfirm: (applySubsequent: boolean) => void;
  } | null>(null);

  const {
    recentlyMovedId,
    handleDropOnRoom, handleDropOnPool, handleDropOnParty,
    onDropZoneClick,
  } = useGuestMove({
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
  });

  const [extendStayConflict, setExtendStayConflict] = useState<{
    open: boolean;
    newResId: number;
    roomId: number;
    roomNumber: string;
    existingGuests: string[];
  } | null>(null);

  const [dateChangeModal, setDateChangeModal] = useState<{
    open: boolean;
    resId: number;
    customerName: string;
    checkIn: string;
    checkOut: string;
  } | null>(null);

  const [tableSettingsOpen, setTableSettingsOpen] = useState(false);
  const { customHighlightColors, rowColors, isDarkMode, applyCustomColors, applyRowColors } = useHighlightColors();

  const stayGroup = useStayGroup({ reservations });

  const {
    contextMenu, setContextMenu,
    mobileContextMenuOpen, setMobileContextMenuOpen, mobileContextBtnRef,
    longPressTimerRef, longPressFiredRef,
    onGuestContextMenu,
  } = useContextMenu({
    canOpen: !modalVisible && !stayGroup.show && !multiNightConfirm?.open,
    selectedGuestIds,
  });

  const handleFieldSave = async (resId: number, field: string, value: string, targetDate?: Dayjs) => {
    const effectiveDate = targetDate || selectedDate;
    if (field === 'party_type') {
      try {
        await reservationsAPI.updateDailyInfo(resId, { date: effectiveDate.format('YYYY-MM-DD'), party_type: value || null });
        _invalidateReservations();
      } catch {
        toast.error('저장 실패');
      }
      return;
    }
    if (field === 'notes') {
      try {
        await reservationsAPI.updateDailyInfo(resId, { date: effectiveDate.format('YYYY-MM-DD'), notes: value });
        _invalidateReservations();
      } catch {
        toast.error('저장 실패');
      }
      return;
    }
    try {
      if (field === 'genderPeople') {
        // Parse mixed gender format: "남1여1", "남2", "여3", "남1", etc.
        const maleMatch = (value || '').match(/남(\d+)/);
        const femaleMatch = (value || '').match(/여(\d+)/);
        const male_count = maleMatch ? Number(maleMatch[1]) : 0;
        const female_count = femaleMatch ? Number(femaleMatch[1]) : 0;
        // Also update party_size as total
        const total = male_count + female_count;
        const gender = male_count > 0 && female_count > 0 ? '혼성' : male_count > 0 ? '남' : female_count > 0 ? '여' : null;
        await reservationsAPI.update(resId, { male_count, female_count, gender, party_size: total || null });
      } else {
        await reservationsAPI.update(resId, { [field]: value });
      }
      _invalidateReservations();
    } catch {
      toast.error('저장 실패');
    }
  };


  const {
    colWidths,
    resizeGuideX,
    dateHeaderH,
    effectiveNameWidth,
    effectiveNameWidthNext,
    GUEST_COLS,
    NEXT_GUEST_COLS,
    NEXT_DAY_EXPANDED_WIDTH,
    tableContainerRef,
    dateHeaderRef,
    startResize,
  } = useColumnResize({ selectedDate, reservations, nextDayReservations });

  const {
    selectedTemplateKey, setSelectedTemplateKey,
    campaignDropdownOpen, setCampaignDropdownOpen, campaignDropdownRef,
    targets, clearTargets,
    sending,
    loadTargets, requestSendCampaign, handleSendCampaign,
  } = useCampaignSend({
    reservations,
    selectedDate,
    templateLabels,
    onConfirmRequest: () => setSendConfirm({ type: 'campaign' }),
    onConfirmClose: () => setSendConfirm(null),
  });
  const [sendConfirm, setSendConfirm] = useState<{ type: 'campaign' | 'toggle'; resId?: number; templateKey?: string; customerName?: string; templateName?: string } | null>(null);
  const { autoAssignConfirm, autoAssigning, handleAutoAssign, openConfirm: openAutoAssignConfirm, closeConfirm: closeAutoAssignConfirm } =
    useAutoAssign(selectedDate, () => _invalidateReservations());

  // 날짜 변경 시 캠페인 발송 대상 초기화 (데이터 페칭은 useReservationsData 내부에서 처리)
  useEffect(() => {
    clearTargets();
  }, [selectedDate, clearTargets]);

  // SSE: 스케줄 발송 완료 시 예약 목록 자동 새로고침 (Phase 4)
  useSseInvalidator(selectedDate);

  // quickAddedId 자동 클리어 제거 — 새 InlineInput 의 마운트 effect 가 autoFocus
  // 처리 후 자체적으로 편집 모드 진입. 500ms race 로 fetch 가 늦으면 autoFocus 미작동
  // 가능했음. 다음 quickAdd 시 새 ID 가 덮어쓰므로 stale 영향 없음.

  // Keyboard shortcut: Ctrl+Z = undo room assignment (ESC 는 useGuestSelection 내부에서 처리)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
        e.preventDefault();
        handleUndo();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleUndo]);



  // recentlyMovedId 가 있을 때만 해당 게스트를 리스트 맨 위로 끌어올림.
  // (raw 분류는 useReservationsData 가 담당, bumping 은 UI 책임으로 본체에서)
  const bumpToTop = (list: Reservation[], movedId: number | null): Reservation[] => {
    if (movedId === null) return list;
    const idx = list.findIndex(r => r.id === movedId);
    if (idx <= 0) return list;
    const next = [...list];
    const [item] = next.splice(idx, 1);
    next.unshift(item);
    return next;
  };

  const unassigned = useMemo(() => bumpToTop(rawUnassigned, recentlyMovedId), [rawUnassigned, recentlyMovedId]);
  const partyOnly = useMemo(() => bumpToTop(rawPartyOnly, recentlyMovedId), [rawPartyOnly, recentlyMovedId]);

  // 드롭 액션은 useGuestMove 훅으로 분리됨 (Phase I-2).




  const contextMenuActions = useMemo(() => {
    if (!contextMenu) return null;
    const { targetIds } = contextMenu;
    const found = findReservation(targetIds[0]);
    const firstRes = found?.res ?? null;
    const contextIsNextDay = found?.isNextDay ?? false;
    if (!firstRes) return null;

    const effectiveSection = firstRes.room_id ? 'room' : (sectionOverrides[firstRes.id] ?? firstRes.section ?? 'unassigned');
    const isCopied = contextMenu.zone === 'unstable' && firstRes.section !== 'unstable';
    const dateStr = (contextIsNextDay ? selectedDate.add(1, 'day') : selectedDate).format('YYYY-MM-DD');
    const optimisticUpdate = (updater: (r: Reservation) => Reservation) => {
      qc.setQueryData<Reservation[]>(queryKeys.reservations.list(dateStr), (prev) =>
        prev?.map((r) => (targetIds.includes(r.id) ? updater(r) : r))
      );
    };

    return {
      targetCount: targetIds.length,
      currentSection: effectiveSection as 'room' | 'unassigned' | 'party' | 'unstable',
      hasStayGroup: !!firstRes.stay_group_id,
      isUnstableCopy: isCopied,
      isAlreadyCopiedToUnstable: !!firstRes.unstable_party,
      hasRealUnstableBooking: !!firstRes.has_unstable_booking,
      onMoveToPool: () => {
        // DIAG_BLOCK_START
        window.__diagAction = 'ctx_menu:move_to_pool';
        // DIAG_BLOCK_END
        targetIds.forEach((id) => handleDropOnPool(id));
        setContextMenu(null);
      },
      onMoveToParty: () => {
        // DIAG_BLOCK_START
        window.__diagAction = 'ctx_menu:move_to_party';
        // DIAG_BLOCK_END
        targetIds.forEach((id) => handleDropOnParty(id));
        setContextMenu(null);
      },
      onDelete: () => {
        if (targetIds.length > 1) {
          const names = targetIds.map((id) => findReservation(id)?.res.customer_name?.trim() || '?').slice(0, 5);
          const nameList = names.join(', ') + (targetIds.length > 5 ? ` 외 ${targetIds.length - 5}명` : '');
          showConfirm('게스트 일괄 삭제', `${nameList} (총 ${targetIds.length}명) 을 삭제하시겠습니까?`, async () => {
            for (const id of targetIds) {
              try {
                // DIAG_BLOCK_START
                window.__diagAction = 'ctx_menu:delete_guest';
                // DIAG_BLOCK_END
                await reservationsAPI.delete(id);
              } catch { /* skip */ }
            }
            toast.success(`${targetIds.length}명 삭제 완료`);
            _invalidateReservations();
          });
        } else {
          // DIAG_BLOCK_START
          window.__diagAction = 'ctx_menu:delete_guest';
          // DIAG_BLOCK_END
          handleDeleteGuest(targetIds[0]);
        }
        setContextMenu(null);
      },
      onLinkStayGroup: targetIds.length === 1 && !firstRes.stay_group_id ? () => {
        // DIAG_BLOCK_START
        window.__diagAction = 'ctx_menu:stay_group_link';
        // DIAG_BLOCK_END
        stayGroup.open(firstRes.id);
        setContextMenu(null);
      } : undefined,
      onUnlinkStayGroup: firstRes.stay_group_id ? () => {
        // DIAG_BLOCK_START
        window.__diagAction = 'ctx_menu:stay_group_unlink';
        // DIAG_BLOCK_END
        stayGroup.unlink(firstRes.id);
        setContextMenu(null);
      } : undefined,
      onSetColor: (color: string | null) => {
        // DIAG_BLOCK_START
        window.__diagAction = 'ctx_menu:set_color';
        // DIAG_BLOCK_END
        // Optimistic local update
        optimisticUpdate(r => ({ ...r, highlight_color: color }));
        setColorMutation.mutate(
          { ids: targetIds, color },
          { onSettled: () => _invalidateReservations() },
        );
        setContextMenu(null);
      },
      onCopyToUnstable: () => {
        // DIAG_BLOCK_START
        window.__diagAction = 'ctx_menu:copy_to_unstable';
        // DIAG_BLOCK_END
        // Optimistic local update
        optimisticUpdate(r => ({ ...r, unstable_party: true }));
        toast.success(`언스테이블에 복사${targetIds.length > 1 ? ` (${targetIds.length}명)` : ''}`);
        copyToUnstableMutation.mutate(
          { ids: targetIds, dateStr },
          { onSettled: () => _invalidateReservations() },
        );
        setContextMenu(null);
      },
      onRemoveFromUnstable: () => {
        // DIAG_BLOCK_START
        window.__diagAction = 'ctx_menu:remove_from_unstable';
        // DIAG_BLOCK_END
        // Optimistic local update
        optimisticUpdate(r => ({ ...r, unstable_party: false }));
        toast.success('언스테이블 복사본 제거');
        removeFromUnstableMutation.mutate(
          { ids: targetIds, dateStr },
          { onSettled: () => _invalidateReservations() },
        );
        setContextMenu(null);
      },
      onExtendStay: (targetIds.length === 1 && !contextIsNextDay) ? () => {
        const resId = targetIds[0];
        const res = reservations.find((r) => r.id === resId);
        if (!res) return;
        setContextMenu(null);
        const nextDate = selectedDate.add(1, 'day');
        const extendNextDateStr = nextDate.format('YYYY-MM-DD');
        // DIAG_BLOCK_START
        window.__diagAction = 'ctx_menu:extend_stay';
        // DIAG_BLOCK_END
        extendStayMutation.mutate(
          { resId, roomId: res.room_id || null },
          {
            onSuccess: ({ data }) => {
              if (data.conflict_guests && data.conflict_guests.length > 0) {
                const roomEntry = activeRoomEntries.find((e: any) => e.room_id === res.room_id);
                setExtendStayConflict({
                  open: true,
                  newResId: data.reservation_id ?? data.new_reservation_id,
                  roomId: res.room_id!,
                  roomNumber: roomEntry?.room_number || String((res as any).room_number || ''),
                  existingGuests: data.conflict_guests,
                });
              } else {
                toast.success(`연박추가 완료 — ${res.customer_name} (${extendNextDateStr})`);
              }
            },
          },
        );
      } : undefined,
      onCancelExtendStay: (targetIds.length === 1 && !!firstRes?.manually_extended_until) ? () => {
        const resId = targetIds[0];
        setContextMenu(null);
        // DIAG_BLOCK_START
        window.__diagAction = 'ctx_menu:cancel_extend_stay';
        // DIAG_BLOCK_END
        cancelExtendStayMutation.mutate(resId);
      } : undefined,
      onChangeDates: (targetIds.length === 1) ? () => {
        const res = findReservation(targetIds[0])?.res;
        if (!res) return;
        setDateChangeModal({
          open: true,
          resId: res.id,
          customerName: res.customer_name,
          checkIn: res.check_in_date,
          checkOut: res.check_out_date || res.check_in_date,
        });
        setContextMenu(null);
      } : undefined,
      onCall: (targetIds.length === 1) ? () => {
        const found = findReservation(targetIds[0]);
        const res = found?.res;
        const phone = res?.phone?.trim();
        const name = res?.customer_name || '게스트';
        if (!phone) {
          toast.warning('연락처가 등록되지 않은 게스트입니다');
          setContextMenu(null);
          return;
        }
        setContextMenu(null);
        // tel: 호출은 OS(iOS/Android)가 자체 확인 다이얼로그를 띄우므로 앱 측 확인은 생략.
        window.location.href = `tel:${phone}`;
      } : undefined,
    };
  }, [contextMenu, reservations, nextDayReservations, findReservation, sectionOverrides, handleDropOnPool, handleDropOnParty, handleDeleteGuest, selectedDate, qc, stayGroup.open, stayGroup.unlink, showConfirm, activeRoomEntries, setColorMutation, copyToUnstableMutation, removeFromUnstableMutation, extendStayMutation, cancelExtendStayMutation, _invalidateReservations]);



  const { handleSmsToggle, doSmsToggle, handleSmsAssign, handleSmsRemove } = useSmsAssignment({
    reservations,
    selectedDate,
    templateLabels,
    onToggleConfirmRequest: (params) => setSendConfirm({ type: 'toggle', ...params }),
  });

  const onZoneHover = useCallback((zoneId: string) => {
    // 모바일은 hover 가 실제 사용자 의도가 아님 — 터치 후 합성 mouseenter 가 발화해
    // "여기에 놓으세요" 가 잘못 표시되는 문제 방지.
    if (isMobile) return;
    if (selectedGuestIds.size === 0) return;
    if (zoneId.startsWith('next-room-')) setHover({ type: 'next-room', roomId: Number(zoneId.replace('next-room-', '')) });
    else if (zoneId.startsWith('room-')) setHover({ type: 'room', roomId: Number(zoneId.replace('room-', '')) });
    else if (zoneId === 'next-pool') setHover({ type: 'next-pool' });
    else if (zoneId === 'next-party') setHover({ type: 'next-party' });
    else if (zoneId === 'pool') setHover({ type: 'pool' });
    else if (zoneId === 'party') setHover({ type: 'party' });
  }, [selectedGuestIds.size, isMobile, setHover]);

  const onZoneLeave = useCallback(() => {
    clearHover();
  }, [clearHover]);

  // GuestRow 가 공유하는 props 묶음 — 7곳 호출처에 spread 로 전달
  const sharedRowProps = {
    selectionActive, isDarkMode, GUEST_COLS, templateLabels, selectedDate, quickAddedId,
    onGripClick, onGuestContextMenu, handleFieldSave,
    handleSmsToggle, handleSmsAssign, handleSmsRemove,
    cancelDeselect, longPressTimerRef, longPressFiredRef,
  };
  // CompactGuestCell 가 공유하는 props 묶음 — 3곳 호출처에 spread 로 전달
  const sharedNextProps = {
    selectionActive, selectedDate, NEXT_GUEST_COLS,
    onGripClick, onGuestContextMenu, handleFieldSave, cancelDeselect,
  };
  // 다음날 컬럼의 게스트 한 명을 그리는 공통 함수 — 4 zone 모두 같은 형태 사용
  const renderCompactCell = (guest: Reservation) => (
    <CompactGuestCell
      guest={guest}
      expanded={nextDayExpanded}
      isSelected={selectedGuestIds.has(guest.id)}
      {...sharedNextProps}
    />
  );
  const renderGuestRow = (res: Reservation, showGrip: boolean, zone?: string) => (
    <GuestRow
      key={res.id}
      res={res}
      showGrip={showGrip}
      isSelected={selectedGuestIds.has(res.id)}
      zone={zone}
      {...sharedRowProps}
    />
  );
  // 4 zone 컴포넌트가 공유하는 props 묶음
  const sharedZoneProps = {
    hover, setHover, clearHover,
    onDropZoneClick,
    selectionActive,
    nextDayExpanded,
    NEXT_DAY_EXPANDED_WIDTH,
    nextDayColWidth: colWidths.nextDay,
    GUEST_COLS,
    renderGuestRow,
    renderCompactCell,
  };

  const renderRoomRow = (entry: RoomEntry, rowIndex: number) => {
    const groupInfo = roomGroupMap.get(entry.room_id);
    const groupColor = groupInfo?.isLast
      ? roomGroups.find(g => g.id === groupInfo.group_id)?.color
      : undefined;
    return (
      <RoomRow
        key={entry.room_id}
        entry={entry}
        rowIndex={rowIndex}
        groupInfo={groupInfo}
        groupColor={groupColor}
        guestsToday={assignedRooms.get(entry.room_id) || []}
        guestsNextDay={nextDayRoomMap.get(entry.room_id) || []}
        roomMemo={roomMemoMap[entry.room_id] || ''}
        onSaveRoomMemo={saveRoomMemo}
        isDarkMode={isDarkMode}
        rowColors={rowColors}
        {...sharedZoneProps}
      />
    );
  };

  const navigateDate = useCallback(
    async (direction: 'prev' | 'next') => {
      if (animDirection !== 'none') return;

      const newDate = direction === 'next'
        ? selectedDate.add(1, 'day')
        : selectedDate.subtract(1, 'day');
      const newDateStr = newDate.format('YYYY-MM-DD');
      const newNextDateStr = newDate.add(1, 'day').format('YYYY-MM-DD');

      setAnimDirection(direction === 'next' ? 'left' : 'right');

      const animPromise = new Promise((r) => setTimeout(r, 200));

      // RQ cache が fresh なら即座に解決。キャッシュ未ヒットなら fetch する。
      const dataPromise = Promise.all([
        qc.prefetchQuery({
          queryKey: queryKeys.reservations.list(newDateStr),
          queryFn: () =>
            reservationsAPI
              .getAll({ date: newDateStr, limit: 200 })
              .then((res) => filterActive(res.data.items ?? res.data, newDateStr)),
          staleTime: 30_000,
        }),
        qc.prefetchQuery({
          queryKey: queryKeys.reservations.list(newNextDateStr),
          queryFn: () =>
            reservationsAPI
              .getAll({ date: newNextDateStr, limit: 200 })
              .then((res) => filterActive(res.data.items ?? res.data, newNextDateStr)),
          staleTime: 30_000,
        }),
      ]).catch(() => { toast.error('예약 목록을 불러오지 못했습니다.'); });

      await Promise.all([animPromise, dataPromise]);
      setSelectedDate(newDate);
      setAnimDirection('none');
    },
    [animDirection, selectedDate, qc, filterActive],
  );

  // suppress unused handleEditGuest warning — used via modal open
  void handleEditGuest;

  // Summary stats
  const summary = useMemo(() => {
    // Room guest totals (복사본 = unstable_party=true인 비-unstable 예약자 제외)
    let roomTotal = 0, roomMale = 0, roomFemale = 0;
    for (const r of reservations) {
      if (r.section !== 'unstable' && r.unstable_party) continue; // 복사본 제외
      const m = r.male_count || 0;
      const f = r.female_count || 0;
      roomMale += m;
      roomFemale += f;
      roomTotal += m + f;
    }

    // Party guest totals (only those with party_type)
    const partyGuests = reservations.filter((r) => r.party_type);
    let partyMale = 0, partyFemale = 0;
    let firstMale = 0, firstFemale = 0;
    let secondOnlyMale = 0, secondOnlyFemale = 0;

    for (const r of partyGuests) {
      const m = r.male_count || 0;
      const f = r.female_count || 0;
      partyMale += m;
      partyFemale += f;

      if (r.party_type === '1' || r.party_type === '2') {
        // 1차 참여 = 1차만 + 1,2차
        firstMale += m;
        firstFemale += f;
      }
      if (r.party_type === '2차만') {
        secondOnlyMale += m;
        secondOnlyFemale += f;
      }
    }

    const partyTotal = partyMale + partyFemale;
    const firstTotal = firstMale + firstFemale;
    const secondOnlyTotal = secondOnlyMale + secondOnlyFemale;
    // 2차 전환율 = 1차 중 2차도 참여한 인원 / 1차 전체
    const bothGuests = partyGuests.filter((r) => r.party_type === '2');
    const bothTotal = bothGuests.reduce((sum, r) => sum + (r.male_count || 0) + (r.female_count || 0), 0);
    const conversionRate = firstTotal > 0 ? Math.round((bothTotal / firstTotal) * 100) : 0;
    const genderRatio = firstFemale > 0 ? `${(firstMale / firstFemale).toFixed(1)}:1` : firstMale > 0 ? `${firstMale}:0` : '-';

    // Unstable guest totals (순수 section="unstable" + 복사된 unstable_party=true)
    let unstableMale = 0, unstableFemale = 0;
    for (const r of unstableGuests) {
      unstableMale += r.male_count || 0;
      unstableFemale += r.female_count || 0;
    }
    const unstableTotal = unstableMale + unstableFemale;

    return {
      roomTotal, roomMale, roomFemale,
      partyTotal, partyMale, partyFemale,
      firstTotal, firstMale, firstFemale,
      secondOnlyTotal, secondOnlyMale, secondOnlyFemale,
      conversionRate, genderRatio,
      unstableTotal, unstableMale, unstableFemale,
    };
  }, [reservations, unstableGuests]);

  return (
    <div className={`space-y-4 pb-14 min-w-0 ${processing ? 'opacity-60 pointer-events-none' : ''}`}>

      <PageHeader />

      <SummaryCards summary={summary} hasUnstable={hasUnstable} />

      <CampaignToolbar
        templateLabels={templateLabels}
        selectedTemplateKey={selectedTemplateKey}
        setSelectedTemplateKey={setSelectedTemplateKey}
        campaignDropdownOpen={campaignDropdownOpen}
        setCampaignDropdownOpen={setCampaignDropdownOpen}
        campaignDropdownRef={campaignDropdownRef}
        targets={targets}
        clearTargets={clearTargets}
        sending={sending}
        loadTargets={loadTargets}
        requestSendCampaign={requestSendCampaign}
        onOpenTableSettings={() => setTableSettingsOpen(true)}
        onAddPartyGuest={handleAddPartyGuest}
      />

      {/* Main grid card */}
      <div className="section-card !overflow-visible w-max min-w-full">
        {/* Date navigation header — sticky */}
        <div ref={dateHeaderRef} className="sticky top-0 z-20">
          <div className="section-header justify-center bg-white dark:bg-[#1E1E24]">
            <div className="flex items-center gap-1">
              <button
                onClick={() => navigateDate('prev')}
                className="cursor-pointer p-1 text-[#B0B8C1] hover:text-[#191F28] dark:text-[#4E5968] dark:hover:text-white transition-colors bg-transparent border-none"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <TextInput
                type="date"
                sizing="sm"
                value={selectedDate.format('YYYY-MM-DD')}
                onChange={(e) => {
                  if (e.target.value) setSelectedDate(dayjs(e.target.value));
                }}
              />
              <button
                onClick={() => navigateDate('next')}
                className="cursor-pointer p-1 text-[#B0B8C1] hover:text-[#191F28] dark:text-[#4E5968] dark:hover:text-white transition-colors bg-transparent border-none"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>

        <div className="section-body !pt-2">
          <div
            key={selectedDate.format('YYYY-MM-DD')}
            className={
              animDirection === 'left'
                ? 'date-slide-left'
                : animDirection === 'right'
                  ? 'date-slide-right'
                  : ''
            }
          >
            {/* Unified Table */}
            <div ref={tableContainerRef} className="relative rounded-xl border border-[#F2F4F6] dark:border-[#2C2C34]">
              {resizeGuideX !== null && (
                <div className="absolute top-0 bottom-0 w-px bg-[#3182F6] z-50 pointer-events-none" style={{ left: resizeGuideX }} />
              )}
              {/* Header */}
              <div className="flex items-center h-10 bg-[#F2F4F6] dark:bg-[#17171C] border-b border-[#D1D5DB] dark:border-[#4E5968] sticky z-[19]" style={{ top: dateHeaderH }}>
                <div className="flex-shrink-0 pl-3 pr-2 w-38 border-r border-[#F2F4F6] dark:border-[#2C2C34]">
                  <span className="text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">객실</span>
                </div>
                <div className="w-10 flex-shrink-0" />
                <div
                  className="flex-1 grid items-center"
                  style={{ gridTemplateColumns: GUEST_COLS }}
                >
                  <div className="relative pl-[9px] pr-1.5 text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">이름<div onMouseDown={(e) => startResize('name', e)} className="absolute right-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:right-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" /></div>
                  <div className="relative pl-[9px] pr-1.5 text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">전화번호<div onMouseDown={(e) => startResize('phone', e)} className="absolute right-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:right-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" /></div>
                  <div className="relative px-1.5 text-center text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">파티<div onMouseDown={(e) => startResize('party', e)} className="absolute right-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:right-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" /></div>
                  <div className="relative px-1.5 text-center text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">성별<div onMouseDown={(e) => startResize('gender', e)} className="absolute right-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:right-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" /></div>
                  <div className="relative px-1.5 text-center text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">예약객실<div onMouseDown={(e) => startResize('roomType', e)} className="absolute right-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:right-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" /></div>
                  <div className="relative pl-[9px] pr-1.5 text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">메모<div onMouseDown={(e) => startResize('notes', e)} className="absolute right-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:right-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" /></div>
                  <div className="relative pl-[9px] pr-1.5 text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">문자<div onMouseDown={(e) => startResize('sms', e)} className="absolute right-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:right-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" /></div>
                </div>
                <div className="relative flex-shrink-0 z-[2] before:content-[''] before:absolute before:inset-y-0 before:left-0 before:w-px before:bg-[#E5E8EB] dark:before:bg-gray-700 before:z-10 before:pointer-events-none flex flex-col justify-center self-stretch transition-all duration-200" style={{ width: nextDayExpanded ? NEXT_DAY_EXPANDED_WIDTH : colWidths.nextDay }}>
                  {!nextDayExpanded && (
                    <div onMouseDown={(e) => startResize('nextDay', e)} className="absolute left-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:left-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" />
                  )}
                  {!nextDayExpanded ? (
                    <div className="flex items-center justify-center gap-1 px-2">
                      <button onClick={() => setNextDayExpanded(true)} className="text-[#8B95A1] hover:text-[#3182F6] transition-colors cursor-pointer" title="펼치기">
                        <ChevronsLeft className="h-3.5 w-3.5" />
                      </button>
                      <span className="text-caption font-semibold text-[#8B95A1] dark:text-[#8B95A1]">{selectedDate.add(1, 'day').format('M/D')}</span>
                    </div>
                  ) : (
                    <div className="flex items-center">
                      <button onClick={() => setNextDayExpanded(false)} className="w-8 flex-shrink-0 flex items-center justify-center text-[#8B95A1] hover:text-[#3182F6] transition-colors cursor-pointer" title="접기">
                        <ChevronsRight className="h-3.5 w-3.5" />
                      </button>
                      <div className="flex-1 grid items-center" style={{ gridTemplateColumns: NEXT_GUEST_COLS }}>
                        <div className="px-1 text-caption font-semibold text-[#8B95A1] whitespace-nowrap">{selectedDate.add(1, 'day').format('M/D')}</div>
                        <div className="px-1 text-[10px] font-semibold text-[#8B95A1]">전화번호</div>
                        <div className="px-1 text-center text-[10px] font-semibold text-[#8B95A1]">파티</div>
                        <div className="px-1 text-center text-[10px] font-semibold text-[#8B95A1]">성별</div>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Selection mode toast is handled via useEffect */}

              {/* Room Rows (stale-while-revalidate: 이전 데이터 유지, 새 데이터 조용히 교체) */}
              <div className={loading ? 'pointer-events-none' : ''} onContextMenu={(e) => { if (!(e.target as HTMLElement).closest('[data-allow-context]')) e.preventDefault(); }}>
                {(() => {
                  let rowIdx = 0;
                  return buildingGroups.map((group) => {
                    const startIdx = rowIdx;
                    rowIdx += group.entries.length;
                    return (
                      <BuildingGroup
                        key={`building-${group.building_id ?? 'none'}`}
                        group={group}
                        isCollapsed={collapsedBuildings.has(group.building_id)}
                        onToggle={toggleBuildingCollapse}
                        startRowIndex={startIdx}
                        renderRoomRow={renderRoomRow}
                      />
                    );
                  });
                })()}
              </div>

              <UnassignedZone
                guests={unassigned}
                nextDayGuests={nextDayUnassigned}
                {...sharedZoneProps}
              />

              <PartyZone
                guests={partyOnly}
                nextDayGuests={nextDayPartyOnly}
                {...sharedZoneProps}
              />

              <UnstableZone
                guests={unstableGuests}
                nextDayGuests={[]}
                {...sharedZoneProps}
              />

              <CancelledZone
                guests={cancelledGuests}
                nextDayGuests={[]}
                {...sharedZoneProps}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Guest Form Modal */}
      <ReservationFormModal
        show={modalVisible}
        onClose={closeModal}
        editingId={editingId}
        formValues={formValues}
        setFormValues={setFormValues}
        saving={savingReservation}
        onSubmit={handleSubmit}
      />

      <QuickMenuBar
        autoAssigning={autoAssigning}
        onAutoAssign={openAutoAssignConfirm}
        onPartyAdd={handleQuickAddParty}
        canUndo={canUndo}
        onUndo={handleUndo}
        isMobile={isMobile}
        selectionActive={selectionActive}
        selectedCount={selectedGuestIds.size}
        mobileContextBtnRef={mobileContextBtnRef}
        mobileContextMenuOpen={mobileContextMenuOpen}
        onToggleMobileContext={() => {
          if (mobileContextMenuOpen) {
            setContextMenu(null);
            setMobileContextMenuOpen(false);
          } else {
            const ids = [...selectedGuestIds];
            if (ids.length === 0) return;
            const rect = mobileContextBtnRef.current!.getBoundingClientRect();
            setContextMenu({ x: rect.left, y: rect.top - 8, targetIds: ids });
            setMobileContextMenuOpen(true);
          }
        }}
        onCallSelected={() => {
          if (selectedGuestIds.size !== 1) return;
          const id = [...selectedGuestIds][0];
          const found = findReservation(id);
          const phone = found?.res?.phone?.trim();
          if (!phone) {
            toast.warning('연락처가 등록되지 않은 게스트입니다');
            return;
          }
          window.location.href = `tel:${phone}`;
        }}
        onDeleteSelected={() => {
          const ids = [...selectedGuestIds];
          if (ids.length === 0) return;
          if (ids.length > 1) {
            const names = ids.map((id) => findReservation(id)?.res.customer_name?.trim() || '?').slice(0, 5);
            const nameList = names.join(', ') + (ids.length > 5 ? ` 외 ${ids.length - 5}명` : '');
            showConfirm('게스트 일괄 삭제', `${nameList} (총 ${ids.length}명) 을 삭제하시겠습니까?`, async () => {
              for (const id of ids) {
                try { await reservationsAPI.delete(id); } catch { /* skip */ }
              }
              toast.success(`${ids.length}명 삭제 완료`);
              setSelectedGuestIds(new Set());
              _invalidateReservations();
            });
          } else {
            handleDeleteGuest(ids[0]);
            setSelectedGuestIds(new Set());
          }
        }}
      />

      <ConfirmDialog
        state={confirmState}
        onClose={closeConfirm}
      />

      <MultiNightConfirmModal
        data={multiNightConfirm}
        onClose={() => setMultiNightConfirm(null)}
      />

      <SendConfirmModal
        data={sendConfirm}
        onClose={() => setSendConfirm(null)}
        reservations={reservations}
        templateLabels={templateLabels}
        selectedTemplateKey={selectedTemplateKey}
        targetsCount={targets.length}
        selectedDate={selectedDate}
        onSendCampaign={handleSendCampaign}
        onSmsToggle={doSmsToggle}
      />

      {/* Slide animations (transform only, no opacity = no flicker) */}
      <style>{`
        @keyframes slideLeft {
          from { transform: translateX(-8px); }
          to   { transform: translateX(0); }
        }
        @keyframes slideRight {
          from { transform: translateX(8px); }
          to   { transform: translateX(0); }
        }
        .date-slide-left  { animation: slideLeft  0.15s ease-out; }
        .date-slide-right { animation: slideRight 0.15s ease-out; }
      `}</style>

      <AutoAssignConfirmModal
        open={autoAssignConfirm}
        onClose={closeAutoAssignConfirm}
        unassigned={unassigned}
        onConfirm={handleAutoAssign}
        loading={autoAssigning}
      />

      {/* Table Settings Modal (replaces old Group Settings Modal) */}
      <TableSettingsModal
        show={tableSettingsOpen}
        onClose={() => setTableSettingsOpen(false)}
        customColors={customHighlightColors}
        onSaveCustomColors={applyCustomColors}
        activeRoomEntries={activeRoomEntries.filter(e => e.isActive !== false)}
        roomGroups={roomGroups}
        roomInfoMap={roomInfoMap}
        onSaveDividers={async (dividers, dividerColors) => {
          try {
            // Delete all existing groups
            for (const rg of roomGroups) {
              await roomsAPI.deleteGroup(rg.id);
            }

            // Convert dividers → groups
            const roomIds = activeRoomEntries.filter(e => e.isActive !== false).map(e => e.room_id);
            const groups: { name: string; room_ids: number[]; sort_order: number; color?: string }[] = [];
            let current: number[] = [];
            let groupIdx = 0;

            roomIds.forEach((id, i) => {
              current.push(id);
              if (dividers.has(i) || i === roomIds.length - 1) {
                const existingName = roomGroups[groupIdx]?.name;
                groups.push({
                  name: existingName || `그룹 ${groupIdx + 1}`,
                  room_ids: current,
                  sort_order: groupIdx,
                  color: dividerColors.get(i) || undefined,
                });
                current = [];
                groupIdx++;
              }
            });

            // Only create groups if there are dividers (more than 1 group)
            if (groups.length > 1) {
              for (const g of groups) {
                await roomsAPI.createGroup(g);
              }
            }

            toast.success('구분선 설정이 저장되었습니다');
            setTableSettingsOpen(false);
            await Promise.all([
              qc.invalidateQueries({ queryKey: queryKeys.rooms.list() }),
              qc.invalidateQueries({ queryKey: queryKeys.rooms.groups() }),
            ]);
          } catch {
            toast.error('구분선 설정 저장에 실패했습니다');
          }
        }}
        rowColors={rowColors}
        onSaveRowColors={(colors) => {
          applyRowColors(colors);
          setTableSettingsOpen(false);
        }}
      />

      <StayGroupChainModal
        show={stayGroup.show}
        onClose={stayGroup.close}
        chain={stayGroup.chain}
        direction={stayGroup.direction}
        onDirectionChange={stayGroup.changeDirection}
        dateReservations={stayGroup.candidates}
        loading={stayGroup.loading}
        selectedId={stayGroup.selectedId}
        onSelectId={stayGroup.setSelectedId}
        linking={stayGroup.linking}
        onAddMore={stayGroup.addMore}
        onComplete={stayGroup.complete}
      />

      <ExtendStayConflictModal
        data={extendStayConflict}
        onClose={() => setExtendStayConflict(null)}
        onKeepSameRoom={() => {
          if (!extendStayConflict) return;
          assignExtendStayRoomMutation.mutate(
            {
              newResId: extendStayConflict.newResId,
              roomId: extendStayConflict.roomId,
              date: selectedDate.add(1, 'day').format('YYYY-MM-DD'),
            },
            {
              onSuccess: () => toast.success('같은 방에 배정 완료'),
              onSettled: () => setExtendStayConflict(null),
            },
          );
        }}
        onSkipAssign={() => {
          toast.info('방 배정 없이 연박추가 완료');
          setExtendStayConflict(null);
          _invalidateReservations();
        }}
      />

      <DateChangeModal
        data={dateChangeModal}
        onChange={(next) => setDateChangeModal(next)}
        onClose={() => setDateChangeModal(null)}
        onSubmit={async (resId, checkIn, checkOut) => {
          const hadRoom = findReservation(resId)?.res?.room_id;
          try {
            await reservationsAPI.update(resId, {
              check_in_date: checkIn,
              check_out_date: checkOut,
            });
            toast.success('예약 날짜 변경 완료');
            if (hadRoom) {
              toast.info('날짜 변경으로 기존 객실 배정이 해제될 수 있습니다', { duration: 5000 });
            }
            setDateChangeModal(null);
            _invalidateReservations();
          } catch (err: any) {
            toast.error(err?.response?.data?.detail || '날짜 변경 실패');
          }
        }}
      />

      {/* Context menu */}
      {contextMenu && contextMenuActions && (
        <>
          <div
            className="fixed inset-0 z-[55]"
            onClick={() => {
              // long-press 직후 합성 click 은 메뉴 열린 직후 발화 → 즉시 닫힘 방지.
              // 한 번만 무시하고 flag 리셋해 다음 backdrop click 은 정상 닫기.
              if (longPressFiredRef.current) {
                longPressFiredRef.current = false;
                return;
              }
              setContextMenu(null);
              setMobileContextMenuOpen(false);
            }}
            onContextMenu={(e) => { e.preventDefault(); setContextMenu(null); setMobileContextMenuOpen(false); }}
          />
        <GuestContextMenu
          position={{ x: contextMenu.x, y: contextMenu.y }}
          targetCount={contextMenuActions.targetCount}
          currentSection={contextMenuActions.currentSection}
          hasStayGroup={contextMenuActions.hasStayGroup}
          isUnstableCopy={contextMenuActions.isUnstableCopy}
          customColors={customHighlightColors}
          onMoveToPool={contextMenuActions.onMoveToPool}
          onMoveToParty={contextMenuActions.onMoveToParty}
          onDelete={contextMenuActions.onDelete}
          onLinkStayGroup={contextMenuActions.onLinkStayGroup}
          onUnlinkStayGroup={contextMenuActions.onUnlinkStayGroup}
          onSetColor={contextMenuActions.onSetColor}
          onCopyToUnstable={hasUnstable && !contextMenuActions.isAlreadyCopiedToUnstable && !contextMenuActions.hasRealUnstableBooking ? contextMenuActions.onCopyToUnstable : undefined}
          onRemoveFromUnstable={hasUnstable && contextMenuActions.isAlreadyCopiedToUnstable && !contextMenuActions.hasRealUnstableBooking ? contextMenuActions.onRemoveFromUnstable : undefined}
          onExtendStay={contextMenuActions.onExtendStay}
          onCancelExtendStay={contextMenuActions.onCancelExtendStay}
          onChangeDates={contextMenuActions.onChangeDates}
          onCall={contextMenuActions.onCall}
          hideDelete={isMobile && mobileContextMenuOpen}
          onClose={() => { setContextMenu(null); setMobileContextMenuOpen(false); }}
        />
        </>
      )}
    </div>
  );
};

export default RoomAssignment;
