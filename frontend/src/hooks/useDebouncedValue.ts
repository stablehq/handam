import { useEffect, useState } from 'react';

/**
 * 입력값을 지정 시간만큼 지연시켜 반환. 빠른 타이핑 중 fetch thrash 회피.
 *
 * 사용 예:
 *   const debouncedSearch = useDebouncedValue(searchQuery, 300);
 *   useQuery({ queryKey: [..., debouncedSearch], ... });
 */
export function useDebouncedValue<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);

  return debounced;
}
