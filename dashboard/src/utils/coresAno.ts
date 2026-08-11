/** Cores por ano, fonte única para o dropdown de período, o gráfico e as legendas.
 *  Espelham `--accent` / `--accent-secondary-bright` do index.css em hex, porque
 *  o recharts precisa de cor literal nos gradientes (`stopColor`). */
export const COR_ANO_RECENTE = '#6f8cc4';
export const COR_ANO_ANTERIOR = '#dabb6c';

/** Ano mais recente = azul; qualquer ano anterior = dourado. */
export function corDoAno(ano: number, anoMaisRecente: number): string {
  return ano === anoMaisRecente ? COR_ANO_RECENTE : COR_ANO_ANTERIOR;
}
