import { useState, useEffect, useCallback } from 'react';
import { toast } from 'sonner';
import { Search, ChevronDown, ChevronRight, Users, Eye, UserPlus, Trash2 } from 'lucide-react';
import { Modal, ModalHeader, ModalBody } from '@/components/ui/modal';
import { TextInput } from '@/components/ui/input';
import dayjs from 'dayjs';

import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import { Badge } from '@/components/ui/badge';
import { Table, TableHead, TableBody, TableRow, TableHeadCell, TableCell } from '@/components/ui/table';

import { salesReportAPI, partyHostsAPI } from '@/services/api';
import { normalizeUtcString } from '@/lib/utils';

// 펼침 상세 행의 배경색 — 다크 모드 분기 포함 (인라인 style 로는 dark variant 불가)
const DETAIL_ROW_BG = 'bg-[#F8F9FB] dark:bg-[#2C2C34]';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type PaymentMethod = '카드' | '이체' | '현금';

const PAYMENT_BADGE_COLOR: Record<string, 'info' | 'purple' | 'success' | 'gray'> = {
  '카드': 'info',
  '이체': 'purple',
  '현금': 'success',
};

interface SalesItemDetail {
  item_name: string;
  amount: number;
  payment_method: PaymentMethod | string | null;
  created_at: string | null;
}

interface DateDetail {
  date: string;
  participants: number;
  sales_total: number;
  auction_amount: number | null;
  auction_payment_method: string | null;
  reviews_count: number;
  invited_females: number;
  sales_by_payment: Record<string, number>;
  items: SalesItemDetail[];
}

interface HostSummary {
  host_username: string;
  days_count: number;
  total_sales: number;
  total_auction: number;
  total_revenue: number;
  total_participants: number;
  total_reviews: number;
  total_invited_females: number;
  sales_by_payment: Record<string, number>;
  auction_by_payment: Record<string, number>;
  avg_per_person: number;
  daily_avg: number;
  dates: DateDetail[];
}

interface ReportData {
  hosts: HostSummary[];
  grand_total_revenue: number;
  grand_total_participants: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt(n: number): string {
  return n.toLocaleString('ko-KR');
}

type ViewMode = 'total' | 'daily' | 'per_person';

const VIEW_MODE_OPTIONS: { value: ViewMode; label: string }[] = [
  { value: 'total', label: '총합' },
  { value: 'daily', label: '일평균' },
  { value: 'per_person', label: '인당평균' },
];

// 진행자 요약 행 변환: total = 원본, daily = ÷ days_count(or 명시된 dailyDivisor), per_person = ÷ participants (perPersonApplies=true일 때만)
function transformHost(value: number, host: HostSummary, mode: ViewMode, perPersonApplies: boolean = true, dailyDivisor?: number, decimals: number = 0): string {
  if (mode === 'total') return fmt(value);
  if (mode === 'daily') {
    const div = dailyDivisor ?? host.days_count;
    if (div <= 0) return '-';
    const result = value / div;
    return decimals > 0
      ? result.toLocaleString('ko-KR', { maximumFractionDigits: decimals })
      : fmt(Math.round(result));
  }
  if (!perPersonApplies) return fmt(value);
  return host.total_participants > 0 ? fmt(Math.round(value / host.total_participants)) : '-';
}

// 일자별 상세 행 변환: total/daily = 원본 (1일이라 동일), per_person = ÷ 그날 participants
function transformDate(value: number, dd: DateDetail, mode: ViewMode, perPersonApplies: boolean = true): string {
  if (mode === 'total' || mode === 'daily') return fmt(value);
  if (!perPersonApplies) return fmt(value);
  return dd.participants > 0 ? fmt(Math.round(value / dd.participants)) : '-';
}


// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function SalesReport() {
  const [dateFrom, setDateFrom] = useState(dayjs().startOf('month').format('YYYY-MM-DD'));
  const [dateTo, setDateTo] = useState(dayjs().format('YYYY-MM-DD'));

  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<ReportData>({ hosts: [], grand_total_revenue: 0, grand_total_participants: 0 });
  const [viewMode, setViewMode] = useState<ViewMode>('total');

