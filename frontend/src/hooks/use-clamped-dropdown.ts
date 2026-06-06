import { useEffect, useLayoutEffect, useState, type CSSProperties, type RefObject } from 'react';

/** getBoundingClientRect() 결과와 구조 호환 — DOMRect 를 그대로 전달 가능 */
export interface AnchorRect {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

interface UseClampedDropdownOptions {
  /** 'end' = 메뉴 우측을 anchor 우측에 정렬(우측 가장자리 버튼용), 'start' = 좌측 정렬 */
  align?: 'start' | 'end';
  /** anchor 와 메뉴 사이 세로 간격(px) */
  gap?: number;
  /** 뷰포트 가장자리 최소 여백(px) */
  margin?: number;
  /**
   * 페이지 스크롤/리사이즈/핀치줌/Escape 시 닫기 콜백 (detach 방지).
   * useCallback 등으로 참조가 안정적이어야 한다 — 매 렌더 새 함수면 리스너가 계속 재등록되고
   * 300ms open guard 가 재시작된다.
   */
  onClose?: () => void;
  /** scroll-close 에서 무시할 내부 스크롤 영역 (menuRef 는 자동 무시) */
  ignoreScrollWithinRef?: RefObject<HTMLElement | null>;
}

/**
 * body 포탈 + position:fixed 드롭다운의 뷰포트 클램핑 공용 훅.
 *
 * GuestContextMenu.tsx L93-141 의 검증된 패턴(visualViewport 기준 공간 측정 →
 * 아래 우선 / 위 플립 / 양쪽 부족 시 하단 정렬 → 최종 clamp + maxHeight 내부 스크롤)을
 * anchor 사각형 기반으로 일반화 추출. (GuestContextMenu 자체의 마이그레이션은 별도 단계 —
 * 점 anchor 를 퇴화 rect 로 넘길 때 객체 리터럴 재생성으로 인한 재계산 루프 주의, plan 문서 참조)
 *
 * 사용 규약:
 * 1) 메뉴는 createPortal(…, document.body) 로 렌더하고 이 훅의 반환 style 을 적용
 * 2) 반환값이 null 인 측정 전 1프레임은 호출부에서
 *    { position: 'fixed', top: 0, left: 0, visibility: 'hidden', maxWidth: 'calc(100vw - 16px)' }
 *    fallback 을 적용해 자연 크기를 측정하게 한다
 * 3) 열 때마다 anchor 를 새 getBoundingClientRect() 로 갱신할 것 (참조 변경이 재계산 트리거)
 *
 * 설계 문서: docs/plans/sms-chip-dropdown-clamp-portal.md
 */
export function useClampedDropdown(
  open: boolean,
  anchor: AnchorRect | null,
  menuRef: RefObject<HTMLElement | null>,
  options: UseClampedDropdownOptions = {},
): CSSProperties | null {
  const { align = 'start', gap = 4, margin = 8, onClose, ignoreScrollWithinRef } = options;
  const [style, setStyle] = useState<CSSProperties | null>(null);

  useLayoutEffect(() => {
    if (!open || !anchor || !menuRef.current) {
      setStyle(null);
      return;
    }
    const rect = menuRef.current.getBoundingClientRect();
    // 모바일 핀치줌 대응: visualViewport(실제 보이는 영역) 기준 배치 (GuestContextMenu L96-102 동일)
    const vv = window.visualViewport;
    const vLeft = vv ? vv.offsetLeft : 0;
    const vTop = vv ? vv.offsetTop : 0;
    const vWidth = vv ? vv.width : window.innerWidth;
    const vHeight = vv ? vv.height : window.innerHeight;

    const maxWidth = vWidth - margin * 2;
    const maxHeight = vHeight - margin * 2;
    const w = Math.min(rect.width, maxWidth);
    const h = Math.min(rect.height, maxHeight);

    // 가로: 선호 정렬 → 반대쪽 플립 → 아래 최종 clamp 가 마무리
    let left: number;
    if (align === 'end') {
      left = anchor.right - w;
      if (left < vLeft + margin) left = anchor.left;
    } else {
      left = anchor.left;
      if (left + w > vLeft + vWidth - margin) left = anchor.right - w;
    }

    // 세로: 아래 우선 → 위 플립 → 양쪽 부족 시 하단 정렬(내부 스크롤로 수렴)
    const spaceBelow = vTop + vHeight - anchor.bottom - gap;
    const spaceAbove = anchor.top - vTop - gap;
    let top: number;
    if (spaceBelow >= h + margin) {
      top = anchor.bottom + gap;
    } else if (spaceAbove >= h + margin) {
      top = anchor.top - gap - h;
    } else {
      top = vTop + vHeight - h - margin;
    }

    // 최종 clamp — visual viewport 안으로 강제 (GuestContextMenu L136-138 동일)
    left = Math.max(vLeft + margin, Math.min(left, vLeft + vWidth - w - margin));
    top = Math.max(vTop + margin, Math.min(top, vTop + vHeight - h - margin));

    setStyle({ position: 'fixed', left, top, maxWidth, maxHeight });
  }, [open, anchor, align, gap, margin, menuRef]);

  // detach 방지: 페이지 스크롤(캡처)/리사이즈/핀치줌 시 닫기 + Escape.
  // open 직후 300ms 가드 — iOS momentum scroll 잔여 이벤트로 열리자마자 닫히는 것 방지
  // (useContextMenu.ts L37-38 과 동일 패턴)
  useEffect(() => {
    if (!open || !onClose) return;
    const openTime = Date.now();
    const guardedClose = () => {
      if (Date.now() - openTime > 300) onClose();
    };
    const onScroll = (e: Event) => {
      const t = e.target;
      if (t instanceof Node) {
        if (menuRef.current?.contains(t)) return; // 메뉴 내부 스크롤은 무시
        if (ignoreScrollWithinRef?.current?.contains(t)) return; // 호출부 지정 영역(칩 스트립 등)
      }
      guardedClose();
    };
    // resize 계열: 뷰포트 높이가 "줄어드는" 방향(가상 키보드 오픈, 창 축소)만 닫고
    // "커지는" 방향(키보드 dismiss, 주소창 수축)은 무시 — 모바일에서 키보드가 내려가는
    // 도중 + 버튼을 탭하면 메뉴가 열리자마자 닫히는 플리커 방지.
    // (선례 useContextMenu 에는 resize 리스너 자체가 없음 — detach 방지용 신규 동작이라 방향 가드 필요)
    let lastVH = window.visualViewport?.height ?? window.innerHeight;
    const onResize = () => {
      const vh = window.visualViewport?.height ?? window.innerHeight;
      const grew = vh > lastVH + 1;
      lastVH = vh;
      if (!grew) guardedClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    // capture: window 스크롤 + 내부 overflow 컨테이너 스크롤 모두 포착 (useContextMenu.ts L41 동일)
    document.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onResize);
    window.visualViewport?.addEventListener('resize', onResize);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onResize);
      window.visualViewport?.removeEventListener('resize', onResize);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, onClose, menuRef, ignoreScrollWithinRef]);

  return style;
}
