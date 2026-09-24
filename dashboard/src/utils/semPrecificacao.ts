/** A empresa ainda não tem rodada de precificação no PRICE (o backend responde
 *  404 com esta frase). Não é erro: é o estado normal de quem não foi
 *  precificado ainda, e as abas mostram um aviso em vez de uma falha. */
export const MENSAGEM_SEM_PRECIFICACAO = 'ainda não tem precificação';

export function ehSemPrecificacao(erro: string | null | undefined): boolean {
  return !!erro && erro.toLowerCase().includes(MENSAGEM_SEM_PRECIFICACAO);
}
