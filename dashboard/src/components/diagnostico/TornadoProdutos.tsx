import { Bar, BarChart, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { LinhaTornado } from '../../api/client';
import { formatCompacto, formatCurrency, formatPercent } from '../../utils/formatters';

interface Props {
  linhas: LinhaTornado[];
  rotuloAnterior: string | null;
  rotuloPeriodo: string | null;
}

function TooltipTornado({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload?: LinhaTornado }>;
}) {
  const linha = payload?.[0]?.payload;
  if (!active || !linha) return null;
  return (
    <div className="vendedores-chart-tooltip">
      <strong>{linha.descricao}</strong>
      <dl>
        <div><dt>Antes</dt><dd>{formatCurrency(linha.receita_anterior ?? 0)}</dd></div>
        <div><dt>Agora</dt><dd>{formatCurrency(linha.receita_atual ?? 0)}</dd></div>
        <div>
          <dt>Efeito</dt>
          <dd>{linha.delta_receita > 0 ? '+' : ''}{formatCurrency(linha.delta_receita)}</dd>
        </div>
        {linha.variacao_pct != null && (
          <div><dt>Variação</dt><dd>{formatPercent(linha.variacao_pct, 1)}</dd></div>
        )}
      </dl>
    </div>
  );
}

/** ATO II: o que puxou o mês para cima e para baixo, em R$.
 *
 *  Barra divergente em torno do zero: quem perdeu fica à esquerda, quem ganhou à
 *  direita. A posição em relação ao zero é o encoding principal — a cor só
 *  reforça, porque verde e vermelho colapsam sob daltonismo.
 *
 *  O eixo é R$ e não %, de propósito: o boletim do Analisador ranqueia por
 *  variação percentual e deixa um item de R$ 10 → R$ 100 na frente de outro que
 *  perdeu R$ 50 mil. Aqui a pergunta é impacto financeiro. */
export function TornadoProdutos({ linhas, rotuloAnterior, rotuloPeriodo }: Props) {
  if (linhas.length === 0) {
    return <p className="analisador-hint">Sem período anterior para comparar.</p>;
  }

  const maiorQueda = linhas[linhas.length - 1];
  const quedaTotal = linhas
    .filter((linha) => linha.delta_receita < 0)
    .reduce((soma, linha) => soma + linha.delta_receita, 0);
  const parteDaQueda = quedaTotal < 0 ? (maiorQueda.delta_receita / quedaTotal) * 100 : null;

  return (
    <section className="glass-card glass-card-flat clientes-visao-card">
      <header className="clientes-visao-card-topo">
        <div>
          <h2>
            {maiorQueda.descricao} responde por {parteDaQueda == null ? '—' : formatPercent(parteDaQueda, 0)}{' '}
            da queda do mês
          </h2>
          <p>Efeito de cada produto em R$, de {rotuloAnterior} para {rotuloPeriodo}.</p>
        </div>
        {/* Par do chip da cascata: aqui a régua é o mês anterior, lá é o ano. */}
        <span className="diagnostico-base-chip">vs {rotuloAnterior} · mês anterior</span>
      </header>

      <div className="vendedores-chart diagnostico-tornado-chart">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={linhas}
            layout="vertical"
            margin={{ top: 4, right: 12, left: 4, bottom: 4 }}
            barCategoryGap={4}
          >
            <XAxis
              type="number"
              tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(valor: number) => formatCompacto(valor, true)}
            />
            <YAxis
              type="category"
              dataKey="descricao"
              tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={150}
              tickFormatter={(valor: string) => (valor.length > 16 ? `${valor.slice(0, 15)}…` : valor)}
            />
            <Tooltip content={<TooltipTornado />} cursor={{ fill: 'var(--surface-2)' }} />
            <ReferenceLine x={0} stroke="var(--border-strong)" />
            <Bar dataKey="delta_receita" radius={3} isAnimationActive={false}>
              {linhas.map((linha) => (
                <Cell
                  key={linha.descricao}
                  fill={linha.delta_receita >= 0 ? 'var(--success)' : 'var(--danger)'}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
