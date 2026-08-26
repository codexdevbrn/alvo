/**
 * Lojas selecionadas, global e por empresa.
 *
 * Mesmo desenho de `empresaSelecionada`: localStorage como fonte de verdade e um
 * CustomEvent para acordar quem já está montado na mesma aba — sem contexto
 * global, porque o seletor vive na sidebar e as telas são irmãs, não filhas dele.
 *
 * A chave é por empresa (`prisma_loja_<empresa>`). Empresa nova começa em "todas
 * as lojas", e voltar para a anterior devolve o escopo que estava em uso.
 *
 * Lista vazia = todas as lojas. Qualquer combinação é válida, e é ela que define
 * o escopo em que `config.json` e `clientes_tags.json` são lidos e gravados.
 */
export const EVENTO_LOJA = 'prisma-loja-change';

/** Contrato do backend: uma loja viaja pelo nome puro; várias, em JSON prefixado. */
const PREFIXO_ESCOPO_MULTILOJAS = '@lojas:';

function chave(empresa: string): string {
  return `prisma_loja_${empresa}`;
}

/** Lojas em uso na empresa. Lista vazia = todas. */
export function lerLojas(empresa: string): string[] {
  if (!empresa) return [];
  let salvo: string | null = null;
  try {
    salvo = localStorage.getItem(chave(empresa));
  } catch {
    return [];
  }
  if (!salvo) return [];
  try {
    const valores = JSON.parse(salvo) as unknown;
    if (Array.isArray(valores)) {
      return valores.map(String).map((item) => item.trim()).filter(Boolean);
    }
  } catch {
    // Valor gravado por versão anterior era o nome puro de uma única loja.
  }
  return [salvo];
}

/** Persiste e avisa as telas montadas. Lista vazia = todas as lojas. */
export function selecionarLojasGlobal(empresa: string, lojas: string[]) {
  const unicas = [...new Set(lojas.map((item) => item.trim()).filter(Boolean))];
  try {
    if (empresa && unicas.length > 0) localStorage.setItem(chave(empresa), JSON.stringify(unicas));
    else if (empresa) localStorage.removeItem(chave(empresa));
  } catch {
    /* Modo privado pode bloquear localStorage; o evento ainda sincroniza a aba. */
  }
  window.dispatchEvent(new CustomEvent(EVENTO_LOJA, { detail: { empresa, lojas: unicas } }));
}

/**
 * Esquece as lojas de uma empresa. Usado quando o que estava gravado não existe
 * mais na base — renomear loja na fonte deixaria a tela filtrando por um nome
 * morto, e o backend responde 400 para loja inexistente.
 */
export function limparLojas(empresa: string) {
  selecionarLojasGlobal(empresa, []);
}

/**
 * Escopo no formato que as APIs esperam: `null` = todas as lojas, nome puro para
 * uma, JSON prefixado para várias. Ordenado para a mesma seleção sempre gerar a
 * mesma chave — é ela que nomeia o escopo de config e tags no disco.
 */
export function codificarEscopoLojas(lojas: string[]): string | null {
  const unicas = [...new Set(lojas.map((item) => item.trim()).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, 'pt-BR'));
  if (unicas.length === 0) return null;
  if (unicas.length === 1) return unicas[0];
  return `${PREFIXO_ESCOPO_MULTILOJAS}${JSON.stringify(unicas)}`;
}

/** Rótulo curto do escopo, para cabeçalhos e mensagens. */
export function rotuloEscopoLojas(lojas: string[]): string {
  if (lojas.length === 0) return 'Todas as lojas';
  if (lojas.length === 1) return lojas[0];
  return `${lojas.length} lojas`;
}
