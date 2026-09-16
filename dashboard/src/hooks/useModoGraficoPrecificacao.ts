import { useCallback, useEffect, useState } from 'react';
import {
  EVENTO_MODO_GRAFICO_PRECIFICACAO,
  definirModoGraficoPrecificacao,
  lerModoGraficoPrecificacao,
  type ModoGraficoPrecificacao,
} from '../utils/modoGraficoPrecificacao';

/** Sintética/Detalhada da tela Pós precificação — mesmo padrão de `useMesesFechados`. */
export function useModoGraficoPrecificacao(): [ModoGraficoPrecificacao, (valor: ModoGraficoPrecificacao) => void] {
  const [modo, setEstado] = useState(lerModoGraficoPrecificacao);

  useEffect(() => {
    const sincronizar = () => setEstado(lerModoGraficoPrecificacao());
    window.addEventListener(EVENTO_MODO_GRAFICO_PRECIFICACAO, sincronizar);
    window.addEventListener('storage', sincronizar);
    return () => {
      window.removeEventListener(EVENTO_MODO_GRAFICO_PRECIFICACAO, sincronizar);
      window.removeEventListener('storage', sincronizar);
    };
  }, []);

  const definir = useCallback((valor: ModoGraficoPrecificacao) => {
    definirModoGraficoPrecificacao(valor);
    setEstado(valor);
  }, []);

  return [modo, definir];
}
