/**
 * Janela de venda média do Estoque (3/6/12 meses), no topo ao lado de
 * empresa/loja. Mesmo desenho de `mesesFechados`: localStorage + CustomEvent
 * pra EstoquePage e o prefetch acordarem sem contexto global.
 */
export const LS_VENDA_MEDIA = 'prisma_venda_media';
export const EVENTO_VENDA_MEDIA = 'prisma-venda-media-change';

export const MESES_VENDA_MEDIA = [3, 6, 12] as const;
export type MesesVendaMedia = (typeof MESES_VENDA_MEDIA)[number];

const PADRAO: MesesVendaMedia = 6;

function normalizar(valor: string | null): MesesVendaMedia {
  const n = Number(valor);
  return (MESES_VENDA_MEDIA as readonly number[]).includes(n) ? (n as MesesVendaMedia) : PADRAO;
}

export function lerMesesVendaMedia(): MesesVendaMedia {
  try {
    return normalizar(localStorage.getItem(LS_VENDA_MEDIA));
  } catch {
    return PADRAO;
  }
}

export function definirMesesVendaMedia(valor: MesesVendaMedia) {
  try {
    localStorage.setItem(LS_VENDA_MEDIA, String(valor));
  } catch {
    /* modo privado */
  }
  window.dispatchEvent(new CustomEvent(EVENTO_VENDA_MEDIA, { detail: valor }));
}