  // 조회 기간 일수 (inclusive) — 여자초대수 일평균 계산에 사용
  const rangeDays = Math.max(1, dayjs(dateTo).diff(dayjs(dateFrom), 'day') + 1);
  const [expandedHosts, setExpandedHosts] = useState<Set<string>>(new Set());
  const [detailModal, setDetailModal] = useState<{ open: boolean; host: string; dd: DateDetail | null }>({ open: false, host: '', dd: null });

  // 진행자 관리
  const [hostModalOpen, setHostModalOpen] = useState(false);
  const [hosts, setHosts] = useState<{ id: number; name: string }[]>([]);
  const [newHostName, setNewHostName] = useState('');

  const fetchHosts = useCallback(async () => {
    try {
      const { data: res } = await partyHostsAPI.list();
      setHosts(res ?? []);
    } catch {}
  }, []);

  useEffect(() => { fetchHosts(); }, [fetchHosts]);

  const handleAddHost = async () => {
    const name = newHostName.trim();
    if (!name) return;
    try {
      await partyHostsAPI.create({ name });
      toast.success('진행자가 추가되었습니다');
      setNewHostName('');
      fetchHosts();
    } catch (e: any) {
      toast.error(e.response?.data?.detail ?? '진행자 추가에 실패했습니다');
    }
  };

