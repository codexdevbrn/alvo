import type { RodadaPrecificacao } from '../api/client';

/**
 * Rodada da Pós precificação, por empresa. O seletor vive na topbar
 * (`TopoPosPrecificacaoRodadaSelect`) e a lista de rodadas só existe depois que
 * `PosPrecificacaoVisao` recebe a resposta — irmãos na árvore, então a visão
 * publica aqui o que carregou e o topo publica o que foi escolhido.
 *
 * Só em memória, de propósito: rodada salva em localStorage sobreviveria a um
 * dump novo sem aquele dia, e a tela abriria vazia.
 */
export const EVENTO_RODADA_PRECIFICACAO = 'prisma-pos-precificacao-rodada-change';

export type RodadasPublicadas = {
  rodadas: RodadaPrecificacao[];
  /** Rodada que a resposta atual usou — a mais recente quando nada foi escolhido. */
  ativa: string | null;
  /** Recalculando depois de uma troca de rodada. */
  ocupado: boolean;
};

const escolhidas: Record<string, string> = {};
const publicadas: Record<string, RodadasPublicadas> = {};
let versao = 0;

function avisar() {
  versao += 1;
  window.dispatchEvent(new CustomEvent(EVENTO_RODADA_PRECIFICACAO));
}

export function versaoRodadas(): number {
  return versao;
}

export function lerRodadaEscolhida(empresa: string): string | null {
  return escolhidas[empresa] ?? null;
}

export function escolherRodada(empresa: string, dia: string) {
  if (escolhidas[empresa] === dia) return;
  escolhidas[empresa] = dia;
  avisar();
}

export function lerRodadasPublicadas(empresa: string): RodadasPublicadas | null {
  return publicadas[empresa] ?? null;
}

export function publicarRodadas(empresa: string, estado: RodadasPublicadas) {
  const atual = publicadas[empresa];
  const chave = (e: RodadasPublicadas) => `${e.ativa}|${e.ocupado}|${e.rodadas.map((r) => `${r.dia}:${r.pares}`).join(',')}`;
  if (atual && chave(atual) === chave(estado)) return;
  publicadas[empresa] = estado;
  avisar();
}
