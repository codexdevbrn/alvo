import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { formatCompacto, formatCurrency } from '../../utils/formatters';
import { COR_ANO_ANTERIOR, COR_ANO_RECENTE } from '../../utils/coresAno';

export type PontoComparativo = {
  nome: string;
  atual: number;
  media: number;
};

type Props = {
  pontos: PontoComparativo[];
  /** `colunas` = poucos vendedores; `barras` = nomes longos (cliente/produto). */
  modo: 'colunas' | 'barras';
  altura?: number;
  ativo?: string | null;
  onSelect?: (nome: string) => void;
};

function encurtar(nome: string, max: number): string {
  const texto = nome.trim();
  if (texto.length <= max) return texto;
  return `${texto.slice(0, max - 1)}…`;
}

function TooltipComparativo({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload?: PontoComparativo }>;
}) {
  const ponto = payload?.[0]?.payload;
  if (!active || !ponto) return null;
  return (
    <div className="vendedores-chart-tooltip">
      <strong>{ponto.nome}</strong>
      <dl>
        <div><dt>Mês</dt><dd>{formatCurrency(ponto.atual)}</dd></div>
        <div><dt>Média 6 meses</dt><dd>{formatCurrency(ponto.media)}</dd></div>
      </dl>
    </div>
  );
}

function nomeDoClique(ponto: unknown): string {
  if (!ponto || typeof ponto !== 'object') return '';
  if ('nome' in ponto && ponto.nome != null) return String(ponto.nome);
  if ('payload' in ponto) {
    const payload = (ponto as { payload?: { nome?: unknown } }).payload;
    if (payload?.nome != null) return String(payload.nome);
  }
  return '';
}

function opacidade(nome: string, ativo: string | null): number {
  if (!ativo) return 1;
  return nome === ativo ? 1 : 0.35;
}

/** Barras lado a lado: mês de referência contra a média dos 6 anteriores. */
export function VendedoresComparativoChart({
  pontos,
  modo,
  altura,
  ativo = null,
  onSelect,
}: Props) {
  if (!pontos || pontos.length === 0) return null;
  const horizontal = modo === 'barras';
  const alto = altura ?? (horizontal ? Math.max(160, pontos.length * 28) : 220);

  return (
    <div className="vendedores-chart" style={{ height: alto }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={pontos}
          layout={horizontal ? 'vertical' : 'horizontal'}
          margin={horizontal
            ? { top: 4, right: 12, left: 4, bottom: 4 }
            : { top: 8, right: 8, left: 0, bottom: 4 }}
          barCategoryGap={horizontal ? '18%' : '24%'}
        >
          <CartesianGrid
            stroke="var(--border)"
            strokeDasharray="3 3"
            horizontal={!horizontal}
            vertical={horizontal}
          />
          {horizontal ? (
            <>
              <XAxis
                type="number"
                tickFormatter={(v) => formatCompacto(Number(v), true)}
                tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                type="category"
                dataKey="nome"
                width={140}
                tickFormatter={(v) => encurtar(String(v), 20)}
                tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
            </>
          ) : (
            <>
              <XAxis
                dataKey="nome"
                tickFormatter={(v) => encurtar(String(v), 14)}
                tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                interval={0}
              />
              <YAxis
                tickFormatter={(v) => formatCompacto(Number(v), true)}
                tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={56}
              />
            </>
          )}
          <Tooltip
            cursor={{ fill: 'var(--surface-2)' }}
            content={<TooltipComparativo />}
          />
          <Bar
            dataKey="media"
            name="Média 6 meses"
            fill={COR_ANO_ANTERIOR}
            radius={horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]}
            maxBarSize={28}
            onClick={(ponto) => {
              const nome = nomeDoClique(ponto);
              if (nome) onSelect?.(nome);
            }}
            cursor={onSelect ? 'pointer' : undefined}
          >
            {pontos.map((ponto) => (
              <Cell key={`media-${ponto.nome}`} fillOpacity={opacidade(ponto.nome, ativo)} />
            ))}
          </Bar>
          <Bar
            dataKey="atual"
            name="Mês"
            fill={COR_ANO_RECENTE}
            radius={horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]}
            maxBarSize={28}
            onClick={(ponto) => {
              const nome = nomeDoClique(ponto);
              if (nome) onSelect?.(nome);
            }}
            cursor={onSelect ? 'pointer' : undefined}
          >
            {pontos.map((ponto) => (
              <Cell key={`atual-${ponto.nome}`} fillOpacity={opacidade(ponto.nome, ativo)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
