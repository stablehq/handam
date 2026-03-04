import { useState, useEffect, useMemo } from 'react';
import {
  RefreshCw,
  Plus,
  Pencil,
  Trash2,
  CheckCircle,
  Clock,
  XCircle,
  ShoppingBag,
  CalendarDays,
} from 'lucide-react';
import { toast } from 'sonner';
import dayjs from 'dayjs';

import { reservationsAPI } from '@/services/api';

import {
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableHeadCell,
  TableCell,
  Badge,
  Button,
  Modal,
  ModalHeader,
  ModalBody,
  ModalFooter,
  Label,
  Select,
  TextInput,
  Textarea,
  Spinner,
} from 'flowbite-react';

const TAG_OPTIONS = ['1초', '2차만', '객후', '객후,1초', '1초,2차만'];

interface Reservation {
  id: number;
  external_id?: string | null;
  customer_name: string;
  phone: string;
  date: string;
  time?: string | null;
  status: string;
  source?: string | null;
  party_participants?: number | null;
  gender?: string | null;
  room_info?: string | null;
  room_number?: string | null;
  tags?: string | null;
  notes?: string | null;
}

interface FormState {
  customer_name: string;
  phone: string;
  reservation_date: string;
  reservation_time: string;
  status: string;
  party_size: string;
  gender: string;
  room_type: string;
  tags: string;
  notes: string;
}

const EMPTY_FORM: FormState = {
  customer_name: '',
  phone: '',
  reservation_date: '',
  reservation_time: '',
  status: 'pending',
  party_size: '',
  gender: '',
  room_type: '',
  tags: '',
  notes: '',
};

function fmtDate(val: string | null | undefined): string {
  if (!val) return '-';
  return dayjs(val).format('YYYY.MM.DD');
}

function fmtTime(val: string | null | undefined): string {
  if (!val) return '';
  if (val.includes('T')) return dayjs(val).format('HH:mm');
  return val.slice(0, 5);
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; color: 'success' | 'warning' | 'failure' | 'gray' }> = {
    confirmed: { label: '확정', color: 'success' },
    pending:   { label: '대기', color: 'warning' },
    cancelled: { label: '취소', color: 'failure' },
    completed: { label: '완료', color: 'gray' },
  };
  const m = map[status] ?? { label: status, color: 'gray' as const };
  return <Badge color={m.color} size="sm">{m.label}</Badge>;
}

function SourceBadge({ source }: { source?: string | null }) {
  const key = source ?? 'manual';
  const map: Record<string, { label: string; color: 'success' | 'gray' }> = {
    naver:  { label: '네이버', color: 'success' },
    manual: { label: '수동',   color: 'gray' },
    phone:  { label: '전화',   color: 'gray' },
  };
  const m = map[key] ?? { label: key, color: 'gray' as const };
  return <Badge color={m.color} size="xs">{m.label}</Badge>;
}

