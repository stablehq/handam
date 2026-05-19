import { useEffect, useState, DragEvent } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Home, Plus, Pencil, Trash2, GripVertical, RefreshCw, Building2, ArrowUpDown, Settings, Undo2 } from 'lucide-react';
import { toast } from 'sonner';
import { roomsAPI, buildingsAPI } from '@/services/api';
import { queryKeys } from '@/lib/queryKeys';

import { ToggleSwitch } from '@/components/ui/toggle-switch';
import { Table, TableHead, TableBody, TableRow, TableHeadCell, TableCell } from '@/components/ui/table';
import { Modal, ModalHeader, ModalBody, ModalFooter } from '@/components/ui/modal';
import { TextInput } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import { Spinner } from '@/components/ui/spinner';
import { Button } from '@/components/ui/button';

// ── Types ─────────────────────────────────────────────

interface Building {
  id: number;
  name: string;
  description?: string | null;
  room_count?: number;
}

// Building manage modal: local editable row
interface BuildingEditRow {
  id: number | null; // null = new
  name: string;
  description: string;
  _deleted?: boolean;
}

interface BizItemLinkDetail {
  biz_item_id: string;
  male_priority: number;
  female_priority: number;
}

interface Room {
  id: number;
  room_number: string;
  room_type: string;
  base_capacity: number;
  max_capacity: number;
  active: boolean;
  sort_order: number;
  created_at: string;
  naver_biz_item_id?: string | null;
  biz_item_ids?: string[];
  biz_item_links_detail?: BizItemLinkDetail[];
  dormitory: boolean;
  bed_capacity: number;
  door_password?: string | null;
  building_id?: number | null;
  building_name?: string | null;
  grade?: number | null;  // 1~5 객실 등급 (room_upgrade_review 칩 발송 조건)
}

// 객실 등급 가이드 — 객실 설정 / 상품 설정 모달 양쪽에서 동일 척도 사용.
const GRADE_GUIDE_TEXT = '1=도미 < 2=더블 < 3=트윈 < 4=트윈3인실 < 5=스위트';
const GRADE_OPTIONS = [1, 2, 3, 4, 5];

interface RoomForm {
  room_number: string;
  room_type: string;
  base_capacity: number;
  max_capacity: number;
  sort_order: number;
  active: boolean;
  biz_item_ids: string[];
  biz_item_priorities: Record<string, { male_priority: number; female_priority: number }>;
  dormitory: boolean;
  bed_capacity: number;
  door_password: string;
  no_door_password: boolean;
  building_id: number | null;
}

interface NaverBizItem {
  id: number;
  biz_item_id: string;
  name: string;
  biz_item_type?: string | null;
  exposed?: boolean;
  active: boolean;
}

// ── Constants ─────────────────────────────────────────

const EMPTY_ROOM_FORM: RoomForm = {
  room_number: '',
  room_type: '',
  base_capacity: 2,
  max_capacity: 4,
  sort_order: 1,
  active: true,
  biz_item_ids: [],
  biz_item_priorities: {},
  dormitory: false,
  bed_capacity: 1,
  door_password: '',
  no_door_password: false,
  building_id: null,
};

// EMPTY_BUILDING_FORM removed — building editing is now inline in manage modal

// ── Component ─────────────────────────────────────────

