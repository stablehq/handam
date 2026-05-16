import { formatGenderPeople, formatGuestSuffix } from '../../utils/reservationFormat';
import type { Reservation } from '../../types';

interface GuestDragCardProps {
  reservation: Reservation;
}

/**
 * DragOverlay 내용물 — 드래그 중 마우스 위에 떠다니는 컴팩트 카드.
 * 이름 + suffix(N회/M세) + 파티/성별 인원 표시.
 */
export function GuestDragCard({ reservation }: GuestDragCardProps) {
  const gp = formatGenderPeople(reservation);
  const suffix = formatGuestSuffix(reservation);

  return (
    <div className="rounded-xl bg-white dark:bg-[#1E1E24] shadow-lg border border-[#3182F6]/30 dark:border-[#3182F6]/30 px-3 py-2 flex items-center gap-2 whitespace-nowrap min-w-[120px]">
      <span className="font-medium text-body text-[#191F28] dark:text-white">
        {reservation.customer_name}
      </span>
      {suffix && (
        <span className="text-caption text-[#8B95A1] dark:text-[#4E5968]">{suffix}</span>
      )}
      {gp && (
        <span className="text-caption text-[#8B95A1] dark:text-[#4E5968]">{gp}</span>
      )}
    </div>
  );
}
