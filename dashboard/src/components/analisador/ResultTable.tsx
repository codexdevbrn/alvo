import type { ReactNode } from 'react';
import { ArrowDown, ArrowUp } from 'lucide-react';
import type { TabelaResultado } from '../../api/client';
import { formatCurrency, formatNumber, formatPercent } from '../../utils/formatters';
import { rotuloColuna } from '../../utils/rotulosColuna';

export type OrdenacaoTabela = { coluna: string; direcao: 'asc' | 'desc' };

// Colunas em R$ nos relatórios do motor (mesmo critério de
// COLUNAS_MOEDA_POR_ANALISE em backend/exportar_excel.py, unificado por nome
// de coluna — os nomes são únicos entre análises).
const COLUNAS_MOEDA = new Set([
  'Receita',
  'Receita_Periodo_Anterior',
  'Receita_Periodo_Atual',
  'Receita_Ano_Anterior',
  'Receita_Ano_Atual',
  'Ganho_Perda',
  'Receita_Ultimo_Periodo',
  'Receita_Primeiro_Periodo',
  'Reducao_Receita',
  'Poder_De_Compra',
  'Renuncia',
  'Renuncia_Acumulada',
  'Perda_Receita',
  'Receita_Sob_Risco',
  'Total_Ano_Atual',
  'Receita Acumulada 11 Meses',
  'Preço_médio_de_venda',
  'Preço_médio_cmv',
  'Último_custo',
]);

function ehColunaPercentual(coluna: string) {
  return coluna.includes('Percentual') || coluna.endsWith('_Pct');
}

// ==========================================
// Semáforo das colunas
// ==========================================
// Duas famílias, porque o sinal não quer dizer a mesma coisa em todas:
//
// DELTA  — variação de verdade: positivo é bom (verde ↑), negativo é ruim
//          (vermelho ↓), zero é neutro.
// PERDA  — magnitude de perda já registrada como número POSITIVO (renúncia,
//          erosão, receita sob risco). Aqui "positivo" é ruim: pinta vermelho ↓
//          quando há valor, e nunca verde — senão uma coluna inteira de prejuízo
//          apareceria como ganho.
//
// Colunas fora das duas listas (participação, receita, quantidade, preço) ficam
// neutras de propósito: cor sem significado vira ruído e a tabela deixa de
// destacar o que importa.
const COLUNAS_DELTA = new Set([
  'Desempenho_Pct',
  'Ganho_Perda',
  'Variacao_Percentual',
  'Variacao_Global_Periodo_Pct',
  'Tendencia_Pct',
]);

const COLUNAS_PERDA = new Set([
  'Reducao_Receita',
  'Reducao_Percentual',
  'Renuncia',
  'Renuncia_Acumulada',
  'Renuncia_Percentual',
  'Perda_Receita',
  'Receita_Sob_Risco',
  'Impacto_Financeiro_Churn',
  'Maior_Retracao_Individual_Pct',
]);

/** Texto que já diz a direção por extenso (coluna `Direcao` da migração de grupo). */
const TEXTO_DIRECAO: Record<string, 'pos' | 'neg'> = {
  Subiu: 'pos',
  Desceu: 'neg',
};

type Tom = 'pos' | 'neg' | null;

function tomDaCelula(valor: unknown, coluna: string): Tom {
  if (typeof valor === 'string') {
    return TEXTO_DIRECAO[valor.trim()] ?? null;
  }
  if (typeof valor !== 'number' || !Number.isFinite(valor) || valor === 0) return null;
  if (COLUNAS_DELTA.has(coluna)) return valor > 0 ? 'pos' : 'neg';
  if (COLUNAS_PERDA.has(coluna)) return valor > 0 ? 'neg' : null;
  return null;
}

function formatarValor(valor: unknown, coluna: string): string {
  if (valor === null || valor === undefined) return '—';
  if (typeof valor === 'boolean') return valor ? 'Sim' : 'Não';
  if (typeof valor === 'number') {
    if (ehColunaPercentual(coluna)) return formatPercent(valor);
    if (COLUNAS_MOEDA.has(coluna)) return formatCurrency(valor);
    if (Number.isInteger(valor)) return formatNumber(valor);
    return valor.toLocaleString('pt-BR', { maximumFractionDigits: 2 });
  }
  return String(valor);
}

