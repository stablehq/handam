import { useState, useEffect, useCallback } from 'react'
import dayjs from 'dayjs'
import { useTenantStore } from '@/stores/tenant-store'
import { useAuthStore } from '@/stores/auth-store'
import { Modal, ModalHeader, ModalBody } from '@/components/ui/modal'
import { Spinner } from '@/components/ui/spinner'
import { Button } from '@/components/ui/button'
import { TextInput } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Users, AlertTriangle, ChevronLeft, ChevronRight, Trash2 } from 'lucide-react'
import { partyCheckinAPI, onsiteSalesAPI, dailyHostAPI, onsiteAuctionAPI, partyHostsAPI, dailyReviewAPI, onsiteFemaleInviteAPI, reservationsAPI } from '@/services/api'
import { normalizeUtcString } from '@/lib/utils'
import { toast } from 'sonner'

interface PartyGuest {
  id: number
  customer_name: string
  phone: string
  gender: string | null
  male_count: number | null
  female_count: number | null
  party_type: string | null
  checked_in: boolean
  checked_in_at: string | null
  room_number: string | null
  notes: string | null
  stay_group_id?: string | null
  stay_group_order?: number | null
  is_long_stay?: boolean
}

type PaymentMethod = '카드' | '이체' | '현금'

interface Sale {
  id: number
  item_name: string
  amount: number
  payment_method: PaymentMethod | null
  created_by: string | null
  created_at: string | null
}

const PAYMENT_METHODS: PaymentMethod[] = ['카드', '이체', '현금']
const PAYMENT_BADGE_COLOR: Record<PaymentMethod, 'info' | 'purple' | 'success'> = {
  '카드': 'info',
  '이체': 'purple',
  '현금': 'success',
}

interface Auction {
  id: number
  date: string
  item_name: string
  final_amount: number
  winner_name: string
  payment_method: PaymentMethod | null
  created_by: string | null
  created_at: string | null
}

interface HostItem {
  id: number
  name: string
}

interface InviteRow {
  id: number
  date: string
  host_username: string
  count: number
}

