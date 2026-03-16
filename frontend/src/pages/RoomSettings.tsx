import { useEffect, useState, DragEvent } from 'react';
import { Home, Plus, Pencil, Trash2, GripVertical, RefreshCw, Building2, ChevronDown, ChevronUp } from 'lucide-react';
import { toast } from 'sonner';
import { roomsAPI, buildingsAPI } from '@/services/api';

import {
  Button,
  Modal,
  ModalHeader,
  ModalBody,
  ModalFooter,
  TextInput,
  Label,
  ToggleSwitch,
  Badge,
  Spinner,
  Table,
  TableHead,
  TableHeadCell,
  TableBody,
  TableRow,
  TableCell,
  Select,
  Textarea,
} from 'flowbite-react';

// ── Types ─────────────────────────────────────────────

interface Building {
  id: number;
  name: string;
  description?: string | null;
  room_count?: number;
}

interface BuildingForm {
  name: string;
  description: string;
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
  dormitory: boolean;
  bed_capacity?: number | null;
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
  dormitory: false,
  bed_capacity: 1,
  door_password: '',
  building_id: null,
};

const EMPTY_BUILDING_FORM: BuildingForm = {
  name: '',
  description: '',
};

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
  const [syncingBizItems, setSyncingBizItems] = useState(false);

  // ── Buildings state ──
  const [buildings, setBuildings] = useState<Building[]>([]);
  const [buildingsLoading, setBuildingsLoading] = useState(false);
  const [buildingSectionOpen, setBuildingSectionOpen] = useState(true);
  const [buildingDialogOpen, setBuildingDialogOpen] = useState(false);
  const [editingBuildingId, setEditingBuildingId] = useState<number | null>(null);
  const [buildingForm, setBuildingForm] = useState<BuildingForm>(EMPTY_BUILDING_FORM);
  const [savingBuilding, setSavingBuilding] = useState(false);
  const [deleteBuildingTarget, setDeleteBuildingTarget] = useState<Building | null>(null);

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


  // ── Naver sync ──
  const handleSyncBizItems = async () => {
    setSyncingBizItems(true);
    try {
      const res = await roomsAPI.syncBizItems();
      toast.success(`네이버 상품 동기화 완료 (${res.data.added}건 추가, ${res.data.updated}건 갱신)`);
      loadBizItems();
    } catch {
      toast.error('상품 동기화 실패');
    } finally {
      setSyncingBizItems(false);
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
    setForm({
      room_number: room.room_number,
      room_type: room.room_type,
      base_capacity: room.base_capacity,
      max_capacity: room.max_capacity,
      sort_order: room.sort_order,
      active: room.active,
      biz_item_ids: ids,
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
      return { ...f, biz_item_ids: newIds, room_type: newRoomType };
    });
  };

  const handleSubmit = async () => {
    if (!form.room_number.trim() || !form.room_type.trim()) {
      toast.error('객실 번호와 타입은 필수입니다');
      return;
    }
    setSaving(true);
    try {
      if (editingId !== null) {
        await roomsAPI.update(editingId, form);
        toast.success('수정 완료');
      } else {
        await roomsAPI.create(form);
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

  // ── Building CRUD ──
  const openCreateBuilding = () => {
    setEditingBuildingId(null);
    setBuildingForm(EMPTY_BUILDING_FORM);
    setBuildingDialogOpen(true);
  };

  const openEditBuilding = (building: Building) => {
    setEditingBuildingId(building.id);
    setBuildingForm({
      name: building.name,
      description: building.description || '',
    });
    setBuildingDialogOpen(true);
  };

  const handleBuildingSubmit = async () => {
    if (!buildingForm.name.trim()) {
      toast.error('건물 이름은 필수입니다');
      return;
    }
    setSavingBuilding(true);
    try {
      const payload = { ...buildingForm };
      if (editingBuildingId !== null) {
        await buildingsAPI.update(editingBuildingId, payload);
        toast.success('건물 수정 완료');
      } else {
        await buildingsAPI.create(payload);
        toast.success('건물 추가 완료');
      }
      setBuildingDialogOpen(false);
      loadBuildings();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || '저장 실패');
    } finally {
      setSavingBuilding(false);
    }
  };

  const confirmDeleteBuilding = async () => {
    if (!deleteBuildingTarget) return;
    try {
      await buildingsAPI.delete(deleteBuildingTarget.id);
      toast.success('건물 삭제 완료');
      loadBuildings();
      loadRooms();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || '삭제 실패');
    } finally {
      setDeleteBuildingTarget(null);
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
          <div className="ml-auto flex items-center gap-2">
            <Button color="light" size="sm" onClick={handleSyncBizItems} disabled={syncingBizItems}>
              {syncingBizItems ? (
                <Spinner size="sm" className="mr-1.5" />
              ) : (
                <RefreshCw className="mr-1.5 h-4 w-4" />
              )}
              상품 동기화
            </Button>
            <Button color="blue" size="sm" onClick={openCreate}>
              <Plus className="mr-1.5 h-4 w-4" />
              객실 추가
            </Button>
          </div>
        </div>
      </div>

      {/* ── Building Management Section ── */}
      <div className="section-card">
        <div className="section-header cursor-pointer select-none" onClick={() => setBuildingSectionOpen((v) => !v)}>
          <div className="flex items-center gap-2">
            <Building2 size={16} className="text-[#3182F6]" />
            <span className="text-subheading font-semibold text-[#191F28] dark:text-white">건물 관리</span>
            {buildings.length > 0 && (
              <Badge color="info" size="sm">{buildings.length}</Badge>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button
              color="blue"
              size="sm"
              onClick={(e) => { e.stopPropagation(); openCreateBuilding(); }}
            >
              <Plus className="mr-1.5 h-3.5 w-3.5" />
              건물 추가
            </Button>
            {buildingSectionOpen ? (
              <ChevronUp size={16} className="text-[#8B95A1] dark:text-gray-500" />
            ) : (
              <ChevronDown size={16} className="text-[#8B95A1] dark:text-gray-500" />
            )}
          </div>
        </div>

        {buildingSectionOpen && (
          <>
            {buildingsLoading ? (
              <div className="flex items-center justify-center py-10">
                <Spinner size="md" />
              </div>
            ) : buildings.length === 0 ? (
              <div className="empty-state py-10">
                <Building2 size={36} strokeWidth={1} className="text-[#B0B8C1] dark:text-gray-600" />
                <p className="text-body text-[#8B95A1] dark:text-gray-500">등록된 건물이 없습니다</p>
                <Button color="light" size="sm" onClick={openCreateBuilding} className="mt-2">
                  <Plus className="mr-1.5 h-3.5 w-3.5" />
                  건물 추가
                </Button>
              </div>
            ) : (
              <Table hoverable>
                <TableHead>
                  <TableRow>
                    <TableHeadCell>이름</TableHeadCell>
                    <TableHeadCell>설명</TableHeadCell>
                    <TableHeadCell className="w-px text-center">객실 수</TableHeadCell>
                    <TableHeadCell className="w-px text-center">작업</TableHeadCell>
                  </TableRow>
                </TableHead>
                <TableBody className="divide-y">
                  {buildings.map((building) => (
                    <TableRow key={building.id}>
                      <TableCell className="font-semibold text-[#191F28] dark:text-white">
                        {building.name}
                      </TableCell>
                      <TableCell className="text-[#4E5968] dark:text-gray-400">
                        {building.description || (
                          <span className="text-caption text-[#B0B8C1] dark:text-gray-600">-</span>
                        )}
                      </TableCell>
                      <TableCell className="text-center">
                        <span className="tabular-nums font-semibold text-[#191F28] dark:text-white">
                          {building.room_count ?? rooms.filter((r) => r.building_id === building.id).length}
                        </span>
                        <span className="ml-0.5 text-label font-normal text-[#B0B8C1]">개</span>
                      </TableCell>
                      <TableCell className="text-center">
                        <div className="flex justify-center gap-1">
                          <Button color="light" size="xs" onClick={() => openEditBuilding(building)}>
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button color="failure" size="xs" onClick={() => setDeleteBuildingTarget(building)}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </>
        )}
      </div>

      {/* ── Room List Section ── */}
      <div className="section-card">
        <div className="section-header">
          <div className="flex items-center gap-2">
            <Home size={16} className="text-[#3182F6]" />
            <span className="text-subheading font-semibold text-[#191F28] dark:text-white">객실 목록</span>
          </div>
          <div className="flex items-center gap-1.5 text-caption text-[#B0B8C1] dark:text-gray-600">
            <GripVertical size={14} />
            <span>드래그하여 순서 변경</span>
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
              <div className="flex items-center gap-2">
                <Label className="mb-0">도미토리</Label>
                <span className={`text-body font-medium ${form.dormitory ? 'text-[#9061F9]' : 'text-[#B0B8C1]'}`}>
                  {form.dormitory ? '도미토리' : '일반'}
                </span>
              </div>
              <ToggleSwitch
                checked={form.dormitory}
                onChange={(v) => setForm((f) => ({ ...f, dormitory: v }))}
              />
              {form.dormitory && (
                <div className="space-y-1 pt-1">
                  <Label htmlFor="dormitory-beds">인실 수</Label>
                  <TextInput
                    id="dormitory-beds"
                    type="number"
                    min={1}
                    max={20}
                    value={String(form.bed_capacity ?? 1)}
                    onChange={(e) => setForm((f) => ({ ...f, bed_capacity: parseInt(e.target.value) || 1 }))}
                  />
                </div>
              )}
            </div>
          </div>
        </ModalBody>
        <ModalFooter>
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
          <Button color="light" onClick={() => setDialogOpen(false)}>취소</Button>
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

      {/* ── Building Modal ── */}
      <Modal show={buildingDialogOpen} onClose={() => setBuildingDialogOpen(false)} size="md">
        <ModalHeader>{editingBuildingId !== null ? '건물 수정' : '건물 추가'}</ModalHeader>
        <ModalBody>
          <div className="flex flex-col gap-4">
            <div className="space-y-2">
              <Label htmlFor="building-name">
                건물 이름 <span className="text-[#F04452] dark:text-red-400">*</span>
              </Label>
              <TextInput
                id="building-name"
                value={buildingForm.name}
                onChange={(e) => setBuildingForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="본관"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="building-description">설명</Label>
              <Textarea
                id="building-description"
                value={buildingForm.description}
                onChange={(e) => setBuildingForm((f) => ({ ...f, description: e.target.value }))}
                placeholder="건물에 대한 설명을 입력하세요"
                rows={2}
              />
            </div>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button color="blue" onClick={handleBuildingSubmit} disabled={savingBuilding}>
            {savingBuilding ? (
              <>
                <Spinner size="sm" className="mr-2" />
                저장 중...
              </>
            ) : (
              '저장'
            )}
          </Button>
          <Button color="light" onClick={() => setBuildingDialogOpen(false)}>취소</Button>
        </ModalFooter>
      </Modal>

      {/* ── Building Delete Confirm ── */}
      <Modal show={!!deleteBuildingTarget} onClose={() => setDeleteBuildingTarget(null)} size="md" popup>
        <ModalHeader />
        <ModalBody>
          <div className="text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#FFEBEE] dark:bg-[#F04452]/10">
              <Building2 className="h-6 w-6 text-[#F04452] dark:text-red-400" />
            </div>
            <h3 className="mb-2 text-heading font-semibold text-[#191F28] dark:text-white">건물 삭제</h3>
            <p className="mb-5 text-body text-[#8B95A1] dark:text-gray-400">
              건물 <strong>"{deleteBuildingTarget?.name}"</strong>을(를) 정말 삭제하시겠습니까?
              이 건물에 배정된 객실의 건물 정보가 해제됩니다.
            </p>
            <div className="flex justify-center gap-3">
              <Button color="failure" onClick={confirmDeleteBuilding}>삭제</Button>
              <Button color="light" onClick={() => setDeleteBuildingTarget(null)}>취소</Button>
            </div>
          </div>
        </ModalBody>
      </Modal>
    </div>
  );
};

export default RoomSettings;
