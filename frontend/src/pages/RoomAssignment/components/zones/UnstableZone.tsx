import { GuestZone, type GuestZoneProps } from './GuestZone';
import { MobileGuestZone } from './MobileGuestZone';
import { useIsMobile } from '../../../../hooks/use-mobile';

type WrapperProps = Omit<
  GuestZoneProps,
  'title' | 'titleColorClass' | 'accept' | 'hideWhenEmpty' | 'rowZone'
>;

/** 언스테이블 zone 래퍼 — 드롭 안 받음, 빨강-주황 테마, 비었으면 숨김. */
export function UnstableZone(props: WrapperProps) {
  const isMobile = useIsMobile();
  const Zone = isMobile ? MobileGuestZone : GuestZone;
  return (
    <Zone
      title="언스테이블"
      titleColorClass="text-[#FF6B2C] dark:text-[#FF8A50]"
      accept={false}
      hideWhenEmpty
      rowZone="unstable"
      {...props}
    />
  );
}
