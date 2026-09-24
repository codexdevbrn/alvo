export type AbaPrecificacao = 'pos' | 'historico';

export const ABAS_PRECIFICACAO: AbaPrecificacao[] = ['pos', 'historico'];

/** Aba da tela Precificação, lida de `?aba=`. Fica na URL (e não em estado da
 *  página) porque o AppShell também precisa dela: a topbar da Pós precificação
 *  (rodada, itens, visão, loja) só aparece nessa aba. Sem parâmetro ou com valor
 *  desconhecido, abre na Pós precificação. */
export function abaPrecificacao(search: string): AbaPrecificacao {
  const aba = new URLSearchParams(search).get('aba');
  return ABAS_PRECIFICACAO.includes(aba as AbaPrecificacao) ? (aba as AbaPrecificacao) : 'pos';
}
