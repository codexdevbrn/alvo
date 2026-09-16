/**
 * Preferência "Sintética vs Detalhada" da tela Pós precificação.
 *
 * Mesmo desenho de `mesesFechados.ts`: localStorage como fonte de verdade e
 * um CustomEvent para acordar quem já está montado na mesma aba — o toggle
 * vive na topbar (`TopoPosPrecificacaoModoToggle`, AppShell) e o gráfico vive
 * em `PosPrecificacaoVisao`, irmãos na árvore, não pai/filho.
 */
export const LS_MODO_GRAFICO_PRECIFICACAO = 'prisma_pos_precificacao_modo';
export const EVENTO_MODO_GRAFICO_PRECIFICACAO = 'prisma-pos-precificacao-modo-change';

export type ModoGraficoPrecificacao = 'sintetica' | 'detalhada';

function normalizar(valor: string | null): ModoGraficoPrecificacao {
  return valor === 'detalhada' ? 'detalhada' : 'sintetica';
}

export function lerModoGraficoPrecificacao(): ModoGraficoPrecificacao {
  try {
    return normalizar(localStorage.getItem(LS_MODO_GRAFICO_PRECIFICACAO));
  } catch {
    return 'sintetica';
  }
}

export function definirModoGraficoPrecificacao(valor: ModoGraficoPrecificacao) {
  try {
    localStorage.setItem(LS_MODO_GRAFICO_PRECIFICACAO, valor);
  } catch {
    /* Modo privado pode bloquear localStorage; o evento ainda sincroniza a aba. */
  }
  window.dispatchEvent(new CustomEvent(EVENTO_MODO_GRAFICO_PRECIFICACAO, { detail: valor }));
}
