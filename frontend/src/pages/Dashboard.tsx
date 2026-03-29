import { useEffect, useState } from 'react'
import { Card } from '@/components/ui/card'
import { Table, TableHead, TableBody, TableRow, TableHeadCell, TableCell } from '@/components/ui/table'
import { Spinner } from '@/components/ui/spinner'

import {
  CalendarRange,
  Send,
  Users,
  Clock,
  RefreshCw,
} from 'lucide-react'
import { dashboardAPI } from '@/services/api'
import { normalizeUtcString } from '../lib/utils'

const STATUS_LABELS: Record<string, string> = {
  pending: '대기중',
  confirmed: '확정',
  cancelled: '취소',
  completed: '완료',
}

function LoadingSkeleton() {
  return (
    <div className="flex items-center justify-center py-32">
      <Spinner size="lg" />
    </div>
  )
}

interface MetricCardProps {
  title: string
  value: string | number
  subtitle?: string
  icon: React.ReactNode
  iconBg: string
}

function MetricCard({ title, value, subtitle, icon, iconBg }: MetricCardProps) {
  return (
    <div className="stat-card">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="stat-label">{title}</p>
          <p className="stat-value mt-1">{value}</p>
          {subtitle && (
            <p className="mt-0.5 text-caption text-gray-400 dark:text-gray-600">{subtitle}</p>
          )}
        </div>
        <div className={`stat-icon ${iconBg}`}>
          {icon}
        </div>
      </div>
    </div>
  )
}

