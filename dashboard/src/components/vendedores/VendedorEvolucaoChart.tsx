import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { formatCompacto, formatCurrency } from '../../utils/formatters';
import type { PontoSerieVendedor } from '../../api/client';

type Props = {
  pontos: PontoSerieVendedor[];
  media: number;
};

function TooltipEvolucao({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload?: PontoSerieVendedor }>;
}) {
  const ponto = payload?.[0]?.payload;
  if (!active || !ponto) return null;
  return (
    <div className="vendedores-chart-tooltip">
      <strong>{ponto.rotulo}</strong>
      <dl>
        <div><dt>Receita</dt><dd>{formatCurrency(ponto.valor)}</dd></div>
      </dl>
    </div>
  );
}

/** Caminhar de vendas do vendedor: linha mês a mês, régua da média dos 6
 *  anteriores. Mesma paleta do HistoryChart (tokens, ouro, sem vidro). */
export function VendedorEvolucaoChart({ pontos, media }: Props) {
  if (!pontos || pontos.length === 0) {
    return <p className="analisador-hint">Sem movimento mensal neste recorte.</p>;
  }
  return (
    <div className="vendedores-chart" style={{ height: 240 }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={pontos} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="rotulo"
            tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tickFormatter={(v) => formatCompacto(Number(v), true)}
            tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={56}
          />
          <Tooltip cursor={{ stroke: 'var(--border-strong)' }} content={<TooltipEvolucao />} />
          {media > 0 && (
            <ReferenceLine
              y={media}
              stroke="var(--text-muted)"
              strokeDasharray="4 4"
              label={{
                value: `Média ${formatCompacto(media, true)}`,
                position: 'insideTopRight',
                fill: 'var(--text-muted)',
                fontSize: 11,
              }}
            />
          )}
          <Line
            type="monotone"
            dataKey="valor"
            name="Receita"
            stroke="var(--accent)"
            strokeWidth={2}
            dot={{ r: 3, fill: 'var(--accent)', strokeWidth: 0 }}
            activeDot={{ r: 5, fill: 'var(--accent)', stroke: 'var(--accent-contrast)', strokeWidth: 1 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
