import { useState, useEffect, useCallback } from 'react'
import { useTenantStore } from '@/stores/tenant-store'
import { Modal, ModalHeader, ModalBody } from '@/components/ui/modal'
import { Spinner } from '@/components/ui/spinner'
import { Button } from '@/components/ui/button'
import { TextInput } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { Users, AlertTriangle, ChevronLeft, ChevronRight, Trash2 } from 'lucide-react'
import { partyCheckinAPI, onsiteSalesAPI, dailyHostAPI, onsiteAuctionAPI, authAPI } from '@/services/api'
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

interface Sale {
  id: number
  item_name: string
  amount: number
  created_by: string | null
  created_at: string | null
}

interface Auction {
  id: number
  date: string
  item_name: string
  final_amount: number
  winner_name: string
  created_by: string | null
  created_at: string | null
}

interface UserItem {
  id: number
  username: string
  role: string
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

  // ── Sales state ──
  const [sales, setSales] = useState<Sale[]>([])
  const [salesLoading, setSalesLoading] = useState(false)
  const [newItemName, setNewItemName] = useState('')
  const [newAmount, setNewAmount] = useState('')

  // ── Host state ──
  const [users, setUsers] = useState<UserItem[]>([])
  const [hostUsername, setHostUsername] = useState('')
  const [hostSaving, setHostSaving] = useState(false)

  // ── Auction state ──
  const [auction, setAuction] = useState<Auction | null>(null)
  const [auctionItemName, setAuctionItemName] = useState('')
  const [auctionAmount, setAuctionAmount] = useState('')
  const [auctionWinner, setAuctionWinner] = useState('')
  const [auctionSaving, setAuctionSaving] = useState(false)
  const [auctionEditing, setAuctionEditing] = useState(false)

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

  // ── Fetch sales/host/auction when sales tab active ──
  const fetchSalesData = useCallback(async (date: string) => {
    setSalesLoading(true)
    try {
      const [salesRes, hostRes, auctionRes] = await Promise.all([
        onsiteSalesAPI.getList(date),
        dailyHostAPI.get(date),
        onsiteAuctionAPI.get(date),
      ])
      setSales(salesRes.data ?? [])

      const host = hostRes.data
      setHostUsername(host?.host_username ?? '')

      const auc = auctionRes.data
      setAuction(auc)
      if (auc) {
        setAuctionItemName(auc.item_name)
        setAuctionAmount(String(auc.final_amount))
        setAuctionWinner(auc.winner_name)
      } else {
        setAuctionItemName('')
        setAuctionAmount('')
        setAuctionWinner('')
      }
    } catch {
      toast.error('매출 데이터를 불러오지 못했습니다')
    } finally {
      setSalesLoading(false)
    }
  }, [])

  useEffect(() => {
    if (activeTab === 'sales') {
      fetchSalesData(selectedDate)
    }
  }, [activeTab, selectedDate, fetchSalesData])

  // Fetch users once
  useEffect(() => {
    authAPI.getUsers()
      .then((res) => setUsers(res.data ?? []))
      .catch(() => {})
  }, [])

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
      const res = await onsiteSalesAPI.create({ date: selectedDate, item_name: newItemName.trim(), amount: Number(newAmount) })
      setSales(prev => [res.data, ...prev])
      setNewItemName('')
      setNewAmount('')
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

  // ── Host handler ──
  async function handleHostSave(username: string) {
    setHostUsername(username)
    if (!username) return
    setHostSaving(true)
    try {
      await dailyHostAPI.upsert({ date: selectedDate, host_username: username })
      toast.success('진행자가 저장되었습니다')
    } catch { toast.error('진행자 저장에 실패했습니다') }
    finally { setHostSaving(false) }
  }

  // ── Auction handlers ──
  async function handleAuctionSave() {
    if (auctionAmount === '' || isNaN(Number(auctionAmount)) || Number(auctionAmount) < 0) { toast.error('경매 판매액을 입력해주세요'); return }
    setAuctionSaving(true)
    try {
      const res = await onsiteAuctionAPI.upsert({
        date: selectedDate,
        item_name: auctionItemName.trim() || '경매',
        final_amount: Number(auctionAmount),
        winner_name: auctionWinner.trim() || '-',
      })
      setAuction(res.data)
      setAuctionEditing(false)
      toast.success(auction ? '경매 기록이 수정되었습니다' : '경매 기록이 저장되었습니다')
    } catch { toast.error('경매 기록 저장에 실패했습니다') }
    finally { setAuctionSaving(false) }
  }

