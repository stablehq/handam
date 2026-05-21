import { useEffect, useState } from 'react'
import { BedDouble } from 'lucide-react'
import { Spinner } from '@/components/ui/spinner'
import { cleancrewAPI, type CleanSkipRoom } from '@/services/api'

export default function ConsecutiveStays() {
  const [rooms, setRooms] = useState<CleanSkipRoom[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    cleancrewAPI
      .listConsecutiveStays()
      .then((res) => {
        if (alive) setRooms(res.data)
      })
      .catch(() => {
        if (alive) setError('객실 목록을 불러오지 못했습니다.')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2.5">
        <div className="stat-icon bg-[#E8F3FF] text-[#3182F6] dark:bg-[#3182F6]/15 dark:text-[#3182F6]">
          <BedDouble size={20} />
        </div>
        <div>
          <h1 className="page-title">청소 건너뛸 객실</h1>
          <p className="page-subtitle">오늘 체크아웃하지 않는 객실 (어제부터 같은 방에 머무는 게스트)</p>
        </div>
      </div>

      <div className="section-card">
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Spinner size="lg" />
          </div>
        ) : error ? (
          <div className="empty-state">
            <p className="text-label text-[#F04452] dark:text-[#F87171]">{error}</p>
          </div>
        ) : rooms.length === 0 ? (
          <div className="empty-state">
            <p className="text-label text-[#8B95A1]">오늘 체크아웃 없이 머무는 객실이 없습니다.</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3 p-5 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
            {rooms.map((room) => (
              <div
                key={room.room_number}
                className="rounded-2xl border border-[#E5E8EB] bg-[#F8F9FA] px-4 py-6 text-center dark:border-gray-800 dark:bg-[#1E1E24]"
              >
                <div className="text-title font-bold tabular-nums text-[#191F28] dark:text-white">
                  {room.room_number}
                </div>
                {room.is_dormitory && room.capacity ? (
                  <div className="mt-1.5 text-caption font-medium text-[#3182F6] dark:text-[#60A5FA] tabular-nums">
                    연박 {room.stayover_count ?? 0}/{room.capacity}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