// Análises que mostram uma faixa de totais ACIMA da tabela — espelho de
// COLUNAS_TOTALIZAVEIS_POR_ANALISE em backend/exportar_excel.py. O total não é
// linha de dados de propósito: dentro da tabela ele entraria na ordenação e no
// filtro, e duplicaria qualquer soma da coluna.
const COLUNAS_TOTALIZAVEIS: Record<string, string[]> = {
  comparativo_receita: ['Receita_Ano_Anterior', 'Receita_Ano_Atual', 'Ganho_Perda'],
};

// Colunas que repetem o MESMO valor em toda linha (o período comparado, por
// exemplo): viram informação da faixa do topo em vez de coluna. Dentro da
// tabela elas só gastam largura repetindo o mesmo texto centenas de vezes.
// Só afeta a tela — a exportação continua trazendo a coluna.
const COLUNAS_INFORMACIONAIS: Record<string, string[]> = {
  comparativo_receita: ['Periodo_Ano_Anterior', 'Periodo_Ano_Atual'],
};

/** Valor único da coluna, ou null se ela varia entre as linhas (aí continua
 *  sendo dado e permanece na tabela). */
function valorConstante(tabela: TabelaResultado, coluna: string): string | null {
  const indice = tabela.colunas.indexOf(coluna);
  if (indice < 0 || tabela.linhas.length === 0) return null;
  const primeiro = tabela.linhas[0][indice];
  if (primeiro === null || primeiro === undefined) return null;
  const todosIguais = tabela.linhas.every((linha) => linha[indice] === primeiro);
  return todosIguais ? formatarValor(primeiro, coluna) : null;
}

function informacionais(tabela: TabelaResultado, chave?: string) {
  const colunas = chave ? COLUNAS_INFORMACIONAIS[chave] : undefined;
  if (!colunas) return [];
  return colunas
    .map((coluna) => ({ coluna, valor: valorConstante(tabela, coluna) }))
    .filter((item): item is { coluna: string; valor: string } => item.valor !== null);
}

function somarColuna(tabela: TabelaResultado, coluna: string): number | null {
  const indice = tabela.colunas.indexOf(coluna);
  if (indice < 0) return null;
  return tabela.linhas.reduce<number>((soma, linha) => {
    const valor = linha[indice];
    return soma + (typeof valor === 'number' && Number.isFinite(valor) ? valor : 0);
  }, 0);
}

function FaixaTotais({
  tabela,
  chave,
  info,
}: {
  tabela: TabelaResultado;
  chave?: string;
  info: Array<{ coluna: string; valor: string }>;
}) {
  const colunas = chave ? COLUNAS_TOTALIZAVEIS[chave] : undefined;
  if (tabela.linhas.length === 0) return null;

  const itens = (colunas ?? [])
    .map((coluna) => ({ coluna, valor: somarColuna(tabela, coluna) }))
    .filter((item): item is { coluna: string; valor: number } => item.valor !== null);
  if (itens.length === 0 && info.length === 0) return null;

  const anterior = itens.find((i) => i.coluna === 'Receita_Ano_Anterior')?.valor ?? 0;
  const atual = itens.find((i) => i.coluna === 'Receita_Ano_Atual')?.valor ?? 0;
  const desempenho = anterior > 0 ? ((atual - anterior) / anterior) * 100 : null;

  return (
    <div className="analisador-faixa-totais">
      {info.map((item) => (
        <span key={item.coluna} className="analisador-faixa-totais-item is-info">
          <span>{rotuloColuna(item.coluna)}</span>
          <strong>{item.valor}</strong>
        </span>
      ))}
      {itens.length > 0 && (
        <>
          <span className="analisador-faixa-totais-rotulo">Totais</span>
          {itens.map((item) => (
            <span key={item.coluna} className="analisador-faixa-totais-item">
              <span>{rotuloColuna(item.coluna)}</span>
              <strong><Celula valor={item.valor} coluna={item.coluna} /></strong>
            </span>
          ))}
          <span className="analisador-faixa-totais-item">
            <span>Desempenho</span>
            <strong>
              {desempenho === null
                ? '—'
                : <Celula valor={desempenho} coluna="Desempenho_Pct" />}
            </strong>
          </span>
        </>
      )}
    </div>
  );
}

