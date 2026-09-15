import { useCallback, useEffect, useState } from 'react';
import {
  EVENTO_DESPESAS_PERIODO,
  definirMesesDespesasPeriodo,
  lerMesesDespesasPeriodo,
  type MesesDespesasPeriodo,
} from '../utils/despesasPeriodo';

/** Preferência "Janela" do topo, compartilhada pelas Despesas. */
export function useDespesasPeriodo(): [MesesDespesasPeriodo, (valor: MesesDespesasPeriodo) => void] {
  const [meses, setEstado] = useState(lerMesesDespesasPeriodo);

  useEffect(() => {
    const sincronizar = () => setEstado(lerMesesDespesasPeriodo());
    window.addEventListener(EVENTO_DESPESAS_PERIODO, sincronizar);
    window.addEventListener('storage', sincronizar);
    return () => {
      window.removeEventListener(EVENTO_DESPESAS_PERIODO, sincronizar);
      window.removeEventListener('storage', sincronizar);
    };
  }, []);

  const definir = useCallback((valor: MesesDespesasPeriodo) => {
    definirMesesDespesasPeriodo(valor);
    setEstado(valor);
  }, []);

  return [meses, definir];
}
