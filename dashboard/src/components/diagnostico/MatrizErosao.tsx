import { useState } from 'react';
import type { MatrizErosaoDiagnostico } from '../../api/client';
import { formatCurrency, formatNumber, formatPercent } from '../../utils/formatters';
import { TituloDiagnostico } from './TituloDiagnostico';

interface Props {
  matriz: MatrizErosaoDiagnostico;
}

type ModoCelula = 'valor' | 'percentual';

/** ATO III: cruzamento cliente × produto — coluna inteira escura é produto
 *  abandonado por vários clientes ao mesmo tempo, o padrão que a lista de
 *  erosão (ordenada por linha) não deixa ver. Grade CSS, mesmo padrão de
 *  `MatrizStreak`: é pequena (até 10 × 8) e o valor precisa ser lido por cima
 *  da célula, não só apontado com o mouse.
 *
 *  Rampa sequencial sobre `--danger`, não `--viz-seq` (dourado): aqui só
 *  existe uma direção (perda), mas dourado é a cor de destaque/bom no resto
 *  do app — usar essa rampa pra "quanto pior" lia como o oposto do que é.
 *  Mesma base de cor que `MatrizStreak` usa pra queda, teto em 60% de mistura
 *  pra manter o texto branco legível até na célula de maior perda. */
export function MatrizErosao({ matriz }: Props) {
  const [modo, setModo] = useState<ModoCelula>('valor');

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
          <TituloDiagnostico
            texto={`${produtoTopo} abandonado`}
            destaque={`${formatNumber(clientesDoTopo)} cliente(s)`}
            variante="queda"
          />
          <p>Redução de receita por cliente e produto, entre os dois últimos meses.</p>
        </div>
      </header>

      <div className="periodo-segmented diagnostico-streak-segmented" role="radiogroup" aria-label="Como mostrar a célula">
        <button
          type="button" role="radio" aria-checked={modo === 'valor'}
          className={`periodo-segmented-btn${modo === 'valor' ? ' is-active' : ''}`}
          onClick={() => setModo('valor')}
        >
          R$
        </button>
        <button
          type="button" role="radio" aria-checked={modo === 'percentual'}
          className={`periodo-segmented-btn${modo === 'percentual' ? ' is-active' : ''}`}
          onClick={() => setModo('percentual')}
        >
          %
        </button>
      </div>

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
                : `color-mix(in srgb, var(--danger) ${Math.round(intensidade * 60)}%, var(--surface-1))`;
              const receitaAnterior = celula.receita_anterior;
              const receitaAtual = perda == null || receitaAnterior == null ? null : receitaAnterior - perda;
              const titulo = perda == null
                ? `${celula.produto}: sem queda`
                : `${celula.produto}: ${formatCurrency(receitaAnterior ?? 0)} → ${formatCurrency(receitaAtual ?? 0)} · ${formatPercent(celula.variacao_pct ?? 0, 1)}`;
              const texto = perda == null
                ? '—'
                : modo === 'valor'
                  ? formatCurrency(perda).replace('R$', '').trim()
                  : formatPercent(celula.variacao_pct ?? 0, 0);
              return (
                <div
                  key={`${cliente.cliente}-${celula.produto}`}
                  className="diagnostico-streak-celula"
                  style={{ background: cor }}
                  title={titulo}
                >
                  {texto}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </section>
  );
}
