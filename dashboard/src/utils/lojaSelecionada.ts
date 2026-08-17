/**
 * Loja selecionada, global e por empresa.
 *
 * Mesmo desenho de `empresaSelecionada`: localStorage como fonte de verdade e um
 * CustomEvent para acordar quem já está montado na mesma aba — sem contexto
 * global, porque o seletor vive na sidebar e as telas são irmãs, não filhas dele.
 *
 * A chave é por empresa (`prisma_loja_<empresa>`). Empresa nova começa em "todas
 * as lojas", e voltar para a anterior devolve o escopo que estava em uso — que é
 * o que o Analisador já fazia com `analisador_loja_<empresa>`.
 *
 * Uma loja por vez: `''` = todas. O backend aceita escopo com várias lojas
 * (`@lojas:[...]`), e arquivos gravados assim continuam válidos no disco, mas
 * nenhuma tela produz mais esse escopo.
 */
export const EVENTO_LOJA = 'prisma-loja-change';

function chave(empresa: string): string {
  return `prisma_loja_${empresa}`;
}

/** Loja em uso na empresa, ou '' para todas. */
export function lerLoja(empresa: string): string {
  if (!empresa) return '';
  try {
    return localStorage.getItem(chave(empresa)) || '';
  } catch {
    return '';
  }
}

/** Persiste e avisa as telas montadas. `loja` vazia = todas. */
export function selecionarLojaGlobal(empresa: string, loja: string) {
  try {
    if (empresa && loja) localStorage.setItem(chave(empresa), loja);
    else if (empresa) localStorage.removeItem(chave(empresa));
  } catch {
    /* Modo privado pode bloquear localStorage; o evento ainda sincroniza a aba. */
  }
  window.dispatchEvent(new CustomEvent(EVENTO_LOJA, { detail: { empresa, loja } }));
}

/**
 * Esquece a loja de uma empresa. Usado quando a loja gravada não existe mais na
 * base — renomear loja na fonte deixaria a tela filtrando por um nome morto, e o
 * backend responde 400 para loja inexistente.
 */
export function limparLoja(empresa: string) {
  selecionarLojaGlobal(empresa, '');
}
