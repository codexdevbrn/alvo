/**
 * Rótulos legíveis para nomes de coluna que vêm da base/motor.
 *
 * A base é export do BI: os nomes chegam como `NOME_FABRICANTE`, `descricao`,
 * `Receita_Ano_Anterior`. Mostrar isso cru na tela vaza detalhe de implementação
 * para quem só quer ler o número. Aqui é só apresentação — as chaves usadas em
 * lógica (moeda, percentual, semáforo, ordenação) continuam sendo o nome cru.
 */

/** Casos que a regra genérica não resolve bem. */
const ROTULOS: Record<string, string> = {
  descricao: 'Descrição',
  DESCRICAO_PRODUTO: 'Descrição',
  NOME_FABRICANTE: 'Fabricante',
  NOME_CLIENTE: 'Cliente',
  ID_LOJA: 'Loja',
  CODIGO_INTERNO_PRODUTO: 'Código interno',
  CODIGO_REFERENCIA_PRODUTO: 'Código de referência',
  // A base vem com o nome errado ("referêcia", sem o n). Corrigir na origem
  // renomearia a coluna e quebraria quem já usa a chave; aqui é só o rótulo.
  'Código de referêcia': 'Código de referência',
  QTD: 'Quantidade',
  Periodo_Mensal: 'Período mensal',
  Periodo_Trimestral: 'Período trimestral',
  Periodo_Semestral: 'Período semestral',
  Periodo_Anual: 'Período anual',
  Faixa_ABC: 'Faixa ABC',
  Desempenho_Pct: 'Desempenho',
  Percentual_Do_Total: '% do total',
  Percentual_Acumulado: '% acumulado',
  Percentual_Individual: '% individual',
  Ganho_Perda: 'Ganho / perda',
  Diferenca_QTD: 'Diferença de quantidade',
  Variacao_Percentual: 'Variação',
  Tendencia_Pct: 'Tendência',
  Periodos_Consecutivos_Em_Queda: 'Períodos em queda',
  Receita_Ano_Anterior: 'Receita ano anterior',
  Receita_Ano_Atual: 'Receita ano atual',
  Periodo_Ano_Anterior: 'Período ano anterior',
  Periodo_Ano_Atual: 'Período ano atual',
};

/** Nome de coluna → texto para o usuário. */
export function rotuloColuna(nome: string): string {
  const bruto = String(nome ?? '');
  if (!bruto) return '';
  const conhecido = ROTULOS[bruto];
  if (conhecido) return conhecido;

  const comEspacos = bruto.replace(/_/g, ' ').trim();
  // ALL_CAPS do BI (ex.: "ID_LOJA") viraria "ID LOJA" gritando na tela.
  const gritando = comEspacos === comEspacos.toUpperCase() && /[A-Z]{2,}/.test(comEspacos);
  const base = gritando ? comEspacos.toLowerCase() : comEspacos;
  const texto = base.charAt(0).toUpperCase() + base.slice(1);
  // "Pct" no fim é jargão de coluna, não informação: a formatação já mostra "%".
  return texto.replace(/\s+Pct$/i, '');
}

/** Dimensão de tempo — deve ser lida em ordem cronológica, nunca por valor. */
export function ehDimensaoTemporal(nome: string): boolean {
  return /^(ano|m[êe]s|periodo[_\s])/i.test(String(nome ?? '').trim());
}

const MESES_ORDEM: Record<string, number> = {
  janeiro: 1, fevereiro: 2, marco: 3, abril: 4, maio: 5, junho: 6,
  julho: 7, agosto: 8, setembro: 9, outubro: 10, novembro: 11, dezembro: 12,
};

/**
 * Chave de ordenação cronológica de um valor de dimensão temporal.
 *
 * A coluna `Mês` da base vem com o nome do mês ("Julho", "Março"), não com o
 * número: ordenar como texto daria Abril, Agosto, Dezembro… Já `Periodo_Mensal`
 * ("2026-03") e `Ano` (2026) ordenam direto.
 */
export function chaveOrdemTemporal(valor: unknown): number | string {
  if (typeof valor === 'number') return valor;
  const texto = String(valor ?? '').trim();
  // Faixa ̀-ͯ = diacríticos combinantes gerados pelo NFD.
  const semAcento = texto
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase();
  return MESES_ORDEM[semAcento] ?? texto;
}
