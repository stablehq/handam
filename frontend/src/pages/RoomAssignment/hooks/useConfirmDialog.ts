import { useState } from 'react';
import type { ConfirmState } from '../types';

/**
 * 확인 다이얼로그(`<ConfirmDialog>`)의 상태와 띄우기/닫기 동작을 제공한다.
 *
 * Phase A-2: RoomAssignment.tsx 의 confirmState/showConfirm 분리.
 * setConfirmState 는 외부에 노출하지 않아 임의 상태 변경을 막는다.
 */
export function useConfirmDialog() {
  const [confirmState, setConfirmState] = useState<ConfirmState>({
    open: false,
    title: '',
    content: '',
    onOk: () => {},
  });

  const showConfirm = (title: string, content: string, onOk: () => void) => {
    setConfirmState({ open: true, title, content, onOk });
  };

  const closeConfirm = () => {
    setConfirmState((s) => ({ ...s, open: false }));
  };

  return { confirmState, showConfirm, closeConfirm };
}
