import {
  Area,
  CartesianGrid,
  ComposedChart,
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

/** Receita mês a mês do vendedor, com a régua da média dos 6 meses anteriores
 *  como referência — mesmo recorte que a tabela compara ponto a ponto. */
export function VendedorEvolucaoChart({ pontos, media }: Props) {
  if (!pontos || pontos.length === 0) return null;
  return (
    <div className="vendedores-chart" style={{ height: 220 }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={pontos} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
          <defs>
            <linearGradient id="vendedorEvolucaoFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.35} />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
            </linearGradient>
          </defs>
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
          <Area
            type="monotone"
            dataKey="valor"
            name="Receita"
            stroke="var(--accent)"
            strokeWidth={2}
            fill="url(#vendedorEvolucaoFill)"
            dot={{ r: 3, fill: 'var(--accent)', strokeWidth: 0 }}
            activeDot={{ r: 5 }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
