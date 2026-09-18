import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import type { QuedaQuantidadeDiagnostico } from '../../api/client';
import { formatCurrency, formatNumber, formatPercent } from '../../utils/formatters';

interface Props {
  queda: QuedaQuantidadeDiagnostico;
}

function TooltipQuantidade({ active, payload }: { active?: boolean; payload?: Array<{ payload?: { cliente: string; qtd_anterior: number; qtd_atual: number } }> }) {
  const data = payload?.[0]?.payload;
  if (!active || !data) return null;
  return (
    <div className="vendedores-chart-tooltip">
      <strong>{data.cliente}</strong>
      <dl>
        <div><dt>Antes</dt><dd>{formatNumber(data.qtd_anterior)} un.</dd></div>
        <div><dt>Agora</dt><dd>{formatNumber(data.qtd_atual)} un.</dd></div>
      </dl>
    </div>
  );
}

/** ATO III: quem compra o de sempre, mas em menos quantidade — antes→depois em
 *  unidades, não receita, porque é a dimensão que o Score de migração (faixa
 *  ABC) não cobre. Barras lado a lado: cinzento (antes) vs vermelho (agora),
 *  com nota abaixo mostrando produto crítico e perda em R$.
 *
 *  Produto crítico e perda em R$ ficam na nota, não em tooltip — é a regra do
 *  Ato III: nenhum valor só no hover. */
export function DumbbellQuantidade({ queda }: Props) {
  if (!queda.disponivel || queda.clientes.length === 0) {
    return <p className="analisador-hint">{queda.mensagem || 'Nenhuma queda de quantidade no período.'}</p>;
  }

  const maior = queda.clientes[0];
  const dadosGrafico = queda.clientes.map((cliente) => ({
    cliente: cliente.cliente,
    qtd_anterior: cliente.qtd_anterior ?? 0,
    qtd_atual: Math.max(0, cliente.qtd_atual ?? 0),
    variacao_pct: cliente.variacao_pct ?? 0,
    produto_critico: cliente.produto_critico,
    perda_receita: cliente.perda_receita ?? 0,
  }));

  return (
    <section className="glass-card glass-card-flat clientes-visao-card">
      <header className="clientes-visao-card-topo">
        <div>
          <h2>
            {maior.cliente} caiu {formatPercent(Math.abs(maior.variacao_pct ?? 0), 0)} em volume — puxado por{' '}
            {maior.produto_critico}
          </h2>
          <p>Quantidade comprada entre os dois últimos meses, ordenada pela maior redução.</p>
        </div>
      </header>

      <div className="vendedores-chart diagnostico-scatter-chart">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={dadosGrafico} margin={{ top: 8, right: 16, left: 4, bottom: 60 }} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis type="number" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis
              type="category" dataKey="cliente" width={120} tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
              axisLine={false} tickLine={false}
            />
            <Tooltip content={<TooltipQuantidade />} cursor={{ fill: 'var(--surface-1)' }} />
            <Bar dataKey="qtd_anterior" name="Mês anterior" fill="var(--text-muted)" radius={[0, 4, 4, 0]} />
            <Bar dataKey="qtd_atual" name="Mês atual" fill="var(--danger)" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <ul className="diagnostico-dumbbell-lista-legenda">
        {dadosGrafico.map((item) => (
          <li key={item.cliente}>
            <strong>{item.cliente}</strong>
            <p>
              {item.produto_critico} · {formatPercent(item.variacao_pct, 1)} em volume
              {item.perda_receita < 0 && <> · −{formatCurrency(Math.abs(item.perda_receita))} em receita</>}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
