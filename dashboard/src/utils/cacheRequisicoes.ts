/**
 * Gerencia o cache local das requisições para evitar telas de carregamento repetidas.
 * Usa Memória (Map) primariamente e tenta usar o Local Storage para persistir caso dê F5.
 */

const CACHE_PREFIX = 'prisma_req_cache_';
const memoriaCache = new Map<string, unknown>();
/** Pedidos iguais em voo compartilham a Promise. Sem isso, o Strict Mode
 *  (mount → abort → remount) dispara duas idas ao backend síncrono e a
 *  segunda espera a primeira acabar — a aba Escopo fica girando no primeiro open.
 *  O fetcher NÃO pode fechar sobre AbortSignal do caller: abort do 1º mount
 *  rejeita a Promise compartilhada e o remount engole AbortError com tela vazia. */
const inflight = new Map<string, Promise<unknown>>();

export function getChaveCache(url: string, params?: unknown): string {
  if (!params) return url;
  return `${url}|${JSON.stringify(params)}`;
}

export function lerCache<T>(chave: string): T | null {
  if (memoriaCache.has(chave)) {
    return memoriaCache.get(chave) as T;
  }
  try {
    const salvo = localStorage.getItem(CACHE_PREFIX + chave);
    if (salvo) {
      const parsed = JSON.parse(salvo);
      memoriaCache.set(chave, parsed);
      return parsed as T;
    }
  } catch {
    // Modo anônimo, cota cheia ou parse inválido
  }
  return null;
}

export function gravarCache(chave: string, dados: unknown): void {
  memoriaCache.set(chave, dados);
  try {
    localStorage.setItem(CACHE_PREFIX + chave, JSON.stringify(dados));
  } catch (e) {
    if (e instanceof DOMException && (e.name === 'QuotaExceededError' || e.name === 'NS_ERROR_DOM_QUOTA_REACHED')) {
      console.warn('Prisma: Local Storage cheio. O cache desta requisição existirá apenas na memória até o fechamento da aba.');
    }
  }
}

/** Limpa todo o cache (memória e localStorage). Útil ao trocar de empresa ou regenerar base. */
export function limparCacheGeral(): void {
  inflight.clear();
  memoriaCache.clear();
  try {
    const chaves: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith(CACHE_PREFIX)) {
        chaves.push(key);
      }
    }
    chaves.forEach((k) => localStorage.removeItem(k));
  } catch {
    // Segurança
  }
}

/** Wrapper para facilitar o uso no client.ts */
export async function comCache<T>(
  chave: string,
  fetcher: () => Promise<T>,
  forcarNovo = false
): Promise<T> {
  if (!forcarNovo) {
    const emCache = lerCache<T>(chave);
    if (emCache) return emCache;
    const emVoo = inflight.get(chave);
    if (emVoo) return emVoo as Promise<T>;
  }
  const pendente = fetcher()
    .then((dados) => {
      gravarCache(chave, dados);
      return dados;
    })
    .finally(() => {
      inflight.delete(chave);
    });
  inflight.set(chave, pendente);
  return pendente;
}
