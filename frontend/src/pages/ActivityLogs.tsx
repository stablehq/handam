import React, { useEffect, useState, useCallback } from 'react'
import { Table, TableHead, TableBody, TableRow, TableHeadCell, TableCell } from '@/components/ui/table'
import { TextInput } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Spinner } from '@/components/ui/spinner'
import { Button } from '@/components/ui/button'
import {
  History,
  BedDouble,
  MessageSquareText,
  RefreshCw,
  Megaphone,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  User,
  CheckCircle2,
  XCircle,
  AlertCircle,
} from 'lucide-react'
import { activityLogsAPI } from '@/services/api'
import { normalizeUtcString } from '../lib/utils'

// ── Type helpers ──────────────────────────────────────────────

type ActivityType =
  | 'room_assign'
  | 'room_move'
  | 'sms_manual'
  | 'sms_send'
  | 'naver_sync'

type ActivityStatus = 'success' | 'failed' | 'partial'

interface ActivityLog {
  id: number
  type: ActivityType
  title: string
  detail?: Record<string, unknown> | null
  target?: string | null
  success_count?: number | null
  failed_count?: number | null
  status: ActivityStatus
  actor?: string | null
  created_at: string
}

interface ActivityStats {
  total_today: number
  room_assign_today: number
  sms_sent_today: number
  naver_sync_today: number
}

// ── Label / color maps ────────────────────────────────────────

const TYPE_LABELS: Record<ActivityType, string> = {
  room_assign: '객실 배정',
  room_move: '객실 이동',
  sms_manual: 'SMS 발송',
  sms_send: 'SMS 발송',
  naver_sync: '네이버 동기화',
}

const TYPE_BADGE_COLOR: Record<ActivityType, string> = {
  room_assign: 'info',
  room_move: 'info',
  sms_manual: 'success',
  sms_send: 'success',
  naver_sync: 'warning',
}

const STATUS_LABELS: Record<ActivityStatus, string> = {
  success: '성공',
  failed: '실패',
  partial: '부분',
}

function statusBadgeColor(s: ActivityStatus): 'success' | 'failure' | 'warning' {
  if (s === 'success') return 'success'
  if (s === 'failed') return 'failure'
  return 'warning'
}

// ── Stat card ─────────────────────────────────────────────────

interface StatCardProps {
  title: string
  value: number
  icon: React.ReactNode
  iconBg: string
}

