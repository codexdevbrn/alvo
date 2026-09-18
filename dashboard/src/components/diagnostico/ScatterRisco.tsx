import { useState } from 'react';
import {
  Cell, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from 'recharts';
import type { ClienteRisco, RiscoDiagnostico } from '../../api/client';
import { formatCompacto, formatCurrency, formatNumber, formatPercent } from '../../utils/formatters';

interface Props {
  risco: RiscoDiagnostico;
}

/** Mesma paleta categórica usada em Clientes (`ClientesPotencialCompra`) para as
 *  faixas ABC — ouro forte no Grupo 1, esfriando até o cinza de "Demais". */
const CORES_FAIXA: Record<string, string> = {
  'Grupo 1': '#dabb6c', 'Grupo 2': '#c2a45f', 'Grupo 3': '#8e8a7d', Demais: '#5d5d66',
};
const COR_FAIXA_PADRAO = '#43434b';

function TooltipRisco({ active, payload }: { active?: boolean; payload?: Array<{ payload?: ClienteRisco }> }) {
  const cliente = payload?.[0]?.payload;
  if (!active || !cliente) return null;
  return (
    <div className="vendedores-chart-tooltip">
      <strong>{cliente.cliente}</strong>
      <dl>
        <div><dt>Antes</dt><dd>{formatCurrency(cliente.receita_anterior ?? 0)}</dd></div>
        <div><dt>Agora</dt><dd>{formatCurrency(cliente.receita_atual ?? 0)}</dd></div>
        <div><dt>Perda</dt><dd>{formatCurrency(cliente.perda_rs ?? 0)}</dd></div>
      </dl>
    </div>
  );
}

/** ATO III: quem está sumindo, e quanto isso vale — scatter (redução % × R$ em
 *  jogo) porque a tabela ordena por um eixo só e esconde o cruzamento: o
 *  cliente grande que caiu pouco pesa tanto quanto o pequeno que caiu tudo.
 *
 *  Clicar num ponto abre o detalhe abaixo — nome, faixa e se já parou de
 *  comprar — sem precisar de outro request: o payload já tem tudo. */
export function ScatterRisco({ risco }: Props) {
  const [selecionado, setSelecionado] = useState<string | null>(null);

  if (!risco.disponivel || risco.clientes.length === 0) {
    return <p className="analisador-hint">{risco.mensagem || 'Nenhum cliente com receita em queda no período.'}</p>;
  }

  const perdaTotal = risco.clientes.reduce((soma, cliente) => soma + (cliente.perda_rs ?? 0), 0);
  const pararam = risco.clientes.filter((cliente) => cliente.parou_de_comprar).length;
  const cliente = risco.clientes.find((item) => item.cliente === selecionado) ?? null;

  const pontos = risco.clientes.map((item) => ({ ...item, x: Math.abs(item.variacao_pct ?? 0), y: item.perda_rs ?? 0 }));
  const medianaX = [...pontos.map((p) => p.x)].sort((a, b) => a - b)[Math.floor(pontos.length / 2)] ?? 0;

  return (
    <section className="glass-card glass-card-flat clientes-visao-card">
      <header className="clientes-visao-card-topo">
        <div>
          <h2>{formatNumber(risco.clientes.length)} clientes com receita em queda somam {formatCompacto(perdaTotal, true)}</h2>
          <p>
            Redução de receita entre os dois últimos meses. Cada ponto é 1 cliente — canto
            superior direito é quem caiu mais forte e mais perdeu em R$.
            {pararam > 0 && ` ${formatNumber(pararam)} já pararam de comprar.`}
          </p>
        </div>
      </header>

      <div className="vendedores-chart diagnostico-scatter-chart">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
            <XAxis
              type="number" dataKey="x" domain={[0, 'auto']} unit="%"
              tick={{ fill: 'var(--text-muted)', fontSize: 11 }} axisLine={false} tickLine={false}
              label={{ value: 'Queda %', position: 'insideBottom', offset: -4, fill: 'var(--text-muted)', fontSize: 11 }}
            />
            <YAxis
              type="number" dataKey="y"
              tick={{ fill: 'var(--text-muted)', fontSize: 11 }} axisLine={false} tickLine={false} width={64}
              tickFormatter={(valor: number) => formatCompacto(valor, true)}
            />
            <ZAxis range={[60, 60]} />
            <ReferenceLine x={medianaX} stroke="var(--border-strong)" strokeDasharray="3 3" />
            <Tooltip content={<TooltipRisco />} cursor={{ strokeDasharray: '3 3' }} />
            <Scatter
              data={pontos}
              onClick={(ponto: unknown) => {
                const item = (ponto as { cliente?: string } | undefined)?.cliente;
                if (item) setSelecionado((atual) => (atual === item ? null : item));
              }}
              cursor="pointer"
              isAnimationActive={false}
            >
              {pontos.map((ponto) => (
                <Cell
                  key={ponto.cliente}
                  fill={CORES_FAIXA[ponto.faixa] ?? COR_FAIXA_PADRAO}
                  fillOpacity={selecionado == null || selecionado === ponto.cliente ? 0.9 : 0.25}
                  stroke={selecionado === ponto.cliente ? 'var(--accent)' : 'none'}
                  strokeWidth={2}
                />
              ))}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </div>

      {cliente && (
        <div className="diagnostico-drill">
          <strong title={cliente.cliente}>{cliente.cliente}</strong>
          <span>{cliente.faixa}</span>
          <span>{formatCurrency(cliente.receita_anterior ?? 0)} → {formatCurrency(cliente.receita_atual ?? 0)}</span>
          <span className="is-queda">−{formatCurrency(cliente.perda_rs ?? 0)} ({formatPercent(cliente.variacao_pct ?? 0, 1)})</span>
          {cliente.parou_de_comprar && <span className="diagnostico-drill-tag">Parou de comprar</span>}
        </div>
      )}

      {risco.composicao.length > 0 && (
        <>
          <p className="diagnostico-nota-eixo">Perda por faixa ABC:</p>
          <div className="diagnostico-composicao-barra" role="img" aria-label="Perda por faixa ABC">
            {risco.composicao.map((item) => {
              const totalComposicao = risco.composicao.reduce((soma, faixa) => soma + (faixa.perda_rs ?? 0), 0);
              const largura = totalComposicao > 0 ? ((item.perda_rs ?? 0) / totalComposicao) * 100 : 0;
              return (
                <span
                  key={item.faixa}
                  style={{ width: `${largura}%`, background: CORES_FAIXA[item.faixa] ?? COR_FAIXA_PADRAO }}
                  title={`${item.faixa}: ${formatCurrency(item.perda_rs ?? 0)} (${formatNumber(item.clientes)} clientes)`}
                />
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}
