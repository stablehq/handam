import { useState, useEffect, useCallback } from 'react';
import { toast } from 'sonner';
import { Search, ChevronDown, ChevronRight, Users, Eye, UserPlus, Trash2 } from 'lucide-react';
import { Modal, ModalHeader, ModalBody } from '@/components/ui/modal';
import { TextInput } from '@/components/ui/input';
import dayjs from 'dayjs';

import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import { Table, TableHead, TableBody, TableRow, TableHeadCell, TableCell } from '@/components/ui/table';

import { salesReportAPI, partyHostsAPI } from '@/services/api';

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

function SalesChips({ sales, auction, unit = '원' }: { sales: number; auction: number; unit?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="inline-flex items-center gap-1">
        <span className="rounded bg-[#E8F3FF] px-1.5 py-0.5 text-tiny font-medium text-[#3182F6] dark:bg-[#3182F6]/15">판매</span>
        <span>{fmt(sales)}</span>
      </span>
      <span className="inline-flex items-center gap-1">
        <span className="rounded bg-[#FFF4E5] px-1.5 py-0.5 text-tiny font-medium text-[#FF9500] dark:bg-[#FF9500]/15">경매</span>
        <span>{fmt(auction)}</span>
      </span>
      <span className="text-[#B0B8C1] font-normal">{unit}</span>
    </span>
  );
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

      {/* 진행자별 테이블 */}
      <div className="section-card overflow-hidden">
        <div className="overflow-x-auto">
          <Table className="table-fixed">
            <colgroup>
              <col className="w-10" />
              <col className="w-[20%]" />
              <col className="w-[12%]" />
              <col className="w-[12%]" />
              <col className="w-[18%]" />
              <col className="w-[14%]" />
              <col className="w-[14%]" />
            </colgroup>
            <TableHead>
              <TableRow>
                <TableHeadCell></TableHeadCell>
                <TableHeadCell>진행자</TableHeadCell>
                <TableHeadCell className="text-center">진행일</TableHeadCell>
                <TableHeadCell className="text-center">총 게스트</TableHeadCell>
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
                            <SalesChips sales={host.total_sales} auction={host.total_auction} />
                          </TableCell>
                          <TableCell className="text-right tabular-nums font-medium text-[#3182F6]">
                            {host.total_participants > 0 ? <SalesChips sales={Math.round(host.total_sales / host.total_participants)} auction={Math.round(host.total_auction / host.total_participants)} /> : '-'}
                          </TableCell>
                          <TableCell className="text-right tabular-nums font-medium">
                            {fmt(host.daily_avg)}<span className="ml-0.5 text-[#B0B8C1] font-normal">원</span>
                          </TableCell>
                        </TableRow>

                        {/* 날짜별 상세 (펼침) */}
                        {isExpanded && <>
                          {host.dates.map((dd) => (
                            <TableRow key={`${host.host_username}|${dd.date}`} className="bg-[#F8F9FA] dark:bg-[#1E1E24] hover:bg-[#F2F4F6] dark:hover:bg-[#2C2C34]">
                              <TableCell></TableCell>
                              <TableCell></TableCell>
                              <TableCell className="text-center text-caption tabular-nums text-[#4E5968] dark:text-gray-300">{dd.date}</TableCell>
                              <TableCell className="text-center text-caption tabular-nums text-[#4E5968] dark:text-gray-300">{dd.participants}명</TableCell>
                              <TableCell className="text-right text-caption tabular-nums text-[#4E5968] dark:text-gray-300">
                                <SalesChips sales={dd.sales_total} auction={dd.auction_amount ?? 0} />
                              </TableCell>
                              <TableCell className="text-right text-caption tabular-nums text-[#3182F6]">
                                {dd.participants > 0 ? <SalesChips sales={Math.round(dd.sales_total / dd.participants)} auction={Math.round((dd.auction_amount ?? 0) / dd.participants)} /> : '-'}
                              </TableCell>
                              <TableCell className="text-right">
                                {dd.items.length > 0 && (
                                  <Button color="light" size="xs" onClick={() => setDetailModal({ open: true, host: host.host_username, dd })}>
                                    <Eye className="h-3.5 w-3.5 mr-1" />상세
                                  </Button>
                                )}
                              </TableCell>
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
              <div className="flex items-center justify-between rounded-xl bg-[#F8F9FA] px-4 py-3 dark:bg-[#1E1E24]">
                <span className="text-body text-[#4E5968] dark:text-gray-300">인원 <span className="font-semibold text-[#191F28] dark:text-white">{detailModal.dd.participants}명</span></span>
                <div className="flex items-center gap-3">
                  <span className="text-body text-[#4E5968] dark:text-gray-300">판매 <span className="font-semibold text-[#191F28] dark:text-white tabular-nums">{fmt(detailModal.dd.sales_total)}원</span></span>
                  {detailModal.dd.auction_amount != null && (
                    <span className="text-body text-[#FF9500]">경매 <span className="font-semibold tabular-nums">{fmt(detailModal.dd.auction_amount)}원</span></span>
                  )}
                </div>
              </div>

              {/* 판매 기록 */}
              <div className="divide-y divide-[#F2F4F6] rounded-xl border border-[#E5E8EB] dark:divide-gray-800 dark:border-gray-800">
                {detailModal.dd.items.map((item, idx) => (
                  <div key={idx} className="flex items-center justify-between px-4 py-3">
                    <div className="flex items-center gap-3 flex-1">
                      {item.created_at && <span className="shrink-0 whitespace-nowrap text-tiny text-[#8B95A1] dark:text-gray-500 tabular-nums">{(() => { const d = new Date(item.created_at); return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`; })()}</span>}
                      <span className="text-body font-medium text-[#191F28] dark:text-white">{item.item_name}</span>
                    </div>
                    <span className="tabular-nums text-body font-semibold text-[#191F28] dark:text-white">
                      {fmt(item.amount)}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">원</span>
                    </span>
                  </div>
                ))}
              </div>

              {/* 총액 */}
              <div className="flex items-center justify-between rounded-xl bg-[#F8F9FA] px-4 py-3 dark:bg-[#1E1E24]">
                <span className="text-body font-semibold text-[#191F28] dark:text-white">총액</span>
                <span className="tabular-nums text-heading font-bold text-[#3182F6]">
                  {fmt(detailModal.dd.items.reduce((sum, i) => sum + i.amount, 0))}<span className="ml-0.5 text-body font-normal text-[#B0B8C1]">원</span>
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
