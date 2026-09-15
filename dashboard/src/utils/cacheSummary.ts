import type { DashboardData } from '../types/dashboard';

/**
 * Cache em memória do summary do Dashboard, por empresa ('' = base estática).
 *
 * Existe para que trocar de tela e voltar ao Dashboard não refaça o download
 * (o summary por empresa tem dezenas de MB) nem mostre animação de carregamento:
 * a página volta instantânea, como acontece no Analisador. O prisma fica
 * reservado para a primeira entrada no site e para a troca de base.
 *
 * Vive num módulo, não em React state: a `DashboardPage` é desmontada a cada
 * troca de rota. Zera num F5 — recarregar busca dados frescos. Trocar a base ou
 * clicar em "Regenerar base" também busca de novo (ver `invalidarSummary`).
 */
const cache = new Map<string, DashboardData>();

/** `chave` normalmente é a empresa; inclua o filtro de grupos de clientes nela
 *  (ex.: `${empresa}::${grupos}`) quando ele puder mudar o resultado, senão
 *  trocar de grupo mostraria o summary do grupo anterior. */
export function lerSummaryCache(chave: string): DashboardData | null {
  return cache.get(chave) ?? null;
}

export function gravarSummaryCache(chave: string, dados: DashboardData): void {
  cache.set(chave, dados);
}

/** Sem argumento: limpa tudo. Com `empresa`: limpa essa empresa em qualquer
 *  filtro de grupos — a chave vira `${empresa}::${grupos}`, então o match é
 *  por prefixo, não igualdade exata. */
export function invalidarSummary(empresa?: string): void {
  if (empresa === undefined) {
    cache.clear();
    return;
  }
  for (const chave of cache.keys()) {
    if (chave === empresa || chave.startsWith(`${empresa}::`)) {
      cache.delete(chave);
    }
  }
}
