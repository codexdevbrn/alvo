/**
 * Janela de meses das Despesas (6/12/24 meses), no topo ao lado de
 * empresa/loja. Mesmo desenho de `vendaMedia`: localStorage + CustomEvent
 * pra DespesasPage acordar sem contexto global.
 */
export const LS_DESPESAS_PERIODO = 'prisma_despesas_periodo';
export const EVENTO_DESPESAS_PERIODO = 'prisma-despesas-periodo-change';

export const MESES_DESPESAS_PERIODO = [6, 12, 24] as const;
export type MesesDespesasPeriodo = (typeof MESES_DESPESAS_PERIODO)[number];

const PADRAO: MesesDespesasPeriodo = 12;

function normalizar(valor: string | null): MesesDespesasPeriodo {
  const n = Number(valor);
  return (MESES_DESPESAS_PERIODO as readonly number[]).includes(n) ? (n as MesesDespesasPeriodo) : PADRAO;
}

export function lerMesesDespesasPeriodo(): MesesDespesasPeriodo {
  try {
    return normalizar(localStorage.getItem(LS_DESPESAS_PERIODO));
  } catch {
    return PADRAO;
  }
}

export function definirMesesDespesasPeriodo(valor: MesesDespesasPeriodo) {
  try {
    localStorage.setItem(LS_DESPESAS_PERIODO, String(valor));
  } catch {
    /* modo privado */
  }
  window.dispatchEvent(new CustomEvent(EVENTO_DESPESAS_PERIODO, { detail: valor }));
}
