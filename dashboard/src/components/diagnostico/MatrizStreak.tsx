import { useState } from 'react';
import type { CriterioStreak, ProdutoStreak, StreakDiagnostico } from '../../api/client';
import { formatCompacto, formatCurrency, formatPercent } from '../../utils/formatters';

interface Props {
  streak: StreakDiagnostico;
}

const PILULAS: Array<{ valor: CriterioStreak; rotulo: string; titulo: string }> = [
  { valor: 'receita', rotulo: 'Maior participação', titulo: 'Quem mais pesa na receita agora, sem olhar tendência' },
  { valor: 'perda', rotulo: 'Maior perda', titulo: 'Em queda consecutiva agora, ordenado por R$ perdido' },
  { valor: 'ganho', rotulo: 'Maior ganho', titulo: 'Em alta consecutiva agora, ordenado por R$ ganho' },
];

function legenda(produto: ProdutoStreak, criterio: CriterioStreak): string {
  if (criterio === 'receita') return `${formatPercent(produto.participacao_pct ?? 0, 1)} da receita`;
  if (criterio === 'ganho') return `${produto.periodos_consecutivos} em alta`;
  return `${produto.periodos_consecutivos} em queda`;
}

function titulo(produto: ProdutoStreak, criterio: CriterioStreak): string {
  const valor = formatCurrency(Math.abs(produto.valor ?? 0));
  if (criterio === 'receita') {
    return `${produto.descricao} responde por ${formatPercent(produto.participacao_pct ?? 0, 1)} da receita do período`;
  }
  if (criterio === 'ganho') {
    return `${produto.descricao} subiu ${produto.periodos_consecutivos} período(s) seguidos, ${valor} ganhos`;
  }
  return `${produto.descricao} caiu ${produto.periodos_consecutivos} período(s) seguidos, ${valor} perdidos`;
}

/** ATO II: quais produtos vêm caindo mês a mês, sem interrupção — grade CSS,
 *  não SVG, porque a matriz é pequena (até 10 × 6) e cada célula precisa ser
 *  lida por cima do texto, não só apontada com o mouse.
 *
 *  Três pílulas escolhem QUEM entra na matriz — maior perda, maior ganho ou
 *  maior participação na receita — sem voltar ao servidor: as três listas já
 *  vêm prontas no mesmo payload (`painel_diagnostico._streak`).
 *
 *  Cor por célula reaproveita a mesma linguagem de Cascata/Tornado (verde
 *  ganhou, vermelho caiu) em vez da rampa sequencial padrão de heatmap do
 *  projeto — as quatro peças do Ato II precisam ler como um sistema só, e
 *  aqui o sinal é direção (subiu/desceu), não magnitude sequencial. */
export function MatrizStreak({ streak }: Props) {
  const [criterio, setCriterio] = useState<CriterioStreak>('perda');
  const produtos = streak[criterio];

  return (
    <section className="glass-card glass-card-flat clientes-visao-card">
      <header className="clientes-visao-card-topo">
        <div>
          <h2>{produtos.length > 0 ? titulo(produtos[0], criterio) : 'Sem produto nessa classificação'}</h2>
          <p>Receita de cada produto, mês a mês.</p>
        </div>
        {streak.periodos.length > 0 && (
          <span className="diagnostico-base-chip">
            {streak.periodos[0]} → {streak.periodos[streak.periodos.length - 1]} · mês a mês
          </span>
        )}
      </header>

      <div className="periodo-segmented diagnostico-streak-segmented" role="radiogroup" aria-label="Classificação da matriz">
        {PILULAS.map((pilula) => (
          <button
            key={pilula.valor}
            type="button"
            role="radio"
            aria-checked={criterio === pilula.valor}
            title={pilula.titulo}
            className={`periodo-segmented-btn${criterio === pilula.valor ? ' is-active' : ''}`}
            onClick={() => setCriterio(pilula.valor)}
          >
            {pilula.rotulo}
          </button>
        ))}
      </div>

      {produtos.length === 0 ? (
        <p className="analisador-hint">Nenhum produto nessa classificação no período.</p>
      ) : (
        <>
          <div
            className="diagnostico-streak-grid"
            style={{ gridTemplateColumns: `minmax(0, 12rem) repeat(${streak.periodos.length}, minmax(0, 1fr))` }}
          >
            <div className="diagnostico-streak-cabecalho diagnostico-streak-produto" aria-hidden="true" />
            {streak.periodos.map((periodo) => (
              <div key={periodo} className="diagnostico-streak-cabecalho">{periodo}</div>
            ))}

            {produtos.map((produto) => (
              <div className="diagnostico-streak-linha" key={produto.descricao}>
                <div className="diagnostico-streak-produto" title={produto.descricao}>
                  <span>{produto.descricao}</span>
                  <em>{legenda(produto, criterio)}</em>
                </div>
                {produto.celulas.map((celula, indice) => {
                  const variacao = celula.variacao_pct;
                  const semComparacao = variacao == null;
                  const cor = variacao == null
                    ? undefined
                    : variacao === 0
                      ? 'var(--surface-3)'
                      : variacao > 0
                        ? `color-mix(in srgb, var(--success) ${Math.min(Math.abs(variacao), 60)}%, var(--surface-1))`
                        : `color-mix(in srgb, var(--danger) ${Math.min(Math.abs(variacao), 60)}%, var(--surface-1))`;
                  const titulo_ = variacao == null
                    ? `${formatCurrency(celula.receita ?? 0)} · sem período anterior na janela`
                    : `${formatCurrency(celula.receita ?? 0)} · ${formatPercent(variacao, 1)}`;
                  return (
                    <div
                      key={`${produto.descricao}-${indice}`}
                      className="diagnostico-streak-celula"
                      style={{ background: cor }}
                      title={titulo_}
                    >
                      {semComparacao ? '—' : formatPercent(celula.variacao_pct ?? 0, 0)}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
          <p className="diagnostico-nota-eixo">
            {produtos[0].receita_atual != null &&
              `Receita atual de ${produtos[0].descricao}: ${formatCompacto(produtos[0].receita_atual, true)}. `}
            Passe o mouse sobre a célula para ver a receita exata.
          </p>
        </>
      )}
    </section>
  );
}