/** Célula da tabela: neutra, ou com cor + seta quando a coluna tem direção. */
function Celula({ valor, coluna }: { valor: unknown; coluna: string }) {
  const texto = formatarValor(valor, coluna);
  const tom = tomDaCelula(valor, coluna);
  if (!tom) return <>{texto}</>;
  return (
    <span className={`analisador-celula-delta is-${tom}`}>
      <span aria-hidden="true" className="analisador-celula-delta-seta">
        {tom === 'pos' ? '▲' : '▼'}
      </span>
      {texto}
    </span>
  );
}

export function ResultTable({
  tabela,
  chave,
  ordenacao,
  onOrdenar,
  faixaExtra,
}: {
  tabela: TabelaResultado;
  chave?: string;
  /** Coluna/direção atual — só para desenhar a seta no cabeçalho. */
  ordenacao?: OrdenacaoTabela | null;
  /** Quando presente, o cabeçalho vira botão de ordenar. Ausente = tabela estática
   *  (é o caso dos relatórios do catálogo, que já vêm ordenados pelo motor). */
  onOrdenar?: (coluna: string) => void;
  /** Faixa própria acima da tabela (ex.: totais das tabelas dinâmicas). */
  faixaExtra?: ReactNode;
}) {
  if (tabela.colunas.length === 0) {
    return <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Sem dados para esta análise.</p>;
  }

  const numerica = tabela.colunas.map(
    (coluna, indiceColuna) => COLUNAS_MOEDA.has(coluna) || ehColunaPercentual(coluna)
      || tabela.linhas.slice(0, 20).some((linha) => typeof linha[indiceColuna] === 'number'),
  );

  const info = informacionais(tabela, chave);
  const ocultas = new Set(info.map((item) => tabela.colunas.indexOf(item.coluna)));
  const visiveis = tabela.colunas
    .map((_, indice) => indice)
    .filter((indice) => !ocultas.has(indice));

  return (
    <>
      {faixaExtra}
      <FaixaTotais tabela={tabela} chave={chave} info={info} />
      <div className="analisador-tabela-wrap custom-scrollbar">
      <table className="analisador-tabela" style={{ tableLayout: 'auto', minWidth: 0 }}>
        <thead>
          <tr>
            {visiveis.map((indiceColuna) => {
              const nome = tabela.colunas[indiceColuna];
              const ativa = ordenacao?.coluna === nome;
              return (
                <th
                  key={nome}
                  style={{ textAlign: numerica[indiceColuna] ? 'right' : 'left' }}
                  title={nome}
                >
                  {onOrdenar ? (
                    <button
                      type="button"
                      className={`analisador-tabela-ordenar${ativa ? ' is-ativa' : ''}`}
                      style={{ justifyContent: numerica[indiceColuna] ? 'flex-end' : 'flex-start' }}
                      onClick={() => onOrdenar(nome)}
                      title={`Ordenar por ${rotuloColuna(nome)}`}
                    >
                      {rotuloColuna(nome)}
                      {ativa && (ordenacao?.direcao === 'asc'
                        ? <ArrowUp size={11} aria-hidden="true" />
                        : <ArrowDown size={11} aria-hidden="true" />)}
                    </button>
                  ) : rotuloColuna(nome)}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {tabela.linhas.map((linha, indiceLinha) => (
            <tr key={indiceLinha}>
              {visiveis.map((indiceColuna) => (
                <td
                  key={indiceColuna}
                  style={{ textAlign: numerica[indiceColuna] ? 'right' : 'left' }}
                >
                  <Celula valor={linha[indiceColuna]} coluna={tabela.colunas[indiceColuna]} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        </table>
      </div>
    </>
  );
}
