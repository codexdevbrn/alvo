import { useEffect, useState } from 'react';

/** Retorna `value` só depois de `delay` ms sem mudanças — para não recalcular a cada clique. */
export function useDebouncedValue<T>(value: T, delay = 280): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(id);
  }, [value, delay]);

  return debounced;
}
