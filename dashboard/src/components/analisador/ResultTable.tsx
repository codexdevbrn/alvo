import type { TabelaResultado } from '../../api/client';

export function ResultTable({ tabela }: { tabela: TabelaResultado }) {
  if (tabela.colunas.length === 0) {
    return <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Sem dados para esta análise.</p>;
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
        <thead>
          <tr>
            {tabela.colunas.map((coluna) => (
              <th
                key={coluna}
                style={{
                  textAlign: 'left', padding: '0.5rem 0.7rem', background: 'rgba(99,102,241,0.15)',
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
                <td key={indiceColuna} style={{ padding: '0.5rem 0.7rem', whiteSpace: 'nowrap', color: 'var(--text-secondary)' }}>
                  {valor === null || valor === undefined ? '—' : String(valor)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
