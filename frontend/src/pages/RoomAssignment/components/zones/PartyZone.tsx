import { GuestZone, type GuestZoneProps } from './GuestZone';

type WrapperProps = Omit<
  GuestZoneProps,
  'title' | 'titleColorClass' | 'accept' | 'zoneId' | 'nextZoneId' | 'hoverBgClass' | 'emptyMessage' | 'emptyMessageColorClass'
>;

/** 파티만 zone 래퍼 — 드롭 받음, 보라 테마. */
export function PartyZone(props: WrapperProps) {
  return (
    <GuestZone
      title="파티만"
      titleColorClass="text-[#7B61FF] dark:text-[#7B61FF]"
      accept
      zoneId="party"
      nextZoneId="next-party"
      hoverBgClass="bg-[#7B61FF]/5 dark:bg-[#7B61FF]/8"
      emptyMessage="클릭하면 파티만으로 전환"
      emptyMessageColorClass="text-[#7B61FF] dark:text-[#7B61FF]"
      {...props}
    />
  );
}
