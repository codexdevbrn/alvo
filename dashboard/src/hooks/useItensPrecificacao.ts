import { useCallback, useEffect, useState } from 'react';
import {
  EVENTO_ITENS_PRECIFICACAO,
  definirItensPrecificacao,
  lerItensPrecificacao,
  type ItensPrecificacao,
} from '../utils/itensPrecificacao';

/** Todos/Precificados da tela Pós precificação — mesmo padrão de `useModoGraficoPrecificacao`. */
export function useItensPrecificacao(): [ItensPrecificacao, (valor: ItensPrecificacao) => void] {
  const [itens, setEstado] = useState(lerItensPrecificacao);

  useEffect(() => {
    const sincronizar = () => setEstado(lerItensPrecificacao());
    window.addEventListener(EVENTO_ITENS_PRECIFICACAO, sincronizar);
    window.addEventListener('storage', sincronizar);
    return () => {
      window.removeEventListener(EVENTO_ITENS_PRECIFICACAO, sincronizar);
      window.removeEventListener('storage', sincronizar);
    };
  }, []);

  const definir = useCallback((valor: ItensPrecificacao) => {
    definirItensPrecificacao(valor);
    setEstado(valor);
  }, []);

  return [itens, definir];
}
