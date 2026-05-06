import dayjs from 'dayjs';
import { Plus, Link2 } from 'lucide-react';
import { Modal, ModalHeader, ModalBody, ModalFooter } from '@/components/ui/modal';
import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import { Badge } from '@/components/ui/badge';

export interface StayGroupChainEntry {
  id: number;
  customer_name: string;
  phone: string;
  check_in_date: string;
  check_out_date: string;
  stay_group_id?: string | null;
}

interface StayGroupChainModalProps {
  show: boolean;
  onClose: () => void;
  chain: StayGroupChainEntry[];
  direction: 'left' | 'right';
  onDirectionChange: (dir: 'left' | 'right') => void;
  dateReservations: any[];
  loading: boolean;
  selectedId: number | null;
  onSelectId: (id: number) => void;
  linking: boolean;
  onAddMore: () => void;
  onComplete: () => void;
}

export function StayGroupChainModal({
  show,
  onClose,
  chain,
  direction,
  onDirectionChange,
  dateReservations,
  loading,
  selectedId,
  onSelectId,
  linking,
  onAddMore,
  onComplete,
}: StayGroupChainModalProps) {
  return (
    <Modal show={show} onClose={onClose} size="lg">
      <ModalHeader>
        연박 묶기 — 연결할 예약자 선택
      </ModalHeader>
      <ModalBody>
        <div className="space-y-4">
          {/* Chain with bidirectional + buttons */}
          {chain.length > 0 && (
            <div className="rounded-xl bg-[#E8F3FF] dark:bg-[#3182F6]/10 p-3">
              <p className="text-caption font-medium text-[#3182F6] mb-2">연박 체인</p>
              <div className="flex flex-wrap items-center gap-2">
                {/* Left + button */}
                <button
                  onClick={() => onDirectionChange('left')}
                  className={`w-7 h-7 flex-shrink-0 rounded-lg border-2 border-dashed flex items-center justify-center transition-colors ${
                    direction === 'left'
                      ? 'border-[#3182F6] text-[#3182F6] bg-[#3182F6]/10'
                      : 'border-[#B0B8C1] text-[#B0B8C1] hover:border-[#3182F6] hover:text-[#3182F6]'
                  }`}
                >
                  <Plus className="h-3.5 w-3.5" />
                </button>

                <Link2 className="h-3.5 w-3.5 text-[#3182F6]" />

                {/* Chain items */}
                {chain.map((item, idx) => (
                  <span key={item.id} className="flex items-center gap-2">
                    {idx > 0 && <Link2 className="h-3.5 w-3.5 text-[#3182F6]" />}
                    <span className="rounded-lg bg-white dark:bg-[#1E1E24] px-3 py-1.5 shadow-sm text-center">
                      <span className="block text-caption text-[#8B95A1] tabular-nums">{item.check_in_date.slice(5)}~{item.check_out_date?.slice(5)}</span>
                      <span className="block text-caption font-medium text-[#191F28] dark:text-white">{item.customer_name}</span>
                    </span>
                  </span>
                ))}

                <Link2 className="h-3.5 w-3.5 text-[#3182F6]" />

                {/* Right + button */}
                <button
                  onClick={() => onDirectionChange('right')}
                  className={`w-7 h-7 flex-shrink-0 rounded-lg border-2 border-dashed flex items-center justify-center transition-colors ${
                    direction === 'right'
                      ? 'border-[#3182F6] text-[#3182F6] bg-[#3182F6]/10'
                      : 'border-[#B0B8C1] text-[#B0B8C1] hover:border-[#3182F6] hover:text-[#3182F6]'
                  }`}
                >
                  <Plus className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          )}

          {/* SMS warning */}
          {chain.length >= 1 && (
            <div className="rounded-xl bg-[#FFF8E1] dark:bg-[#FF9F00]/10 p-3">
              <p className="text-caption text-[#FF9F00] dark:text-[#FFB84D]">
                연박을 묶으면 SMS 스케줄(마지막 날 발송, 연박 제외 등)이 변경될 수 있습니다.
              </p>
            </div>
          )}

          {/* Date label */}
          <div className="flex items-center gap-2">
            <span className="text-label font-semibold text-[#191F28] dark:text-white">
              {direction === 'left'
                ? `${dayjs(chain[0]?.check_in_date).subtract(1, 'day').format('YYYY-MM-DD')} 예약자`
                : `${chain[chain.length - 1]?.check_out_date || ''} 예약자`
              }
            </span>
          </div>

          {/* Reservation list */}
          {loading ? (
            <div className="flex justify-center py-8">
              <Spinner size="md" />
            </div>
          ) : dateReservations
                .filter((r: any) => !chain.some(c => c.id === r.id)).length === 0 ? (
            <div className="py-8 text-center text-label text-[#B0B8C1]">해당 날짜에 예약이 없습니다</div>
          ) : (
            <div className="divide-y divide-[#F2F4F6] dark:divide-gray-800 rounded-xl border border-[#E5E8EB] dark:border-gray-700">
              {dateReservations
                .filter((r: any) => !chain.some(c => c.id === r.id))
                .map((r: any) => (
                <label
                  key={r.id}
                  className={`flex items-center gap-3 px-4 py-3 cursor-pointer transition-colors ${
                    selectedId === r.id
                      ? 'bg-[#E8F3FF] dark:bg-[#3182F6]/10'
                      : 'hover:bg-[#F2F4F6] dark:hover:bg-[#1E1E24]'
                  }`}
                >
                  <input
                    type="radio"
                    name="stayGroupSelect"
                    checked={selectedId === r.id}
                    onChange={() => onSelectId(r.id)}
                    className="h-4 w-4 text-[#3182F6] border-[#E5E8EB] focus:ring-[#3182F6]"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-body text-[#191F28] dark:text-white">{r.customer_name}</span>
                      <span className="text-caption tabular-nums text-[#8B95A1]">{r.phone}</span>
                    </div>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-caption text-[#B0B8C1]">{r.check_in_date} ~ {r.check_out_date}</span>
                      {r.stay_group_id && (
                        <Badge color="warning" size="sm">이미 연박 그룹</Badge>
                      )}
                    </div>
                  </div>
                </label>
              ))}
            </div>
          )}
        </div>
      </ModalBody>
      <ModalFooter>
        <>
          <Button color="light" onClick={onClose}>취소</Button>
          <Button color="light" disabled={!selectedId} onClick={onAddMore}>
            {selectedId ? '+ 선택 추가' : '예약자를 선택하세요'}
          </Button>
          {chain.length >= 2 && (
            <Button color="blue" disabled={linking} onClick={onComplete}>
              {linking ? <><Spinner size="sm" className="mr-2" />묶는 중...</> : `완료 (${chain.length}건 연박)`}
            </Button>
          )}
        </>
      </ModalFooter>
    </Modal>
  );
}
