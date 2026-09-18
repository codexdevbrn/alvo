import type { MatrizErosaoDiagnostico } from '../../api/client';
import { formatCurrency, formatNumber } from '../../utils/formatters';

interface Props {
  matriz: MatrizErosaoDiagnostico;
}

/** ATO III: cruzamento cliente × produto — coluna inteira escura é produto
 *  abandonado por vários clientes ao mesmo tempo, o padrão que a lista de
 *  erosão (ordenada por linha) não deixa ver. Grade CSS, mesmo padrão de
 *  `MatrizStreak`: é pequena (até 10 × 8) e o valor precisa ser lido por cima
 *  da célula, não só apontado com o mouse.
 *
 *  Rampa sequencial (`--viz-seq`), não a divergente de Cascata/Tornado: aqui
 *  só existe uma direção (perda), a pergunta é magnitude, não sinal. */
export function MatrizErosao({ matriz }: Props) {
  if (!matriz.disponivel || matriz.produtos.length === 0) {
    return <p className="analisador-hint">{matriz.mensagem || 'Nenhuma erosão de produto no período.'}</p>;
  }

  const maiorPerda = Math.max(
    1,
    ...matriz.clientes.flatMap((cliente) => cliente.celulas.map((celula) => celula.perda_rs ?? 0)),
  );
  const produtoTopo = matriz.produtos[0];
  const clientesDoTopo = matriz.clientes.filter((cliente) =>
    cliente.celulas.some((celula) => celula.produto === produtoTopo && celula.perda_rs != null),
  ).length;

  return (
    <section className="glass-card glass-card-flat clientes-visao-card">
      <header className="clientes-visao-card-topo">
        <div>
          <h2>{produtoTopo} foi abandonado por {formatNumber(clientesDoTopo)} cliente(s) ao mesmo tempo</h2>
          <p>Redução de receita por cliente e produto, entre os dois últimos meses.</p>
        </div>
      </header>

      <div
        className="diagnostico-streak-grid diagnostico-erosao-grid"
        style={{ gridTemplateColumns: `minmax(0, 10rem) repeat(${matriz.produtos.length}, minmax(0, 1fr))` }}
      >
        <div className="diagnostico-streak-cabecalho diagnostico-streak-produto" aria-hidden="true" />
        {matriz.produtos.map((produto) => (
          <div key={produto} className="diagnostico-streak-cabecalho" title={produto}>
            {produto.length > 14 ? `${produto.slice(0, 13)}…` : produto}
          </div>
        ))}

        {matriz.clientes.map((cliente) => (
          <div className="diagnostico-streak-linha" key={cliente.cliente}>
            <div className="diagnostico-streak-produto" title={cliente.cliente}>
              <span>{cliente.cliente}</span>
              <em>−{formatCurrency(cliente.perda_total ?? 0)}</em>
            </div>
            {cliente.celulas.map((celula) => {
              const perda = celula.perda_rs;
              const intensidade = perda == null ? 0 : Math.min(Math.abs(perda) / maiorPerda, 1);
              const cor = perda == null
                ? 'var(--surface-1)'
                : `color-mix(in srgb, var(--viz-seq-5) ${Math.round(intensidade * 100)}%, var(--surface-1))`;
              return (
                <div
                  key={`${cliente.cliente}-${celula.produto}`}
                  className="diagnostico-streak-celula"
                  style={{ background: cor }}
                  title={perda == null ? `${celula.produto}: sem queda` : `${celula.produto}: −${formatCurrency(perda)}`}
                >
                  {perda == null ? '—' : formatCurrency(perda).replace('R$', '').trim()}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </section>
  );
}
