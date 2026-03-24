import { useState, useEffect, useCallback } from 'react'
import { Button, Modal, ModalHeader, ModalBody, Spinner } from 'flowbite-react'
import { Users, AlertTriangle, ChevronLeft, ChevronRight } from 'lucide-react'
import { partyCheckinAPI } from '@/services/api'
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
  stay_group_id?: string | null
  stay_group_order?: number | null
  is_long_stay?: boolean
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

function formatRoom(roomNumber: string | null): string {
  if (!roomNumber) return '파티만'
  return roomNumber
}

export default function PartyCheckin() {
  const [selectedDate, setSelectedDate] = useState(getTodayStr())
  const [guests, setGuests] = useState<PartyGuest[]>([])
  const [loading, setLoading] = useState(false)
  const [toggling, setToggling] = useState<number | null>(null)

  const [cancelModal, setCancelModal] = useState<{ open: boolean; guest: PartyGuest | null }>({
    open: false,
    guest: null,
  })

  const fetchGuests = useCallback(async (date: string) => {
    setLoading(true)
    try {
      const res = await partyCheckinAPI.getList(date)
      setGuests(res.data)
    } catch {
      toast.error('파티 예약자 목록을 불러오지 못했습니다')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchGuests(selectedDate)
  }, [selectedDate, fetchGuests])

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

  // 전체 인원 = male_count + female_count 합계
  const totalPeople = guests.reduce((sum, g) => {
    return sum + (g.male_count ?? 0) + (g.female_count ?? 0)
  }, 0)

  // 입장 인원 = 체크인된 예약자의 인원 합계
  const checkedInPeople = guests
    .filter((g) => g.checked_in)
    .reduce((sum, g) => sum + (g.male_count ?? 0) + (g.female_count ?? 0), 0)

  const notCheckedInPeople = totalPeople - checkedInPeople

  return (
    <div className="mx-auto max-w-lg space-y-5">
      {/* 날짜 선택 — Toss style */}
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

      {/* 카운터 */}
      <div className="flex items-center justify-center gap-[15px] text-body tabular-nums">
        <span className="flex items-center gap-1.5"><span className="inline-block h-[5px] w-[5px] rounded-full bg-[#191F28] dark:bg-white" /><span>전체 <span className="font-bold text-[#191F28] dark:text-white">{totalPeople}</span><span className="text-[#B0B8C1]">명</span></span></span>
        <span className="flex items-center gap-1.5"><span className="inline-block h-[5px] w-[5px] rounded-full bg-[#00C9A7]" /><span>입장 <span className="font-bold text-[#00C9A7]">{checkedInPeople}</span><span className="text-[#B0B8C1]">명</span></span></span>
        <span className="flex items-center gap-1.5"><span className="inline-block h-[5px] w-[5px] rounded-full bg-[#FF9F00]" /><span>미입장 <span className="font-bold text-[#FF9F00]">{notCheckedInPeople}</span><span className="text-[#B0B8C1]">명</span></span></span>
      </div>

      {/* 테이블 */}
      <div className="section-card overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Spinner size="lg" />
          </div>
        ) : guests.length === 0 ? (
          <div className="empty-state">
            <Users size={40} className="text-[#B0B8C1]" />
            <p className="mt-3 text-body text-[#8B95A1]">해당 날짜의 파티 예약자가 없습니다</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[#E5E8EB] dark:border-gray-800">
                  <th className="px-4 py-2.5 text-left text-caption font-medium text-[#8B95A1]">
                    이름
                  </th>
                  <th className="px-4 py-2.5 text-center text-caption font-medium text-[#8B95A1]">
                    성별
                  </th>
                  <th className="px-4 py-2.5 text-center text-caption font-medium text-[#8B95A1]">
                    파티
                  </th>
                  <th className="px-4 py-2.5 text-center text-caption font-medium text-[#8B95A1]">
                    구분
                  </th>
                </tr>
              </thead>
              <tbody>
                {guests.map((guest) => (
                  <tr
                    key={guest.id}
                    onClick={() => handleRowClick(guest)}
                    className={`cursor-pointer border-b border-[#E5E8EB] transition-colors last:border-0 dark:border-gray-800 ${
                      guest.checked_in
                        ? 'bg-[#E8F3FF] hover:bg-[#D6EAFF] dark:bg-[#3182F6]/15 dark:hover:bg-[#3182F6]/20'
                        : 'hover:bg-[#F2F4F6] dark:hover:bg-[#2C2C34]'
                    } ${toggling === guest.id ? 'opacity-50' : ''}`}
                  >
                    {/* 이름 */}
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-2">
                        {toggling === guest.id ? (
                          <Spinner size="sm" />
                        ) : null}
                        <span
                          className={`text-body ${
                            guest.checked_in
                              ? 'font-semibold text-[#3182F6]'
                              : 'font-medium text-[#191F28] dark:text-white'
                          }`}
                        >
                          {guest.customer_name}
                        </span>
                        {guest.is_long_stay && <span className="text-caption text-[#8B95A1] ml-1">연박 {(guest.stay_group_order ?? 0) + 1}일차</span>}
                      </div>
                    </td>

                    {/* 성별 */}
                    <td className="px-4 py-3.5 text-center">
                      <span
                        className={`text-label tabular-nums ${
                          guest.checked_in
                            ? 'text-[#3182F6]'
                            : 'text-[#4E5968] dark:text-gray-300'
                        }`}
                      >
                        {formatGender(guest.male_count, guest.female_count)}
                      </span>
                    </td>

                    {/* 파티 */}
                    <td className="px-4 py-3.5 text-center">
                      <span
                        className={`text-label ${
                          guest.checked_in
                            ? 'text-[#3182F6]'
                            : 'text-[#4E5968] dark:text-gray-300'
                        }`}
                      >
                        {guest.party_type || '-'}
                      </span>
                    </td>

                    {/* 구분 */}
                    <td className="px-4 py-3.5 text-center">
                      <span
                        className={`text-label ${
                          guest.room_number
                            ? guest.checked_in
                              ? 'font-medium text-[#3182F6]'
                              : 'font-medium text-[#4E5968] dark:text-gray-300'
                            : guest.checked_in
                            ? 'text-[#3182F6]/70'
                            : 'text-[#8B95A1]'
                        }`}
                      >
                        {formatRoom(guest.room_number)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 입장 취소 확인 모달 */}
      <Modal
        show={cancelModal.open}
        size="md"
        popup
        onClose={() => setCancelModal({ open: false, guest: null })}
      >
        <ModalHeader />
        <ModalBody>
          <div className="flex flex-col items-center gap-4 text-center">
            <AlertTriangle size={48} className="text-[#FF9F00]" />
            <div>
              <h3 className="text-heading font-semibold text-[#191F28] dark:text-white">
                입장 취소 확인
              </h3>
              <p className="mt-2 text-body text-[#4E5968] dark:text-gray-300">
                <span className="font-semibold text-[#191F28] dark:text-white">
                  {cancelModal.guest?.customer_name}
                </span>
                님의 입장을 취소하시겠습니까?
              </p>
            </div>
            <div className="flex w-full gap-3">
              <Button
                color="light"
                className="flex-1"
                onClick={() => setCancelModal({ open: false, guest: null })}
              >
                닫기
              </Button>
              <Button
                color="failure"
                className="flex-1"
                onClick={handleCancelConfirm}
              >
                입장 취소
              </Button>
            </div>
          </div>
        </ModalBody>
      </Modal>
    </div>
  )
}
