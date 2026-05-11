import { Modal, ModalHeader, ModalBody, ModalFooter } from '@/components/ui/modal';
import { Button } from '@/components/ui/button';

export interface ExtendStayConflictData {
  open: boolean;
  newResId: number;
  roomId: number;
  roomNumber: string;
  existingGuests: string[];
}

interface ExtendStayConflictModalProps {
  data: ExtendStayConflictData | null;
  onClose: () => void;
  onKeepSameRoom: () => void;  // '같은방에 유지' (공동 점유)
  onSkipAssign: () => void;    // 방 배정 없이 연박만
}

export function ExtendStayConflictModal({
  data,
  onClose,
  onKeepSameRoom,
  onSkipAssign,
}: ExtendStayConflictModalProps) {
  return (
    <Modal show={!!data?.open} onClose={onClose} size="md">
      <ModalHeader>방 배정 충돌</ModalHeader>
      <ModalBody>
        <div className="space-y-3">
          <p className="text-body text-[#191F28] dark:text-white">
            <span className="font-semibold">{data?.roomNumber}호</span>에 이미 배정된 게스트가 있습니다.
          </p>
          <div className="rounded-lg bg-[#F2F4F6] dark:bg-[#2C2C34] p-3">
            {data?.existingGuests.map((name, i) => (
              <div key={i} className="text-body text-[#4E5968] dark:text-gray-300">{name}</div>
            ))}
          </div>
        </div>
      </ModalBody>
      <ModalFooter>
        <div className="flex gap-2 w-full">
          <Button color="blue" className="flex-1" onClick={onKeepSameRoom}>
            같은방에 유지
          </Button>
          <Button color="light" className="flex-1" onClick={onSkipAssign}>
            취소
          </Button>
        </div>
      </ModalFooter>
    </Modal>
  );
}
