import { useEffect, useState, DragEvent } from 'react';
import { Home, Plus, Pencil, Trash2, GripVertical, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { roomsAPI } from '@/services/api';

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
} from 'flowbite-react';

interface Room {
  id: number;
  room_number: string;
  room_type: string;
  base_capacity: number;
  max_capacity: number;
  is_active: boolean;
  sort_order: number;
  created_at: string;
  naver_biz_item_id?: string | null;
  is_dormitory: boolean;
  dormitory_beds: number;
  default_password?: string | null;
}

interface RoomForm {
  room_number: string;
  room_type: string;
  base_capacity: number;
  max_capacity: number;
  sort_order: number;
  is_active: boolean;
  naver_biz_item_id: string;
  is_dormitory: boolean;
  dormitory_beds: number;
  default_password: string;
}

interface NaverBizItem {
  id: number;
  biz_item_id: string;
  name: string;
  biz_item_type?: string | null;
  is_exposed?: boolean;
  is_active: boolean;
  is_dormitory: boolean;
  dormitory_beds?: number | null;
}

const EMPTY_FORM: RoomForm = {
  room_number: '',
  room_type: '',
  base_capacity: 2,
  max_capacity: 4,
  sort_order: 1,
  is_active: true,
  naver_biz_item_id: '',
  is_dormitory: false,
  dormitory_beds: 1,
  default_password: '',
};

