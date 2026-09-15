import { useEffect, useState } from 'react';
import { EVENTO_CORTES_RELATORIOS } from '../utils/cortesRelatorios';

/**
 * Incrementa a cada vez que o toggle "Cortes" (sidebar, Sem corte/Com corte)
 * muda. O toggle já limpa o cache (`invalidarSummary`/`limparCacheGeral`), mas
 * sem isto nenhuma tela reagia — o efeito de busca só reexecuta quando algo no
 * seu array de dependências muda, e nenhuma delas dependia desse evento.
 * Inclua o retorno no array de dependências do efeito que busca os dados.
 */
export function useVersaoCortesRelatorios(): number {
  const [versao, setVersao] = useState(0);
  useEffect(() => {
    const incrementar = () => setVersao((v) => v + 1);
    window.addEventListener(EVENTO_CORTES_RELATORIOS, incrementar);
    return () => window.removeEventListener(EVENTO_CORTES_RELATORIOS, incrementar);
  }, []);
  return versao;
}
