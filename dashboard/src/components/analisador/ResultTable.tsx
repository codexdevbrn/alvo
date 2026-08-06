import type { TabelaResultado } from '../../api/client';
import { formatCurrency, formatNumber, formatPercent } from '../../utils/formatters';

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

export function ResultTable({ tabela }: { tabela: TabelaResultado }) {
  if (tabela.colunas.length === 0) {
    return <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Sem dados para esta análise.</p>;
  }

  const numerica = tabela.colunas.map(
    (coluna, indiceColuna) => COLUNAS_MOEDA.has(coluna) || ehColunaPercentual(coluna)
      || tabela.linhas.slice(0, 20).some((linha) => typeof linha[indiceColuna] === 'number'),
  );

  return (
    <div className="analisador-tabela-wrap custom-scrollbar">
      <table className="analisador-tabela" style={{ tableLayout: 'auto', minWidth: 0 }}>
        <thead>
          <tr>
            {tabela.colunas.map((coluna, indiceColuna) => (
              <th key={coluna} style={{ textAlign: numerica[indiceColuna] ? 'right' : 'left' }}>
                {coluna}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {tabela.linhas.map((linha, indiceLinha) => (
            <tr key={indiceLinha}>
              {linha.map((valor, indiceColuna) => (
                <td
                  key={indiceColuna}
                  style={{ textAlign: numerica[indiceColuna] ? 'right' : 'left' }}
                >
                  {formatarValor(valor, tabela.colunas[indiceColuna])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
