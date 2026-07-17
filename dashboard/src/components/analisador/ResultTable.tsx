import type { TabelaResultado } from '../../api/client';
import { formatCurrency, formatNumber, formatPercent } from '../../utils/formatters';

// Colunas em R$ nos relatórios do motor (mesmo critério de
// COLUNAS_MOEDA_POR_ANALISE em backend/exportar_excel.py, unificado por nome
// de coluna — os nomes são únicos entre análises).
const COLUNAS_MOEDA = new Set([
  'Receita',
  'Receita_Periodo_Anterior',
  'Receita_Periodo_Atual',
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
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
        <thead>
          <tr>
            {tabela.colunas.map((coluna, indiceColuna) => (
              <th
                key={coluna}
                style={{
                  textAlign: numerica[indiceColuna] ? 'right' : 'left',
                  padding: '0.5rem 0.7rem', background: 'rgba(99,102,241,0.15)',
                  color: 'var(--text-primary)', whiteSpace: 'nowrap', position: 'sticky', top: 0,
                }}
              >
                {coluna}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {tabela.linhas.map((linha, indiceLinha) => (
            <tr key={indiceLinha} style={{ borderBottom: '1px solid var(--border)' }}>
              {linha.map((valor, indiceColuna) => (
                <td
                  key={indiceColuna}
                  style={{
                    padding: '0.5rem 0.7rem', whiteSpace: 'nowrap', color: 'var(--text-secondary)',
                    textAlign: numerica[indiceColuna] ? 'right' : 'left',
                  }}
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
