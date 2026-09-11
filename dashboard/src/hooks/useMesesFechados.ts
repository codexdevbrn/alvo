import { useCallback, useEffect, useState } from 'react';
import {
  EVENTO_MESES_FECHADOS,
  definirModoPeriodo,
  lerModoPeriodo,
  type ModoPeriodo,
} from '../utils/mesesFechados';

/**
 * Preferência global "período usado nos cálculos" (sidebar), sincronizada
 * entre Dashboard, Clientes, Vendedores e Estoque — mesmo padrão de
 * `useEscopoAtual` para empresa/loja.
 */
export function useMesesFechados(): [ModoPeriodo, (valor: ModoPeriodo) => void] {
  const [modoPeriodo, setEstado] = useState(lerModoPeriodo);

  useEffect(() => {
    const sincronizar = () => setEstado(lerModoPeriodo());
    window.addEventListener(EVENTO_MESES_FECHADOS, sincronizar);
    window.addEventListener('storage', sincronizar);
    return () => {
      window.removeEventListener(EVENTO_MESES_FECHADOS, sincronizar);
      window.removeEventListener('storage', sincronizar);
    };
  }, []);

  const definir = useCallback((valor: ModoPeriodo) => {
    definirModoPeriodo(valor);
    setEstado(valor);
  }, []);

  return [modoPeriodo, definir];
}
