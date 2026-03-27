import { useEffect, useState, useCallback, DragEvent } from 'react';
import { Home, Plus, Pencil, Trash2, GripVertical, RefreshCw, Building2, ArrowUpDown, Settings } from 'lucide-react';
import { toast } from 'sonner';
import { roomsAPI, buildingsAPI } from '@/services/api';

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
}

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
  building_id: null,
};

// EMPTY_BUILDING_FORM removed — building editing is now inline in manage modal

// ── Component ─────────────────────────────────────────

const RoomSettings = () => {
  // ── Rooms state ──
  const [rooms, setRooms] = useState<Room[]>([]);
  const [loading, setLoading] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<RoomForm>(EMPTY_ROOM_FORM);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Room | null>(null);
  const [draggingIndex, setDraggingIndex] = useState<number | null>(null);
  const [bizItems, setBizItems] = useState<NaverBizItem[]>([]);
  // ── Buildings state ──
  const [buildings, setBuildings] = useState<Building[]>([]);
  const [buildingsLoading, setBuildingsLoading] = useState(false);
  const [buildingManageOpen, setBuildingManageOpen] = useState(false);
  const [buildingRows, setBuildingRows] = useState<BuildingEditRow[]>([]);
  const [buildingHistory, setBuildingHistory] = useState<BuildingEditRow[][]>([]);
  const [savingBuildings, setSavingBuildings] = useState(false);

  // ── Priority modal state ──
  const [priorityOpen, setPriorityOpen] = useState(false);
  // { [biz_item_id]: { [room_id]: { male_priority, female_priority } } }
  const [priorityData, setPriorityData] = useState<Record<string, Record<number, { male_priority: number; female_priority: number }>>>({});
  const [savingPriority, setSavingPriority] = useState(false);

  // ── Biz item settings modal state ──
  const [bizItemModalOpen, setBizItemModalOpen] = useState(false);
  const [bizItemSettingsList, setBizItemSettingsList] = useState<Array<{
    biz_item_id: string;
    name: string;
    display_name: string;
    default_capacity: number;
    section_hint: string;
    active: boolean;
    exposed?: boolean;
  }>>([]);
  const [bizItemEdits, setBizItemEdits] = useState<Record<string, {display_name?: string; default_capacity?: number; section_hint?: string}>>({});
  const [bizItemSaving, setBizItemSaving] = useState(false);
  const [bizItemSyncing, setBizItemSyncing] = useState(false);

  // ── Init ──
  useEffect(() => {
    loadRooms();
    loadBizItems();
    loadBuildings();
  }, []);

  // ── Loaders ──
  const loadRooms = async () => {
    setLoading(true);
    try {
      const res = await roomsAPI.getAll({ include_inactive: true });
      setRooms(res.data);
    } catch {
      toast.error('객실 목록 로드 실패');
    } finally {
      setLoading(false);
    }
  };

  const loadBizItems = async () => {
    try {
      const res = await roomsAPI.getBizItems();
      setBizItems(res.data);
    } catch {
      // silently fail - biz items are optional
    }
  };

  const loadBuildings = async () => {
    setBuildingsLoading(true);
    try {
      const res = await buildingsAPI.getAll();
      setBuildings(res.data);
    } catch {
      toast.error('건물 목록 로드 실패');
    } finally {
      setBuildingsLoading(false);
    }
  };


  // ── Biz item settings modal ──
  const loadBizItemSettings = useCallback(async () => {
    try {
      const res = await roomsAPI.getBizItems();
      setBizItemSettingsList(res.data || []);
      setBizItemEdits({});
    } catch {
      toast.error('상품 목록을 불러오지 못했습니다.');
    }
  }, []);

  useEffect(() => {
    if (bizItemModalOpen) loadBizItemSettings();
  }, [bizItemModalOpen, loadBizItemSettings]);

  const handleBizItemEdit = (bizItemId: string, field: string, value: string | number) => {
    setBizItemEdits(prev => ({
      ...prev,
      [bizItemId]: { ...prev[bizItemId], [field]: value }
    }));
  };

  const handleBizItemSave = async () => {
    const changes = Object.entries(bizItemEdits).map(([biz_item_id, edits]) => ({
      biz_item_id,
      ...edits,
    }));
    if (changes.length === 0) {
      setBizItemModalOpen(false);
      return;
    }
    setBizItemSaving(true);
    try {
      await roomsAPI.updateBizItems(changes);
      toast.success('상품 설정이 저장되었습니다.');
      await loadBizItemSettings();
    } catch {
      toast.error('상품 설정 저장에 실패했습니다.');
    } finally {
      setBizItemSaving(false);
    }
  };

  const handleBizItemSync = async () => {
    setBizItemSyncing(true);
    try {
      await roomsAPI.syncBizItems();
      toast.success('네이버 상품 동기화 완료');
      await loadBizItemSettings();
    } catch {
      toast.error('네이버 상품 동기화에 실패했습니다.');
    } finally {
      setBizItemSyncing(false);
    }
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

  const updatePriority = (bizItemId: string, field: 'male_priority' | 'female_priority', value: number) => {
    setForm((f) => ({
      ...f,
      biz_item_priorities: {
        ...f.biz_item_priorities,
        [bizItemId]: {
          ...(f.biz_item_priorities[bizItemId] || { male_priority: 0, female_priority: 0 }),
          [field]: value,
        },
      },
    }));
  };

  const handleSubmit = async () => {
    if (!form.room_number.trim() || !form.room_type.trim()) {
      toast.error('객실 번호와 타입은 필수입니다');
      return;
    }
    setSaving(true);
    try {
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
      if (editingId !== null) {
        await roomsAPI.update(editingId, payload);
        toast.success('수정 완료');
      } else {
        await roomsAPI.create(payload);
        toast.success('추가 완료');
      }
      setDialogOpen(false);
      loadRooms();
      loadBuildings();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || '저장 실패');
    } finally {
      setSaving(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      await roomsAPI.delete(deleteTarget.id);
      toast.success('삭제 완료');
      loadRooms();
      loadBuildings();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || '삭제 실패');
    } finally {
      setDeleteTarget(null);
    }
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

  const handleBuildingSaveAll = async () => {
    const visibleRows = buildingRows.filter((r) => !r._deleted);
    if (visibleRows.some((r) => !r.name.trim())) {
      toast.error('건물 이름을 입력하세요');
      return;
    }
    setSavingBuildings(true);
    try {
      // Delete removed buildings
      const deletedIds = buildingRows.filter((r) => r._deleted && r.id !== null).map((r) => r.id!);
      for (const id of deletedIds) {
        await buildingsAPI.delete(id);
      }
      // Create or update
      for (const row of visibleRows) {
        if (row.id === null) {
          await buildingsAPI.create({ name: row.name.trim(), description: row.description.trim() });
        } else {
          const original = buildings.find((b) => b.id === row.id);
          if (original && (original.name !== row.name.trim() || (original.description || '') !== row.description.trim())) {
            await buildingsAPI.update(row.id, { name: row.name.trim(), description: row.description.trim() });
          }
        }
      }
      toast.success('건물 저장 완료');
      setBuildingManageOpen(false);
      loadBuildings();
      loadRooms();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || '저장 실패');
    } finally {
      setSavingBuildings(false);
    }
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

  const handlePrioritySave = async () => {
    setSavingPriority(true);
    try {
      // Group by room_id: collect all biz_item_links for each room
      const roomLinks: Record<number, { biz_item_id: string; male_priority: number; female_priority: number }[]> = {};
      for (const [bizItemId, roomMap] of Object.entries(priorityData)) {
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
      // Update each room with its biz_item_links
      await Promise.all(
        Object.entries(roomLinks).map(([roomIdStr, links]) =>
          roomsAPI.update(Number(roomIdStr), { biz_item_links: links })
        )
      );
      toast.success('배정 순서 저장 완료');
      setPriorityOpen(false);
      loadRooms();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || '저장 실패');
    } finally {
      setSavingPriority(false);
    }
  };

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

  const onDrop = async (e: DragEvent, targetIndex: number) => {
    e.preventDefault();
    setDraggingIndex(null);

    const sourceIndex = parseInt(e.dataTransfer.getData('text/plain'), 10);
    if (sourceIndex === targetIndex) return;

    const newRooms = [...rooms];
    const [moved] = newRooms.splice(sourceIndex, 1);
    newRooms.splice(targetIndex, 0, moved);
    setRooms(newRooms);

    try {
      await Promise.all(
        newRooms.map((room, idx) => roomsAPI.update(room.id, { sort_order: idx + 1 }))
      );
      toast.success('정렬 순서 변경 완료');
      loadRooms();
    } catch {
      toast.error('정렬 순서 변경 실패');
      loadRooms();
    }
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
                      <span className="text-caption text-[#B0B8C1] dark:text-gray-600">자동</span>
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
              <Label htmlFor="default-password">객실 비밀번호</Label>
              <TextInput
                id="default-password"
                placeholder="비어있으면 자동 생성"
                value={form.door_password}
                onChange={(e) => setForm((f) => ({ ...f, door_password: e.target.value }))}
              />
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
        <ModalHeader>건물 관리</ModalHeader>
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
          <div className="flex w-full items-center justify-between">
            <Button color="light" size="sm" onClick={() => setBuildingManageOpen(false)}>
              취소
            </Button>
            <div className="flex items-center gap-2">
              <Button
                color="light"
                size="sm"
                disabled={buildingHistory.length === 0}
                onClick={handleBuildingUndo}
              >
                되돌리기
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
          <Button color="light" onClick={() => setPriorityOpen(false)}>취소</Button>
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

            {bizItemSettingsList.length > 0 ? (
              <div className="rounded-lg border border-[#E5E8EB] dark:border-gray-700">
                <Table className="whitespace-nowrap">
                  <TableHead>
                    <TableRow>
                      <TableHeadCell className="text-caption">상품명 (네이버)</TableHeadCell>
                      <TableHeadCell className="text-caption">표시명</TableHeadCell>
                      <TableHeadCell className="text-caption w-24">기준인원</TableHeadCell>
                      <TableHeadCell className="text-caption w-28">섹션</TableHeadCell>
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
                              value={edits.section_hint ?? item.section_hint ?? ''}
                              onChange={e => handleBizItemEdit(item.biz_item_id, 'section_hint', e.target.value)}
                            >
                              <option value="">미배정</option>
                              <option value="party">파티만</option>
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
    </div>
  );
};

export default RoomSettings;