function GenderWeekly({ daily }: { daily: { date: string; male: number; female: number }[] }) {
  const formatDate = (dateStr: string) => {
    const d = new Date(dateStr + 'T00:00:00')
    const days = ['일', '월', '화', '수', '목', '금', '토']
    return `${d.getMonth() + 1}/${d.getDate()}(${days[d.getDay()]})`
  }

  const isToday = (dateStr: string) => {
    const today = new Date()
    return dateStr === `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
  }

  return (
    <div className="overflow-x-auto scrollbar-none -mx-1 px-1">
    <div className="flex gap-2 w-full min-w-[600px]">
      {daily.map((d) => {
        const dayTotal = d.male + d.female
        const today = isToday(d.date)
        const ratio = d.female === 0 ? (d.male > 0 ? 99 : 0) : d.male / d.female
        const riskBg = dayTotal === 0 ? 'bg-[#F8F9FA] dark:bg-[#1E1E24]'
          : ratio <= 2 ? 'bg-[#E8F3FF] dark:bg-[#3182F6]/15'
          : ratio <= 3 ? 'bg-[#FFF8E1] dark:bg-[#FF9F00]/15'
          : 'bg-[#FFEBEE] dark:bg-[#F04452]/15'
        const dayOfWeek = new Date(d.date + 'T00:00:00').getDay()
        return (
          <div
            key={d.date}
            className={`rounded-xl p-3 text-center min-w-[80px] flex-1 ${riskBg}`}
          >
            <div className="flex items-center justify-center gap-1">
              {today ? (
                <span className="rounded-full bg-[#3182F6] px-1.5 py-0.5 text-[9px] font-bold leading-none text-white">TODAY</span>
              ) : (
                <span className={`text-overline font-semibold ${
                  dayOfWeek === 0 ? 'text-[#F04452]'
                  : dayOfWeek === 6 ? 'text-[#3182F6]'
                  : 'text-gray-500'
                }`}>
                  {formatDate(d.date)}
                </span>
              )}
            </div>
            <p className="mt-1.5 text-heading font-bold tabular-nums text-[#191F28] dark:text-white">
              {d.female === 0 ? `${d.male}:0` : `${(d.male / d.female).toFixed(1)}:1`}
            </p>
            <div className="mt-1.5 flex items-center justify-center gap-2">
              <span className="tabular-nums text-tiny text-[#3182F6]">남{d.male}</span>
              <span className="tabular-nums text-tiny text-[#F04452] dark:text-red-400">여{d.female}</span>
            </div>
          </div>
        )
      })}
    </div>
    </div>
  )
}


const Dashboard = () => {
  const [stats, setStats] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [schedules, setSchedules] = useState<any[]>([])

  useEffect(() => {
    loadStats()
  }, [])

  useEffect(() => {
    dashboardAPI.getTodaySchedules().then(res => setSchedules(res.data)).catch(() => {})
  }, [])

  const loadStats = async () => {
    try {
      const response = await dashboardAPI.getStats()
      setStats(response.data)
    } catch (error) {
      console.error('Failed to load stats:', error)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return <LoadingSkeleton />
  }

  if (!stats) {
    return (
      <div className="empty-state">
        <p className="text-body">데이터를 불러올 수 없습니다.</p>
      </div>
    )
  }

  const todaySent = stats.campaigns?.today_sent ?? 0

  return (
    <div className="space-y-6">
      <div>
        <h1 className="page-title">대시보드</h1>
        <p className="page-subtitle">SMS 예약 시스템 현황을 한눈에 확인하세요.</p>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <MetricCard
          title="오늘 예약"
          value={stats.totals.today_reservations?.toLocaleString() ?? '0'}
          subtitle="오늘 새로 들어온 예약"
          icon={<CalendarRange size={20} />}
          iconBg="bg-[#E8F3FF] text-[#3182F6] dark:bg-[#3182F6]/15 dark:text-[#3182F6]"
        />
        <MetricCard
          title="오늘 발송"
          value={todaySent.toLocaleString()}
          subtitle="오늘 발송된 문자 건수"
          icon={<Send size={20} />}
          iconBg="bg-[#FFF5E6] text-[#FF9F00] dark:bg-[#FF9F00]/15 dark:text-[#FF9F00]"
        />
        <MetricCard
          title="네이버 동기화"
          value={stats.naver_sync?.status === 'success' ? '실행중' : stats.naver_sync?.status === 'failed' ? '오류' : '-'}
          subtitle={stats.naver_sync?.last_sync_at
            ? `${new Date(normalizeUtcString(stats.naver_sync.last_sync_at)).toLocaleString('ko-KR', { hour: '2-digit', minute: '2-digit' })} · 다음 ${new Date(normalizeUtcString(stats.naver_sync.next_sync_at)).toLocaleString('ko-KR', { hour: '2-digit', minute: '2-digit' })}`
            : '스케줄러 미실행'}
          icon={<RefreshCw size={20} />}
          iconBg={stats.naver_sync?.status === 'failed'
            ? 'bg-[#FFEBEE] text-[#F04452] dark:bg-[#F04452]/15 dark:text-[#F04452]'
            : 'bg-[#E8FAF5] text-[#00C9A7] dark:bg-[#00C9A7]/15 dark:text-[#00C9A7]'}
        />
      </div>

      {/* Gender weekly - full width */}
      <Card>
        <div className="flex items-center gap-2">
          <Users size={18} className="text-gray-400" />
          <h3 className="text-body font-semibold text-[#191F28] dark:text-white">7일간 성별 현황</h3>
        </div>
        <GenderWeekly daily={stats.gender_stats?.daily ?? []} />
      </Card>

      {/* Two-column: timeline + recent reservations */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
      <div className="section-card">
        <div className="section-header">
          <div className="flex items-center gap-2">
            <Clock size={18} className="text-gray-400" />
            <h3 className="text-body font-semibold text-[#191F28] dark:text-white">오늘 자동발송 일정표</h3>
          </div>
        </div>
        {schedules.length === 0 ? (
          <div className="py-8 text-center text-label text-gray-400">등록된 스케줄이 없습니다</div>
        ) : (
          <Table hoverable striped>
              <TableHead>
                <TableRow>
                  <TableHeadCell>템플릿</TableHeadCell>
                  <TableHeadCell>발송 시간</TableHeadCell>
                  <TableHeadCell className="text-center">상태</TableHeadCell>
                  <TableHeadCell className="text-center">결과</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody className="divide-y">
                {schedules.map((s: any, idx: number) => (
                  <TableRow key={idx}>
                    <TableCell>
                      <span className="font-medium text-gray-900 dark:text-white">{s.template_name}</span>
                    </TableCell>
                    <TableCell>
                      <span className="tabular-nums text-gray-500">{s.time}</span>
                    </TableCell>
                    <TableCell className="text-center">
                      <span className={`text-body font-medium ${
                        s.status === '완료' ? 'text-[#00C9A7]'
                        : s.status === '진행중' ? 'text-[#3182F6]'
                        : s.status === '미발송' ? 'text-[#F04452]'
                        : 'text-[#FF9F00]'
                      }`}>{s.status}</span>
                    </TableCell>
                    <TableCell className="text-center">
                      <span className="text-caption text-gray-500">{s.result}</span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
        )}
      </div>

      {/* Recent reservations (right column) */}
      <div className="section-card">
        <div className="section-header">
          <div className="flex items-center gap-2">
            <CalendarRange size={18} className="text-gray-400" />
            <h3 className="text-body font-semibold text-[#191F28] dark:text-white">최근 예약</h3>
          </div>
        </div>
          <Table hoverable striped>
            <TableHead>
              <TableRow>
                <TableHeadCell>고객명</TableHeadCell>
                <TableHeadCell>전화번호</TableHeadCell>
                <TableHeadCell>일시</TableHeadCell>
                <TableHeadCell className="text-center">상태</TableHeadCell>
              </TableRow>
            </TableHead>
            <TableBody className="divide-y">
              {(stats.recent_reservations ?? []).length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4}>
                    <div className="py-4 text-center text-label text-gray-400">
                      예약 내역이 없습니다
                    </div>
                  </TableCell>
                </TableRow>
              ) : (
                (stats.recent_reservations ?? []).slice(0, 5).map((r: any, idx: number) => (
                  <TableRow key={r.id ?? idx}>
                    <TableCell>
                      <span className="font-medium text-gray-900 dark:text-white">{r.customer_name ?? '—'}</span>
                    </TableCell>
                    <TableCell>
                      <span className="tabular-nums text-gray-500">{r.phone ?? '—'}</span>
                    </TableCell>
                    <TableCell>
                      <span className="text-gray-500">{r.check_in_date ?? ''} {r.check_in_time ?? ''}</span>
                    </TableCell>
                    <TableCell className="text-center">
                      <span className={`text-body font-medium ${
                        r.status === 'confirmed' ? 'text-[#00C9A7]'
                        : r.status === 'pending' ? 'text-[#FF9F00]'
                        : r.status === 'cancelled' ? 'text-[#F04452]'
                        : 'text-[#3182F6]'
                      }`}>{STATUS_LABELS[r.status] ?? r.status}</span>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
      </div>
      </div>
    </div>
  )
}

export default Dashboard
