import { formatCurrency } from '../../utils/formatters';

const MESES_CURTOS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

export function quantidade(valor: number | null | undefined, casas = 0): string {
  if (valor == null || !Number.isFinite(valor)) return '—';
  // Estoque e venda podem vir fracionados (produto vendido a metro, litro).
  const maximo = Number.isInteger(valor) ? casas : Math.max(casas, 2);
  return valor.toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: maximo });
}

export function moedaOuTraco(valor: number | null | undefined): string {
  return valor == null || !Number.isFinite(valor) ? '—' : formatCurrency(valor);
}

/** "2026-09" → "set". */
export function mesCurto(rotulo: string): string {
  const mes = Number(rotulo.split('-')[1]);
  return MESES_CURTOS[mes - 1] ?? rotulo;
}

/** "2026-09" → "set/2026". */
export function mesLongo(rotulo: string): string {
  const [ano] = rotulo.split('-');
  return `${mesCurto(rotulo)}/${ano}`;
}

/** Produto = descrição × fabricante; mesma chave em qualquer lugar da tela. */
export function chaveProduto(produto: { descricao: string; fabricante: string }): string {
  return `${produto.descricao}\u0000${produto.fabricante}`;
}

export type Selecao = { tipo: 'produto'; chave: string } | { tipo: 'sku'; chave: string; codigo: string };
