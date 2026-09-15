/**
 * Filtro global "Grupos de clientes" (1/2/3/X/B) do topo — só aparece com o
 * toggle "Cortes: Com corte" ligado. Mesmo desenho de `cortesRelatorios`/
 * `empresaSelecionada`: localStorage como fonte de verdade + CustomEvent para
 * acordar quem já está montado na mesma aba.
 *
 * Os tokens são os mesmos de `rotuloGrupoCurto` no frontend e `_token_da_faixa`
 * no backend: "1"/"2"/"3" = Grupo N (ordem dos cortes salvos em Cortes),
 * "X" = Demais, "B" = Balcão. Lista vazia = sem filtro (todos os grupos).
 */
export const EVENTO_GRUPOS_CLIENTES = 'prisma-grupos-clientes-change';

const LS_GRUPOS_CLIENTES = 'prisma_grupos_clientes_filtro';

export function lerGruposClientesFiltro(): string[] {
  try {
    const salvo = localStorage.getItem(LS_GRUPOS_CLIENTES);
    if (!salvo) return [];
    const valores = JSON.parse(salvo) as unknown;
    return Array.isArray(valores) ? valores.map(String) : [];
  } catch {
    return [];
  }
}

export function definirGruposClientesFiltro(grupos: string[]): void {
  const unicos = [...new Set(grupos.map((g) => g.trim().toUpperCase()).filter(Boolean))];
  try {
    if (unicos.length > 0) localStorage.setItem(LS_GRUPOS_CLIENTES, JSON.stringify(unicos));
    else localStorage.removeItem(LS_GRUPOS_CLIENTES);
  } catch {
    /* Modo privado pode bloquear localStorage; o evento ainda sincroniza a aba. */
  }
  window.dispatchEvent(new CustomEvent(EVENTO_GRUPOS_CLIENTES, { detail: unicos }));
}

/** Parâmetro pronto pra mandar pro backend — undefined quando não há filtro. */
export function gruposClientesParam(grupos: string[]): string | undefined {
  return grupos.length > 0 ? grupos.join(',') : undefined;
}
