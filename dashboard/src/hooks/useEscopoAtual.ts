import { useEffect, useState } from 'react';
import { EVENTO_EMPRESA } from '../utils/empresaSelecionada';
import { EVENTO_LOJA, lerLoja } from '../utils/lojaSelecionada';

const LS_EMPRESA = 'alvo_empresa';

function lerEmpresa(): string {
  try {
    return localStorage.getItem(LS_EMPRESA) || '';
  } catch {
    return '';
  }
}

export interface EscopoAtual {
  /** '' = base padrão (nenhuma empresa selecionada). */
  empresa: string;
  /** null = todas as lojas. É o formato que as APIs esperam. */
  loja: string | null;
}

/**
 * Escopo em uso (empresa + loja) da barra lateral, sincronizado.
 *
 * Cada tela lia o localStorage e assinava os eventos por conta própria, e cada
 * cópia divergia um pouco (uma zerava a loja ao trocar de empresa, outra não).
 * Aqui é um lugar só: quem precisa do escopo chama isto e reage à mudança.
 */
export function useEscopoAtual(): EscopoAtual {
  const [empresa, setEmpresa] = useState(lerEmpresa);
  const [loja, setLoja] = useState(() => lerLoja(lerEmpresa()));

  useEffect(() => {
    const sincronizar = () => {
      const nome = lerEmpresa();
      setEmpresa(nome);
      setLoja(lerLoja(nome));
    };
    // 'storage' cobre outra aba; os CustomEvent cobrem esta.
    window.addEventListener(EVENTO_EMPRESA, sincronizar);
    window.addEventListener(EVENTO_LOJA, sincronizar);
    window.addEventListener('storage', sincronizar);
    return () => {
      window.removeEventListener(EVENTO_EMPRESA, sincronizar);
      window.removeEventListener(EVENTO_LOJA, sincronizar);
      window.removeEventListener('storage', sincronizar);
    };
  }, []);

  return { empresa, loja: loja || null };
}