function getTodayStr(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function formatGender(male: number | null, female: number | null): string {
  const m = male ?? 0
  const f = female ?? 0
  if (m === 0 && f === 0) return '-'
  const parts: string[] = []
  if (m > 0) parts.push(`남${m}`)
  if (f > 0) parts.push(`여${f}`)
  return parts.join(' ')
}


export default function PartyCheckin() {
  const { tenants, currentTenantId } = useTenantStore()
  const hasUnstable = tenants.find(t => String(t.id) === currentTenantId)?.has_unstable ?? false
  const userRole = useAuthStore((s) => s.user?.role)
  const canManageHost = userRole === 'admin' || userRole === 'superadmin'

  const [selectedDate, setSelectedDate] = useState(getTodayStr())
  const [activeTab, setActiveTab] = useState<'checkin' | 'sales'>('checkin')

  // ── Checkin state ──
  const [guests, setGuests] = useState<PartyGuest[]>([])
  const [unstableGuests, setUnstableGuests] = useState<PartyGuest[]>([])
  const [loading, setLoading] = useState(false)
  const [toggling, setToggling] = useState<number | null>(null)
  const [cancelModal, setCancelModal] = useState<{ open: boolean; guest: PartyGuest | null }>({
    open: false,
    guest: null,
  })

  // ── Add participant modal (현장추가) ──
  const [addModal, setAddModal] = useState({
    open: false,
    name: '',
    phone: '',
    maleCount: '',
    femaleCount: '',
    partyType: '1' as '1' | '2' | '2차만',
    saving: false,
  })

  // 추가 후 입장 처리 확인 모달
  const [checkInConfirm, setCheckInConfirm] = useState(false)

  function resetAddModal() {
    setAddModal({ open: false, name: '', phone: '', maleCount: '', femaleCount: '', partyType: '1', saving: false })
    setCheckInConfirm(false)
  }

  function openCheckInConfirm() {
    const trimmedName = addModal.name.trim()
    if (!trimmedName) { toast.error('이름을 입력해주세요'); return }
    const m = Number(addModal.maleCount) || 0
    const f = Number(addModal.femaleCount) || 0
    if (m + f < 1) { toast.error('남/여 인원 합이 1명 이상이어야 합니다'); return }
    setAddModal(prev => ({ ...prev, open: false }))
    setCheckInConfirm(true)
  }

  async function handleAddParticipant(checkIn: boolean) {
    const trimmedName = addModal.name.trim()
    const m = Number(addModal.maleCount) || 0
    const f = Number(addModal.femaleCount) || 0

    setCheckInConfirm(false)
    setAddModal(prev => ({ ...prev, saving: true }))
    try {
      const res = await reservationsAPI.create({
        customer_name: trimmedName,
        phone: addModal.phone.trim(),
        check_in_date: selectedDate,
        check_in_time: '00:00',
        check_out_date: dayjs(selectedDate).add(1, 'day').format('YYYY-MM-DD'),
        status: 'confirmed',
        male_count: m || null,
        female_count: f || null,
        party_type: addModal.partyType,
        booking_source: 'manual',
        naver_room_type: '현장추가',
        section: 'party',
      })

      if (checkIn && res.data?.id) {
        try { await partyCheckinAPI.toggle(res.data.id, selectedDate) } catch { /* 입장 처리 실패해도 추가는 성공 */ }
      }

      resetAddModal()
      fetchGuests(selectedDate)
      toast.success(`${trimmedName}님 추가됨`)
    } catch {
      toast.error('추가에 실패했습니다')
      setAddModal(prev => ({ ...prev, open: true, saving: false }))
    }
  }

  // ── Sales state ──
  const [sales, setSales] = useState<Sale[]>([])
  const [salesLoading, setSalesLoading] = useState(false)
  const [newItemName, setNewItemName] = useState('')
  const [newAmount, setNewAmount] = useState('')
  const [newPaymentMethod, setNewPaymentMethod] = useState<PaymentMethod>('카드')

  // ── Host state ──
  const [hosts, setHosts] = useState<HostItem[]>([])
  const [hostName, setHostName] = useState('')

  // ── Auction state ──
  const [auction, setAuction] = useState<Auction | null>(null)
  const [auctionItemName, setAuctionItemName] = useState('')
  const [auctionAmount, setAuctionAmount] = useState('')
  const [auctionWinner, setAuctionWinner] = useState('')
  const [auctionPaymentMethod, setAuctionPaymentMethod] = useState<PaymentMethod>('카드')

  // ── Review state ──
  const [reviewCount, setReviewCount] = useState('')

  // ── 진행자 카드 통합 저장/수정 모드 ──
  const [cardEditing, setCardEditing] = useState(true)
  const [cardSaving, setCardSaving] = useState(false)

  // ── Female invite state ──
  const [invites, setInvites] = useState<InviteRow[]>([])
  const [pendingInvites, setPendingInvites] = useState<{ tempId: number; host: string; count: string }[]>([])
  const [inviteSaving, setInviteSaving] = useState(false)
  const [inviteEditing, setInviteEditing] = useState(true)

  // ── Fetch checkin guests ──
  const fetchGuests = useCallback(async (date: string) => {
    setLoading(true)
    try {
      const [stableRes, unstableRes] = await Promise.all([
        partyCheckinAPI.getList(date, 'stable'),
        hasUnstable ? partyCheckinAPI.getList(date, 'unstable') : Promise.resolve({ data: [] }),
      ])
      setGuests(stableRes.data)
      setUnstableGuests(unstableRes.data)
    } catch {
      toast.error('파티 예약자 목록을 불러오지 못했습니다')
    } finally {
      setLoading(false)
    }
  }, [hasUnstable])

  useEffect(() => {
    fetchGuests(selectedDate)
  }, [selectedDate, fetchGuests])

  // ── Fetch sales/host/auction/review/invites when sales tab active ──
  const fetchSalesData = useCallback(async (date: string) => {
    setSalesLoading(true)
    try {
      const [salesRes, hostRes, auctionRes, reviewRes, invitesRes] = await Promise.all([
        onsiteSalesAPI.getList(date),
        canManageHost ? dailyHostAPI.get(date) : Promise.resolve({ data: null }),
        canManageHost ? onsiteAuctionAPI.get(date) : Promise.resolve({ data: null }),
        canManageHost ? dailyReviewAPI.get(date) : Promise.resolve({ data: null }),
        canManageHost ? onsiteFemaleInviteAPI.list(date) : Promise.resolve({ data: [] }),
      ])
      setSales(salesRes.data ?? [])

      const host = hostRes.data
      const fetchedHost = host?.host_username ?? ''
      setHostName(fetchedHost)

      const auc = auctionRes.data
      setAuction(auc)
      if (auc) {
        setAuctionItemName(auc.item_name)
        setAuctionAmount(String(auc.final_amount))
        setAuctionWinner(auc.winner_name)
        setAuctionPaymentMethod((auc.payment_method as PaymentMethod) ?? '카드')
      } else {
        setAuctionItemName('')
        setAuctionAmount('')
        setAuctionWinner('')
        setAuctionPaymentMethod('카드')
      }

      const rev = reviewRes.data
      setReviewCount(rev ? String(rev.count) : '')

      // 카드: 어떤 데이터든 있으면 잠금
      setCardEditing(!fetchedHost && !auc && !rev)

      const fetchedInvites = invitesRes.data ?? []
      setInvites(fetchedInvites)
      const editingMode = fetchedInvites.length === 0
      setInviteEditing(editingMode)
      setPendingInvites(editingMode ? [{ tempId: Date.now() + Math.random(), host: '', count: '' }] : [])
    } catch {
      toast.error('매출 데이터를 불러오지 못했습니다')
    } finally {
      setSalesLoading(false)
    }
  }, [canManageHost])

  useEffect(() => {
    if (activeTab === 'sales') {
      fetchSalesData(selectedDate)
    }
  }, [activeTab, selectedDate, fetchSalesData])

  // Fetch party hosts (admin/superadmin 전용)
  useEffect(() => {
    if (!canManageHost) return
    partyHostsAPI.list()
      .then((res) => setHosts(res.data ?? []))
      .catch(() => {})
  }, [canManageHost])

  // ── Checkin handlers ──
  const handleRowClick = (guest: PartyGuest) => {
    if (toggling === guest.id) return
    if (guest.checked_in) {
      setCancelModal({ open: true, guest })
    } else {
      doToggle(guest)
    }
  }

  const doToggle = async (guest: PartyGuest) => {
    setToggling(guest.id)
    try {
      const res = await partyCheckinAPI.toggle(guest.id, selectedDate)
      const { checked_in, checked_in_at } = res.data
      setGuests((prev) =>
        prev.map((g) =>
          g.id === guest.id ? { ...g, checked_in, checked_in_at } : g
        )
      )
      if (checked_in) {
        toast.success(`${guest.customer_name}님 입장 완료`)
      } else {
        toast.success(`${guest.customer_name}님 입장 취소`)
      }
    } catch {
      toast.error('처리 중 오류가 발생했습니다')
    } finally {
      setToggling(null)
    }
  }

  const handleCancelConfirm = async () => {
    if (!cancelModal.guest) return
    setCancelModal({ open: false, guest: null })
    await doToggle(cancelModal.guest)
  }

  const allGuests = [...guests, ...unstableGuests]
  const totalPeople = allGuests.reduce((sum, g) => sum + (g.male_count ?? 0) + (g.female_count ?? 0), 0)
  const checkedInPeople = allGuests.filter((g) => g.checked_in).reduce((sum, g) => sum + (g.male_count ?? 0) + (g.female_count ?? 0), 0)
  const notCheckedInPeople = totalPeople - checkedInPeople

  // ── Sales handlers ──
  async function handleAddSale() {
    if (!newItemName.trim()) { toast.error('품명을 입력해주세요'); return }
    if (!newAmount || Number(newAmount) <= 0) { toast.error('금액을 입력해주세요'); return }
    try {
      const res = await onsiteSalesAPI.create({ date: selectedDate, item_name: newItemName.trim(), amount: Number(newAmount), payment_method: newPaymentMethod })
      setSales(prev => [res.data, ...prev])
      setNewItemName('')
      setNewAmount('')
      setNewPaymentMethod('카드')
      toast.success('판매 기록이 추가되었습니다')
    } catch { toast.error('판매 기록 추가에 실패했습니다') }
  }

  const [deleteModal, setDeleteModal] = useState<{ open: boolean; id: number | null; name: string }>({ open: false, id: null, name: '' })

  async function confirmDeleteSale() {
    if (!deleteModal.id) return
    try {
      await onsiteSalesAPI.delete(deleteModal.id)
      setSales(prev => prev.filter(s => s.id !== deleteModal.id))
      toast.success('판매 기록이 삭제되었습니다')
    } catch { toast.error('삭제에 실패했습니다') }
    finally { setDeleteModal({ open: false, id: null, name: '' }) }
  }

  const salesTotalAmount = sales.reduce((sum, s) => sum + s.amount, 0)

  // ── 진행자 카드 통합 저장 (진행자 + 리뷰수 + 경매액) ──
  async function handleCardSave() {
    if (!hostName) { toast.error('진행자를 선택해주세요'); return }
    setCardSaving(true)
    try {
      const promises: Promise<unknown>[] = []

      promises.push(dailyHostAPI.upsert({ date: selectedDate, host_username: hostName }))

      if (reviewCount !== '' && !isNaN(Number(reviewCount)) && Number(reviewCount) >= 0) {
        promises.push(dailyReviewAPI.upsert({ date: selectedDate, count: Number(reviewCount) }))
      }

      if (auctionAmount !== '' && !isNaN(Number(auctionAmount)) && Number(auctionAmount) >= 0) {
        promises.push(
          onsiteAuctionAPI.upsert({
            date: selectedDate,
            item_name: auctionItemName.trim() || '경매',
            final_amount: Number(auctionAmount),
            winner_name: auctionWinner.trim() || '-',
            payment_method: auctionPaymentMethod,
          }).then((res) => { setAuction(res.data) })
        )
      }

      await Promise.all(promises)
      setCardEditing(false)
      toast.success('저장되었습니다')
    } catch {
      toast.error('저장에 실패했습니다')
    } finally {
      setCardSaving(false)
    }
  }

  // ── Female invite handlers ──
  function handleAddBlankRow() {
    setPendingInvites(prev => [...prev, { tempId: Date.now() + Math.random(), host: '', count: '' }])
  }

  // 편집 모드 진입 시 빈 행 1개 기본 보장
  useEffect(() => {
    if (inviteEditing) {
      setPendingInvites(prev => prev.length === 0 ? [{ tempId: Date.now() + Math.random(), host: '', count: '' }] : prev)
    }
  }, [inviteEditing])

  function handlePendingChange(tempId: number, field: 'host' | 'count', value: string) {
    setPendingInvites(prev => prev.map(p => p.tempId === tempId ? { ...p, [field]: value } : p))
  }

  function handlePendingRemove(tempId: number) {
    setPendingInvites(prev => prev.filter(p => p.tempId !== tempId))
  }

  async function handleInvitesSave() {
    if (pendingInvites.length === 0) return
    for (const p of pendingInvites) {
      if (!p.host) { toast.error('진행자가 선택되지 않은 행이 있습니다'); return }
      if (p.count === '' || isNaN(Number(p.count)) || Number(p.count) <= 0) {
        toast.error(`${p.host} 행의 수치를 확인해주세요`); return
      }
    }
    setInviteSaving(true)
    try {
      await Promise.all(
        pendingInvites.map(p =>
          onsiteFemaleInviteAPI.add({ date: selectedDate, host_username: p.host, count: Number(p.count) })
        )
      )
      const res = await onsiteFemaleInviteAPI.list(selectedDate)
      setInvites(res.data ?? [])
      setPendingInvites([])
      setInviteEditing(false)
      toast.success('저장되었습니다')
    } catch { toast.error('저장에 실패했습니다') }
    finally { setInviteSaving(false) }
  }

  async function handleInviteDelete(id: number) {
    try {
      await onsiteFemaleInviteAPI.delete(id)
      setInvites(prev => prev.filter(i => i.id !== id))
      toast.success('삭제되었습니다')
    } catch { toast.error('삭제에 실패했습니다') }
  }



  const renderGuestTable = (guestList: PartyGuest[], label: string, showAddButton: boolean = false) => (
    <div className="section-card overflow-hidden">
      <div className="section-header flex items-center justify-between">
        <div className="flex items-center gap-2">
          {label && (
            <span className={`text-subheading font-semibold ${label === '언스테이블' ? 'text-[#FF6B2C]' : 'text-[#191F28] dark:text-white'}`}>{label}</span>
          )}
          <span className="text-caption text-[#8B95A1] tabular-nums">{guestList.filter(g => g.checked_in).length}/{guestList.length}팀</span>
        </div>
        {showAddButton && (
          <Button color="blue" size="sm" onClick={() => setAddModal(prev => ({ ...prev, open: true }))} className="h-8">+ 예약자 추가</Button>
        )}
      </div>
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Spinner size="lg" />
        </div>
      ) : guestList.length === 0 ? (
        <div className="empty-state">
          <Users size={40} className="text-[#B0B8C1]" />
          <p className="mt-3 text-body text-[#8B95A1]">해당 날짜의 파티 예약자가 없습니다</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-[#E5E8EB] dark:border-gray-800">
                <th className="whitespace-nowrap px-4 py-2.5 text-left text-caption font-medium text-[#8B95A1]">이름</th>
                <th className="whitespace-nowrap px-4 py-2.5 text-left text-caption font-medium text-[#8B95A1]">전화번호</th>
                <th className="whitespace-nowrap px-4 py-2.5 text-center text-caption font-medium text-[#8B95A1]">성별</th>
                <th className="whitespace-nowrap px-4 py-2.5 text-center text-caption font-medium text-[#8B95A1]">파티</th>
                <th className="w-full px-4 py-2.5 text-left text-caption font-medium text-[#8B95A1]">메모</th>
              </tr>
            </thead>
            <tbody>
              {guestList.map((guest) => (
                <tr
                  key={guest.id}
                  onClick={() => handleRowClick(guest)}
                  className={`cursor-pointer border-b border-[#E5E8EB] transition-colors last:border-0 dark:border-gray-800 ${
                    guest.checked_in
                      ? label === '언스테이블'
                        ? 'bg-[#FFF0E0] hover:bg-[#FFE4CC] dark:bg-[#FF6B2C]/15 dark:hover:bg-[#FF6B2C]/20'
                        : 'bg-[#E8F3FF] hover:bg-[#D6EAFF] dark:bg-[#3182F6]/15 dark:hover:bg-[#3182F6]/20'
                      : 'hover:bg-[#F2F4F6] dark:hover:bg-[#2C2C34]'
                  } ${toggling === guest.id ? 'opacity-50' : ''}`}
                >
                  <td className="whitespace-nowrap px-4 py-3.5">
                    <div className="flex items-center gap-2">
                      {toggling === guest.id ? <Spinner size="sm" /> : null}
                      <span className={`text-body ${guest.checked_in ? `font-semibold ${label === '언스테이블' ? 'text-[#FF6B2C]' : 'text-[#3182F6]'}` : 'font-medium text-[#191F28] dark:text-white'}`}>
                        {guest.customer_name}
                      </span>
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3.5">
                    <span className={`text-label tabular-nums ${guest.checked_in ? (label === '언스테이블' ? 'text-[#FF6B2C]' : 'text-[#3182F6]') : 'text-[#4E5968] dark:text-gray-300'}`}>
                      {guest.phone || '-'}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3.5 text-center">
                    <span className={`text-label tabular-nums ${guest.checked_in ? (label === '언스테이블' ? 'text-[#FF6B2C]' : 'text-[#3182F6]') : 'text-[#4E5968] dark:text-gray-300'}`}>
                      {formatGender(guest.male_count, guest.female_count)}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3.5 text-center">
                    <span className={`text-label ${guest.checked_in ? (label === '언스테이블' ? 'text-[#FF6B2C]' : 'text-[#3182F6]') : 'text-[#4E5968] dark:text-gray-300'}`}>
                      {guest.party_type || '-'}
                    </span>
                  </td>
                  <td className="px-4 py-3.5">
                    <span className="text-caption text-[#4E5968] dark:text-gray-400">{guest.notes || ''}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )

  return (
    <div className="mx-auto min-w-lg w-fit space-y-5">
      {/* 날짜 선택 */}
      <div className="flex flex-col items-center pt-2">
        {(() => {
          const d = new Date(selectedDate + 'T00:00:00');
          const days = ['일', '월', '화', '수', '목', '금', '토'];
          const isToday = selectedDate === getTodayStr();
          return (
            <>
              <span className="text-label text-[#8B95A1]">
                {`${days[d.getDay()]}요일`}
                {isToday && <span className="ml-1.5 text-[#3182F6] font-medium">오늘</span>}
              </span>
              <div className="mt-1 flex items-center gap-5">
                <button
                  onClick={() => {
                    const prev = new Date(selectedDate + 'T00:00:00');
                    prev.setDate(prev.getDate() - 1);
                    setSelectedDate(`${prev.getFullYear()}-${String(prev.getMonth() + 1).padStart(2, '0')}-${String(prev.getDate()).padStart(2, '0')}`);
                  }}
                  className="flex h-10 w-10 items-center justify-center rounded-full text-[#B0B8C1] transition-all hover:bg-[#F2F4F6] hover:text-[#4E5968] active:scale-95 dark:hover:bg-[#2C2C34] dark:hover:text-gray-300"
                >
                  <ChevronLeft size={22} strokeWidth={1.5} />
                </button>
                <label className="relative cursor-pointer select-none">
                  <input
                    type="date"
                    value={selectedDate}
                    onChange={(e) => setSelectedDate(e.target.value)}
                    className="absolute inset-0 opacity-0 cursor-pointer"
                  />
                  <span className="text-[36px] font-bold leading-none tracking-tight text-[#191F28] dark:text-white">
                    {`${d.getMonth() + 1}월 ${d.getDate()}일`}
                  </span>
                </label>
                <button
                  onClick={() => {
                    const next = new Date(selectedDate + 'T00:00:00');
                    next.setDate(next.getDate() + 1);
                    setSelectedDate(`${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}-${String(next.getDate()).padStart(2, '0')}`);
                  }}
                  className="flex h-10 w-10 items-center justify-center rounded-full text-[#B0B8C1] transition-all hover:bg-[#F2F4F6] hover:text-[#4E5968] active:scale-95 dark:hover:bg-[#2C2C34] dark:hover:text-gray-300"
                >
                  <ChevronRight size={22} strokeWidth={1.5} />
                </button>
              </div>
            </>
          );
        })()}
      </div>

      {/* 탭: 입장체크 / 파티매출 */}
      <div className="flex items-center justify-center gap-1">
        {[
          { value: 'checkin' as const, label: '입장체크' },
          { value: 'sales' as const, label: '파티매출' },
        ].map(tab => (
          <button
            key={tab.value}
            onClick={() => setActiveTab(tab.value)}
            className={`px-5 py-2 rounded-lg text-body font-medium transition-colors cursor-pointer ${
              activeTab === tab.value
                ? 'bg-[#3182F6] text-white'
                : 'bg-[#F2F4F6] text-[#8B95A1] hover:bg-[#E5E8EB] dark:bg-[#2C2C34] dark:text-gray-400 dark:hover:bg-[#35353E]'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ════════ 입장체크 탭 ════════ */}
      {activeTab === 'checkin' && (
        <>
          {/* 카운터 */}
          <div className="flex items-center justify-center">
            <div className="flex items-center gap-[15px] text-body tabular-nums">
              <span className="flex items-center gap-1.5"><span className="inline-block h-[5px] w-[5px] rounded-full bg-[#191F28] dark:bg-white" /><span>전체 <span className="font-bold text-[#191F28] dark:text-white">{totalPeople}</span><span className="text-[#B0B8C1]">명</span></span></span>
              <span className="flex items-center gap-1.5"><span className="inline-block h-[5px] w-[5px] rounded-full bg-[#3182F6]" /><span>입장 <span className="font-bold text-[#3182F6]">{checkedInPeople}</span><span className="text-[#B0B8C1]">명</span></span></span>
              <span className="flex items-center gap-1.5"><span className="inline-block h-[5px] w-[5px] rounded-full bg-[#F04452]" /><span>미입장 <span className="font-bold text-[#F04452]">{notCheckedInPeople}</span><span className="text-[#B0B8C1]">명</span></span></span>
            </div>
          </div>

          {/* 스테이블 체크인 테이블 (언스테이블 운영 테넌트만 라벨 노출) */}
          {renderGuestTable(guests, hasUnstable ? '스테이블' : '', true)}

          {/* 언스테이블 체크인 테이블 */}
          {hasUnstable && renderGuestTable(unstableGuests, '언스테이블')}

          {/* 입장 취소 확인 모달 */}
          <Modal show={cancelModal.open} size="md" popup onClose={() => setCancelModal({ open: false, guest: null })}>
            <ModalHeader />
            <ModalBody>
              <div className="flex flex-col items-center gap-4 text-center">
                <AlertTriangle size={48} className="text-[#FF9F00]" />
                <div>
                  <h3 className="text-heading font-semibold text-[#191F28] dark:text-white">입장 취소 확인</h3>
                  <p className="mt-2 text-body text-[#4E5968] dark:text-gray-300">
                    <span className="font-semibold text-[#191F28] dark:text-white">{cancelModal.guest?.customer_name}</span>님의 입장을 취소하시겠습니까?
                  </p>
                </div>
                <div className="flex w-full gap-3">
                  <Button color="light" className="flex-1" onClick={() => setCancelModal({ open: false, guest: null })}>닫기</Button>
                  <Button color="failure" className="flex-1" onClick={handleCancelConfirm}>입장 취소</Button>
                </div>
              </div>
            </ModalBody>
          </Modal>

          {/* 예약자 추가 모달 (현장추가) */}
          <Modal show={addModal.open} size="sm" onClose={() => addModal.saving ? null : resetAddModal()}>
            <ModalHeader>예약자 추가</ModalHeader>
            <ModalBody>
              <div className="space-y-3">
                <div>
                  <Label className="mb-1.5 block text-caption font-medium text-[#4E5968] dark:text-gray-300">이름</Label>
                  <TextInput value={addModal.name} onChange={(e) => setAddModal(prev => ({ ...prev, name: e.target.value }))} placeholder="이름 입력" />
                </div>
                <div>
                  <Label className="mb-1.5 block text-caption font-medium text-[#4E5968] dark:text-gray-300">전화번호 (선택)</Label>
                  <TextInput value={addModal.phone} onChange={(e) => setAddModal(prev => ({ ...prev, phone: e.target.value }))} placeholder="010-0000-0000" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label className="mb-1.5 block text-caption font-medium text-[#4E5968] dark:text-gray-300">남자</Label>
                    <TextInput type="number" value={addModal.maleCount} onChange={(e) => setAddModal(prev => ({ ...prev, maleCount: e.target.value }))} placeholder="0" />
                  </div>
                  <div>
                    <Label className="mb-1.5 block text-caption font-medium text-[#4E5968] dark:text-gray-300">여자</Label>
                    <TextInput type="number" value={addModal.femaleCount} onChange={(e) => setAddModal(prev => ({ ...prev, femaleCount: e.target.value }))} placeholder="0" />
                  </div>
                </div>
                <div>
                  <Label className="mb-1.5 block text-caption font-medium text-[#4E5968] dark:text-gray-300">참여 파티</Label>
                  <Select value={addModal.partyType} onChange={(e) => setAddModal(prev => ({ ...prev, partyType: e.target.value as '1' | '2' | '2차만' }))}>
                    <option value="1">1차</option>
                    <option value="2">1+2차</option>
                    <option value="2차만">2차만</option>
                  </Select>
                </div>
                <div className="flex w-full gap-3 pt-2">
                  <Button color="light" className="flex-1" onClick={resetAddModal} disabled={addModal.saving}>취소</Button>
                  <Button color="blue" className="flex-1" onClick={openCheckInConfirm} disabled={addModal.saving}>
                    {addModal.saving && <Spinner size="sm" className="mr-1.5" />}
                    추가
                  </Button>
                </div>
              </div>
            </ModalBody>
          </Modal>

          {/* 입장 처리 확인 모달 */}
          <Modal show={checkInConfirm} size="md" popup onClose={() => setCheckInConfirm(false)}>
            <ModalHeader />
            <ModalBody>
              <div className="flex flex-col items-center gap-4 text-center">
                <h3 className="text-heading font-semibold text-[#191F28] dark:text-white">
                  <span className="text-[#3182F6]">{addModal.name.trim()}</span>님을 입장 처리 하시겠습니까?
                </h3>
                <div className="flex w-full gap-3">
                  <Button color="light" className="flex-1" onClick={() => handleAddParticipant(false)} disabled={addModal.saving}>아니오</Button>
                  <Button color="blue" className="flex-1" onClick={() => handleAddParticipant(true)} disabled={addModal.saving}>예</Button>
                </div>
              </div>
            </ModalBody>
          </Modal>
        </>
      )}

      {/* ════════ 파티매출 탭 ════════ */}
      {activeTab === 'sales' && (
        <>
          {/* 진행자 영역 + 여자초대수 (admin / superadmin 전용, 좌우 2컬럼) */}
          {canManageHost && (
          <div className="grid grid-cols-2 gap-3">
          <div className="section-card">
            <div className="p-5">
            <div className="w-fit space-y-3">
              {/* 진행자 + 리뷰수 한 줄 */}
              <div className="flex items-end gap-3">
                <div>
                  <Label className="mb-1.5 block text-caption font-medium text-[#4E5968] dark:text-gray-300">진행자</Label>
                  <Select value={hostName} onChange={(e) => setHostName(e.target.value)} disabled={!cardEditing} sizing="sm" className={`h-9 w-24 ${!cardEditing ? 'bg-[#F2F4F6] text-[#8B95A1] dark:bg-[#2C2C34] dark:text-gray-500' : !hostName ? 'text-label text-[#8B95A1]' : ''}`}>
                    <option value="">진행자 선택</option>
                    {hosts.map((h) => (
                      <option key={h.id} value={h.name}>{h.name}</option>
                    ))}
                  </Select>
                </div>
                <div>
                  <Label className="mb-1.5 block text-caption font-medium text-[#4E5968] dark:text-gray-300">리뷰수</Label>
                  <TextInput type="number" value={reviewCount} onChange={(e) => setReviewCount(e.target.value)} placeholder="0" disabled={!cardEditing} className={`h-9 w-24 ${!cardEditing ? 'bg-[#F2F4F6] text-[#8B95A1] dark:bg-[#2C2C34] dark:text-gray-500' : ''}`} />
                </div>
              </div>

              {/* 경매액: 결제방식 + 판매액 */}
              <div>
                <Label className="mb-1.5 block text-caption font-medium text-[#4E5968] dark:text-gray-300">경매액</Label>
                <div className="flex items-center gap-3">
                  <Select value={auctionPaymentMethod} onChange={(e) => setAuctionPaymentMethod(e.target.value as PaymentMethod)} disabled={!cardEditing} sizing="sm" className={`h-9 w-24 ${!cardEditing ? 'bg-[#F2F4F6] text-[#8B95A1] dark:bg-[#2C2C34] dark:text-gray-500' : ''}`}>
                    {PAYMENT_METHODS.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </Select>
                  <TextInput type="number" value={auctionAmount} onChange={(e) => setAuctionAmount(e.target.value)} placeholder="판매액" disabled={!cardEditing} className={`h-9 w-24 ${!cardEditing ? 'bg-[#F2F4F6] text-[#8B95A1] dark:bg-[#2C2C34] dark:text-gray-500' : ''}`} />
                </div>
              </div>

              {/* 통합 저장/수정 */}
              <div>
                {cardEditing ? (
                  <Button color="blue" size="sm" onClick={handleCardSave} disabled={cardSaving} className="h-9 w-full">
                    {cardSaving && <Spinner size="sm" className="mr-1.5" />}
                    저장
                  </Button>
                ) : (
                  <Button color="light" size="sm" onClick={() => setCardEditing(true)} className="h-9 w-full">수정</Button>
                )}
              </div>
            </div>
            </div>
          </div>

          {/* 여자초대수 (진행자별 독립 실적) */}
          <div className="section-card">
            <div className="p-5">
              <Label className="mb-1.5 block text-caption font-medium text-[#4E5968] dark:text-gray-300">여자초대수</Label>
              {(invites.length > 0 || pendingInvites.length > 0) && (
                <div className="space-y-1.5">
                  {invites.map((inv) => (
                    <div key={`saved-${inv.id}`} className="flex items-center justify-between py-1">
                      <span className="text-body font-medium text-[#191F28] dark:text-white">{inv.host_username}</span>
                      <div className="flex items-center gap-2">
                        <span className="tabular-nums text-body font-semibold text-[#191F28] dark:text-white">
                          {inv.count}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span>
                        </span>
                        <button onClick={() => handleInviteDelete(inv.id)} disabled={!inviteEditing} className="rounded-lg p-1 text-[#B0B8C1] transition-colors hover:bg-[#FFF0F0] hover:text-[#F04452] disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-[#B0B8C1] dark:hover:bg-[#F04452]/10" title="삭제">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </div>
                  ))}
                  {inviteEditing && pendingInvites.map((p) => (
                    <div key={`pending-${p.tempId}`} className="flex items-center gap-2">
                      <Select value={p.host} onChange={(e) => handlePendingChange(p.tempId, 'host', e.target.value)} sizing="sm" className={`h-9 min-w-0 flex-1 ${!p.host ? 'text-label text-[#8B95A1]' : ''}`}>
                        <option value="">초대자 선택</option>
                        {hosts.map((h) => (
                          <option key={h.id} value={h.name}>{h.name}</option>
                        ))}
                      </Select>
                      <TextInput type="number" value={p.count} onChange={(e) => handlePendingChange(p.tempId, 'count', e.target.value)} placeholder="0" className="h-9 w-16" />
                      <button onClick={() => handlePendingRemove(p.tempId)} className="shrink-0 rounded-lg p-1 text-[#B0B8C1] transition-colors hover:bg-[#FFF0F0] hover:text-[#F04452] dark:hover:bg-[#F04452]/10" title="제거">
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-3 grid grid-cols-2 gap-2">
                <Button color="light" size="sm" onClick={handleAddBlankRow} disabled={!inviteEditing} className="h-9">행추가</Button>
                {inviteEditing ? (
                  <Button color="blue" size="sm" onClick={handleInvitesSave} disabled={inviteSaving || pendingInvites.length === 0} className="h-9">
                    {inviteSaving && <Spinner size="sm" className="mr-1.5" />}
                    저장
                  </Button>
                ) : (
                  <Button color="light" size="sm" onClick={() => setInviteEditing(true)} className="h-9">수정</Button>
                )}
              </div>
            </div>
          </div>
          </div>
          )}

          {/* 판매 기록 */}
          <div className="section-card">
            <div className="section-header">
              <span className="text-subheading font-semibold text-[#191F28] dark:text-white">판매 기록</span>
            </div>
            <div className="px-5 pb-5">
              <div className="grid grid-cols-[1fr_auto_auto] gap-3 max-w-xl">
                <div>
                  <Label className="mb-1.5 block text-caption font-medium text-[#4E5968] dark:text-gray-300">품명</Label>
                  <TextInput value={newItemName} onChange={(e) => setNewItemName(e.target.value)} placeholder="품명 입력" className="h-9" onKeyDown={(e) => e.key === 'Enter' && handleAddSale()} />
                </div>
                <div>
                  <Label className="mb-1.5 block text-caption font-medium text-[#4E5968] dark:text-gray-300">결제방식</Label>
                  <Select value={newPaymentMethod} onChange={(e) => setNewPaymentMethod(e.target.value as PaymentMethod)} sizing="sm" className="h-9 w-24">
                    {PAYMENT_METHODS.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </Select>
                </div>
                <div>
                  <Label className="mb-1.5 block text-caption font-medium text-[#4E5968] dark:text-gray-300">금액</Label>
                  <div className="flex items-center gap-2">
                    <TextInput type="number" value={newAmount} onChange={(e) => setNewAmount(e.target.value)} placeholder="0" className="h-9 w-24" onKeyDown={(e) => e.key === 'Enter' && handleAddSale()} />
                    <Button color="blue" size="sm" onClick={handleAddSale} className="shrink-0 h-9">추가</Button>
                  </div>
                </div>
              </div>

              <div className="mt-4">
                {salesLoading ? (
                  <div className="flex justify-center py-8"><Spinner size="md" /></div>
                ) : sales.length === 0 ? (
                  <div className="py-8 text-center text-body text-[#8B95A1] dark:text-gray-500">판매 기록이 없습니다</div>
                ) : (
                  <div className="divide-y divide-[#F2F4F6] rounded-xl border border-[#E5E8EB] dark:divide-gray-800 dark:border-gray-800">
                    {sales.map((sale) => (
                      <div key={sale.id} className="flex items-center justify-between px-4 py-3">
                        <div className="flex items-center gap-3 flex-1">
                          {sale.created_at && <span className="shrink-0 whitespace-nowrap text-tiny text-[#8B95A1] dark:text-gray-500 tabular-nums">{(() => { const d = new Date(normalizeUtcString(sale.created_at)); return `${String(d.getMonth()+1).padStart(2,'0')}/${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`; })()}</span>}
                          <span className="text-body font-medium text-[#191F28] dark:text-white">{sale.item_name}</span>
                          {sale.payment_method && (
                            <Badge color={PAYMENT_BADGE_COLOR[sale.payment_method as PaymentMethod] ?? 'gray'} size="xs">{sale.payment_method}</Badge>
                          )}
                        </div>
                        <div className="flex items-center gap-3">
                          <span className="tabular-nums text-body font-semibold text-[#191F28] dark:text-white">
                            {sale.amount.toLocaleString()}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">원</span>
                          </span>
                          <button onClick={() => setDeleteModal({ open: true, id: sale.id, name: sale.item_name })} className="rounded-lg p-1 text-[#B0B8C1] transition-colors hover:bg-[#FFF0F0] hover:text-[#F04452] dark:hover:bg-[#F04452]/10" title="삭제">
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {sales.length > 0 && (
                <div className="mt-4 flex items-center justify-between rounded-xl bg-[#F8F9FA] px-4 py-3 dark:bg-[#1E1E24]">
                  <span className="text-body font-semibold text-[#191F28] dark:text-white">총액</span>
                  <span className="tabular-nums text-heading font-bold text-[#3182F6]">
                    {salesTotalAmount.toLocaleString()}<span className="ml-0.5 text-body font-normal text-[#B0B8C1]">원</span>
                  </span>
                </div>
              )}
            </div>
          </div>

        </>
      )}

      {/* 판매 삭제 확인 모달 */}
      <Modal show={deleteModal.open} size="md" popup onClose={() => setDeleteModal({ open: false, id: null, name: '' })}>
        <ModalHeader />
        <ModalBody>
          <div className="flex flex-col items-center gap-4 text-center">
            <AlertTriangle size={48} className="text-[#F04452]" />
            <div>
              <h3 className="text-heading font-semibold text-[#191F28] dark:text-white">삭제 확인</h3>
              <p className="mt-2 text-body text-[#4E5968] dark:text-gray-300">
                <span className="font-semibold text-[#191F28] dark:text-white">{deleteModal.name}</span> 항목을 삭제하시겠습니까?
              </p>
            </div>
            <div className="flex w-full gap-3">
              <Button color="light" className="flex-1" onClick={() => setDeleteModal({ open: false, id: null, name: '' })}>취소</Button>
              <Button color="failure" className="flex-1" onClick={confirmDeleteSale}>삭제</Button>
            </div>
          </div>
        </ModalBody>
      </Modal>
    </div>
  )
}