function StatCard({ title, value, icon, iconBg }: StatCardProps) {
  return (
    <div className="stat-card">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="stat-label">{title}</p>
          <p className="stat-value mt-1 tabular-nums">{value.toLocaleString()}</p>
        </div>
        <div className={`stat-icon ${iconBg}`}>{icon}</div>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────

const PAGE_SIZE = 20

const ActivityLogs = () => {
  const [logs, setLogs] = useState<ActivityLog[]>([])
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [stats, setStats] = useState<ActivityStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [statsLoading, setStatsLoading] = useState(true)

  // Filters
  const [filterType, setFilterType] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [filterDate, setFilterDate] = useState('')
  const [searchQuery, setSearchQuery] = useState('')

  // Pagination
  const [page, setPage] = useState(0)
  const [hasMore, setHasMore] = useState(true)

  // ── Data fetching ──────────────────────────────────────────

  const loadStats = useCallback(async () => {
    setStatsLoading(true)
    try {
      const res = await activityLogsAPI.getStats()
      const d = res.data
      const s = d.stats || {}
      setStats({
        total_today: d.total_activities ?? 0,
        room_assign_today: s.room_assign?.count ?? 0,
        sms_sent_today: (s.sms_send?.count ?? 0) + (s.sms_manual?.count ?? 0),
        naver_sync_today: s.naver_sync?.count ?? 0,
      })
    } catch {
      // API not yet wired — show zeros gracefully
      setStats({ total_today: 0, room_assign_today: 0, sms_sent_today: 0, naver_sync_today: 0 })
    } finally {
      setStatsLoading(false)
    }
  }, [])

  const loadLogs = useCallback(
    async (pageNum: number) => {
      setLoading(true)
      try {
        const params: Record<string, any> = {
          skip: pageNum * PAGE_SIZE,
          limit: PAGE_SIZE + 1,
        }
        if (filterType) params.type = filterType
        if (filterStatus) params.status = filterStatus
        if (filterDate) params.date = filterDate
        if (searchQuery.trim()) params.search = searchQuery.trim()

        const res = await activityLogsAPI.getAll(params)
        const data: ActivityLog[] = res.data ?? []
        setHasMore(data.length > PAGE_SIZE)
        setLogs(data.slice(0, PAGE_SIZE))
      } catch {
        setLogs([])
        setHasMore(false)
      } finally {
        setLoading(false)
      }
    },
    [filterType, filterStatus, filterDate, searchQuery],
  )

  useEffect(() => {
    loadStats()
  }, [loadStats])

  useEffect(() => {
    setPage(0)
    loadLogs(0)
  }, [filterType, filterStatus, filterDate, loadLogs])

  const handlePageChange = (next: number) => {
    setPage(next)
    loadLogs(next)
  }

  // ── Helpers ────────────────────────────────────────────────

  const fmtTime = (iso: string) => {
    try {
      const normalized = normalizeUtcString(iso);
      return new Date(normalized).toLocaleString('ko-KR', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
    } catch {
      return iso
    }
  }

  // ── Render ─────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div>
          <h1 className="page-title">활동 로그</h1>
          <p className="page-subtitle">시스템 작업 이력을 타입·상태·날짜로 조회합니다.</p>
        </div>
        <Button
          color="light"
          size="sm"
          onClick={() => {
            loadStats()
            loadLogs(page)
          }}
        >
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
          새로고침
        </Button>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {statsLoading ? (
          <div className="col-span-4 flex items-center justify-center py-10">
            <Spinner size="md" />
          </div>
        ) : (
          <>
            <StatCard
              title="오늘 총 활동"
              value={stats?.total_today ?? 0}
              icon={<History size={18} />}
              iconBg="bg-[#E8F3FF] text-[#3182F6] dark:bg-[#3182F6]/15 dark:text-[#3182F6]"
            />
            <StatCard
              title="객실 배정"
              value={stats?.room_assign_today ?? 0}
              icon={<BedDouble size={18} />}
              iconBg="bg-[#F3EEFF] text-[#7B61FF] dark:bg-[#7B61FF]/15 dark:text-[#7B61FF]"
            />
            <StatCard
              title="SMS 발송"
              value={stats?.sms_sent_today ?? 0}
              icon={<MessageSquareText size={18} />}
              iconBg="bg-[#E8FAF5] text-[#00C9A7] dark:bg-[#00C9A7]/15 dark:text-[#00C9A7]"
            />
            <StatCard
              title="네이버 동기화"
              value={stats?.naver_sync_today ?? 0}
              icon={<Megaphone size={18} />}
              iconBg="bg-[#FFF5E6] text-[#FF9F00] dark:bg-[#FF9F00]/15 dark:text-[#FF9F00]"
            />
          </>
        )}
      </div>

      {/* Main section */}
      <div className="section-card">
        {/* Filter bar */}
        <div className="filter-bar border-b border-[#E5E8EB] dark:border-gray-800">
          <TextInput
            sizing="sm"
            placeholder="제목 검색..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full sm:w-48"
          />
          <Select
            sizing="sm"
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className="w-full sm:w-40"
          >
            <option value="">전체 타입</option>
            <option value="room_assign">객실 배정</option>
            <option value="room_move">객실 이동</option>
            <option value="sms_send">SMS 발송</option>
            <option value="naver_sync">네이버 동기화</option>
          </Select>

          <Select
            sizing="sm"
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            className="w-full sm:w-32"
          >
            <option value="">전체 상태</option>
            <option value="success">성공</option>
            <option value="failed">실패</option>
            <option value="partial">부분</option>
          </Select>

          <TextInput
            sizing="sm"
            type="date"
            value={filterDate}
            onChange={(e) => setFilterDate(e.target.value)}
            className="w-full sm:w-40"
          />
        </div>

        {/* Table */}
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <Spinner size="lg" />
            </div>
          ) : logs.length === 0 ? (
            <div className="empty-state">
              <History size={40} className="mb-3 text-[#B0B8C1] dark:text-gray-600" />
              <p className="text-body font-medium text-[#4E5968] dark:text-gray-300">
                활동 기록이 없습니다
              </p>
              <p className="mt-1 text-label text-[#8B95A1] dark:text-gray-500">
                조건을 변경하거나 새로고침을 눌러보세요.
              </p>
            </div>
          ) : (
            <Table hoverable striped>
              <TableHead>
                <TableRow>
                  <TableHeadCell className="w-36 whitespace-nowrap">시간</TableHeadCell>
                  <TableHeadCell className="w-28">타입</TableHeadCell>
                  <TableHeadCell>제목</TableHeadCell>
                  <TableHeadCell className="w-28 text-right">대상/성공/실패</TableHeadCell>
                  <TableHeadCell className="w-20">상태</TableHeadCell>
                  <TableHeadCell className="w-24">실행자</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody className="divide-y">
                {logs.map((log) => {
                  const isExpanded = expandedId === log.id
                  const parsedDetail = (() => {
                    if (!log.detail) return null;
                    if (typeof log.detail === 'string') {
                      try { return JSON.parse(log.detail); } catch { return null; }
                    }
                    return log.detail;
                  })();
                  const hasDetail = parsedDetail && typeof parsedDetail === 'object' && Object.keys(parsedDetail).length > 0
                  return (
                    <React.Fragment key={log.id}>
                      <TableRow
                        className={hasDetail ? 'cursor-pointer' : ''}
                        onClick={() => hasDetail && setExpandedId(isExpanded ? null : log.id)}
                      >
                        {/* Time */}
                        <TableCell>
                          <div className="flex items-center gap-1.5">
                            <ChevronDown className={`h-3 w-3 shrink-0 text-[#B0B8C1] transition-transform ${isExpanded ? 'rotate-180' : ''} ${hasDetail ? '' : 'invisible'}`} />
                            <span className="whitespace-nowrap text-caption tabular-nums text-[#8B95A1] dark:text-gray-500">
                              {fmtTime(log.created_at)}
                            </span>
                          </div>
                        </TableCell>

                        {/* Type badge */}
                        <TableCell>
                          <Badge
                            color={TYPE_BADGE_COLOR[log.type] as any}
                            size="sm"
                            className="whitespace-nowrap"
                          >
                            {TYPE_LABELS[log.type] ?? log.type}
                          </Badge>
                        </TableCell>

                        {/* Title */}
                        <TableCell>
                          <span className="line-clamp-1 flex items-center gap-1 text-body whitespace-nowrap">
                            {(() => {
                              // [이름] 나머지 → 뱃지 + 텍스트 (테넌트 접두어 제거)
                              const stripped = log.title.replace(/^\[[^\]]+\]\s*/, '')
                              const match = stripped.match(/^(?:\[([^\]]+)\]\s*)?(.*)$/)
                              if (!match) return <span className="text-[#191F28] dark:text-white">{stripped}</span>
                              const [, name, rest] = match
                              return (
                                <>
                                  {name && (
                                    <span className="inline-flex items-center rounded px-3 py-0.5 text-caption font-semibold bg-[#F2F4F6] text-[#191F28] dark:bg-[#2C2C34] dark:text-gray-200">
                                      {name}
                                    </span>
                                  )}
                                  <span className="text-[#191F28] dark:text-white">{rest}</span>
                                </>
                              )
                            })()}
                          </span>
                          {log.target && (
                            <span className="mt-0.5 block text-caption text-[#8B95A1] dark:text-gray-500">
                              {log.target}
                            </span>
                          )}
                        </TableCell>

                        {/* Counts */}
                        <TableCell>
                          <div className="flex items-center justify-end gap-1.5 text-caption tabular-nums">
                            {log.success_count != null && (
                              <span className="flex items-center gap-0.5 text-[#00C9A7]">
                                <CheckCircle2 className="h-3 w-3" />
                                {log.success_count}
                              </span>
                            )}
                            {log.failed_count != null && log.failed_count > 0 && (
                              <span className="flex items-center gap-0.5 text-[#F04452]">
                                <XCircle className="h-3 w-3" />
                                {log.failed_count}
                              </span>
                            )}
                            {log.success_count == null && log.failed_count == null && (
                              <span className="text-[#B0B8C1]">—</span>
                            )}
                          </div>
                        </TableCell>

                        {/* Status badge */}
                        <TableCell>
                          <Badge color={statusBadgeColor(log.status)} size="sm">
                            {STATUS_LABELS[log.status] ?? log.status}
                          </Badge>
                        </TableCell>

                        {/* Actor */}
                        <TableCell>
                          {log.actor ? (
                            <span className="flex items-center gap-1 text-label text-[#4E5968] dark:text-gray-300">
                              <User className="h-3 w-3 shrink-0 text-[#B0B8C1]" />
                              {log.actor}
                            </span>
                          ) : (
                            <span className="flex items-center gap-1 text-label text-[#B0B8C1]">
                              <AlertCircle className="h-3 w-3" />
                              시스템
                            </span>
                          )}
                        </TableCell>
                      </TableRow>

                      {/* Detail row — 2-column layout */}
                      {isExpanded && hasDetail && (() => {
                        const d = parsedDetail!
                        const targets = Array.isArray(d.targets) ? d.targets as Array<{name: string; phone: string; status: string; error?: string; message_id?: string; template_detail?: string; message?: string; customer_name?: string; guest_name?: string; room_number?: string; reservation_id?: number}> : []
                        const metaKeys = Object.keys(d).filter(k => k !== 'message' && k !== 'targets')
                        // 단건 발송이면 message가 detail에 직접 있고, 배치면 targets[0].message
                        const messageContent = d.message ? String(d.message) : (targets.length > 0 && targets[0].message ? String(targets[0].message) : '')

                        // 필드명 → 한글 설명 매핑
                        const FIELD_LABELS: Record<string, string> = {
                          reservation_id: '예약 ID',
                          customer_name: '예약자명',
                          phone: '전화번호',
                          template_key: '템플릿',
                          room_number: '객실',
                          provider: '발송 경로',
                          message_id: '메시지 ID',
                          error: '오류',
                          schedule_id: '스케줄 ID',
                          date_filter: '대상 날짜',
                          old_room: '이전 객실',
                          new_room: '변경 객실',
                          guest_name: '예약자명',
                          move_type: '배정 유형',
                          dates: '적용 일자',
                          old_section: '이전 섹션',
                          new_section: '변경 섹션',
                          target_date: '대상 날짜',
                          period_start: '시작 시간',
                          period_end: '종료 시간',
                          total: '전체 건수',
                          synced: '동기화 건수',
                          created: '생성 건수',
                          updated: '갱신 건수',
                          success: '성공 여부',
                          content: '내용',
                          to: '수신번호',
                        }

                        return (
                          <TableRow>
                            <TableCell colSpan={6} className="!py-3 !px-5 bg-[#F8F9FA] dark:bg-[#1E1E24]">
                              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                                {/* Column 1: 정보 + 발송 대상자 */}
                                <div className="space-y-2">
                                  {/* Meta fields — 세로 정렬, 한글 라벨 */}
                                  {metaKeys.length > 0 && (
                                    <div className="rounded-lg border border-[#E5E8EB] bg-white dark:border-gray-700 dark:bg-[#2C2C34] overflow-hidden">
                                      <table className="w-full text-caption">
                                        <tbody>
                                          {(() => {
                                            // 2컬럼으로 나누기
                                            const half = Math.ceil(metaKeys.length / 2)
                                            const rows = Array.from({ length: half }, (_, i) => [metaKeys[i], metaKeys[i + half]] as const)
                                            return rows.map(([leftKey, rightKey], i) => {
                                              const fmt = (key: string | undefined) => {
                                                if (!key) return null
                                                const value = d[key]
                                                return value === null || value === undefined
                                                  ? '-'
                                                  : typeof value === 'object'
                                                    ? JSON.stringify(value)
                                                    : String(value)
                                              }
                                              return (
                                                <tr key={i} className="border-b last:border-b-0 border-[#F2F4F6] dark:border-gray-800">
                                                  <td className="px-3 py-1.5 whitespace-nowrap font-medium text-[#8B95A1] dark:text-gray-500 w-24">
                                                    {FIELD_LABELS[leftKey] || leftKey}
                                                  </td>
                                                  <td className="px-3 py-1.5 text-[#191F28] dark:text-gray-200 tabular-nums">
                                                    {fmt(leftKey)}
                                                  </td>
                                                  {rightKey ? (
                                                    <>
                                                      <td className="px-3 py-1.5 whitespace-nowrap font-medium text-[#8B95A1] dark:text-gray-500 w-24 border-l border-[#F2F4F6] dark:border-gray-800">
                                                        {FIELD_LABELS[rightKey] || rightKey}
                                                      </td>
                                                      <td className="px-3 py-1.5 text-[#191F28] dark:text-gray-200 tabular-nums">
                                                        {fmt(rightKey)}
                                                      </td>
                                                    </>
                                                  ) : (
                                                    <>
                                                      <td className="border-l border-[#F2F4F6] dark:border-gray-800" />
                                                      <td />
                                                    </>
                                                  )}
                                                </tr>
                                              )
                                            })
                                          })()}
                                        </tbody>
                                      </table>
                                    </div>
                                  )}
                                  {/* Targets table */}
                                  {targets.length > 0 && (
                                    <div className="rounded-lg border border-[#E5E8EB] bg-white dark:border-gray-700 dark:bg-[#2C2C34] overflow-hidden">
                                      <table className="w-full text-caption">
                                        <thead>
                                          <tr className="border-b border-[#E5E8EB] dark:border-gray-700 bg-[#F8F9FA] dark:bg-[#1E1E24]">
                                            <th className="px-3 py-1.5 text-left font-medium text-[#8B95A1]">이름</th>
                                            {log.type === 'room_assign' ? (
                                              <th className="px-3 py-1.5 text-left font-medium text-[#8B95A1]">배정 객실</th>
                                            ) : (
                                              <>
                                                <th className="px-3 py-1.5 text-left font-medium text-[#8B95A1]">전화번호</th>
                                                <th className="px-3 py-1.5 text-left font-medium text-[#8B95A1]">객실</th>
                                                <th className="px-3 py-1.5 text-left font-medium text-[#8B95A1]">결과</th>
                                              </>
                                            )}
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {targets.map((t, i) => (
                                            <tr key={i} className="border-b last:border-b-0 border-[#F2F4F6] dark:border-gray-800">
                                              <td className="px-3 py-1.5 text-[#191F28] dark:text-gray-200">{t.customer_name || t.guest_name || t.name || '-'}</td>
                                              {log.type === 'room_assign' ? (
                                                <td className="px-3 py-1.5 text-[#4E5968] dark:text-gray-400">{t.room_number || '-'}</td>
                                              ) : (
                                                <>
                                                  <td className="px-3 py-1.5 tabular-nums text-[#4E5968] dark:text-gray-400">{t.phone || '-'}</td>
                                                  <td className="px-3 py-1.5 text-[#4E5968] dark:text-gray-400">{t.template_detail || '-'}</td>
                                                  <td className="px-3 py-1.5">
                                                    {t.status === 'success' ? (
                                                      <span className="text-[#00C9A7]">성공</span>
                                                    ) : (
                                                      <span className="text-[#F04452]">{t.error || '실패'}</span>
                                                    )}
                                                  </td>
                                                </>
                                              )}
                                            </tr>
                                          ))}
                                        </tbody>
                                      </table>
                                    </div>
                                  )}
                                </div>
                                {/* Column 2: 문자 내용 */}
                                {messageContent && (
                                  <div className="space-y-1">
                                    <span className="text-caption font-medium text-[#8B95A1] dark:text-gray-500">문자 내용</span>
                                    <pre className="whitespace-pre-wrap rounded-lg bg-white p-3 text-caption text-[#191F28] border border-[#E5E8EB] dark:bg-[#2C2C34] dark:text-gray-200 dark:border-gray-700">
                                      {messageContent}
                                    </pre>
                                  </div>
                                )}
                              </div>
                            </TableCell>
                          </TableRow>
                        )
                      })()}
                    </React.Fragment>
                  )
                })}
              </TableBody>
            </Table>
          )}

        {/* Pagination */}
        {logs.length > 0 && (
          <div className="flex items-center justify-between border-t border-[#E5E8EB] px-5 py-3 dark:border-gray-800">
            <span className="text-caption text-[#8B95A1] dark:text-gray-500">
              {page * PAGE_SIZE + 1}–{page * PAGE_SIZE + logs.length}번 기록
            </span>
            <div className="flex items-center gap-2">
              <Button
                color="light"
                size="xs"
                disabled={page === 0}
                onClick={() => handlePageChange(page - 1)}
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </Button>
              <span className="min-w-[2rem] text-center text-caption tabular-nums text-[#4E5968] dark:text-gray-300">
                {page + 1}
              </span>
              <Button
                color="light"
                size="xs"
                disabled={!hasMore}
                onClick={() => handlePageChange(page + 1)}
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default ActivityLogs
