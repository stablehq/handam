import { useEffect, useState } from 'react'
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
    <div className="mx-auto flex min-h-[70vh] max-w-md flex-col items-center px-4 py-8 text-center">
      <p className="text-caption text-[#8B95A1] dark:text-gray-500 tabular-nums">
        {(() => {
          const d = new Date()
          return `${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`
        })()}
      </p>
      <h1 className="mt-1 text-title font-bold text-[#191F28] dark:text-white">연박객실</h1>

      <div className="mt-8 w-full">
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Spinner size="lg" />
          </div>
        ) : error ? (
          <p className="py-16 text-label text-[#F04452] dark:text-[#F87171]">{error}</p>
        ) : rooms.length === 0 ? (
          <p className="py-16 text-label text-[#8B95A1]">오늘 연박 객실이 없습니다.</p>
        ) : (
          <ul className="flex flex-col gap-4">
            {rooms.map((room) => (
              <li
                key={room.room_number}
                className="text-heading font-semibold tabular-nums text-[#191F28] dark:text-white"
              >
                {room.room_number}
                {room.is_dormitory ? (
                  <span className="ml-1.5 text-label font-medium text-[#3182F6] dark:text-[#60A5FA]">
                    ({room.stayover_count ?? 0}자리연박)
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
