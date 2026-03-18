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
  Search,
  X,
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


interface Reservation {
  id: number;
  external_id?: string | null;
  customer_name: string;
  phone: string;
  visitor_name?: string | null;
  visitor_phone?: string | null;
  check_in_date: string;
  check_out_date?: string | null;
  check_in_time?: string | null;
  status: string;
  booking_source?: string | null;
  party_size?: number | null;
  gender?: string | null;
  naver_room_type?: string | null;
  room_number?: string | null;
  biz_item_name?: string | null;
  booking_count?: number | null;
  booking_options?: string | null;
  special_requests?: string | null;
  total_price?: number | null;
  confirmed_at?: string | null;
  cancelled_at?: string | null;
  notes?: string | null;
  created_at?: string | null;
}

interface FormState {
  guest_type: string;
  customer_name: string;
  phone: string;
  reservation_date: string;
  status: string;
  male_count: number | null;
  female_count: number | null;
  notes: string;
}

const EMPTY_FORM: FormState = {
  guest_type: 'manual',
  customer_name: '',
  phone: '',
  reservation_date: '',
  status: 'confirmed',
  male_count: null,
  female_count: null,
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

const DAY_NAMES = ['일', '월', '화', '수', '목', '금', '토'];

function fmtPeriod(start: string | null | undefined, end: string | null | undefined): string {
  if (!start) return '-';
  const sd = dayjs(start);
  const s = `${sd.format('YY.MM.DD')}(${DAY_NAMES[sd.day()]})`;
  if (!end) return s;
  const ed = dayjs(end);
  const e = `${ed.format('YY.MM.DD')}(${DAY_NAMES[ed.day()]})`;
  return `${s} ~ ${e}`;
}

function fmtPrice(val: number | null | undefined): string {
  if (val == null) return '-';
  return `${val.toLocaleString()}원`;
}

function fmtDatetime(val: string | null | undefined): string {
  if (!val) return '-';
  return dayjs(val).format('MM.DD HH:mm');
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; className: string }> = {
    confirmed: { label: '확정', className: 'text-[#00C9A7]' },
    pending:   { label: '대기', className: 'text-[#FF9F00]' },
    cancelled: { label: '취소', className: 'text-[#F04452]' },
    completed: { label: '완료', className: 'text-[#8B95A1] dark:text-gray-500' },
  };
  const m = map[status] ?? { label: status, className: 'text-[#8B95A1]' };
  return <span className={`text-body font-medium ${m.className}`}>{m.label}</span>;
}

function SourceBadge({ source }: { source?: string | null }) {
  const key = source ?? 'manual';
  const map: Record<string, { label: string; className: string }> = {
    naver:  { label: '네이버', className: 'text-[#00C9A7]' },
    manual: { label: '수동',   className: 'text-[#8B95A1] dark:text-gray-500' },
    phone:  { label: '전화',   className: 'text-[#8B95A1] dark:text-gray-500' },
  };
  const m = map[key] ?? { label: key, className: 'text-[#8B95A1]' };
  return <span className={`text-body font-medium ${m.className}`}>{m.label}</span>;
}