  async function handleAuctionDelete() {
    if (!auction) return
    try {
      await onsiteAuctionAPI.delete(auction.id)
      setAuction(null)
      setAuctionItemName('')
      setAuctionAmount('')
      setAuctionWinner('')
      toast.success('경매 기록이 삭제되었습니다')
    } catch { toast.error('삭제에 실패했습니다') }
  }

  const renderGuestTable = (guestList: PartyGuest[], label: string) => (
    <div className="section-card overflow-hidden">
      <div className="section-header">
        <span className={`text-subheading font-semibold ${label === '언스테이블' ? 'text-[#FF6B2C]' : 'text-[#191F28] dark:text-white'}`}>{label}</span>
        <span className="text-caption text-[#8B95A1] tabular-nums">{guestList.filter(g => g.checked_in).length}/{guestList.length}명</span>
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

          {/* 스테이블 체크인 테이블 */}
          {renderGuestTable(guests, '스테이블')}

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
        </>
      )}

      {/* ════════ 파티매출 탭 ════════ */}
      {activeTab === 'sales' && (
        <>
          {/* 진행자 + 경매 */}
          <div className="section-card">
            <div className="p-5">
              <div className="grid grid-cols-2 gap-4">
                {/* 1컬럼: 진행자 */}
                <div>
                  <Label className="mb-1.5 block text-caption font-medium text-[#4E5968] dark:text-gray-300">오늘의 진행자</Label>
                  <Select value={hostUsername} onChange={(e) => handleHostSave(e.target.value)} disabled={hostSaving} sizing="sm">
                    <option value="">진행자를 선택하세요</option>
                    {users.map((u) => (
                      <option key={u.id} value={u.username}>{u.username}</option>
                    ))}
                  </Select>
                </div>
                {/* 2컬럼: 경매 판매액 */}
                <div>
                  <Label className="mb-1.5 block text-caption font-medium text-[#4E5968] dark:text-gray-300">경매 판매액</Label>
                  <div className="flex items-center gap-2">
                    <TextInput type="number" value={auctionAmount} onChange={(e) => setAuctionAmount(e.target.value)} placeholder="0" className={`h-9 ${!!auction && !auctionEditing ? 'bg-[#F2F4F6] text-[#8B95A1] dark:bg-[#2C2C34] dark:text-gray-500' : ''}`} disabled={!!auction && !auctionEditing} onKeyDown={(e) => e.key === 'Enter' && handleAuctionSave()} />
                    {!auction || auctionEditing ? (
                      <Button color="blue" size="sm" onClick={handleAuctionSave} disabled={auctionSaving} className="shrink-0 h-9">
                        {auctionSaving && <Spinner size="sm" className="mr-1.5" />}
                        <span className="inline-block w-[2em] text-center">저장</span>
                      </Button>
                    ) : (
                      <Button color="light" size="sm" onClick={() => setAuctionEditing(true)} className="shrink-0 h-9">
                        <span className="inline-block w-[2em] text-center">수정</span>
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* 판매 기록 */}
          <div className="section-card">
            <div className="section-header">
              <span className="text-subheading font-semibold text-[#191F28] dark:text-white">판매 기록</span>
            </div>
            <div className="px-5 pb-5">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label className="mb-1.5 block text-caption font-medium text-[#4E5968] dark:text-gray-300">품명</Label>
                  <TextInput value={newItemName} onChange={(e) => setNewItemName(e.target.value)} placeholder="품명 입력" className="h-9" onKeyDown={(e) => e.key === 'Enter' && handleAddSale()} />
                </div>
                <div>
                  <Label className="mb-1.5 block text-caption font-medium text-[#4E5968] dark:text-gray-300">금액</Label>
                  <div className="flex items-center gap-2">
                    <TextInput type="number" value={newAmount} onChange={(e) => setNewAmount(e.target.value)} placeholder="0" className="h-9" onKeyDown={(e) => e.key === 'Enter' && handleAddSale()} />
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
                          {sale.created_at && <span className="shrink-0 whitespace-nowrap text-tiny text-[#8B95A1] dark:text-gray-500 tabular-nums">{(() => { const d = new Date(sale.created_at); return `${String(d.getMonth()+1).padStart(2,'0')}/${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`; })()}</span>}
                          <span className="text-body font-medium text-[#191F28] dark:text-white">{sale.item_name}</span>
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
