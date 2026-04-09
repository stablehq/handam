import { useState, useEffect, useCallback } from 'react';
import { toast } from 'sonner';
import { Search, ChevronDown, ChevronRight, Users } from 'lucide-react';
import dayjs from 'dayjs';

import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import { Table, TableHead, TableBody, TableRow, TableHeadCell, TableCell } from '@/components/ui/table';

import { salesReportAPI } from '@/services/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SalesItemDetail {
  item_name: string;
  amount: number;
  created_at: string | null;
}

interface DateDetail {
  date: string;
  participants: number;
  sales_total: number;
  auction_amount: number | null;
  items: SalesItemDetail[];
}

interface HostSummary {
  host_username: string;
  days_count: number;
  total_sales: number;
  total_auction: number;
  total_revenue: number;
  total_participants: number;
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

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function SalesReport() {
  const [dateFrom, setDateFrom] = useState(dayjs().startOf('month').format('YYYY-MM-DD'));
  const [dateTo, setDateTo] = useState(dayjs().format('YYYY-MM-DD'));

  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<ReportData>({ hosts: [], grand_total_revenue: 0, grand_total_participants: 0 });
  const [expandedHosts, setExpandedHosts] = useState<Set<string>>(new Set());
  const [expandedDates, setExpandedDates] = useState<Set<string>>(new Set());

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const { data: res } = await salesReportAPI.get({
        date_from: dateFrom,
        date_to: dateTo,
      } as any);
      setData(res);
      setExpandedHosts(new Set());
      setExpandedDates(new Set());
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

  const toggleDate = (key: string) => {
    setExpandedDates(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
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
          <Button color="blue" size="sm" onClick={fetchData} disabled={loading}>
            {loading ? <Spinner size="sm" className="mr-1.5" /> : <Search className="h-3.5 w-3.5 mr-1.5" />}
            조회
          </Button>
        </div>
      </div>

      {/* 전체 요약 */}
      <div className="grid grid-cols-2 gap-3">
        <div className="stat-card">
          <div className="stat-label">총 매출</div>
          <div className="stat-value tabular-nums">
            {fmt(data.grand_total_revenue)}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">원</span>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">총 파티 인원</div>
          <div className="stat-value tabular-nums">
            {fmt(data.grand_total_participants)}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span>
          </div>
        </div>
      </div>

      {/* 진행자별 테이블 */}
      <div className="section-card overflow-hidden">
        <div className="overflow-x-auto">
          <Table>
            <TableHead>
              <TableRow>
                <TableHeadCell className="w-8"></TableHeadCell>
                <TableHeadCell>진행자</TableHeadCell>
                <TableHeadCell className="text-center">일수</TableHeadCell>
                <TableHeadCell className="text-center">인원</TableHeadCell>
                <TableHeadCell className="text-right">총 매출</TableHeadCell>
                <TableHeadCell className="text-right">인당 평균</TableHeadCell>
                <TableHeadCell className="text-right">일 평균</TableHeadCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-12">
                    <Spinner size="md" />
                  </TableCell>
                </TableRow>
              ) : data.hosts.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-12 text-[#8B95A1]">
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
                          <TableCell className="w-8 text-[#8B95A1]">
                            {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                          </TableCell>
                          <TableCell className="font-semibold text-[#191F28] dark:text-white">{host.host_username}</TableCell>
                          <TableCell className="text-center tabular-nums">{host.days_count}<span className="text-[#B0B8C1] ml-0.5">일</span></TableCell>
                          <TableCell className="text-center tabular-nums">{fmt(host.total_participants)}<span className="text-[#B0B8C1] ml-0.5">명</span></TableCell>
                          <TableCell className="text-right tabular-nums font-medium">
                            {fmt(host.total_revenue)}<span className="ml-0.5 text-[#B0B8C1] font-normal">원</span>
                          </TableCell>
                          <TableCell className="text-right tabular-nums font-medium text-[#3182F6]">
                            {fmt(host.avg_per_person)}<span className="ml-0.5 text-[#B0B8C1] font-normal">원</span>
                          </TableCell>
                          <TableCell className="text-right tabular-nums font-medium">
                            {fmt(host.daily_avg)}<span className="ml-0.5 text-[#B0B8C1] font-normal">원</span>
                          </TableCell>
                        </TableRow>

                        {/* 날짜별 상세 (펼침) */}
                        {isExpanded && host.dates.map((dd) => {
                          const dateKey = `${host.host_username}|${dd.date}`;
                          const isDateExpanded = expandedDates.has(dateKey);
                          return (
                            <>{/* 날짜 행 */}
                              <TableRow
                                key={dateKey}
                                className="bg-[#F8F9FA] dark:bg-[#1E1E24] cursor-pointer hover:bg-[#F2F4F6] dark:hover:bg-[#2C2C34]"
                                onClick={() => toggleDate(dateKey)}
                              >
                                <TableCell className="w-8 pl-6 text-[#8B95A1]">
                                  {dd.items.length > 0 ? (isDateExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />) : null}
                                </TableCell>
                                <TableCell className="text-caption tabular-nums text-[#4E5968] dark:text-gray-300">{dd.date}</TableCell>
                                <TableCell></TableCell>
                                <TableCell className="text-center text-caption tabular-nums text-[#4E5968] dark:text-gray-300">{dd.participants}명</TableCell>
                                <TableCell className="text-right text-caption tabular-nums text-[#4E5968] dark:text-gray-300">
                                  판매 {fmt(dd.sales_total)}원
                                  {dd.auction_amount != null && <span className="ml-2 text-[#FF9500]">경매 {fmt(dd.auction_amount)}원</span>}
                                </TableCell>
                                <TableCell></TableCell>
                                <TableCell></TableCell>
                              </TableRow>

                              {/* 개별 판매 항목 (펼침) */}
                              {isDateExpanded && dd.items.map((item, idx) => (
                                <TableRow key={`${dateKey}|${idx}`} className="bg-[#FAFBFC] dark:bg-[#17171C]">
                                  <TableCell></TableCell>
                                  <TableCell className="pl-8 text-caption text-[#8B95A1]">
                                    {item.created_at && (() => { const d = new Date(item.created_at); return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`; })()}
                                  </TableCell>
                                  <TableCell colSpan={2} className="text-caption text-[#4E5968] dark:text-gray-300">{item.item_name}</TableCell>
                                  <TableCell className="text-right text-caption tabular-nums text-[#4E5968] dark:text-gray-300">
                                    {fmt(item.amount)}<span className="ml-0.5 text-[#B0B8C1]">원</span>
                                  </TableCell>
                                  <TableCell></TableCell>
                                  <TableCell></TableCell>
                                </TableRow>
                              ))}
                            </>
                          );
                        })}
                      </>
                    );
                  })}
                </>
              )}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  );
}
