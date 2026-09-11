import type { StatusCoberturaEstoque } from '../../api/client';

/** Rótulo e cor de cada situação vivem juntos: visão geral, mapa e tabela
 *  precisam nomear e colorir a mesma situação do mesmo jeito. */
export const ROTULOS_STATUS: Record<StatusCoberturaEstoque, string> = {
  normal: 'Saudável',
  rupture: 'Risco de ruptura',
  out_of_stock: 'Sem estoque',
  negative: 'Estoque negativo',
  stalled: 'Perdendo força',
  excess: 'Excesso',
  no_sales: 'Sem giro',
};

/** Tokens da paleta, nunca hex solto — o card precisa combinar com o filete. */
export const CORES_STATUS: Record<StatusCoberturaEstoque, string> = {
  normal: 'var(--success)',
  rupture: 'var(--danger)',
  out_of_stock: 'var(--danger)',
  negative: 'var(--danger)',
  stalled: 'var(--accent)',
  excess: 'var(--accent)',
  no_sales: 'var(--text-muted)',
};

export function classeStatus(status: StatusCoberturaEstoque): string {
  if (status === 'normal') return 'is-normal';
  if (status === 'rupture' || status === 'out_of_stock' || status === 'negative') return 'is-perigo';
  return 'is-atencao';
}

const ACENTOS = /[\u0300-\u036f]/g;

export function normalizarBusca(valor: string): string {
  return valor.normalize('NFD').replace(ACENTOS, '').toLocaleLowerCase('pt-BR');
}

export function numero(valor: number, casas = 0): string {
  return valor.toLocaleString('pt-BR', { maximumFractionDigits: casas });
}

/** "3,2 meses" / "—" quando o produto não vende e a conta não existe. */
export function textoCobertura(cobertura: number | null): string {
  return cobertura == null ? '—' : `${numero(cobertura, 1)} ${cobertura === 1 ? 'mês' : 'meses'}`;
}