const RoomSettings = () => {
  const qc = useQueryClient();
  // ── Rooms state ──
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<RoomForm>(EMPTY_ROOM_FORM);
  const [deleteTarget, setDeleteTarget] = useState<Room | null>(null);
  const [draggingIndex, setDraggingIndex] = useState<number | null>(null);
  // ── Buildings state ──
  const [buildingManageOpen, setBuildingManageOpen] = useState(false);
  const [buildingRows, setBuildingRows] = useState<BuildingEditRow[]>([]);
  const [buildingHistory, setBuildingHistory] = useState<BuildingEditRow[][]>([]);
  // (savingBuildings 제거 — saveBuildingsMutation.isPending 으로)

  // ── Priority modal state ──
  const [priorityOpen, setPriorityOpen] = useState(false);
  // { [biz_item_id]: { [room_id]: { male_priority, female_priority } } }
  const [priorityData, setPriorityData] = useState<Record<string, Record<number, { male_priority: number; female_priority: number }>>>({});
  // (savingPriority 제거 — savePriorityMutation.isPending 으로)

  // ── Biz item settings modal state ──
  interface BizItemSetting {
    biz_item_id: string;
    name: string;
    display_name: string;
    default_capacity: number;
    section_hint: string;
    default_party_type: string | null;
    grade: number | null;
    active: boolean;
    exposed?: boolean;
  }
  const [bizItemModalOpen, setBizItemModalOpen] = useState(false);
  // bizItemSettingsList 는 useQuery 로 대체 (아래 bizItemSettingsQuery)
  const [bizItemEdits, setBizItemEdits] = useState<Record<string, {display_name?: string; default_capacity?: number; section_hint?: string; default_party_type?: string; grade?: number}>>({});
  // (bizItemSaving / bizItemSyncing 제거 — mutation.isPending 으로)

  // ── Room grade modal state ──
  const [roomGradeModalOpen, setRoomGradeModalOpen] = useState(false);
  const [roomGradeEdits, setRoomGradeEdits] = useState<Record<number, number>>({});
  // (roomGradeSaving 제거 — saveRoomGradeMutation.isPending 으로)

  // ── React Query: 3 데이터 로드 ──
  const roomsQuery = useQuery<Room[]>({
    queryKey: queryKeys.rooms.listWithInactive(),
    queryFn: () => roomsAPI.getAll({ include_inactive: true }).then(r => r.data),
    staleTime: 300_000,
  });
  const rooms = roomsQuery.data ?? [];
  const loading = roomsQuery.isFetching;

  const bizItemsQuery = useQuery<NaverBizItem[]>({
    queryKey: queryKeys.rooms.bizItems(),
    queryFn: () => roomsAPI.getBizItems().then(r => r.data),
    staleTime: 300_000,
  });
  const bizItems = bizItemsQuery.data ?? [];

  const buildingsQuery = useQuery<Building[]>({
    queryKey: queryKeys.buildings.list(),
    queryFn: () => buildingsAPI.getAll().then(r => r.data),
    staleTime: 300_000,
  });
  const buildings = buildingsQuery.data ?? [];
  const buildingsLoading = buildingsQuery.isFetching;

  // ── Error logging — Step #2 패턴 ──
  useEffect(() => {
    if (roomsQuery.error) { console.error('rooms load:', roomsQuery.error); toast.error('객실 목록 로드 실패'); }
  }, [roomsQuery.error]);
  useEffect(() => {
    if (buildingsQuery.error) { console.error('buildings load:', buildingsQuery.error); toast.error('건물 목록 로드 실패'); }
  }, [buildingsQuery.error]);
  useEffect(() => {
    if (bizItemsQuery.error) console.error('bizItems load:', bizItemsQuery.error);
  }, [bizItemsQuery.error]);

  // (Step #6a helper 제거됨 — 모달 함수가 직접 invalidateQueries 호출)


  // ── Biz item settings modal ──
  // bizItemsQuery 와 같은 queryKey → 캐시 공유. enabled 로 modal 열림 시만 active.
  // bizItemSettingsQuery — Step #6a 의 bizItemsQuery 와 같은 queryKey → 캐시 공유. enabled 만 다름.
  const bizItemSettingsQuery = useQuery<BizItemSetting[]>({
    queryKey: queryKeys.rooms.bizItems(),
    queryFn: () => roomsAPI.getBizItems().then(r => r.data || []),
    staleTime: 300_000,
    enabled: bizItemModalOpen,
  });
  const bizItemSettingsList = bizItemSettingsQuery.data ?? [];

  useEffect(() => {
    if (bizItemModalOpen) setBizItemEdits({});  // 모달 열릴 때 편집 초기화 (refetch 시 보존)
  }, [bizItemModalOpen]);

  useEffect(() => {
    if (bizItemSettingsQuery.error) toast.error('상품 목록을 불러오지 못했습니다.');
  }, [bizItemSettingsQuery.error]);

  const handleBizItemEdit = (bizItemId: string, field: string, value: string | number) => {
    setBizItemEdits(prev => ({
      ...prev,
      [bizItemId]: { ...prev[bizItemId], [field]: value }
    }));
  };

  const saveBizItemMutation = useMutation({
    mutationFn: (changes: any[]) => roomsAPI.updateBizItems(changes),
    onSuccess: () => {
      toast.success('상품 설정이 저장되었습니다.');
      qc.invalidateQueries({ queryKey: queryKeys.rooms.bizItems() });
      qc.invalidateQueries({ queryKey: queryKeys.rooms.all() });
    },
    onError: () => toast.error('상품 설정 저장에 실패했습니다.'),
  });
  const bizItemSaving = saveBizItemMutation.isPending;

  const syncBizItemMutation = useMutation({
    mutationFn: () => roomsAPI.syncBizItems(),
    onSuccess: () => {
      toast.success('네이버 상품 동기화 완료');
      qc.invalidateQueries({ queryKey: queryKeys.rooms.bizItems() });
      qc.invalidateQueries({ queryKey: queryKeys.rooms.all() });
    },
    onError: () => toast.error('네이버 상품 동기화에 실패했습니다.'),
  });
  const bizItemSyncing = syncBizItemMutation.isPending;

  const handleBizItemSave = () => {
    const changes = Object.entries(bizItemEdits).map(([biz_item_id, edits]) => ({
      biz_item_id,
      ...edits,
      default_party_type: edits.default_party_type === '' ? null : edits.default_party_type,
    }));
    if (changes.length === 0) { setBizItemModalOpen(false); return; }
    saveBizItemMutation.mutate(changes);
  };

  const handleBizItemSync = () => syncBizItemMutation.mutate();

  // ── Room grade modal ──
  // 모달 열릴 때 현재 등급으로 edits 초기화 (운영자가 보고 변경 가능).
  useEffect(() => {
    if (!roomGradeModalOpen) return;
    const initial: Record<number, number> = {};
    for (const r of rooms) {
      if (typeof r.grade === 'number') initial[r.id] = r.grade;
    }
    setRoomGradeEdits(initial);
  }, [roomGradeModalOpen, rooms]);

  const handleRoomGradeChange = (roomId: number, grade: number) => {
    setRoomGradeEdits(prev => ({ ...prev, [roomId]: grade }));
  };

  const saveRoomGradeMutation = useMutation({
    mutationFn: (items: { id: number; grade: number }[]) => roomsAPI.updateRoomGrades(items),
    onSuccess: () => {
      toast.success('객실 등급이 저장되었습니다.');
      setRoomGradeModalOpen(false);
      qc.invalidateQueries({ queryKey: queryKeys.rooms.all() });
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail ?? '객실 등급 저장에 실패했습니다.'),
  });
  const roomGradeSaving = saveRoomGradeMutation.isPending;

  const handleRoomGradeSave = () => {
    // 원본과 다른 항목만 PATCH 대상
    const items = Object.entries(roomGradeEdits)
      .map(([id, grade]) => ({ id: Number(id), grade }))
      .filter(({ id, grade }) => {
        const orig = rooms.find(r => r.id === id);
        return orig && orig.grade !== grade;
      });
    if (items.length === 0) { setRoomGradeModalOpen(false); return; }
    saveRoomGradeMutation.mutate(items);
  };


  // ── Room CRUD ──
  const openCreate = () => {
    setEditingId(null);
    setForm({ ...EMPTY_ROOM_FORM, sort_order: rooms.length + 1 });
    setDialogOpen(true);
  };

  const openEdit = (room: Room) => {
    setEditingId(room.id);
    const ids = room.biz_item_ids && room.biz_item_ids.length > 0
      ? room.biz_item_ids
      : room.naver_biz_item_id
        ? [room.naver_biz_item_id]
        : [];
    const priorities: Record<string, { male_priority: number; female_priority: number }> = {};
    if (room.biz_item_links_detail) {
      for (const link of room.biz_item_links_detail) {
        priorities[link.biz_item_id] = {
          male_priority: link.male_priority,
          female_priority: link.female_priority,
        };
      }
    }
    setForm({
      room_number: room.room_number,
      room_type: room.room_type,
      base_capacity: room.base_capacity,
      max_capacity: room.max_capacity,
      sort_order: room.sort_order,
      active: room.active,
      biz_item_ids: ids,
      biz_item_priorities: priorities,
      dormitory: room.dormitory || false,
      bed_capacity: room.bed_capacity || 1,
      door_password: room.door_password || '',
      no_door_password: !room.door_password,
      building_id: room.building_id ?? null,
    });
    setDialogOpen(true);
  };

  const toggleBizItem = (bizItemId: string) => {
    setForm((f) => {
      const already = f.biz_item_ids.includes(bizItemId);
      const newIds = already
        ? f.biz_item_ids.filter((id) => id !== bizItemId)
        : [...f.biz_item_ids, bizItemId];
      let newRoomType = f.room_type;
      if (!already && newIds.length === 1) {
        const item = bizItems.find((b) => b.biz_item_id === bizItemId);
        if (item && !f.room_type.trim()) {
          newRoomType = item.name;
        }
      }
      const newPriorities = { ...f.biz_item_priorities };
      if (already) {
        delete newPriorities[bizItemId];
      } else if (!newPriorities[bizItemId]) {
        newPriorities[bizItemId] = { male_priority: 0, female_priority: 0 };
      }
      return { ...f, biz_item_ids: newIds, biz_item_priorities: newPriorities, room_type: newRoomType };
    });
  };


  const saveRoomMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number | null; payload: any }) =>
      id != null ? roomsAPI.update(id, payload) : roomsAPI.create(payload),
    onSuccess: (res, vars) => {
      toast.success(vars.id != null ? '수정 완료' : '추가 완료');
      if (vars.id != null && res?.data?.warning) toast.warning(res.data.warning, { duration: 10000 });
      setDialogOpen(false);
      qc.invalidateQueries({ queryKey: queryKeys.rooms.all() });
      qc.invalidateQueries({ queryKey: queryKeys.buildings.list() });
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || '저장 실패'),
  });

  const deleteRoomMutation = useMutation({
    mutationFn: (id: number) => roomsAPI.delete(id),
    onSuccess: () => {
      toast.success('삭제 완료');
      qc.invalidateQueries({ queryKey: queryKeys.rooms.all() });
      qc.invalidateQueries({ queryKey: queryKeys.buildings.list() });
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || '삭제 실패'),
    onSettled: () => setDeleteTarget(null),
  });

  const saving = saveRoomMutation.isPending;

  const handleSubmit = () => {
    if (!form.room_number.trim() || !form.room_type.trim()) {
      toast.error('객실 번호와 타입은 필수입니다');
      return;
    }
    // Build biz_item_links with priority for API
    const { biz_item_ids, biz_item_priorities, ...rest } = form;
    const payload = {
      ...rest,
      biz_item_links: biz_item_ids.map((id) => ({
        biz_item_id: id,
        male_priority: biz_item_priorities[id]?.male_priority ?? 0,
        female_priority: biz_item_priorities[id]?.female_priority ?? 0,
      })),
    };
    saveRoomMutation.mutate({ id: editingId, payload });
  };

  const confirmDelete = () => {
    if (!deleteTarget) return;
    deleteRoomMutation.mutate(deleteTarget.id);
  };

  // ── Building manage modal helpers ──
  const openBuildingManage = () => {
    const rows: BuildingEditRow[] = buildings.map((b) => ({ id: b.id, name: b.name, description: b.description || '' }));
    setBuildingRows(rows);
    setBuildingHistory([]);
    setBuildingManageOpen(true);
  };

  const pushBuildingHistory = () => {
    setBuildingHistory((prev) => [...prev, buildingRows]);
  };

  const handleBuildingRowChange = (index: number, field: 'name' | 'description', value: string) => {
    pushBuildingHistory();
    setBuildingRows((prev) => prev.map((r, i) => (i === index ? { ...r, [field]: value } : r)));
  };

  const handleBuildingRowDelete = (index: number) => {
    pushBuildingHistory();
    setBuildingRows((prev) => prev.map((r, i) => (i === index ? { ...r, _deleted: true } : r)));
  };

  const handleBuildingRowAdd = () => {
    pushBuildingHistory();
    setBuildingRows((prev) => [...prev, { id: null, name: '', description: '' }]);
  };

  const handleBuildingUndo = () => {
    if (buildingHistory.length === 0) return;
    const prev = buildingHistory[buildingHistory.length - 1];
    setBuildingHistory((h) => h.slice(0, -1));
    setBuildingRows(prev);
  };

  const saveBuildingsMutation = useMutation({
    mutationFn: async (rows: BuildingEditRow[]): Promise<string[]> => {
      // 단계별 Promise.allSettled — 순차 await 의 부분 저장 문제 해결.
      // 삭제 → 생성 → 수정 순서는 유지 (같은 이름 빌딩 재생성 시나리오 보존).
      const deletedIds = rows.filter((r) => r._deleted && r.id !== null).map((r) => r.id!);
      const visible = rows.filter((r) => !r._deleted);
      const newRows = visible.filter((r) => r.id === null);
      const updateRows = visible.filter((r) => {
        if (r.id === null) return false;
        const original = buildings.find((b) => b.id === r.id);
        return !!original && (original.name !== r.name.trim() || (original.description || '') !== r.description.trim());
      });

      const failures: string[] = [];

      if (deletedIds.length > 0) {
        const results = await Promise.allSettled(deletedIds.map((id) => buildingsAPI.delete(id)));
        results.forEach((r, i) => { if (r.status === 'rejected') failures.push(`삭제[id=${deletedIds[i]}]`); });
      }
      if (newRows.length > 0) {
        const results = await Promise.allSettled(
          newRows.map((row) => buildingsAPI.create({ name: row.name.trim(), description: row.description.trim() })),
        );
        results.forEach((r, i) => { if (r.status === 'rejected') failures.push(`생성[${newRows[i].name}]`); });
      }
      if (updateRows.length > 0) {
        const results = await Promise.allSettled(
          updateRows.map((row) => buildingsAPI.update(row.id!, { name: row.name.trim(), description: row.description.trim() })),
        );
        results.forEach((r, i) => { if (r.status === 'rejected') failures.push(`수정[${updateRows[i].name}]`); });
      }
      return failures;
    },
    onSuccess: (failures) => {
      if (failures.length > 0) {
        toast.error(`${failures.length}건 저장 실패: ${failures.join(', ')}. 다시 시도해주세요.`);
        window.__diagAction = `building_save_partial_failure_${failures.length}`;
      } else {
        toast.success('건물 저장 완료');
        setBuildingManageOpen(false);
      }
      // 부분 저장 / 전체 성공 모두 최신 상태로 재조회
      qc.invalidateQueries({ queryKey: queryKeys.buildings.list() });
      qc.invalidateQueries({ queryKey: queryKeys.rooms.all() });
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || '저장 실패'),
  });
  const savingBuildings = saveBuildingsMutation.isPending;

  const handleBuildingSaveAll = () => {
    const visibleRows = buildingRows.filter((r) => !r._deleted);
    if (visibleRows.some((r) => !r.name.trim())) { toast.error('건물 이름을 입력하세요'); return; }
    saveBuildingsMutation.mutate(buildingRows);
  };

  // ── Priority modal helpers ──
  const openPriorityModal = () => {
    // Build priority data from rooms' biz_item_links_detail grouped by biz_item_id
    const data: Record<string, Record<number, { male_priority: number; female_priority: number }>> = {};
    for (const room of rooms) {
      const links = room.biz_item_links_detail || [];
      for (const link of links) {
        if (!data[link.biz_item_id]) data[link.biz_item_id] = {};
        data[link.biz_item_id][room.id] = {
          male_priority: link.male_priority,
          female_priority: link.female_priority,
        };
      }
    }
    setPriorityData(data);
    setPriorityOpen(true);
  };

  const updatePriorityValue = (bizItemId: string, roomId: number, field: 'male_priority' | 'female_priority', value: number) => {
    setPriorityData((prev) => ({
      ...prev,
      [bizItemId]: {
        ...prev[bizItemId],
        [roomId]: {
          ...(prev[bizItemId]?.[roomId] || { male_priority: 0, female_priority: 0 }),
          [field]: value,
        },
      },
    }));
  };

  const savePriorityMutation = useMutation({
    mutationFn: async (data: typeof priorityData) => {
      const roomLinks: Record<number, { biz_item_id: string; male_priority: number; female_priority: number }[]> = {};
      for (const [bizItemId, roomMap] of Object.entries(data)) {
        for (const [roomIdStr, prio] of Object.entries(roomMap)) {
          const roomId = Number(roomIdStr);
          if (!roomLinks[roomId]) roomLinks[roomId] = [];
          roomLinks[roomId].push({
            biz_item_id: bizItemId,
            male_priority: prio.male_priority,
            female_priority: prio.female_priority,
          });
        }
      }
      await Promise.all(
        Object.entries(roomLinks).map(([roomIdStr, links]) =>
          roomsAPI.update(Number(roomIdStr), { biz_item_links: links })
        )
      );
    },
    onSuccess: () => {
      toast.success('배정 순서 저장 완료');
      setPriorityOpen(false);
      qc.invalidateQueries({ queryKey: queryKeys.rooms.all() });
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || '저장 실패'),
  });
  const savingPriority = savePriorityMutation.isPending;

  const handlePrioritySave = () => savePriorityMutation.mutate(priorityData);

  // ── Drag and Drop ──
  const onDragStart = (e: DragEvent, index: number) => {
    e.dataTransfer.setData('text/plain', String(index));
    e.dataTransfer.effectAllowed = 'move';
    setDraggingIndex(index);
  };

  const onDragEnd = () => {
    setDraggingIndex(null);
  };

  const onDragOver = (e: DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  };

  // Optimistic reorder mutation — RoomAssignment 의 모범사례 패턴
  const reorderRoomsMutation = useMutation({
    mutationFn: (newOrder: number[]) => roomsAPI.reorder(newOrder),
    onMutate: async (newOrder) => {
      await qc.cancelQueries({ queryKey: queryKeys.rooms.listWithInactive() });
      const previous = qc.getQueryData<Room[]>(queryKeys.rooms.listWithInactive());
      qc.setQueryData<Room[]>(queryKeys.rooms.listWithInactive(), (prev) => {
        if (!prev) return prev;
        const map = new Map(prev.map(r => [r.id, r]));
        return newOrder.map(id => map.get(id)).filter(Boolean) as Room[];
      });
      return { previous };
    },
    onError: (err: any, _vars, ctx) => {
      if (ctx?.previous) qc.setQueryData(queryKeys.rooms.listWithInactive(), ctx.previous);
      toast.error(err?.response?.data?.detail || '정렬 순서 변경 실패');
    },
    onSuccess: () => toast.success('정렬 순서 변경 완료'),
    onSettled: () => qc.invalidateQueries({ queryKey: queryKeys.rooms.all() }),
  });

  const onDrop = (e: DragEvent, targetIndex: number) => {
    e.preventDefault();
    setDraggingIndex(null);

    const sourceIndex = parseInt(e.dataTransfer.getData('text/plain'), 10);
    if (sourceIndex === targetIndex) return;

    const newRooms = [...rooms];
    const [moved] = newRooms.splice(sourceIndex, 1);
    newRooms.splice(targetIndex, 0, moved);
    reorderRoomsMutation.mutate(newRooms.map(r => r.id));
  };

  // ── Render ──
  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <div className="flex items-center gap-2.5">
          <div className="stat-icon bg-[#E8F3FF] text-[#3182F6] dark:bg-[#3182F6]/15 dark:text-[#3182F6]">
            <Home size={20} />
          </div>
          <div>
            <h1 className="page-title">객실 설정</h1>
            <p className="page-subtitle">건물 및 객실을 추가, 수정, 삭제하고 순서를 변경합니다.</p>
          </div>
        </div>
      </div>

      {/* ── Building + Room List (combined card) ── */}
      <div className="section-card">
        {/* Building List */}
        <div className="flex flex-wrap items-center gap-3 px-4 sm:px-5 py-4">
          <div className="flex items-center gap-2">
            <Building2 size={16} className="text-[#3182F6]" />
            <span className="text-subheading font-semibold text-[#191F28] dark:text-white whitespace-nowrap">건물 목록</span>
            {buildings.length > 0 && (
              <Badge color="info" size="sm">{buildings.length}</Badge>
            )}
          </div>
          {buildingsLoading ? (
            <Spinner size="sm" />
          ) : buildings.length === 0 ? (
            <span className="text-label text-[#B0B8C1] dark:text-gray-500">등록된 건물이 없습니다</span>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              {buildings.map((building) => (
                <Badge key={building.id} color="gray" size="sm">
                  {building.name}
                  <span className="ml-1 tabular-nums">
                    ({building.room_count ?? rooms.filter((r) => r.building_id === building.id).length})
                  </span>
                </Badge>
              ))}
            </div>
          )}
          <div className="ml-auto">
            <Button color="light" size="sm" className="whitespace-nowrap" onClick={openBuildingManage}>
              <Building2 className="mr-1.5 h-3.5 w-3.5" />
              건물 관리
            </Button>
          </div>
        </div>

        {/* Divider */}
        <div className="border-t border-[#E5E8EB] dark:border-gray-800" />

        {/* Room List */}
        <div className="section-header flex-wrap gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <Home size={16} className="text-[#3182F6]" />
            <span className="text-subheading font-semibold text-[#191F28] dark:text-white whitespace-nowrap">객실 목록</span>
            {rooms.length > 0 && (
              <Badge color="info" size="sm">{rooms.length}</Badge>
            )}
            <div className="hidden sm:flex items-center gap-1.5 text-caption text-[#B0B8C1] dark:text-gray-600">
              <GripVertical size={14} />
              <span>드래그하여 순서 변경</span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button color="light" size="sm" className="whitespace-nowrap" onClick={() => setBizItemModalOpen(true)}>
              <Settings className="mr-1.5 h-3.5 w-3.5" />
              상품 설정
            </Button>
            <Button color="light" size="sm" className="whitespace-nowrap" onClick={() => setRoomGradeModalOpen(true)}>
              <Settings className="mr-1.5 h-3.5 w-3.5" />
              객실 등급
            </Button>
            <Button color="light" size="sm" className="whitespace-nowrap" onClick={openPriorityModal}>
              <ArrowUpDown className="mr-1.5 h-3.5 w-3.5" />
              배정 순서
            </Button>
            <Button color="blue" size="sm" className="whitespace-nowrap" onClick={openCreate}>
              <Plus className="mr-1.5 h-3.5 w-3.5" />
              객실 추가
            </Button>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Spinner size="lg" />
          </div>
        ) : rooms.length === 0 ? (
          <div className="empty-state">
            <Home size={40} strokeWidth={1} />
            <p className="text-body">등록된 객실이 없습니다</p>
          </div>
        ) : (
          <Table hoverable striped>
            <TableHead>
              <TableRow>
                <TableHeadCell className="w-px text-center" />
                <TableHeadCell className="w-px text-center">#</TableHeadCell>
                <TableHeadCell className="w-px text-center">건물</TableHeadCell>
                <TableHeadCell className="w-px text-center">객실</TableHeadCell>
                <TableHeadCell className="w-px text-center">타입</TableHeadCell>
                <TableHeadCell className="w-px text-center">인원</TableHeadCell>
                <TableHeadCell className="w-px text-center">상태</TableHeadCell>
                <TableHeadCell className="w-px text-center">비밀번호</TableHeadCell>
                <TableHeadCell className="w-px text-center">도미토리</TableHeadCell>
                <TableHeadCell className="w-px text-center">네이버 상품</TableHeadCell>
                <TableHeadCell />
                <TableHeadCell className="w-px text-center">작업</TableHeadCell>
              </TableRow>
            </TableHead>
            <TableBody className="divide-y">
              {rooms.map((room, index) => (
                <TableRow
                  key={room.id}
                  draggable
                  onDragStart={(e) => onDragStart(e, index)}
                  onDragEnd={onDragEnd}
                  onDragOver={onDragOver}
                  onDrop={(e) => onDrop(e, index)}
                  className={`transition-opacity ${draggingIndex === index ? 'opacity-40' : ''}`}
                >
                  <TableCell className="text-center px-3">
                    <GripVertical size={16} className="drag-handle mx-auto" />
                  </TableCell>
                  <TableCell className="text-center tabular-nums font-semibold text-[#8B95A1] dark:text-gray-500">
                    {index + 1}
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-center">
                      {room.building_name ? (
                        <Badge color="gray" size="sm">{room.building_name}</Badge>
                      ) : (
                        <span className="text-caption text-[#B0B8C1] dark:text-gray-600">-</span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="text-center font-semibold text-[#191F28] dark:text-white">
                    {room.room_number}
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-center">
                      <Badge color="gray">{room.room_type}</Badge>
                    </div>
                  </TableCell>
                  <TableCell className="text-center text-[#4E5968] dark:text-gray-400">
                    <span className="text-caption text-[#8B95A1] dark:text-gray-500">기준</span>{' '}
                    <span className="tabular-nums font-semibold">{room.base_capacity}인</span>
                    <span className="mx-1 text-[#B0B8C1] dark:text-gray-600">|</span>
                    <span className="text-caption text-[#8B95A1] dark:text-gray-500">최대</span>{' '}
                    <span className="tabular-nums font-semibold">{room.max_capacity}인</span>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-center">
                      <span className={`text-body font-medium ${room.active ? 'text-[#00C9A7]' : 'text-[#F04452]'}`}>
                        {room.active ? '활성' : '비활성'}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="text-center text-[#4E5968] dark:text-gray-400">
                    {room.door_password ? (
                      <span className="tabular-nums font-medium">{room.door_password}</span>
                    ) : (
                      <span className="text-caption text-[#B0B8C1] dark:text-gray-600">없음</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-center">
                      {room.dormitory ? (
                        <Badge color="purple" size="sm">{room.bed_capacity}인실</Badge>
                      ) : (
                        <span className="text-caption text-[#B0B8C1] dark:text-gray-600">-</span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    {(() => {
                      const ids = room.biz_item_ids && room.biz_item_ids.length > 0
                        ? room.biz_item_ids
                        : room.naver_biz_item_id
                          ? [room.naver_biz_item_id]
                          : [];
                      if (ids.length === 0) return <span className="text-caption text-[#B0B8C1] dark:text-gray-600">-</span>;
                      return (
                        <div className="flex flex-wrap justify-center gap-1">
                          {ids.map((id) => {
                            const item = bizItems.find((b) => b.biz_item_id === id);
                            const label = item
                              ? (item.exposed === false ? `[미노출] ${item.name}` : item.name)
                              : id;
                            return (
                              <Badge key={id} color="info" size="xs">
                                {label}
                              </Badge>
                            );
                          })}
                        </div>
                      );
                    })()}
                  </TableCell>
                  <TableCell />
                  <TableCell className="text-center">
                    <div className="flex justify-center gap-1">
                      <Button color="light" size="xs" onClick={() => openEdit(room)}>
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button color="light" size="xs" onClick={() => setDeleteTarget(room)}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      {/* ── Room Modal ── */}
      <Modal show={dialogOpen} onClose={() => setDialogOpen(false)} size="md">
        <ModalHeader>{editingId !== null ? '객실 수정' : '객실 추가'}</ModalHeader>
        <ModalBody>
          <div className="flex flex-col gap-5">
            {/* Building select */}
            <div className="space-y-2">
              <Label htmlFor="room-building">건물</Label>
              <Select
                id="room-building"
                value={form.building_id ?? ''}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    building_id: e.target.value ? Number(e.target.value) : null,
                  }))
                }
              >
                <option value="">건물 없음</option>
                {buildings.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="room-number">
                객실 번호 <span className="text-[#F04452] dark:text-red-400">*</span>
              </Label>
              <TextInput
                id="room-number"
                value={form.room_number}
                onChange={(e) => setForm((f) => ({ ...f, room_number: e.target.value }))}
                placeholder="A101"
              />
            </div>

            <div className="space-y-2">
              <label className="text-caption font-medium text-[#4E5968] dark:text-gray-300">연결 상품</label>
              {bizItems.length === 0 ? (
                <p className="text-caption text-[#B0B8C1]">상품 없음 (상품 동기화 후 사용)</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {bizItems.map((item) => {
                    const selected = form.biz_item_ids.includes(item.biz_item_id);
                    return (
                      <button
                        key={item.biz_item_id}
                        type="button"
                        onClick={() => toggleBizItem(item.biz_item_id)}
                        className={`rounded-lg px-3 py-1.5 text-body transition-colors ${
                          selected
                            ? 'bg-[#3182F6] text-white dark:bg-[#3182F6]'
                            : 'bg-[#F2F4F6] text-[#8B95A1] hover:bg-[#E5E8EB] dark:bg-[#2C2C34] dark:text-gray-400 dark:hover:bg-[#35353E]'
                        }`}
                      >
                        {item.exposed === false ? `[미노출] ${item.name}` : item.name}
                      </button>
                    );
                  })}
                </div>
              )}
              {form.biz_item_ids.length > 0 && (
                <p className="text-caption text-[#3182F6] pt-1">{form.biz_item_ids.length}개 선택됨</p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="room-type">
                객실 타입 <span className="text-[#F04452] dark:text-red-400">*</span>
              </Label>
              <TextInput
                id="room-type"
                value={form.room_type}
                onChange={(e) => setForm((f) => ({ ...f, room_type: e.target.value }))}
                placeholder="더블룸"
              />
            </div>

            <div className={`grid grid-cols-2 gap-4 rounded-lg p-3 transition-all ${form.dormitory ? 'bg-[#F2F4F6] opacity-50 dark:bg-[#1E1E24]' : ''}`}>
              <div className="space-y-2">
                <Label htmlFor="base-capacity" className={form.dormitory ? 'text-[#B0B8C1]' : ''}>기준 인원</Label>
                <TextInput
                  id="base-capacity"
                  type="number"
                  min={1}
                  value={String(form.base_capacity ?? 2)}
                  onChange={(e) => setForm((f) => ({ ...f, base_capacity: parseInt(e.target.value) || 1 }))}
                  disabled={form.dormitory}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="max-capacity" className={form.dormitory ? 'text-[#B0B8C1]' : ''}>최대 인원</Label>
                <TextInput
                  id="max-capacity"
                  type="number"
                  min={1}
                  value={String(form.max_capacity ?? 4)}
                  onChange={(e) => setForm((f) => ({ ...f, max_capacity: parseInt(e.target.value) || 1 }))}
                  disabled={form.dormitory}
                />
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="default-password" className="mb-0">객실 비밀번호</Label>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.no_door_password}
                    onChange={(e) => setForm((f) => ({
                      ...f,
                      no_door_password: e.target.checked,
                      door_password: e.target.checked ? '' : f.door_password,
                    }))}
                    className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  <span className="text-caption text-[#8B95A1]">비밀번호 없음</span>
                </label>
              </div>
              <TextInput
                id="default-password"
                placeholder="객실 도어락 비밀번호"
                value={form.door_password}
                onChange={(e) => setForm((f) => ({ ...f, door_password: e.target.value }))}
                disabled={form.no_door_password}
                color={!form.no_door_password && !form.door_password ? 'failure' : undefined}
              />
              {!form.no_door_password && !form.door_password && (
                <p className="text-caption text-[#F04452]">비밀번호를 입력하거나 &quot;비밀번호 없음&quot;을 체크하세요</p>
              )}
            </div>

            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <Label className="mb-0">객실 상태</Label>
                <span className={`text-body font-medium ${form.active ? 'text-[#00C9A7]' : 'text-[#F04452]'}`}>
                  {form.active ? '활성' : '비활성'}
                </span>
              </div>
              <ToggleSwitch
                checked={form.active}
                onChange={(v) => setForm((f) => ({ ...f, active: v }))}
              />
            </div>

            <div className="space-y-2">
              <div className="flex gap-5">
                <span className="text-label font-medium text-gray-900 dark:text-white" style={{ minWidth: '3rem' }}>도미토리</span>
                <span className={`text-label font-medium transition-opacity ${form.dormitory ? 'text-gray-900 dark:text-white' : 'opacity-40 text-gray-900 dark:text-white'}`}>인실 수</span>
              </div>
              <div className="flex items-center gap-5">
                <ToggleSwitch
                  checked={form.dormitory}
                  onChange={(v) => setForm((f) => ({ ...f, dormitory: v }))}
                />
                <div className={`w-24 transition-opacity ${form.dormitory ? '' : 'opacity-40'}`}>
                  <TextInput
                    id="dormitory-beds"
                    type="number"
                    min={1}
                    max={20}
                    value={String(form.bed_capacity ?? 1)}
                    onChange={(e) => setForm((f) => ({ ...f, bed_capacity: parseInt(e.target.value) || 1 }))}
                    disabled={!form.dormitory}
                  />
                </div>
              </div>
            </div>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button color="light" onClick={() => setDialogOpen(false)}>취소</Button>
          <Button color="blue" onClick={handleSubmit} disabled={saving}>
            {saving ? (
              <>
                <Spinner size="sm" className="mr-2" />
                저장 중...
              </>
            ) : (
              '저장'
            )}
          </Button>
        </ModalFooter>
      </Modal>

      {/* ── Room Delete Confirm ── */}
      <Modal show={!!deleteTarget} onClose={() => setDeleteTarget(null)} size="md" popup>
        <ModalHeader />
        <ModalBody>
          <div className="text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#FFEBEE] dark:bg-[#F04452]/10">
              <Trash2 className="h-6 w-6 text-[#F04452] dark:text-red-400" />
            </div>
            <h3 className="mb-2 text-heading font-semibold text-[#191F28] dark:text-white">객실 삭제</h3>
            <p className="mb-5 text-body text-[#8B95A1] dark:text-gray-400">
              객실 <strong>"{deleteTarget?.room_number}"</strong>을(를) 정말 삭제하시겠습니까?
              이 작업은 되돌릴 수 없습니다.
            </p>
            <div className="flex justify-center gap-3">
              <Button color="failure" onClick={confirmDelete}>삭제</Button>
              <Button color="light" onClick={() => setDeleteTarget(null)}>취소</Button>
            </div>
          </div>
        </ModalBody>
      </Modal>

      {/* ── Building Manage Modal (inline edit) ── */}
      <Modal show={buildingManageOpen} onClose={() => setBuildingManageOpen(false)} size="md">
        <ModalHeader className="[&>h3]:w-full">
          <div className="flex w-full items-center justify-between">
            <span>건물 관리</span>
            <button
              disabled={buildingHistory.length === 0}
              onClick={handleBuildingUndo}
              className="flex items-center gap-1 rounded-lg px-2 py-1 text-caption font-normal text-[#8B95A1] transition-colors hover:bg-[#F2F4F6] disabled:opacity-30 disabled:cursor-not-allowed dark:text-gray-500 dark:hover:bg-[#2C2C34]"
              title="되돌리기"
            >
              <Undo2 className="h-3.5 w-3.5" />
              되돌리기
            </button>
          </div>
        </ModalHeader>
        <ModalBody>
          <div className="flex flex-col gap-2">
            {/* Header row */}
            <div className="flex items-center gap-2">
              <span className="w-28 shrink-0 text-caption font-medium text-[#8B95A1] dark:text-gray-500">건물명</span>
              <span className="flex-1 text-caption font-medium text-[#8B95A1] dark:text-gray-500">설명 <span className="font-normal text-[#B0B8C1] dark:text-gray-600">(선택)</span></span>
              <span className="w-6 shrink-0 text-center text-caption font-medium text-[#8B95A1] dark:text-gray-500">객실</span>
              <span className="w-7 shrink-0" />
            </div>
            {buildingRows.filter((r) => !r._deleted).length === 0 && (
              <p className="py-4 text-center text-label text-[#8B95A1] dark:text-gray-500">
                건물이 없습니다. 아래 버튼으로 추가하세요.
              </p>
            )}
            {buildingRows.map((row, idx) =>
              row._deleted ? null : (
                <div key={row.id ?? `new-${idx}`} className="flex items-center gap-2">
                  <TextInput
                    sizing="sm"
                    className={`w-28 shrink-0 ${row.id === null || row.name ? '' : '!bg-[#F8F9FA] dark:!bg-[#2C2C34]'}`}
                    value={row.name}
                    onChange={(e) => handleBuildingRowChange(idx, 'name', e.target.value)}
                    placeholder={row.id === null ? '건물명' : undefined}
                  />
                  <TextInput
                    sizing="sm"
                    className={`flex-1 ${row.id === null || row.description ? '' : '!bg-[#F8F9FA] dark:!bg-[#2C2C34]'}`}
                    value={row.description}
                    onChange={(e) => handleBuildingRowChange(idx, 'description', e.target.value)}
                    placeholder={row.id === null ? '설명' : undefined}
                  />
                  <span className="w-6 shrink-0 text-center tabular-nums text-caption text-[#8B95A1] dark:text-gray-500">
                    {row.id !== null
                      ? (buildings.find((b) => b.id === row.id)?.room_count ?? rooms.filter((r) => r.building_id === row.id).length)
                      : ''}
                  </span>
                  <Button color="failure" size="xs" onClick={() => handleBuildingRowDelete(idx)}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              )
            )}
            {/* 추가 버튼 */}
            <button
              onClick={handleBuildingRowAdd}
              className="flex items-center justify-center rounded-lg bg-[#F2F4F6] py-2.5 text-[#8B95A1] transition-colors hover:bg-[#E5E8EB] hover:text-[#3182F6] dark:bg-[#2C2C34] dark:text-gray-500 dark:hover:bg-[#35353E] dark:hover:text-[#3182F6]"
            >
              <Plus className="h-4 w-4" />
            </button>
          </div>
        </ModalBody>
        <ModalFooter>
          <div className="flex w-full items-center justify-end gap-2">
            <Button color="light" size="sm" onClick={() => setBuildingManageOpen(false)}>
              취소
            </Button>
            <Button color="blue" size="sm" onClick={handleBuildingSaveAll} disabled={savingBuildings}>
              {savingBuildings ? (
                <>
                  <Spinner size="sm" className="mr-2" />
                  저장 중...
                </>
              ) : (
                '저장'
                )}
              </Button>
          </div>
        </ModalFooter>
      </Modal>

      {/* ── Priority Management Modal ── */}
      <Modal show={priorityOpen} onClose={() => setPriorityOpen(false)} size="lg">
        <ModalHeader>배정 순서 관리</ModalHeader>
        <ModalBody>
          <p className="text-caption text-[#8B95A1] dark:text-gray-500 mb-4">
            상품별로 객실 배정 순서를 설정합니다. 숫자가 낮을수록 먼저 배정되며, 0은 미설정입니다.
          </p>
          {Object.keys(priorityData).length === 0 ? (
            <div className="empty-state">
              <ArrowUpDown size={40} strokeWidth={1} />
              <p className="text-body">상품에 연결된 객실이 없습니다</p>
            </div>
          ) : (
            <div className="space-y-5">
              {Object.entries(priorityData).map(([bizItemId, roomMap]) => {
                const bizItem = bizItems.find((b) => b.biz_item_id === bizItemId);
                const label = bizItem ? bizItem.name : bizItemId;
                // Sort rooms by sort_order
                const roomEntries = Object.entries(roomMap)
                  .map(([roomIdStr, prio]) => {
                    const room = rooms.find((r) => r.id === Number(roomIdStr));
                    return { roomId: Number(roomIdStr), room, prio };
                  })
                  .filter((e) => e.room)
                  .sort((a, b) => (a.room!.sort_order - b.room!.sort_order));

                if (roomEntries.length === 0) return null;

                return (
                  <div key={bizItemId}>
                    <div className="flex items-center gap-2 mb-2">
                      <Badge color="info" size="sm">{label}</Badge>
                      <span className="text-tiny text-[#B0B8C1] dark:text-gray-600">{roomEntries.length}개 객실</span>
                    </div>
                    <div className="rounded-xl border border-[#E5E8EB] dark:border-gray-700 overflow-hidden">
                      {/* Header */}
                      <div className="flex items-center bg-[#F8F9FA] dark:bg-[#1E1E24] px-4 py-2">
                        <span className="flex-1 text-caption font-medium text-[#8B95A1] dark:text-gray-500">객실</span>
                        <span className="w-20 text-center text-caption font-medium text-[#8B95A1] dark:text-gray-500">남자 순서</span>
                        <span className="w-20 text-center text-caption font-medium text-[#8B95A1] dark:text-gray-500">여자 순서</span>
                      </div>
                      {/* Rows */}
                      {roomEntries.map(({ roomId, room, prio }) => (
                        <div
                          key={roomId}
                          className="flex items-center border-t border-[#E5E8EB] dark:border-gray-700 px-4 py-2 hover:bg-[#F8F9FA] dark:hover:bg-[#1E1E24] transition-colors"
                        >
                          <div className="flex-1 flex items-center gap-2">
                            <span className="text-body font-medium text-[#191F28] dark:text-white">{room!.room_number}</span>
                            {room!.building_name && (
                              <span className="text-tiny text-[#B0B8C1] dark:text-gray-600">{room!.building_name}</span>
                            )}
                          </div>
                          <div className="w-20 flex justify-center">
                            <input
                              type="number"
                              min={0}
                              value={prio.male_priority}
                              onChange={(e) => updatePriorityValue(bizItemId, roomId, 'male_priority', parseInt(e.target.value) || 0)}
                              className="w-14 rounded-lg border border-[#E5E8EB] bg-white px-2 py-1.5 text-center text-body tabular-nums dark:border-gray-600 dark:bg-[#2C2C34] dark:text-white focus:border-[#3182F6] focus:ring-1 focus:ring-[#3182F6]"
                            />
                          </div>
                          <div className="w-20 flex justify-center">
                            <input
                              type="number"
                              min={0}
                              value={prio.female_priority}
                              onChange={(e) => updatePriorityValue(bizItemId, roomId, 'female_priority', parseInt(e.target.value) || 0)}
                              className="w-14 rounded-lg border border-[#E5E8EB] bg-white px-2 py-1.5 text-center text-body tabular-nums dark:border-gray-600 dark:bg-[#2C2C34] dark:text-white focus:border-[#3182F6] focus:ring-1 focus:ring-[#3182F6]"
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </ModalBody>
        <ModalFooter>
          <Button color="light" onClick={() => setPriorityOpen(false)}>취소</Button>
          <Button color="blue" onClick={handlePrioritySave} disabled={savingPriority}>
            {savingPriority ? (
              <>
                <Spinner size="sm" className="mr-2" />
                저장 중...
              </>
            ) : (
              '저장'
            )}
          </Button>
        </ModalFooter>
      </Modal>

      {/* ── Biz item settings modal ── */}
      <Modal size="fit" show={bizItemModalOpen} onClose={() => setBizItemModalOpen(false)}>
        <ModalHeader>네이버 상품 설정</ModalHeader>
        <ModalBody>
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-4">
              <p className="text-label text-[#8B95A1] whitespace-nowrap">네이버에서 상품 목록을 가져옵니다.</p>
              <Button color="light" size="sm" onClick={handleBizItemSync} disabled={bizItemSyncing}>
                {bizItemSyncing ? (
                  <><Spinner size="sm" className="mr-1.5" />동기화 중...</>
                ) : (
                  <><RefreshCw className="h-3.5 w-3.5 mr-1.5" />상품 동기화</>
                )}
              </Button>
            </div>
            <p className="text-caption text-[#8B95A1]">
              등급 가이드: {GRADE_GUIDE_TEXT}
            </p>

            {bizItemSettingsList.length > 0 ? (
              <div className="rounded-lg border border-[#E5E8EB] dark:border-gray-700">
                <Table className="whitespace-nowrap">
                  <TableHead>
                    <TableRow>
                      <TableHeadCell className="text-caption">상품명 (네이버)</TableHeadCell>
                      <TableHeadCell className="text-caption">표시명</TableHeadCell>
                      <TableHeadCell className="text-caption w-24">기준인원</TableHeadCell>
                      <TableHeadCell className="text-caption w-24">등급</TableHeadCell>
                      <TableHeadCell className="text-caption w-28">섹션</TableHeadCell>
                      <TableHeadCell className="text-caption w-28">파티포함</TableHeadCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {bizItemSettingsList.map(item => {
                      const edits = bizItemEdits[item.biz_item_id] || {};
                      return (
                        <TableRow key={item.biz_item_id}>
                          <TableCell>
                            <span className="flex items-center gap-1.5 text-caption text-[#8B95A1]">
                              <span className={`inline-block h-[7px] w-[7px] rounded-full flex-shrink-0 ${item.exposed !== false ? 'bg-[#00C9A7]' : 'bg-[#B0B8C1]'}`} />
                              {item.name}
                            </span>
                          </TableCell>
                          <TableCell>
                            <TextInput
                              sizing="sm"
                              className="min-w-[160px]"
                              placeholder={item.name}
                              value={edits.display_name ?? item.display_name ?? ''}
                              onChange={e => handleBizItemEdit(item.biz_item_id, 'display_name', e.target.value)}
                            />
                          </TableCell>
                          <TableCell>
                            <TextInput
                              sizing="sm"
                              type="number"
                              min={1}
                              max={20}
                              value={edits.default_capacity ?? item.default_capacity ?? 1}
                              onChange={e => handleBizItemEdit(item.biz_item_id, 'default_capacity', parseInt(e.target.value) || 1)}
                            />
                          </TableCell>
                          <TableCell>
                            <Select
                              sizing="sm"
                              value={edits.grade ?? item.grade ?? ''}
                              onChange={e => handleBizItemEdit(item.biz_item_id, 'grade', parseInt(e.target.value))}
                            >
                              <option value="">미설정</option>
                              {GRADE_OPTIONS.map(g => (
                                <option key={g} value={g}>{g}</option>
                              ))}
                            </Select>
                          </TableCell>
                          <TableCell>
                            <Select
                              sizing="sm"
                              value={edits.section_hint ?? item.section_hint ?? ''}
                              onChange={e => handleBizItemEdit(item.biz_item_id, 'section_hint', e.target.value)}
                            >
                              <option value="">미배정</option>
                              <option value="party">파티만</option>
                            </Select>
                          </TableCell>
                          <TableCell>
                            <Select
                              sizing="sm"
                              value={edits.default_party_type ?? item.default_party_type ?? ''}
                              onChange={e => handleBizItemEdit(item.biz_item_id, 'default_party_type', e.target.value)}
                            >
                              <option value="">없음</option>
                              <option value="1">1차만</option>
                              <option value="2">1+2차</option>
                              <option value="2차만">2차만</option>
                            </Select>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <div className="empty-state">
                <p className="text-label text-[#8B95A1]">동기화된 상품이 없습니다. 상품 동기화를 먼저 진행해주세요.</p>
              </div>
            )}
          </div>
        </ModalBody>
        <ModalFooter>
          <Button color="light" onClick={() => setBizItemModalOpen(false)}>닫기</Button>
          <Button color="blue" onClick={handleBizItemSave} disabled={bizItemSaving || Object.keys(bizItemEdits).length === 0}>
            {bizItemSaving ? (
              <><Spinner size="sm" className="mr-2" />저장 중...</>
            ) : (
              '저장'
            )}
          </Button>
        </ModalFooter>
      </Modal>

      {/* 객실 등급 설정 모달 — room_upgrade_review (객후) 칩 발송 조건 */}
      <Modal size="lg" show={roomGradeModalOpen} onClose={() => setRoomGradeModalOpen(false)}>
        <ModalHeader>객실 등급 설정</ModalHeader>
        <ModalBody>
          <div className="space-y-4">
            <p className="text-caption text-[#8B95A1]">
              가이드: {GRADE_GUIDE_TEXT} · 무료 업그레이드 안내 SMS(객후) 발송 조건으로 사용됩니다.
            </p>
            {rooms.length === 0 ? (
              <div className="empty-state">
                <p className="text-label text-[#8B95A1]">등록된 객실이 없습니다.</p>
              </div>
            ) : (
              <div className="rounded-lg border border-[#E5E8EB] dark:border-gray-700">
                <Table className="whitespace-nowrap">
                  <TableHead>
                    <TableRow>
                      <TableHeadCell className="text-caption">객실</TableHeadCell>
                      <TableHeadCell className="text-caption">타입</TableHeadCell>
                      <TableHeadCell className="text-caption">건물</TableHeadCell>
                      <TableHeadCell className="text-caption w-32">등급</TableHeadCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {rooms.map(room => {
                      const current = roomGradeEdits[room.id];
                      const displayValue = typeof current === 'number' ? current : (room.grade ?? '');
                      return (
                        <TableRow key={room.id}>
                          <TableCell>
                            <span className="text-body font-medium text-[#191F28] dark:text-white">
                              {room.room_number}
                            </span>
                          </TableCell>
                          <TableCell>
                            <span className="text-caption text-[#8B95A1]">{room.room_type}</span>
                          </TableCell>
                          <TableCell>
                            <span className="text-caption text-[#8B95A1]">{room.building_name ?? '-'}</span>
                          </TableCell>
                          <TableCell>
                            <Select
                              sizing="sm"
                              value={displayValue}
                              onChange={e => handleRoomGradeChange(room.id, parseInt(e.target.value))}
                              className="min-w-[80px]"
                            >
                              <option value="" disabled>미설정</option>
                              {GRADE_OPTIONS.map(g => (
                                <option key={g} value={g}>{g}</option>
                              ))}
                            </Select>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            )}
          </div>
        </ModalBody>
        <ModalFooter>
          <Button color="light" onClick={() => setRoomGradeModalOpen(false)}>닫기</Button>
          <Button color="blue" onClick={handleRoomGradeSave} disabled={roomGradeSaving}>
            {roomGradeSaving ? (
              <><Spinner size="sm" className="mr-2" />저장 중...</>
            ) : (
              '저장'
            )}
          </Button>
        </ModalFooter>
      </Modal>
    </div>
  );
};

export default RoomSettings;
