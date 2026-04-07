import { useState } from 'react';
import { toast } from 'sonner';
import { Search, RotateCcw, Send, MessageSquare } from 'lucide-react';
import dayjs from 'dayjs';

import { Button } from '@/components/ui/button';
import { TextInput } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Select } from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import { Spinner } from '@/components/ui/spinner';
import { Table, TableHead, TableBody, TableRow, TableHeadCell, TableCell } from '@/components/ui/table';

import { eventSmsAPI } from '@/services/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Customer {
  customer_name: string;
  phone: string;
  gender: string | null;
  age_group: string | null;
  visit_count: number;
  total_nights: number;
  last_check_in: string | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function maskPhone(phone: string): string {
  const digits = phone.replace(/\D/g, '');
  if (digits.length === 11) {
    return `${digits.slice(0, 3)}-****-${digits.slice(7)}`;
  }
  if (digits.length === 10) {
    return `${digits.slice(0, 3)}-***-${digits.slice(6)}`;
  }
  return phone.slice(0, 3) + '-****-' + phone.slice(-4);
}

function getByteSize(text: string): number {
  let bytes = 0;
  for (let i = 0; i < text.length; i++) {
    bytes += text.charCodeAt(i) > 127 ? 2 : 1;
  }
  return bytes;
}

function fmtDate(val: string | null | undefined): string {
  if (!val) return '-';
  return dayjs(val).format('MM-DD');
}

const AGE_GROUP_OPTIONS = [
  { value: '20', label: '20대' },
  { value: '30', label: '30대' },
  { value: '40', label: '40대' },
  { value: '50', label: '50대 이상' },
];

// ---------------------------------------------------------------------------
// Page Component
// ---------------------------------------------------------------------------

