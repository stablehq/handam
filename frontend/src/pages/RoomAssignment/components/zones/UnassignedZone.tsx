import { GuestZone, type GuestZoneProps } from './GuestZone';
import { MobileGuestZone } from './MobileGuestZone';
import { useIsMobile } from '../../../../hooks/use-mobile';

type WrapperProps = Omit<
  GuestZoneProps,
  'title' | 'titleColorClass' | 'accept' | 'zoneId' | 'nextZoneId' | 'hoverBgClass' | 'emptyMessage' | 'emptyMessageColorClass'
>;

/** 미배정 zone 래퍼 — 드롭 받음, 주황 테마. */
export function UnassignedZone(props: WrapperProps) {
  const isMobile = useIsMobile();
  const Zone = isMobile ? MobileGuestZone : GuestZone;
  return (
    <Zone
      title="미배정"
      titleColorClass="text-[#FF9500] dark:text-[#FF9500]"
      accept
      zoneId="pool"
      nextZoneId="next-pool"
      hoverBgClass="bg-[#FF9500]/50 dark:bg-[#FF9500]/8"
      emptyMessage="클릭하면 배정 해제"
      emptyMessageColorClass="text-[#FF9500] dark:text-[#FF9500]"
      {...props}
    />
  );
}
