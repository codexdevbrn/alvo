import { useEffect } from 'react';

const INTERVALO_MS = 15_000;

/**
 * Recarrega a aba quando o servidor passa a responder com outra versão.
 *
 * Depois de uma atualização o atualizador religa o app sem abrir aba nova
 * (`--apos-atualizar` em `servidor.py`) — é esta aba, a que já estava aberta,
 * que passa para a versão nova. Vale para qualquer origem da atualização:
 * faixa do topo, Configurações ou o menu da bandeja.
 *
 * A primeira resposta fixa a versão desta aba; falha de rede (app reiniciando)
 * só espera a próxima rodada.
 */
export function useRecarregarQuandoVersaoMudar() {
  useEffect(() => {
    let versaoDaAba: string | null = null;
    const conferir = async () => {
      try {
        const res = await fetch('/api/versao', { cache: 'no-store' });
        if (!res.ok) return;
        const { versao } = (await res.json()) as { versao?: string };
        if (!versao) return;
        if (versaoDaAba == null) versaoDaAba = versao;
        else if (versao !== versaoDaAba) window.location.reload();
      } catch {
        /* reiniciando: tenta de novo na próxima rodada */
      }
    };
    void conferir();
    const id = window.setInterval(() => void conferir(), INTERVALO_MS);
    return () => window.clearInterval(id);
  }, []);
}