export default function EventSms() {
  // Filter state
  const defaultDateFrom = dayjs().subtract(3, 'month').format('YYYY-MM-DD');
  const defaultDateTo = dayjs().format('YYYY-MM-DD');

  const [dateFrom, setDateFrom] = useState(defaultDateFrom);
  const [dateTo, setDateTo] = useState(defaultDateTo);
  const [gender, setGender] = useState<string>('');
  const [minNights, setMinNights] = useState('');
  const [maxNights, setMaxNights] = useState('');
  const [minVisits, setMinVisits] = useState('');
  const [maxVisits, setMaxVisits] = useState('');
  const [ageGroups, setAgeGroups] = useState<string[]>([]);

  // Results state
  const [results, setResults] = useState<Customer[]>([]);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  // SMS state
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);

  // ---------------------------------------------------------------------------
  // Derived
  // ---------------------------------------------------------------------------

  const selectedPhones = results
    .filter((c) => !excluded.has(c.phone))
    .map((c) => c.phone);

  const allSelected = results.length > 0 && excluded.size === 0;
  const byteSize = getByteSize(message);

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  function handleReset() {
    setDateFrom(defaultDateFrom);
    setDateTo(defaultDateTo);
    setGender('');
    setMinNights('');
    setMaxNights('');
    setMinVisits('');
    setMaxVisits('');
    setAgeGroups([]);
    setResults([]);
    setExcluded(new Set());
    setSearched(false);
    setMessage('');
  }

  async function handleSearch() {
    if (!dateFrom || !dateTo) {
      toast.error('체크인 기간을 입력해주세요.');
      return;
    }
    setLoading(true);
    setExcluded(new Set());
    try {
      const { data } = await eventSmsAPI.search({
        date_from: dateFrom,
        date_to: dateTo,
        gender: gender || null,
        min_nights: minNights ? Number(minNights) : null,
        max_nights: maxNights ? Number(maxNights) : null,
        min_visits: minVisits ? Number(minVisits) : null,
        max_visits: maxVisits ? Number(maxVisits) : null,
        exclude_age_groups: ageGroups.length > 0 ? ageGroups : null,
      });
      setResults(data.customers ?? data ?? []);
      setSearched(true);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? '조회 중 오류가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  }

  function toggleExclude(phone: string) {
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(phone)) {
        next.delete(phone);
      } else {
        next.add(phone);
      }
      return next;
    });
  }

  function toggleAll() {
    if (allSelected) {
      setExcluded(new Set(results.map((c) => c.phone)));
    } else {
      setExcluded(new Set());
    }
  }

  function toggleAgeGroup(val: string) {
    setAgeGroups((prev) =>
      prev.includes(val) ? prev.filter((v) => v !== val) : [...prev, val]
    );
  }

  async function handleSend() {
    if (selectedPhones.length === 0) {
      toast.error('발송 대상을 선택해주세요.');
      return;
    }
    if (!message.trim()) {
      toast.error('문자 내용을 입력해주세요.');
      return;
    }
    const confirmed = window.confirm(
      `총 ${selectedPhones.length}명에게 문자를 발송합니다.\n계속하시겠습니까?`
    );
    if (!confirmed) return;

    setSending(true);
    try {
      await eventSmsAPI.send({
        phones: selectedPhones,
        message: message.trim(),
      });
      toast.success(`${selectedPhones.length}명에게 문자를 발송했습니다.`);
      setMessage('');
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? '발송 중 오류가 발생했습니다.');
    } finally {
      setSending(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="page-title">이벤트 문자 발송</h1>
        <p className="page-subtitle">조건별 예약자 필터링 후 대량 문자 발송</p>
      </div>

      {/* 2-Column Layout */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[380px_1fr]">
        {/* Left Column: Filters + SMS Send */}
        <div className="flex flex-col gap-6">
          {/* Filter Card */}
          <div className="section-card">
            <div className="section-header">
              <span className="text-heading font-semibold text-[#191F28] dark:text-white">필터 조건</span>
            </div>
            <div className="px-5 pb-5">
              <div className="flex flex-col gap-4">
                {/* Date Range */}
                <div>
                  <Label className="mb-1.5 block text-caption font-medium text-[#4E5968] dark:text-gray-300">
                    체크인 기간
                  </Label>
                  <div className="flex items-center gap-2">
                    <TextInput
                      type="date"
                      value={dateFrom}
                      onChange={(e) => setDateFrom(e.target.value)}
                      className="w-full"
                    />
                    <span className="shrink-0 text-body text-[#8B95A1]">~</span>
                    <TextInput
                      type="date"
                      value={dateTo}
                      onChange={(e) => setDateTo(e.target.value)}
                      className="w-full"
                    />
                  </div>
                </div>

                {/* Gender */}
                <div>
                  <Label className="mb-1.5 block text-caption font-medium text-[#4E5968] dark:text-gray-300">
                    성별
                  </Label>
                  <Select
                    value={gender}
                    onChange={(e) => setGender(e.target.value)}
                  >
                    <option value="">전체</option>
                    <option value="남">남</option>
                    <option value="여">여</option>
                  </Select>
                </div>

                {/* Nights */}
                <div>
                  <Label className="mb-1.5 block text-caption font-medium text-[#4E5968] dark:text-gray-300">
                    숙박일수
                  </Label>
                  <div className="flex items-center gap-2">
                    <TextInput
                      type="number"
                      min={0}
                      placeholder="최소"
                      value={minNights}
                      onChange={(e) => setMinNights(e.target.value)}
                      className="w-full"
                    />
                    <span className="shrink-0 text-body text-[#8B95A1]">~</span>
                    <TextInput
                      type="number"
                      min={0}
                      placeholder="최대"
                      value={maxNights}
                      onChange={(e) => setMaxNights(e.target.value)}
                      className="w-full"
                    />
                    <span className="shrink-0 text-caption text-[#8B95A1]">박</span>
                  </div>
                </div>

                {/* Visits */}
                <div>
                  <Label className="mb-1.5 block text-caption font-medium text-[#4E5968] dark:text-gray-300">
                    방문횟수
                  </Label>
                  <div className="flex items-center gap-2">
                    <TextInput
                      type="number"
                      min={0}
                      placeholder="최소"
                      value={minVisits}
                      onChange={(e) => setMinVisits(e.target.value)}
                      className="w-full"
                    />
                    <span className="shrink-0 text-body text-[#8B95A1]">~</span>
                    <TextInput
                      type="number"
                      min={0}
                      placeholder="최대"
                      value={maxVisits}
                      onChange={(e) => setMaxVisits(e.target.value)}
                      className="w-full"
                    />
                    <span className="shrink-0 text-caption text-[#8B95A1]">회</span>
                  </div>
                </div>

                {/* Age Groups */}
                <div>
                  <Label className="mb-1.5 block text-caption font-medium text-[#4E5968] dark:text-gray-300">
                    연령대 제외
                  </Label>
                  <div className="flex flex-wrap gap-3">
                    {AGE_GROUP_OPTIONS.map((opt) => (
                      <label
                        key={opt.value}
                        className="flex cursor-pointer items-center gap-1.5 text-body text-[#191F28] dark:text-white"
                      >
                        <input
                          type="checkbox"
                          checked={ageGroups.includes(opt.value)}
                          onChange={() => toggleAgeGroup(opt.value)}
                          className="h-4 w-4 rounded border-[#E5E8EB] text-[#3182F6] accent-[#3182F6] dark:border-gray-600"
                        />
                        {opt.label}
                      </label>
                    ))}
                  </div>
                </div>
              </div>

              {/* Filter Actions */}
              <div className="mt-5 flex justify-end gap-2">
                <Button color="light" size="sm" onClick={handleReset}>
                  <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                  초기화
                </Button>
                <Button color="blue" size="sm" onClick={handleSearch} disabled={loading}>
                  {loading ? (
                    <Spinner size="sm" className="mr-2" />
                  ) : (
                    <Search className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  {loading ? '조회 중...' : '조회하기'}
                </Button>
              </div>
            </div>
          </div>

          {/* SMS Send Card */}
          <div className="section-card">
            <div className="section-header">
              <span className="text-heading font-semibold text-[#191F28] dark:text-white">
                문자 발송
              </span>
              {searched && (
                <span className="text-body text-[#4E5968] dark:text-gray-400">
                  발송 대상:{' '}
                  <span className="tabular-nums font-semibold text-[#3182F6]">
                    {selectedPhones.length}
                  </span>
                  <span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span>
                </span>
              )}
            </div>
            <div className="px-5 pb-5">
              <div className="relative">
                <Textarea
                  rows={6}
                  placeholder="발송할 문자 내용을 입력하세요..."
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  className="w-full resize-none pr-24"
                />
                <span
                  className={`absolute bottom-3 right-3 text-caption tabular-nums ${
                    byteSize > 2000
                      ? 'text-[#F04452]'
                      : byteSize > 1800
                      ? 'text-[#FF9F00]'
                      : 'text-[#B0B8C1] dark:text-gray-600'
                  }`}
                >
                  {byteSize.toLocaleString()} / 2,000 B
                </span>
              </div>

              <div className="mt-4 flex justify-end gap-2">
                <Button
                  color="blue"
                  size="sm"
                  onClick={handleSend}
                  disabled={sending || selectedPhones.length === 0 || !message.trim() || byteSize > 2000}
                >
                  {sending ? (
                    <Spinner size="sm" className="mr-2" />
                  ) : (
                    <Send className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  {sending ? '발송 중...' : '발송하기'}
                </Button>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: Results Table */}
        <div className="section-card min-h-[400px]">
          <div className="section-header">
            <span className="text-heading font-semibold text-[#191F28] dark:text-white">
              조회 결과
            </span>
            {searched && results.length > 0 && (
              <div className="flex items-center gap-3 text-body">
                <span className="text-[#4E5968] dark:text-gray-400">
                  총{' '}
                  <span className="tabular-nums font-semibold text-[#191F28] dark:text-white">
                    {results.length}
                  </span>
                  <span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span>
                </span>
                <span className="text-[#E5E8EB] dark:text-gray-700">|</span>
                <span className="text-[#4E5968] dark:text-gray-400">
                  선택{' '}
                  <span className="tabular-nums font-semibold text-[#3182F6]">
                    {selectedPhones.length}
                  </span>
                  <span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span>
                </span>
              </div>
            )}
          </div>

          {!searched || results.length === 0 ? (
            <div className="empty-state">
              <MessageSquare size={40} className="text-[#B0B8C1] dark:text-gray-600" />
              <p className="mt-3 text-body text-[#8B95A1] dark:text-gray-500">
                {searched ? '조회 결과가 없습니다.' : '필터 조건을 설정하고 조회해주세요.'}
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHead>
                  <TableRow>
                    <TableHeadCell className="w-10">
                      <input
                        type="checkbox"
                        checked={allSelected}
                        onChange={toggleAll}
                        className="h-4 w-4 rounded border-[#E5E8EB] accent-[#3182F6] dark:border-gray-600"
                        title={allSelected ? '전체 해제' : '전체 선택'}
                      />
                    </TableHeadCell>
                    <TableHeadCell>이름</TableHeadCell>
                    <TableHeadCell>전화번호</TableHeadCell>
                    <TableHeadCell>성별</TableHeadCell>
                    <TableHeadCell>연령대</TableHeadCell>
                    <TableHeadCell>방문횟수</TableHeadCell>
                    <TableHeadCell>총 숙박</TableHeadCell>
                    <TableHeadCell>최근 체크인</TableHeadCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {results.map((customer) => {
                    const isExcluded = excluded.has(customer.phone);
                    return (
                      <TableRow
                        key={customer.phone}
                        className={
                          isExcluded
                            ? 'opacity-40 dark:opacity-30'
                            : ''
                        }
                      >
                        <TableCell className="w-10">
                          <input
                            type="checkbox"
                            checked={!isExcluded}
                            onChange={() => toggleExclude(customer.phone)}
                            className="h-4 w-4 rounded border-[#E5E8EB] accent-[#3182F6] dark:border-gray-600"
                          />
                        </TableCell>
                        <TableCell className="text-body font-medium text-[#191F28] dark:text-white">
                          {customer.customer_name}
                        </TableCell>
                        <TableCell className="tabular-nums text-body text-[#4E5968] dark:text-gray-300">
                          {maskPhone(customer.phone)}
                        </TableCell>
                        <TableCell className="text-body text-[#4E5968] dark:text-gray-300">
                          {customer.gender ?? '-'}
                        </TableCell>
                        <TableCell className="text-body text-[#4E5968] dark:text-gray-300">
                          {customer.age_group ? `${customer.age_group}대` : '-'}
                        </TableCell>
                        <TableCell className="tabular-nums text-body text-[#4E5968] dark:text-gray-300">
                          {customer.visit_count}
                          <span className="ml-0.5 text-label font-normal text-[#B0B8C1]">회</span>
                        </TableCell>
                        <TableCell className="tabular-nums text-body text-[#4E5968] dark:text-gray-300">
                          {customer.total_nights}
                          <span className="ml-0.5 text-label font-normal text-[#B0B8C1]">박</span>
                        </TableCell>
                        <TableCell className="tabular-nums text-body text-[#4E5968] dark:text-gray-300">
                          {fmtDate(customer.last_check_in)}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
