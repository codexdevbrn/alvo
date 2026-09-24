/**
 * Preferência "Todos vs Precificados" da tela Pós precificação — quais itens
 * entram no movimento. Mesmo desenho de `modoGraficoPrecificacao.ts`: o toggle
 * vive na topbar e a visão em `PosPrecificacaoVisao`, irmãos na árvore.
 */
export const LS_ITENS_PRECIFICACAO = 'prisma_pos_precificacao_itens';
export const EVENTO_ITENS_PRECIFICACAO = 'prisma-pos-precificacao-itens-change';

export type ItensPrecificacao = 'todos' | 'precificados';

function normalizar(valor: string | null): ItensPrecificacao {
  return valor === 'precificados' ? 'precificados' : 'todos';
}

export function lerItensPrecificacao(): ItensPrecificacao {
  try {
    return normalizar(localStorage.getItem(LS_ITENS_PRECIFICACAO));
  } catch {
    return 'todos';
  }
}

export function definirItensPrecificacao(valor: ItensPrecificacao) {
  try {
    localStorage.setItem(LS_ITENS_PRECIFICACAO, valor);
  } catch {
    /* Modo privado pode bloquear localStorage; o evento ainda sincroniza a aba. */
  }
  window.dispatchEvent(new CustomEvent(EVENTO_ITENS_PRECIFICACAO, { detail: valor }));
}