  const handleDeleteHost = async (id: number) => {
    try {
      await partyHostsAPI.delete(id);
      toast.success('진행자가 삭제되었습니다');
      fetchHosts();
    } catch { toast.error('진행자 삭제에 실패했습니다'); }
  };

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const { data: res } = await salesReportAPI.get({
        date_from: dateFrom,
        date_to: dateTo,
      } as any);
      setData(res);
      setExpandedHosts(new Set());
      setDetailModal({ open: false, host: '', dd: null });
    } catch {
      toast.error('매출 데이터를 불러오는데 실패했습니다');
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const toggleHost = (username: string) => {
    setExpandedHosts(prev => {
      const next = new Set(prev);
      if (next.has(username)) next.delete(username);
      else next.add(username);
      return next;
    });
  };


  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="page-title">현장 매출 조회</h1>
          <p className="page-subtitle">진행자별 매출 기여도를 확인합니다</p>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="section-card">
        <div className="filter-bar">
          <div className="flex items-center gap-2">
            <label className="text-caption text-[#8B95A1] whitespace-nowrap">기간</label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="rounded-lg border border-[#E5E8EB] dark:border-gray-600 bg-white dark:bg-[#1E1E24] text-body text-[#191F28] dark:text-white px-3 py-1.5"
            />
            <span className="text-[#8B95A1]">~</span>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="rounded-lg border border-[#E5E8EB] dark:border-gray-600 bg-white dark:bg-[#1E1E24] text-body text-[#191F28] dark:text-white px-3 py-1.5"
            />
          </div>
          <div className="flex items-center gap-2">
            <Button color="blue" size="sm" onClick={fetchData} disabled={loading}>
              {loading ? <Spinner size="sm" className="mr-1.5" /> : <Search className="h-3.5 w-3.5 mr-1.5" />}
              조회
            </Button>
            <Button color="light" size="sm" onClick={() => setHostModalOpen(true)}>
              <UserPlus className="h-3.5 w-3.5 mr-1.5" />진행자 관리
            </Button>
          </div>
        </div>
      </div>

      {/* 모드 토글 */}
      <div className="flex items-center justify-end gap-1">
        {VIEW_MODE_OPTIONS.map((m) => (
          <button
            key={m.value}
            onClick={() => setViewMode(m.value)}
            className={`px-4 py-1.5 rounded-lg text-body font-medium transition-colors cursor-pointer ${
              viewMode === m.value
                ? 'bg-[#3182F6] text-white'
                : 'bg-[#F2F4F6] text-[#8B95A1] hover:bg-[#E5E8EB] dark:bg-[#2C2C34] dark:text-gray-400 dark:hover:bg-[#35353E]'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>

      {/* 진행자별 — 모바일 카드 뷰 */}
      <div className="md:hidden space-y-3">
        {loading ? (
          <div className="section-card flex justify-center py-12">
            <Spinner size="md" />
          </div>
        ) : data.hosts.length === 0 ? (
          <div className="section-card empty-state">
            <Users size={40} className="text-[#B0B8C1]" />
            <span className="mt-2 text-body text-[#8B95A1]">조회 결과가 없습니다</span>
          </div>
        ) : (
          data.hosts.map((host) => {
            const isExpanded = expandedHosts.has(host.host_username);
            return (
              <div key={host.host_username} className="rounded-2xl border border-[#E5E8EB] bg-white dark:border-gray-700 dark:bg-[#1E1E24] overflow-hidden">
                {/* 헤더 */}
                <button
                  type="button"
                  onClick={() => toggleHost(host.host_username)}
                  className="flex w-full items-center justify-between px-4 py-3 hover:bg-[#F2F4F6] dark:hover:bg-[#2C2C34]"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-heading font-semibold text-[#191F28] dark:text-white">{host.host_username}</span>
                    <span className="text-caption text-[#8B95A1] tabular-nums">{host.days_count}일</span>
                  </div>
                  {isExpanded ? <ChevronDown size={18} className="text-[#8B95A1]" /> : <ChevronRight size={18} className="text-[#8B95A1]" />}
                </button>

                {/* 통계 그리드 */}
                <div className="grid grid-cols-2 gap-2 px-4 pb-4">
                  <div className="rounded-xl bg-[#F8F9FA] p-3 dark:bg-[#17171C]">
                    <div className="text-caption text-[#8B95A1]">게스트</div>
                    <div className="mt-0.5 text-label font-semibold tabular-nums text-[#191F28] dark:text-white">
                      {transformHost(host.total_participants, host, viewMode, false, undefined, 1)}<span className="ml-0.5 text-tiny font-normal text-[#B0B8C1]">명</span>
                    </div>
                  </div>
                  <div className="rounded-xl bg-[#F8F9FA] p-3 dark:bg-[#17171C]">
                    <div className="text-caption text-[#8B95A1]">총매출</div>
                    <div className="mt-0.5 text-label font-bold tabular-nums text-[#191F28] dark:text-white">
                      {transformHost(host.total_revenue, host, viewMode)}<span className="ml-0.5 text-tiny font-normal text-[#B0B8C1]">원</span>
                    </div>
                  </div>
                  <div className="rounded-xl bg-[#F8F9FA] p-3 dark:bg-[#17171C]">
                    <div className="text-caption text-[#8B95A1]">리뷰수</div>
                    <div className="mt-0.5 text-label font-semibold tabular-nums text-[#191F28] dark:text-white">
                      {transformHost(host.total_reviews, host, viewMode, false, undefined, 1)}<span className="ml-0.5 text-tiny font-normal text-[#B0B8C1]">건</span>
                    </div>
                  </div>
                  <div className="rounded-xl bg-[#F8F9FA] p-3 dark:bg-[#17171C]">
                    <div className="text-caption text-[#8B95A1]">초대수</div>
                    <div className="mt-0.5 text-label font-semibold tabular-nums text-[#191F28] dark:text-white">
                      {transformHost(host.total_invited_females, host, viewMode, false, rangeDays, 1)}<span className="ml-0.5 text-tiny font-normal text-[#B0B8C1]">명</span>
                    </div>
                  </div>
                  <div className="rounded-xl bg-[#F8F9FA] p-3 dark:bg-[#17171C]">
                    <div className="text-caption text-[#8B95A1]">현장판매</div>
                    <div className="mt-0.5 text-label font-semibold tabular-nums text-[#191F28] dark:text-white">
                      {transformHost(host.total_sales, host, viewMode)}<span className="ml-0.5 text-tiny font-normal text-[#B0B8C1]">원</span>
                    </div>
                  </div>
                  <div className="rounded-xl bg-[#F8F9FA] p-3 dark:bg-[#17171C]">
                    <div className="text-caption text-[#8B95A1]">경매</div>
                    <div className="mt-0.5 text-label font-semibold tabular-nums text-[#191F28] dark:text-white">
                      {transformHost(host.total_auction, host, viewMode)}<span className="ml-0.5 text-tiny font-normal text-[#B0B8C1]">원</span>
                    </div>
                  </div>
                </div>

                {/* 펼침 — 날짜별 미니 카드 */}
                {isExpanded && (
                  <div className="border-t border-[#E5E8EB] bg-[#F8F9FB] px-4 py-3 dark:border-gray-700 dark:bg-[#17171C]">
                    <div className="space-y-2">
                      {host.dates.map((dd) => (
                        <div key={dd.date} className="rounded-xl bg-white p-3 dark:bg-[#1E1E24]">
                          <div className="flex items-center justify-between">
                            <span className="text-label font-semibold tabular-nums text-[#191F28] dark:text-white">{dd.date}</span>
                            <span className="text-caption text-[#8B95A1] tabular-nums">{dd.participants}명</span>
                          </div>
                          <div className="mt-2 grid grid-cols-2 gap-2">
                            <div>
                              <div className="text-tiny text-[#8B95A1]">현장판매</div>
                              <div className="text-caption font-semibold tabular-nums text-[#191F28] dark:text-white">
                                {fmt(dd.sales_total)}<span className="ml-0.5 text-tiny font-normal text-[#B0B8C1]">원</span>
                              </div>
                              {Object.keys(dd.sales_by_payment ?? {}).length > 0 && (
                                <div className="mt-1 flex flex-wrap gap-1">
                                  {Object.entries(dd.sales_by_payment).map(([pm, amt]) => (
                                    <Badge key={pm} color={PAYMENT_BADGE_COLOR[pm] ?? 'gray'} size="xs">
                                      {pm} {fmt(amt as number)}
                                    </Badge>
                                  ))}
                                </div>
                              )}
                            </div>
                            <div>
                              <div className="text-tiny text-[#8B95A1]">경매</div>
                              <div className="text-caption font-semibold tabular-nums text-[#191F28] dark:text-white">
                                {fmt(dd.auction_amount ?? 0)}<span className="ml-0.5 text-tiny font-normal text-[#B0B8C1]">원</span>
                              </div>
                              {dd.auction_payment_method && (
                                <div className="mt-1">
                                  <Badge color={PAYMENT_BADGE_COLOR[dd.auction_payment_method] ?? 'gray'} size="xs">{dd.auction_payment_method}</Badge>
                                </div>
                              )}
                            </div>
                          </div>
                          {(dd.reviews_count > 0 || dd.invited_females > 0) && (
                            <div className="mt-2 flex items-center gap-3 text-tiny text-[#8B95A1]">
                              {dd.reviews_count > 0 && <span>리뷰 <span className="font-semibold text-[#191F28] dark:text-white tabular-nums">{dd.reviews_count}</span>건</span>}
                              {dd.invited_females > 0 && <span>초대 <span className="font-semibold text-[#191F28] dark:text-white tabular-nums">{dd.invited_females}</span>명</span>}
                            </div>
                          )}
                          {dd.items.length > 0 && (
                            <Button
                              color="light"
                              size="xs"
                              className="mt-2 w-full"
                              onClick={() => setDetailModal({ open: true, host: host.host_username, dd })}
                            >
                              <Eye className="h-3.5 w-3.5 mr-1" />상세 보기
                            </Button>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* 진행자별 테이블 — 데스크톱 전용 */}
      <div className="hidden md:block section-card overflow-hidden">
        <div className="overflow-x-auto">
          <Table className="table-fixed">
            <colgroup>
              <col className="w-[3%]" />
              <col className="w-[12%]" />
              <col className="w-[10%]" />
              <col className="w-[7%]" />
              <col className="w-[9%]" />
              <col className="w-[9%]" />
              <col className="w-[16%]" />
              <col className="w-[16%]" />
              <col className="w-[18%]" />
            </colgroup>
            <TableHead>
              <TableRow>
                <TableHeadCell rowSpan={2} className="text-center align-middle border-r border-[#E5E8EB] dark:border-gray-700" style={{ padding: '0 4px' }}></TableHeadCell>
                <TableHeadCell rowSpan={2} className="text-center align-middle border-r border-[#E5E8EB] dark:border-gray-700">진행자</TableHeadCell>
                <TableHeadCell rowSpan={2} className="text-center align-middle border-r border-[#E5E8EB] dark:border-gray-700">여자초대수</TableHeadCell>
                <TableHeadCell colSpan={3} className="text-center border-b-0 align-middle border-r border-[#E5E8EB] dark:border-gray-700">파티지표</TableHeadCell>
                <TableHeadCell colSpan={3} className="text-center border-b-0 align-middle">매출지표</TableHeadCell>
              </TableRow>
              <TableRow>
                <TableHeadCell className="text-center text-caption font-normal bg-[#F2F4F6] dark:bg-[#2C2C34]">진행일</TableHeadCell>
                <TableHeadCell className="text-center text-caption font-normal bg-[#F2F4F6] dark:bg-[#2C2C34]">게스트</TableHeadCell>
                <TableHeadCell className="text-center text-caption font-normal bg-[#F2F4F6] dark:bg-[#2C2C34] border-r border-[#E5E8EB] dark:border-gray-700">리뷰수</TableHeadCell>
                <TableHeadCell className="text-center text-caption font-normal bg-[#F2F4F6] dark:bg-[#2C2C34]">현장판매(원)</TableHeadCell>
                <TableHeadCell className="text-center text-caption font-normal bg-[#F2F4F6] dark:bg-[#2C2C34]">경매(원)</TableHeadCell>
                <TableHeadCell className="text-center text-caption font-normal bg-[#F2F4F6] dark:bg-[#2C2C34]">총매출(원)</TableHeadCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={9} className="text-center py-12">
                    <Spinner size="md" />
                  </TableCell>
                </TableRow>
              ) : data.hosts.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={9} className="text-center py-12 text-[#8B95A1]">
                    <div className="flex flex-col items-center gap-2">
                      <Users size={32} className="text-[#B0B8C1]" />
                      조회 결과가 없습니다
                    </div>
                  </TableCell>
                </TableRow>
              ) : (
                <>
                  {data.hosts.map((host) => {
                    const isExpanded = expandedHosts.has(host.host_username);
                    return (
                      <>{/* 진행자 요약 행 */}
                        <TableRow
                          key={host.host_username}
                          className="cursor-pointer hover:bg-[#F2F4F6] dark:hover:bg-[#2C2C34]"
                          onClick={() => toggleHost(host.host_username)}
                        >
                          <TableCell className="text-[#8B95A1]" style={{ padding: '0 4px' }}>
                            <div className="flex items-center justify-center">{isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}</div>
                          </TableCell>
                          <TableCell className="text-center font-semibold text-[#191F28] dark:text-white">{host.host_username}</TableCell>
                          <TableCell className="text-center tabular-nums">{transformHost(host.total_invited_females, host, viewMode, false, rangeDays, 1)}<span className="text-[#B0B8C1] ml-0.5">명</span></TableCell>
                          <TableCell className="text-center tabular-nums">{host.days_count}<span className="text-[#B0B8C1] ml-0.5">일</span></TableCell>
                          <TableCell className="text-center tabular-nums">{transformHost(host.total_participants, host, viewMode, false, undefined, 1)}<span className="text-[#B0B8C1] ml-0.5">명</span></TableCell>
                          <TableCell className="text-center tabular-nums">{transformHost(host.total_reviews, host, viewMode, false, undefined, 1)}<span className="text-[#B0B8C1] ml-0.5">건</span></TableCell>
                          <TableCell className="text-center tabular-nums font-medium">{transformHost(host.total_sales, host, viewMode)}</TableCell>
                          <TableCell className="text-center tabular-nums font-medium">{transformHost(host.total_auction, host, viewMode)}</TableCell>
                          <TableCell className="text-center tabular-nums font-bold">{transformHost(host.total_revenue, host, viewMode)}</TableCell>
                        </TableRow>

                        {/* 날짜별 상세 (펼침) */}
                        {isExpanded && <>
                          {host.dates.map((dd) => (
                            <TableRow key={`${host.host_username}|${dd.date}`} className="hover:bg-[#F2F4F6] dark:hover:bg-[#2C2C34]" style={{ height: '36px' }}>
                              <TableCell className={DETAIL_ROW_BG} style={{ padding: '4px' }}></TableCell>
                              <TableCell className={`text-center text-caption tabular-nums text-[#4E5968] dark:text-gray-300 ${DETAIL_ROW_BG}`} style={{ padding: '4px 8px' }}>
                                {dd.items.length > 0 ? (
                                  <button onClick={() => setDetailModal({ open: true, host: host.host_username, dd })} className="text-[#3182F6] hover:underline">
                                    {dd.date}
                                  </button>
                                ) : (
                                  <span>{dd.date}</span>
                                )}
                              </TableCell>
                              <TableCell className={`text-center text-caption tabular-nums text-[#4E5968] dark:text-gray-300 ${DETAIL_ROW_BG}`} style={{ padding: '4px 8px' }}>{dd.invited_females > 0 ? `${transformDate(dd.invited_females, dd, viewMode, false)}명` : '-'}</TableCell>
                              <TableCell className={`text-center text-caption tabular-nums text-[#4E5968] dark:text-gray-300 ${DETAIL_ROW_BG}`} style={{ padding: '4px 8px' }}>1일</TableCell>
                              <TableCell className={`text-center text-caption tabular-nums text-[#4E5968] dark:text-gray-300 ${DETAIL_ROW_BG}`} style={{ padding: '4px 8px' }}>{transformDate(dd.participants, dd, viewMode, false)}명</TableCell>
                              <TableCell className={`text-center text-caption tabular-nums text-[#4E5968] dark:text-gray-300 ${DETAIL_ROW_BG}`} style={{ padding: '4px 8px' }}>{dd.reviews_count > 0 ? `${transformDate(dd.reviews_count, dd, viewMode, false)}건` : '-'}</TableCell>
                              <TableCell className={`text-center text-caption tabular-nums text-[#191F28] dark:text-white ${DETAIL_ROW_BG}`} style={{ padding: '4px 8px' }}>{transformDate(dd.sales_total, dd, viewMode)}</TableCell>
                              <TableCell className={`text-center text-caption tabular-nums text-[#191F28] dark:text-white ${DETAIL_ROW_BG}`} style={{ padding: '4px 8px' }}>{transformDate(dd.auction_amount ?? 0, dd, viewMode)}</TableCell>
                              <TableCell className={`text-center text-caption tabular-nums text-[#191F28] dark:text-white font-bold ${DETAIL_ROW_BG}`} style={{ padding: '4px 8px' }}>{transformDate(dd.sales_total + (dd.auction_amount ?? 0), dd, viewMode)}</TableCell>
                            </TableRow>
                          ))}
                        </>}
                      </>
                    );
                  })}
                </>
              )}
            </TableBody>
          </Table>
        </div>
      </div>
      {/* 판매 상세 모달 */}
      <Modal show={detailModal.open} size="md" onClose={() => setDetailModal({ open: false, host: '', dd: null })}>
        <ModalHeader>{detailModal.host} — {detailModal.dd?.date}</ModalHeader>
        <ModalBody>
          {detailModal.dd && (
            <div className="space-y-4">
              {/* 요약 */}
              <div className="rounded-xl bg-[#F8F9FA] px-4 py-3 dark:bg-[#1E1E24] space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-body text-[#4E5968] dark:text-gray-300">인원 <span className="font-semibold text-[#191F28] dark:text-white">{detailModal.dd.participants}명</span></span>
                  <div className="flex items-center gap-3">
                    <span className="text-body text-[#4E5968] dark:text-gray-300">판매 <span className="font-semibold text-[#191F28] dark:text-white tabular-nums">{fmt(detailModal.dd.sales_total)}원</span></span>
                    {detailModal.dd.auction_amount != null && (
                      <span className="text-body text-[#4E5968] dark:text-gray-300">경매 <span className="font-semibold text-[#191F28] dark:text-white tabular-nums">{fmt(detailModal.dd.auction_amount)}원</span>{detailModal.dd.auction_payment_method && <Badge color={PAYMENT_BADGE_COLOR[detailModal.dd.auction_payment_method] ?? 'gray'} size="xs" className="ml-1.5">{detailModal.dd.auction_payment_method}</Badge>}</span>
                    )}
                  </div>
                </div>
                {(detailModal.dd.reviews_count > 0 || detailModal.dd.invited_females > 0) && (
                  <div className="flex items-center gap-4 text-caption text-[#8B95A1]">
                    {detailModal.dd.reviews_count > 0 && <span>리뷰 <span className="font-semibold text-[#191F28] dark:text-white tabular-nums">{detailModal.dd.reviews_count}</span>건</span>}
                    {detailModal.dd.invited_females > 0 && <span>초대 <span className="font-semibold text-[#191F28] dark:text-white tabular-nums">{detailModal.dd.invited_females}</span>명</span>}
                  </div>
                )}
              </div>

              {/* 판매 기록 */}
              <div className="divide-y divide-[#F2F4F6] rounded-xl border border-[#E5E8EB] dark:divide-gray-800 dark:border-gray-800">
                {detailModal.dd.items.map((item, idx) => (
                  <div key={idx} className="flex items-center justify-between px-4 py-2">
                    <div className="flex items-center gap-3 flex-1">
                      {item.created_at && <span className="shrink-0 whitespace-nowrap text-tiny text-[#8B95A1] dark:text-gray-500 tabular-nums">{(() => { const d = new Date(normalizeUtcString(item.created_at)); return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`; })()}</span>}
                      <span className="text-body font-medium text-[#191F28] dark:text-white">{item.item_name}</span>
                      {item.payment_method && (
                        <Badge color={PAYMENT_BADGE_COLOR[item.payment_method as string] ?? 'gray'} size="xs">{item.payment_method}</Badge>
                      )}
                    </div>
                    <span className="tabular-nums text-body font-semibold text-[#191F28] dark:text-white">
                      {fmt(item.amount)}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">원</span>
                    </span>
                  </div>
                ))}
              </div>

              {/* 총액 (판매 + 경매) */}
              <div className="flex items-center justify-between rounded-xl bg-[#F8F9FA] px-4 py-3 dark:bg-[#1E1E24]">
                <span className="text-body font-semibold text-[#191F28] dark:text-white">총액</span>
                <span className="tabular-nums text-heading font-bold text-[#191F28] dark:text-white">
                  {fmt(detailModal.dd.items.reduce((sum, i) => sum + i.amount, 0) + (detailModal.dd.auction_amount ?? 0))}<span className="ml-0.5 text-body font-normal text-[#B0B8C1]">원</span>
                </span>
              </div>
            </div>
          )}
        </ModalBody>
      </Modal>

      {/* 진행자 관리 모달 */}
      <Modal show={hostModalOpen} size="md" onClose={() => setHostModalOpen(false)}>
        <ModalHeader>진행자 관리</ModalHeader>
        <ModalBody>
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <TextInput
                value={newHostName}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewHostName(e.target.value)}
                placeholder="진행자 이름"
                className="flex-1"
                onKeyDown={(e: React.KeyboardEvent) => e.key === 'Enter' && handleAddHost()}
              />
              <Button color="blue" size="sm" onClick={handleAddHost}>추가</Button>
            </div>

            {hosts.length === 0 ? (
              <div className="py-8 text-center text-body text-[#8B95A1]">등록된 진행자가 없습니다</div>
            ) : (
              <div className="divide-y divide-[#F2F4F6] rounded-xl border border-[#E5E8EB] dark:divide-gray-800 dark:border-gray-800">
                {hosts.map((h) => (
                  <div key={h.id} className="flex items-center justify-between px-4 py-3">
                    <span className="text-body font-medium text-[#191F28] dark:text-white">{h.name}</span>
                    <button onClick={() => handleDeleteHost(h.id)} className="rounded-lg p-1 text-[#B0B8C1] transition-colors hover:bg-[#FFF0F0] hover:text-[#F04452] dark:hover:bg-[#F04452]/10" title="삭제">
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </ModalBody>
      </Modal>
    </div>
  );
}
