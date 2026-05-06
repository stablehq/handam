import { Modal, ModalHeader, ModalBody, ModalFooter } from '@/components/ui/modal';
import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import type { Reservation } from '../types';

interface AutoAssignConfirmModalProps {
  open: boolean;
  onClose: () => void;
  unassigned: Reservation[];
  onConfirm: () => void;
  loading: boolean;
}

export function AutoAssignConfirmModal({
  open,
  onClose,
  unassigned,
  onConfirm,
  loading,
}: AutoAssignConfirmModalProps) {
  return (
    <Modal size="md" show={open} onClose={onClose}>
      <ModalHeader>객실 자동 배정</ModalHeader>
      <ModalBody>
        <p className="text-body text-[#4E5968] dark:text-gray-300 mb-4">
          미배정 예약자를 상품 매칭에 따라 객실에 자동 배정합니다.
        </p>
        <p className="text-label font-medium text-[#8B95A1] mb-2">
          배정 대상 ({unassigned.length}명)
        </p>
        {unassigned.length === 0 ? (
          <p className="text-body text-[#8B95A1] py-4 text-center">미배정 예약자가 없습니다.</p>
        ) : (
          <div className="divide-y divide-[#E5E8EB] dark:divide-gray-700">
            {unassigned.map((guest) => (
              <div key={guest.id} className="flex items-center justify-between py-2.5">
                <div className="flex items-center gap-2">
                  <span className="text-body font-medium text-[#191F28] dark:text-white">
                    {guest.customer_name}
                  </span>
                  <span className="text-caption text-[#8B95A1]">{guest.phone}</span>
                </div>
                <span className="text-caption text-[#8B95A1]">
                  {guest.naver_room_type || '-'}
                </span>
              </div>
            ))}
          </div>
        )}
      </ModalBody>
      <ModalFooter>
        <Button color="light" onClick={onClose}>
          취소
        </Button>
        <Button color="blue" onClick={onConfirm} disabled={loading}>
          {loading ? (
            <>
              <Spinner size="sm" className="mr-2" />
              배정 중...
            </>
          ) : (
            '배정 진행'
          )}
        </Button>
      </ModalFooter>
    </Modal>
  );
}