export default function Reservations() {
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [statsReservations, setStatsReservations] = useState<Reservation[]>([]);
  const [loading, setLoading]           = useState(false);
  const [syncing, setSyncing]           = useState(false);
  const [syncFromDate, setSyncFromDate] = useState('');

  const [filterDate,   setFilterDate]   = useState('');
  const [filterStatus, setFilterStatus] = useState<string[]>([]);
  const [filterSource, setFilterSource] = useState<string[]>([]);
  const [searchQuery,  setSearchQuery]  = useState('');

  function toggleFilter(current: string[], value: string, setter: (v: string[]) => void) {
    if (value === 'all') {
      setter([]);
    } else {
      const next = current.includes(value)
        ? current.filter((v) => v !== value)
        : [...current, value];
      setter(next);
    }
  }

  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [saving,    setSaving]    = useState(false);
  const [form,      setForm]      = useState<FormState>(EMPTY_FORM);

  const [deleteId,  setDeleteId]  = useState<number | null>(null);
  const [deleting,  setDeleting]  = useState(false);

  const [currentPage, setCurrentPage] = useState(1);
  const PAGE_SIZE = 100;

  // Fetch unfiltered data for stat-cards (today's counts)
  async function fetchStats() {
    try {
      const res = await reservationsAPI.getAll({ limit: 200 });
      setStatsReservations(res.data ?? []);
    } catch {
      // Stats fetch failure is non-critical; silently ignore
    }
  }

  async function fetchReservations() {
    setLoading(true);
    try {
      const params: { limit?: number; date?: string; status?: string; source?: string; search?: string } = { limit: 50 };
      if (filterDate) params.date = filterDate;
      if (filterStatus.length === 1) params.status = filterStatus[0];
      if (filterSource.length === 1) params.source = filterSource[0];
      if (searchQuery.trim()) params.search = searchQuery.trim();
      const res = await reservationsAPI.getAll(params);
      setReservations(res.data ?? []);
    } catch {
      toast.error('예약 목록을 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchStats();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    fetchReservations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterDate, filterStatus, filterSource, searchQuery]);

  const filtered = useMemo(() => {
    // Server already filters by status, source, search when a single value is active.
    // Multi-value status/source selections fall back to client-side filtering.
    const list = reservations.filter((r) => {
      if (filterStatus.length > 1 && !filterStatus.includes(r.status)) return false;
      const src = r.booking_source ?? 'manual';
      if (filterSource.length > 1 && !filterSource.includes(src)) return false;
      return true;
    });
    // Sort by most recent confirmed or cancelled datetime
    list.sort((a, b) => {
      const aDate = a.cancelled_at || a.confirmed_at || a.created_at || '';
      const bDate = b.cancelled_at || b.confirmed_at || b.created_at || '';
      return bDate.localeCompare(aDate);
    });
    return list;
  }, [reservations, filterStatus, filterSource]);

  // Reset to page 1 when filters change
  useEffect(() => {
    setCurrentPage(1);
  }, [filterDate, filterStatus, filterSource, searchQuery]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paginated = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return filtered.slice(start, start + PAGE_SIZE);
  }, [filtered, currentPage]);

  const stats = useMemo(() => {
    const today = dayjs().format('YYYY-MM-DD');
    const todayList = statsReservations.filter((r) => r.created_at && dayjs(r.created_at).format('YYYY-MM-DD') === today);
    return {
      total:     todayList.length,
      confirmed: todayList.filter((r) => r.status === 'confirmed').length,
      pending:   todayList.filter((r) => r.status === 'pending').length,
      cancelled: todayList.filter((r) => r.status === 'cancelled').length,
      naver:     todayList.filter((r) => !!r.external_id).length,
    };
  }, [statsReservations]);

  async function handleSync() {
    setSyncing(true);
    try {
      const res = await reservationsAPI.syncNaver(syncFromDate || undefined);
      const added = res.data?.added ?? 0;
      const updated = res.data?.updated ?? 0;
      toast.success(`네이버 동기화 완료 — ${added}건 추가, ${updated}건 갱신`);
      fetchReservations();
      fetchStats();
      setSyncFromDate('');
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
    // Parse gender string like "남2여1" into male/female counts
    let maleCount: number | null = null;
    let femaleCount: number | null = null;
    if (r.gender) {
      const maleMatch = r.gender.match(/남(\d+)/);
      const femaleMatch = r.gender.match(/여(\d+)/);
      if (maleMatch) maleCount = Number(maleMatch[1]);
      if (femaleMatch) femaleCount = Number(femaleMatch[1]);
      // Simple gender like "남" or "여"
      if (!maleMatch && !femaleMatch) {
        if (r.gender === '남') maleCount = r.party_size ?? 1;
        if (r.gender === '여') femaleCount = r.party_size ?? 1;
      }
    }
    setForm({
      guest_type: 'manual',
      customer_name:    r.customer_name ?? '',
      phone:            r.phone ?? '',
      reservation_date: r.check_in_date ? dayjs(r.check_in_date).format('YYYY-MM-DD') : '',
      status:           r.status ?? 'confirmed',
      male_count:       maleCount,
      female_count:     femaleCount,
      notes:            r.notes ?? '',
    });
    setModalOpen(true);
  }

  function setField(key: keyof FormState, value: string) {
    if (key === 'male_count' || key === 'female_count') {
      setForm((prev) => ({ ...prev, [key]: value ? Number(value) : null }));
    } else {
      setForm((prev) => ({ ...prev, [key]: value }));
    }
  }

  async function handleSave() {
    if (!form.customer_name.trim()) { toast.error('예약자 이름을 입력하세요.'); return; }
    if (!form.phone.trim())          { toast.error('전화번호를 입력하세요.');    return; }
    if (!form.reservation_date)      { toast.error('예약 날짜를 선택하세요.');   return; }

    setSaving(true);
    try {
      // Map male_count/female_count to gender + party_size
      const maleCount = form.male_count ? Number(form.male_count) : 0;
      const femaleCount = form.female_count ? Number(form.female_count) : 0;
      const genderParts: string[] = [];
      if (maleCount > 0) genderParts.push(`남${maleCount}`);
      if (femaleCount > 0) genderParts.push(`여${femaleCount}`);

      const payload: Record<string, unknown> = {
        customer_name:      form.customer_name.trim(),
        phone:              form.phone.trim(),
        check_in_date:      form.reservation_date,
        check_in_time:      '00:00',
        status:             form.status,
        party_size: (maleCount + femaleCount) || null,
        gender:             genderParts.join('') || null,
        male_count:         maleCount || null,
        female_count:       femaleCount || null,
        notes:              form.notes.trim() || null,
        booking_source:     'manual',
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
      fetchStats();
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
    setFilterStatus([]);
    setFilterSource([]);
    setSearchQuery('');
  }

  const hasFilter = filterDate || filterStatus.length > 0 || filterSource.length > 0 || searchQuery;

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
          <input
            type="date"
            value={syncFromDate}
            onChange={(e) => setSyncFromDate(e.target.value)}
            className="h-[34px] rounded-lg border border-[#E5E8EB] bg-white px-2.5 text-caption text-[#4E5968] dark:border-gray-600 dark:bg-[#1E1E24] dark:text-gray-300"
            placeholder="시작일"
          />
          <Button color="blue" size="sm" onClick={handleSync} disabled={syncing}>
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5${syncing ? ' animate-spin' : ''}`} />
            {syncFromDate ? `${syncFromDate}부터 동기화` : '네이버 동기화'}
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
            <div className="relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="이름 또는 전화번호"
                className="block w-full rounded-lg border border-[#E5E8EB] bg-white py-2 pl-3 pr-9 text-body text-[#191F28] placeholder:text-[#B0B8C1] focus:border-[#3182F6] focus:ring-1 focus:ring-[#3182F6] focus:outline-none dark:border-gray-600 dark:bg-[#1E1E24] dark:text-gray-100 dark:placeholder:text-gray-500"
              />
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-3">
                <Search className="h-4 w-4 text-[#B0B8C1]" />
              </div>
            </div>

            <input
              type="date"
              value={filterDate}
              onChange={(e) => setFilterDate(e.target.value)}
              className="block rounded-lg border border-[#E5E8EB] bg-white py-2 px-3 text-body text-[#191F28] focus:border-[#3182F6] focus:ring-1 focus:ring-[#3182F6] focus:outline-none dark:border-gray-600 dark:bg-[#1E1E24] dark:text-gray-100"
            />

            <div className="flex rounded-lg overflow-hidden border border-[#E5E8EB] dark:border-gray-600">
              {[
                { value: 'all', label: '전체' },
                { value: 'confirmed', label: '확정' },
                { value: 'pending', label: '대기' },
                { value: 'cancelled', label: '취소' },
                { value: 'completed', label: '완료' },
              ].map((opt) => {
                const isActive = opt.value === 'all'
                  ? filterStatus.length === 0
                  : filterStatus.includes(opt.value);
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => toggleFilter(filterStatus, opt.value, setFilterStatus)}
                    className={`px-3 py-2 text-body font-medium transition-colors cursor-pointer border-r border-[#E5E8EB] dark:border-gray-600 last:border-r-0
                      ${isActive
                        ? 'bg-[#3182F6] text-white'
                        : 'bg-white text-[#B0B8C1] hover:bg-[#F2F4F6] dark:bg-[#1E1E24] dark:text-gray-500 dark:hover:bg-[#2C2C34]'
                      }`}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>

            <div className="flex rounded-lg overflow-hidden border border-[#E5E8EB] dark:border-gray-600">
              {[
                { value: 'all', label: '전체' },
                { value: 'naver', label: '네이버' },
                { value: 'manual', label: '직접입력' },
              ].map((opt) => {
                const isActive = opt.value === 'all'
                  ? filterSource.length === 0
                  : filterSource.includes(opt.value);
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => toggleFilter(filterSource, opt.value, setFilterSource)}
                    className={`px-3 py-2 text-body font-medium transition-colors cursor-pointer border-r border-[#E5E8EB] dark:border-gray-600 last:border-r-0
                      ${isActive
                        ? 'bg-[#3182F6] text-white'
                        : 'bg-white text-[#B0B8C1] hover:bg-[#F2F4F6] dark:bg-[#1E1E24] dark:text-gray-500 dark:hover:bg-[#2C2C34]'
                      }`}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>

            {hasFilter && (
              <button
                type="button"
                onClick={clearFilters}
                className="p-2 rounded-lg text-[#8B95A1] hover:text-[#F04452] hover:bg-[#FFEBEE] dark:hover:bg-[#F04452]/10 transition-colors cursor-pointer"
                title="필터 초기화"
              >
                <X className="h-4 w-4" />
              </button>
            )}

            <span className="ml-auto text-caption tabular-nums text-gray-500">
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
                  <TableHeadCell className="whitespace-nowrap">이용기간</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap text-center">상태</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap text-center">상품명</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap text-center">객실</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap text-right">결제금액</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">요청사항</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap text-center">확정일시</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap text-center">취소일시</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">작업</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody className="divide-y">
                {paginated.map((r) => {
                  const isNaver = !!r.external_id;

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
                        <div>
                          <span className="font-medium text-gray-900 dark:text-white">
                            {r.customer_name}
                          </span>
                          {r.visitor_name && r.visitor_name !== r.customer_name && (
                            <p className="text-caption text-gray-400">{r.visitor_name}</p>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div>
                          <span className="tabular-nums text-gray-500">
                            {r.phone}
                          </span>
                          {r.visitor_phone && r.visitor_phone !== r.phone && (
                            <p className="text-caption tabular-nums text-gray-400">{r.visitor_phone}</p>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <span className="text-body tabular-nums">{fmtPeriod(r.check_in_date, r.check_out_date)}</span>
                      </TableCell>
                      <TableCell className="text-center">
                        <StatusBadge status={r.status} />
                      </TableCell>
                      <TableCell className="text-center">
                        <span className="text-body">{r.biz_item_name || r.naver_room_type || '-'}</span>
                      </TableCell>
                      <TableCell className="text-center">
                        {r.room_number ? (
                          <span className="text-body font-medium text-[#3182F6]">{r.room_number}</span>
                        ) : (
                          <span className="text-caption text-gray-400">미배정</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <span className="tabular-nums text-body text-gray-500">{fmtPrice(r.total_price)}</span>
                      </TableCell>
                      <TableCell>
                        <p className="line-clamp-1 max-w-[160px] text-body text-gray-500" title={r.special_requests ?? ''}>
                          {r.special_requests ?? '-'}
                        </p>
                      </TableCell>
                      <TableCell className="text-center">
                        <span className="tabular-nums text-body text-gray-500">{fmtDatetime(r.confirmed_at)}</span>
                      </TableCell>
                      <TableCell className="text-center">
                        <span className="tabular-nums text-body text-gray-500">{fmtDatetime(r.cancelled_at)}</span>
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

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between border-t border-[#F2F4F6] dark:border-gray-800 px-5 py-3">
            <span className="text-caption text-[#8B95A1] dark:text-gray-500">
              총 <span className="tabular-nums font-medium">{filtered.length}</span>건 중{' '}
              <span className="tabular-nums font-medium">{(currentPage - 1) * PAGE_SIZE + 1}</span>–
              <span className="tabular-nums font-medium">{Math.min(currentPage * PAGE_SIZE, filtered.length)}</span>건
            </span>
            <div className="flex items-center gap-1">
              <Button
                color="light"
                size="xs"
                disabled={currentPage === 1}
                onClick={() => setCurrentPage((p) => p - 1)}
              >
                이전
              </Button>
              {Array.from({ length: totalPages }, (_, i) => i + 1).map((page) => (
                <button
                  key={page}
                  onClick={() => setCurrentPage(page)}
                  className={`px-2.5 py-1 rounded-lg text-caption font-medium transition-colors cursor-pointer ${
                    page === currentPage
                      ? 'bg-[#3182F6] text-white'
                      : 'text-[#8B95A1] hover:bg-[#F2F4F6] dark:text-gray-500 dark:hover:bg-[#2C2C34]'
                  }`}
                >
                  {page}
                </button>
              ))}
              <Button
                color="light"
                size="xs"
                disabled={currentPage === totalPages}
                onClick={() => setCurrentPage((p) => p + 1)}
              >
                다음
              </Button>
            </div>
          </div>
        )}
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
          <div className="flex flex-col gap-4">
            {editingId == null && (
              <div className="flex gap-2">
                {[
                  { value: 'manual', label: '미배정' },
                  { value: 'party_only', label: '파티만' },
                ].map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => {
                      setField('guest_type', opt.value);
                    }}
                    className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors cursor-pointer
                      ${form.guest_type === opt.value
                        ? 'bg-[#3182F6] text-white'
                        : 'bg-[#F2F4F6] text-[#4E5968] hover:bg-[#E5E8EB] dark:bg-[#2C2C34] dark:text-gray-300 dark:hover:bg-[#3A3A44]'
                      }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            )}

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="f-name">이름 <span className="text-[#F04452] dark:text-red-400">*</span></Label>
                <TextInput
                  id="f-name"
                  value={form.customer_name}
                  onChange={(e) => setField('customer_name', e.target.value)}
                  placeholder="이름"
                  sizing="sm"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="f-phone">전화번호 <span className="text-[#F04452] dark:text-red-400">*</span></Label>
                <TextInput
                  id="f-phone"
                  value={form.phone}
                  onChange={(e) => setField('phone', e.target.value)}
                  placeholder="010-1234-5678"
                  sizing="sm"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="f-date">날짜 <span className="text-[#F04452] dark:text-red-400">*</span></Label>
                <TextInput
                  id="f-date"
                  type="date"
                  value={form.reservation_date}
                  onChange={(e) => setField('reservation_date', e.target.value)}
                  sizing="sm"
                />
              </div>
              <div className="space-y-2">
                <Label>성별 / 인원</Label>
                <div className="flex gap-2">
                  <div className="flex items-center gap-0 flex-1">
                    <span className="flex-shrink-0 px-3 py-2 rounded-l-lg bg-[#F2F4F6] dark:bg-[#2C2C34] border border-r-0 border-[#E5E8EB] dark:border-gray-600 text-sm font-medium text-[#4E5968] dark:text-gray-300">남</span>
                    <input
                      type="number"
                      min={0}
                      value={form.male_count ?? ''}
                      onChange={(e) => setField('male_count', e.target.value)}
                      placeholder="0"
                      className="w-full rounded-r-lg rounded-l-none border border-[#E5E8EB] dark:border-gray-600 bg-white dark:bg-[#1E1E24] text-sm text-[#191F28] dark:text-white px-3 py-2 focus:border-[#3182F6] focus:ring-[#3182F6] outline-none"
                    />
                  </div>
                  <div className="flex items-center gap-0 flex-1">
                    <span className="flex-shrink-0 px-3 py-2 rounded-l-lg bg-[#F2F4F6] dark:bg-[#2C2C34] border border-r-0 border-[#E5E8EB] dark:border-gray-600 text-sm font-medium text-[#4E5968] dark:text-gray-300">여</span>
                    <input
                      type="number"
                      min={0}
                      value={form.female_count ?? ''}
                      onChange={(e) => setField('female_count', e.target.value)}
                      placeholder="0"
                      className="w-full rounded-r-lg rounded-l-none border border-[#E5E8EB] dark:border-gray-600 bg-white dark:bg-[#1E1E24] text-sm text-[#191F28] dark:text-white px-3 py-2 focus:border-[#3182F6] focus:ring-[#3182F6] outline-none"
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="f-notes">메모</Label>
              <Textarea
                id="f-notes"
                value={form.notes}
                onChange={(e) => setField('notes', e.target.value)}
                placeholder="메모"
                rows={3}
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