const RoomManagement = () => {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [loading, setLoading] = useState(false);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<RoomForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  const [deleteTarget, setDeleteTarget] = useState<Room | null>(null);

  const [draggingIndex, setDraggingIndex] = useState<number | null>(null);

  const [bizItems, setBizItems] = useState<NaverBizItem[]>([]);
  const [syncingBizItems, setSyncingBizItems] = useState(false);

  useEffect(() => {
    loadRooms();
    loadBizItems();
  }, []);

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

  const openCreate = () => {
    setEditingId(null);
    setForm({ ...EMPTY_FORM, sort_order: rooms.length + 1 });
    setDialogOpen(true);
  };

  const openEdit = (room: Room) => {
    setEditingId(room.id);
    setForm({
      room_number: room.room_number,
      room_type: room.room_type,
      base_capacity: room.base_capacity,
      max_capacity: room.max_capacity,
      sort_order: room.sort_order,
      is_active: room.is_active,
      naver_biz_item_id: room.naver_biz_item_id || '',
      is_dormitory: room.is_dormitory || false,
      dormitory_beds: room.dormitory_beds || 1,
      default_password: room.default_password || '',
    });
    setDialogOpen(true);
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
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || '삭제 실패');
    } finally {
      setDeleteTarget(null);
    }
  };

  // ── Drag and Drop ────────────────────────────────────

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

  // ── Render ───────────────────────────────────────────

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2.5">
          <div className="stat-icon bg-[#E8F3FF] text-[#3182F6] dark:bg-[#3182F6]/15 dark:text-[#3182F6]">
            <Home size={20} />
          </div>
          <div>
            <h1 className="page-title">객실 설정</h1>
            <p className="page-subtitle">객실을 추가, 수정, 삭제하고 순서를 변경합니다.</p>
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

      {/* 네이버 상품 도미토리 설정 */}
      {bizItems.length > 0 && (
        <div className="section-card">
          <div className="section-header">
            <span className="text-subheading font-semibold">네이버 상품 · 도미토리 설정</span>
          </div>
          <div className="px-5 pb-4">
            <div className="flex flex-col gap-2">
              {bizItems.map((item) => (
                <div key={item.biz_item_id} className={`flex items-center gap-3 rounded-lg px-3 py-2 transition-colors ${
                  item.is_dormitory
                    ? 'bg-[#9061F9]/10 ring-1 ring-[#9061F9]/30'
                    : 'bg-gray-50 dark:bg-[#2C2C34]'
                }`}>
                  <button
                    onClick={async () => {
                      const newVal = !item.is_dormitory;
                      try {
                        await roomsAPI.updateBizItem(item.biz_item_id, {
                          is_dormitory: newVal,
                          dormitory_beds: newVal ? (item.dormitory_beds || 4) : null,
                        });
                        setBizItems((prev) =>
                          prev.map((b) =>
                            b.biz_item_id === item.biz_item_id
                              ? { ...b, is_dormitory: newVal, dormitory_beds: newVal ? (b.dormitory_beds || 4) : null }
                              : b
                          )
                        );
                      } catch {
                        toast.error('설정 변경 실패');
                      }
                    }}
                    className={`shrink-0 rounded px-2 py-0.5 text-tiny font-semibold ${
                      item.is_dormitory ? 'bg-[#9061F9] text-white' : 'bg-gray-200 text-[#8B95A1] dark:bg-gray-700'
                    }`}
                  >
                    {item.is_dormitory ? '도미토리' : '일반'}
                  </button>
                  <span className="text-body flex-1">{item.name}</span>
                  {item.is_dormitory && (
                    <select
                      value={item.dormitory_beds || 4}
                      onChange={async (e) => {
                        const beds = parseInt(e.target.value);
                        try {
                          await roomsAPI.updateBizItem(item.biz_item_id, { dormitory_beds: beds });
                          setBizItems((prev) =>
                            prev.map((b) =>
                              b.biz_item_id === item.biz_item_id ? { ...b, dormitory_beds: beds } : b
                            )
                          );
                        } catch {
                          toast.error('인실 수 변경 실패');
                        }
                      }}
                      className="rounded-lg border border-gray-300 bg-white px-2 py-1 text-caption dark:border-gray-600 dark:bg-[#1E1E24]"
                    >
                      <option value={2}>2인실</option>
                      <option value={4}>4인실</option>
                      <option value={6}>6인실</option>
                      <option value={8}>8인실</option>
                    </select>
                  )}
                </div>
              ))}
            </div>
            <p className="mt-2 text-caption text-[#B0B8C1]">일반/도미토리를 클릭하여 전환. 도미토리는 인실 수를 선택하세요.</p>
          </div>
        </div>
      )}

      <div className="section-card">
        <div className="section-header">
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
                  className={`transition-opacity ${
                    draggingIndex === index ? 'opacity-40' : ''
                  }`}
                >
                  <TableCell className="text-center px-3">
                    <GripVertical size={16} className="drag-handle mx-auto" />
                  </TableCell>
                  <TableCell className="text-center tabular-nums font-semibold text-[#8B95A1] dark:text-gray-500">
                    {index + 1}
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
                      <span className={`text-body font-medium ${room.is_active ? 'text-[#00C9A7]' : 'text-[#F04452]'}`}>
                        {room.is_active ? '활성' : '비활성'}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="text-center text-[#4E5968] dark:text-gray-400">
                    {room.default_password ? (
                      <span className="tabular-nums font-medium">{room.default_password}</span>
                    ) : (
                      <span className="text-caption text-[#B0B8C1] dark:text-gray-600">자동</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-center">
                      {room.is_dormitory ? (
                        <Badge color="purple" size="sm">{room.dormitory_beds}인실</Badge>
                      ) : (
                        <span className="text-caption text-[#B0B8C1] dark:text-gray-600">-</span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="text-center text-xs">
                    {room.naver_biz_item_id
                      ? (() => {
                          const item = bizItems.find((b) => b.biz_item_id === room.naver_biz_item_id);
                          if (!item) return <span className="text-gray-500">{room.naver_biz_item_id}</span>;
                          return item.is_exposed === false
                            ? <span className="text-[#B0B8C1]">[미노출] {item.name}</span>
                            : <span className="text-gray-500">{item.name}</span>;
                        })()
                      : '-'}
                  </TableCell>
                  <TableCell />
                  <TableCell className="text-center">
                    <div className="flex justify-center gap-1">
                      <Button
                        color="light"
                        size="xs"
                        onClick={() => openEdit(room)}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        color="light"
                        size="xs"
                        onClick={() => setDeleteTarget(room)}
                      >
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

      {/* Room Modal */}
      <Modal show={dialogOpen} onClose={() => setDialogOpen(false)} size="md">
        <ModalHeader>{editingId !== null ? '객실 수정' : '객실 추가'}</ModalHeader>
        <ModalBody>
          <div className="flex flex-col gap-5">
            <div className="space-y-2">
              <Label htmlFor="room-number">객실 번호 <span className="text-[#F04452] dark:text-red-400">*</span></Label>
              <TextInput
                id="room-number"
                value={form.room_number}
                onChange={(e) => setForm((f) => ({ ...f, room_number: e.target.value }))}
                placeholder="A101"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="room-biz-item">네이버 상품 연동</Label>
              <Select
                id="room-biz-item"
                value={form.naver_biz_item_id}
                onChange={(e) => {
                  const selectedId = e.target.value;
                  if (selectedId) {
                    const item = bizItems.find((b) => b.biz_item_id === selectedId);
                    if (item) {
                      setForm((f) => ({ ...f, naver_biz_item_id: selectedId, room_type: item.name }));
                    } else {
                      setForm((f) => ({ ...f, naver_biz_item_id: selectedId }));
                    }
                  } else {
                    setForm((f) => ({ ...f, naver_biz_item_id: selectedId }));
                  }
                }}
              >
                <option value="">선택 안 함</option>
                {bizItems.map((item) => (
                  <option
                    key={item.biz_item_id}
                    value={item.biz_item_id}
                    style={item.is_exposed === false ? { color: '#B0B8C1' } : undefined}
                  >
                    {item.is_exposed === false ? `[미노출] ${item.name}` : item.name}
                  </option>
                ))}
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="room-type">객실 타입 <span className="text-[#F04452] dark:text-red-400">*</span></Label>
              <TextInput
                id="room-type"
                value={form.room_type}
                onChange={(e) => setForm((f) => ({ ...f, room_type: e.target.value }))}
                placeholder="더블룸"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="base-capacity" className={form.is_dormitory ? 'text-[#B0B8C1]' : ''}>기준 인원</Label>
                <TextInput
                  id="base-capacity"
                  type="number"
                  min={1}
                  value={String(form.base_capacity ?? 2)}
                  onChange={(e) => setForm((f) => ({ ...f, base_capacity: parseInt(e.target.value) || 1 }))}
                  disabled={form.is_dormitory}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="max-capacity" className={form.is_dormitory ? 'text-[#B0B8C1]' : ''}>최대 인원</Label>
                <TextInput
                  id="max-capacity"
                  type="number"
                  min={1}
                  value={String(form.max_capacity ?? 4)}
                  onChange={(e) => setForm((f) => ({ ...f, max_capacity: parseInt(e.target.value) || 1 }))}
                  disabled={form.is_dormitory}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="default-password">객실 비밀번호</Label>
              <TextInput
                id="default-password"
                placeholder="비어있으면 자동 생성"
                value={form.default_password}
                onChange={(e) => setForm((f) => ({ ...f, default_password: e.target.value }))}
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <Label className="mb-0">객실 상태</Label>
                <span className={`text-body font-medium ${form.is_active ? 'text-[#00C9A7]' : 'text-[#F04452]'}`}>
                  {form.is_active ? '활성' : '비활성'}
                </span>
              </div>
              <ToggleSwitch
                checked={form.is_active}
                onChange={(v) => setForm((f) => ({ ...f, is_active: v }))}
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <Label className="mb-0">도미토리</Label>
                <span className={`text-body font-medium ${form.is_dormitory ? 'text-[#9061F9]' : 'text-[#B0B8C1]'}`}>
                  {form.is_dormitory ? '도미토리' : '일반'}
                </span>
              </div>
              <ToggleSwitch
                checked={form.is_dormitory}
                onChange={(v) => setForm((f) => ({ ...f, is_dormitory: v }))}
              />
              {form.is_dormitory && (
                <div className="space-y-1 pt-1">
                  <Label htmlFor="dormitory-beds">인실 수</Label>
                  <TextInput
                    id="dormitory-beds"
                    type="number"
                    min={1}
                    max={20}
                    value={String(form.dormitory_beds ?? 1)}
                    onChange={(e) => setForm((f) => ({ ...f, dormitory_beds: parseInt(e.target.value) || 1 }))}
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

      {/* Delete Confirm Modal */}
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
    </div>
  );
};

export default RoomManagement;
