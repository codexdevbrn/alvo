/**
 * Queda (ou alta) tão extrema que quase sempre é buraco de dado, não movimento
 * real — mês sem lançamento, competência futura, base minúscula. Não pintar
 * como economia/ganho.
 */
export function variacaoSuspeita(
  variacaoPct: number | null | undefined,
  atual: number,
  referencia: number,
): boolean {
  if (variacaoPct == null || !Number.isFinite(variacaoPct)) return false;
  if (Math.abs(variacaoPct) < 80) return false;
  if (!(referencia > 0)) return false;
  return Math.abs(atual) < referencia * 0.15;
}
