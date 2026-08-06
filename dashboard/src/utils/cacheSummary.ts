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

export function lerSummaryCache(empresa: string): DashboardData | null {
  return cache.get(empresa) ?? null;
}

export function gravarSummaryCache(empresa: string, dados: DashboardData): void {
  cache.set(empresa, dados);
}

export function invalidarSummary(empresa?: string): void {
  if (empresa === undefined) cache.clear();
  else cache.delete(empresa);
}