export default function Reservations() {
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [loading, setLoading]           = useState(false);
  const [syncing, setSyncing]           = useState(false);

  const [filterDate,   setFilterDate]   = useState('');
  const [filterStatus, setFilterStatus] = useState('all');
  const [filterSource, setFilterSource] = useState('all');

  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [saving,    setSaving]    = useState(false);
  const [form,      setForm]      = useState<FormState>(EMPTY_FORM);

  const [deleteId,  setDeleteId]  = useState<number | null>(null);
  const [deleting,  setDeleting]  = useState(false);

  async function fetchReservations() {
    setLoading(true);
    try {
      const params: { limit?: number; date?: string } = { limit: 200 };
      if (filterDate) params.date = filterDate;
      const res = await reservationsAPI.getAll(params);
      setReservations(res.data ?? []);
    } catch {
      toast.error('예약 목록을 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchReservations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterDate]);

  const filtered = useMemo(() => {
    return reservations.filter((r) => {
      if (filterStatus !== 'all' && r.status !== filterStatus) return false;
      const src = r.source ?? 'manual';
      if (filterSource !== 'all' && src !== filterSource) return false;
      return true;
    });
  }, [reservations, filterStatus, filterSource]);

  const stats = useMemo(() => ({
    total:     reservations.length,
    confirmed: reservations.filter((r) => r.status === 'confirmed').length,
    pending:   reservations.filter((r) => r.status === 'pending').length,
    cancelled: reservations.filter((r) => r.status === 'cancelled').length,
    naver:     reservations.filter((r) => !!r.external_id).length,
  }), [reservations]);

  async function handleSync() {
    setSyncing(true);
    try {
      const res = await reservationsAPI.syncNaver();
      const added = res.data?.added ?? 0;
      toast.success(`네이버 동기화 완료 — ${added}건 추가`);
      fetchReservations();
    } catch {
      toast.error('네이버 동기화에 실패했습니다.');
    } finally {
      setSyncing(false);
    }
  }

  function openCreate() {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setModalOpen(true);
  }

  function openEdit(r: Reservation) {
    setEditingId(r.id);
    setForm({
      customer_name:    r.customer_name ?? '',
      phone:            r.phone ?? '',
      reservation_date: r.date ? dayjs(r.date).format('YYYY-MM-DD') : '',
      reservation_time: fmtTime(r.time ?? r.date),
      status:           r.status ?? 'pending',
      party_size:       r.party_participants != null ? String(r.party_participants) : '',
      gender:           r.gender ?? '',
      room_type:        r.room_info ?? '',
      tags:             r.tags ?? '',
      notes:            r.notes ?? '',
    });
    setModalOpen(true);
  }

  function setField(key: keyof FormState, value: string) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSave() {
    if (!form.customer_name.trim()) { toast.error('예약자 이름을 입력하세요.'); return; }
    if (!form.phone.trim())          { toast.error('전화번호를 입력하세요.');    return; }
    if (!form.reservation_date)      { toast.error('예약 날짜를 선택하세요.');   return; }

    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        customer_name:      form.customer_name.trim(),
        phone:              form.phone.trim(),
        date:               form.reservation_date,
        time:               form.reservation_time || null,
        status:             form.status,
        party_participants: form.party_size ? Number(form.party_size) : null,
        gender:             form.gender || null,
        room_info:          form.room_type.trim() || null,
        tags:               form.tags.trim() || null,
        notes:              form.notes.trim() || null,
      };

      if (editingId != null) {
        await reservationsAPI.update(editingId, payload);
        toast.success('예약이 수정되었습니다.');
      } else {
        await reservationsAPI.create(payload);
        toast.success('예약이 등록되었습니다.');
      }
      setModalOpen(false);
      fetchReservations();
    } catch {
      toast.error('저장에 실패했습니다.');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (deleteId == null) return;
    setDeleting(true);
    try {
      await reservationsAPI.delete(deleteId);
      toast.success('예약이 삭제되었습니다.');
      setDeleteId(null);
      fetchReservations();
    } catch {
      toast.error('삭제에 실패했습니다.');
    } finally {
      setDeleting(false);
    }
  }

  function clearFilters() {
    setFilterDate('');
    setFilterStatus('all');
    setFilterSource('all');
  }

  const hasFilter = filterDate || filterStatus !== 'all' || filterSource !== 'all';

  return (
    <div className="space-y-6">

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="page-title">예약 관리</h1>
          <p className="page-subtitle">예약 현황을 확인하고 네이버 예약을 동기화합니다.</p>
        </div>
        <div className="flex items-center gap-2">
          <Button color="light" size="sm" onClick={openCreate}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            예약 등록
          </Button>
          <Button color="blue" size="sm" onClick={handleSync} disabled={syncing}>
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5${syncing ? ' animate-spin' : ''}`} />
            네이버 예약 동기화
          </Button>
        </div>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <div className="stat-card">
          <div className="flex items-center gap-3">
            <div className="stat-icon bg-[#E8F3FF] text-[#3182F6] dark:bg-[#3182F6]/15 dark:text-[#3182F6]">
              <CalendarDays size={18} />
            </div>
            <div>
              <p className="stat-value text-xl">{stats.total}<span className="ml-0.5 text-label font-normal text-[#B0B8C1] dark:text-gray-600">건</span></p>
              <p className="stat-label">총 예약</p>
            </div>
          </div>
        </div>

        <div className="stat-card">
          <div className="flex items-center gap-3">
            <div className="stat-icon bg-[#E8FAF5] text-[#00C9A7] dark:bg-[#00C9A7]/15 dark:text-[#00C9A7]">
              <CheckCircle size={18} />
            </div>
            <div>
              <p className="stat-value text-xl">{stats.confirmed}<span className="ml-0.5 text-label font-normal text-[#B0B8C1] dark:text-gray-600">건</span></p>
              <p className="stat-label">확정</p>
            </div>
          </div>
        </div>

        <div className="stat-card">
          <div className="flex items-center gap-3">
            <div className="stat-icon bg-[#FFF5E6] text-[#FF9F00] dark:bg-[#FF9F00]/15 dark:text-[#FF9F00]">
              <Clock size={18} />
            </div>
            <div>
              <p className="stat-value text-xl">{stats.pending}<span className="ml-0.5 text-label font-normal text-[#B0B8C1] dark:text-gray-600">건</span></p>
              <p className="stat-label">대기</p>
            </div>
          </div>
        </div>

        <div className="stat-card">
          <div className="flex items-center gap-3">
            <div className="stat-icon bg-[#FFEBEE] text-[#F04452] dark:bg-[#F04452]/15 dark:text-[#F04452]">
              <XCircle size={18} />
            </div>
            <div>
              <p className="stat-value text-xl">{stats.cancelled}<span className="ml-0.5 text-label font-normal text-[#B0B8C1] dark:text-gray-600">건</span></p>
              <p className="stat-label">취소</p>
            </div>
          </div>
        </div>

        <div className="stat-card">
          <div className="flex items-center gap-3">
            <div className="stat-icon bg-[#E8FAF5] text-[#00C9A7] dark:bg-[#00C9A7]/15 dark:text-[#00C9A7]">
              <ShoppingBag size={18} />
            </div>
            <div>
              <p className="stat-value text-xl">{stats.naver}<span className="ml-0.5 text-label font-normal text-[#B0B8C1] dark:text-gray-600">건</span></p>
              <p className="stat-label">네이버</p>
            </div>
          </div>
        </div>
      </div>

      {/* Filter bar + Table */}
      <div className="section-card">

        <div className="p-4">
          <div className="filter-bar">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="filter-date" className="text-caption">날짜</Label>
              <TextInput
                id="filter-date"
                type="date"
                value={filterDate}
                onChange={(e) => setFilterDate(e.target.value)}
                sizing="sm"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="filter-status" className="text-caption">상태</Label>
              <Select
                id="filter-status"
                value={filterStatus}
                onChange={(e) => setFilterStatus(e.target.value)}
                sizing="sm"
              >
                <option value="all">전체</option>
                <option value="confirmed">확정</option>
                <option value="pending">대기</option>
                <option value="cancelled">취소</option>
                <option value="completed">완료</option>
              </Select>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="filter-source" className="text-caption">출처</Label>
              <Select
                id="filter-source"
                value={filterSource}
                onChange={(e) => setFilterSource(e.target.value)}
                sizing="sm"
              >
                <option value="all">전체</option>
                <option value="naver">네이버</option>
                <option value="manual">수동</option>
                <option value="phone">전화</option>
              </Select>
            </div>

            {hasFilter && (
              <Button color="light" size="sm" onClick={clearFilters}>
                필터 초기화
              </Button>
            )}

            <span className="ml-auto self-end text-caption tabular-nums text-gray-500">
              {filtered.length}건 표시
            </span>
          </div>
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
          {loading ? (
            <div className="flex flex-col items-center justify-center gap-3 py-16">
              <Spinner size="lg" />
              <span className="text-body text-[#B0B8C1] dark:text-gray-600">불러오는 중...</span>
            </div>
          ) : filtered.length === 0 ? (
            <div className="empty-state">
              <CalendarDays size={40} strokeWidth={1} />
              <p className="text-body">예약 내역이 없습니다.</p>
            </div>
          ) : (
            <Table hoverable striped>
              <TableHead>
                <TableRow>
                  <TableHeadCell className="whitespace-nowrap">예약ID</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">이름</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">전화번호</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">예약일시</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">상태</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">출처</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">객실</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">메모</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">작업</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody className="divide-y">
                {filtered.map((r) => {
                  const isNaver = !!r.external_id;
                  const timeStr = fmtTime(r.time ?? r.date);

                  return (
                    <TableRow key={r.id}>
                      <TableCell>
                        <div className="space-y-1">
                          <SourceBadge source={isNaver ? 'naver' : 'manual'} />
                          <p className="text-caption tabular-nums text-gray-400">
                            {isNaver ? r.external_id?.slice(0, 10) : `#${r.id}`}
                          </p>
                        </div>
                      </TableCell>
                      <TableCell>
                        <span className="font-medium text-gray-900 dark:text-white">
                          {r.customer_name}
                        </span>
                      </TableCell>
                      <TableCell>
                        <span className="tabular-nums text-gray-500">
                          {r.phone}
                        </span>
                      </TableCell>
                      <TableCell>
                        <p className="text-body text-gray-900 dark:text-white">{fmtDate(r.date)}</p>
                        {timeStr && <p className="text-caption text-gray-400">{timeStr}</p>}
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={r.status} />
                      </TableCell>
                      <TableCell>
                        <SourceBadge source={r.source} />
                      </TableCell>
                      <TableCell>
                        {r.room_number ? (
                          <Badge color="info" size="sm">{r.room_number}</Badge>
                        ) : (
                          <span className="text-caption text-gray-400">미배정</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <p className="line-clamp-1 max-w-[120px] text-body text-gray-500" title={r.notes ?? ''}>
                          {r.notes ?? '-'}
                        </p>
                      </TableCell>
                      <TableCell>
                        {isNaver ? (
                          <span className="text-caption text-gray-400">네이버 관리</span>
                        ) : (
                          <div className="flex items-center gap-1">
                            <Button color="light" size="xs" onClick={() => openEdit(r)} title="수정">
                              <Pencil className="h-3.5 w-3.5" />
                            </Button>
                            <Button color="failure" size="xs" onClick={() => setDeleteId(r.id)} title="삭제">
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </div>
      </div>

      {/* Create / Edit Modal */}
      <Modal
        show={modalOpen}
        onClose={() => { if (!saving) setModalOpen(false); }}
        size="md"
      >
        <ModalHeader>
          {editingId != null ? '예약 수정' : '예약 등록'}
        </ModalHeader>

        <ModalBody className="max-h-[70vh] overflow-y-auto">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="f-name">
                예약자 이름 <span className="text-[#F04452] dark:text-red-400">*</span>
              </Label>
              <TextInput
                id="f-name"
                value={form.customer_name}
                onChange={(e) => setField('customer_name', e.target.value)}
                placeholder="홍길동"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="f-phone">
                전화번호 <span className="text-[#F04452] dark:text-red-400">*</span>
              </Label>
              <TextInput
                id="f-phone"
                value={form.phone}
                onChange={(e) => setField('phone', e.target.value)}
                placeholder="010-0000-0000"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="f-date">
                예약 날짜 <span className="text-[#F04452] dark:text-red-400">*</span>
              </Label>
              <TextInput
                id="f-date"
                type="date"
                value={form.reservation_date}
                onChange={(e) => setField('reservation_date', e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="f-time">예약 시간</Label>
              <TextInput
                id="f-time"
                type="time"
                value={form.reservation_time}
                onChange={(e) => setField('reservation_time', e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="f-status">예약 상태</Label>
              <Select
                id="f-status"
                value={form.status}
                onChange={(e) => setField('status', e.target.value)}
              >
                <option value="pending">대기</option>
                <option value="confirmed">확정</option>
                <option value="cancelled">취소</option>
                <option value="completed">완료</option>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="f-party">인원 수</Label>
              <TextInput
                id="f-party"
                type="number"
                min={1}
                value={form.party_size}
                onChange={(e) => setField('party_size', e.target.value)}
                placeholder="2"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="f-gender">성별</Label>
              <Select
                id="f-gender"
                value={form.gender || '__none__'}
                onChange={(e) => setField('gender', e.target.value === '__none__' ? '' : e.target.value)}
              >
                <option value="__none__">선택 안 함</option>
                <option value="male">남성</option>
                <option value="female">여성</option>
                <option value="mixed">혼성</option>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="f-room-type">객실 타입</Label>
              <TextInput
                id="f-room-type"
                value={form.room_type}
                onChange={(e) => setField('room_type', e.target.value)}
                placeholder="스탠다드"
              />
            </div>

            <div className="space-y-2 col-span-2">
              <Label htmlFor="f-tags">태그</Label>
              <TextInput
                id="f-tags"
                value={form.tags}
                onChange={(e) => setField('tags', e.target.value)}
                placeholder="쉼표로 구분 (예: 1초,2차만)"
              />
              <div className="flex flex-wrap gap-1">
                {TAG_OPTIONS.map((t) => (
                  <Button
                    key={t}
                    type="button"
                    color={form.tags === t ? 'blue' : 'light'}
                    size="xs"
                    pill
                    className="!text-overline !px-2 !py-0.5"
                    onClick={() => setField('tags', t)}
                  >
                    {t}
                  </Button>
                ))}
              </div>
            </div>

            <div className="space-y-2 col-span-2">
              <Label htmlFor="f-notes">메모</Label>
              <Textarea
                id="f-notes"
                value={form.notes}
                onChange={(e) => setField('notes', e.target.value)}
                rows={2}
                placeholder="추가 메모를 입력하세요"
              />
            </div>
          </div>
        </ModalBody>

        <ModalFooter>
          <Button color="blue" onClick={handleSave} disabled={saving}>
            {saving ? (
              <>
                <Spinner size="sm" className="mr-2" />
                저장 중...
              </>
            ) : (
              editingId != null ? '수정 완료' : '등록'
            )}
          </Button>
          <Button color="light" onClick={() => setModalOpen(false)} disabled={saving}>
            취소
          </Button>
        </ModalFooter>
      </Modal>

      {/* Delete Confirm Modal */}
      <Modal
        show={deleteId != null}
        onClose={() => { if (!deleting) setDeleteId(null); }}
        size="md"
        popup
      >
        <ModalHeader />
        <ModalBody>
          <div className="text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#FFEBEE] dark:bg-[#F04452]/10">
              <Trash2 className="h-6 w-6 text-[#F04452] dark:text-red-400" />
            </div>
            <h3 className="mb-2 text-heading font-semibold text-[#191F28] dark:text-white">예약을 삭제하시겠습니까?</h3>
            <p className="mb-5 text-body text-gray-500">이 작업은 되돌릴 수 없습니다. 예약 정보가 영구적으로 삭제됩니다.</p>
            <div className="flex justify-center gap-3">
              <Button color="failure" onClick={handleDelete} disabled={deleting}>
                {deleting ? (
                  <>
                    <Spinner size="sm" className="mr-2" />
                    삭제 중...
                  </>
                ) : '삭제'}
              </Button>
              <Button color="light" onClick={() => setDeleteId(null)} disabled={deleting}>
                취소
              </Button>
            </div>
          </div>
        </ModalBody>
      </Modal>

    </div>
  );
}
