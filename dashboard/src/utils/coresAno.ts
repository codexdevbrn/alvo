/** Cores por ano, fonte única para o dropdown de período, o gráfico e as legendas.
 *  Espelham `--accent` / `--accent-secondary-bright` do index.css em hex, porque
 *  o recharts precisa de cor literal nos gradientes (`stopColor`). */
export const COR_ANO_RECENTE = '#6f8cc4';
export const COR_ANO_ANTERIOR = '#dabb6c';
/** Mesmo tom de `--danger` — despesa é custo, não uma terceira "safra" de ano. */
export const COR_DESPESAS = '#e0645c';

/** Ano mais recente = azul; qualquer ano anterior = dourado. */
export function corDoAno(ano: number, anoMaisRecente: number): string {
  return ano === anoMaisRecente ? COR_ANO_RECENTE : COR_ANO_ANTERIOR;
}
