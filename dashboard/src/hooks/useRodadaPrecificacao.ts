import { useCallback, useSyncExternalStore } from 'react';
import {
  EVENTO_RODADA_PRECIFICACAO,
  escolherRodada,
  lerRodadaEscolhida,
  lerRodadasPublicadas,
  versaoRodadas,
} from '../utils/rodadaPrecificacao';

function assinar(avisar: () => void) {
  window.addEventListener(EVENTO_RODADA_PRECIFICACAO, avisar);
  return () => window.removeEventListener(EVENTO_RODADA_PRECIFICACAO, avisar);
}

/** Rodada escolhida e rodadas disponíveis da Pós precificação para `empresa`. */
export function useRodadaPrecificacao(empresa: string | null) {
  useSyncExternalStore(assinar, versaoRodadas);
  const escolher = useCallback(
    (dia: string) => {
      if (empresa) escolherRodada(empresa, dia);
    },
    [empresa],
  );
  return {
    escolhida: empresa ? lerRodadaEscolhida(empresa) : null,
    publicadas: empresa ? lerRodadasPublicadas(empresa) : null,
    escolher,
  };
}
