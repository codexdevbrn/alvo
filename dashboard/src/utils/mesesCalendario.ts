const MES_NUM: Record<string, number> = {
  jan: 1, fev: 2, mar: 3, abr: 4, mai: 5, jun: 6,
  jul: 7, ago: 8, set: 9, out: 10, nov: 11, dez: 12,
};

export const MES_ABREV = ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

/** Número do mês (1–12) a partir do rótulo do summary (`jan/25`). */
export function mesDeRotulo(name: string): number {
  return MES_NUM[name.split('/')[0].toLowerCase()] ?? 0;
}

/** Último mês fechado no ano corrente (1–12). 0 = nenhum (ex.: estamos em janeiro). */
export function ultimoMesFechado(ref: Date = new Date()): number {
  return ref.getMonth();
}

/** Mês corrente (1–12). */
export function mesAtualNum(ref: Date = new Date()): number {
  return ref.getMonth() + 1;
}

/** Abreviatura (jan–dez) do mês corrente. */
export function abrevMesAtual(ref: Date = new Date()): string {
  return MES_ABREV[ref.getMonth() + 1];
}

/** Abreviatura do mês a partir do rótulo do summary (`jan/25` → `jan`). */
export function mesAbrevDeRotulo(name: string): string {
  return name.split('/')[0].toLowerCase();
}

/** Abreviatura (jan–dez) do último mês fechado no ano corrente, ou null em janeiro. */
export function abrevUltimoMesFechado(ref: Date = new Date()): string | null {
  const limite = ultimoMesFechado(ref);
  if (limite <= 0) return null;
  return MES_ABREV[limite];
}
