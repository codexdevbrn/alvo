import { useMemo } from 'react';
import {
  CartesianGrid,
  Cell,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts';
import type { ItemCoberturaEstoque, StatusCoberturaEstoque } from '../../api/client';
import { formatCurrency, formatPercent } from '../../utils/formatters';

interface Props {
  itens: ItemCoberturaEstoque[];
  coberturaAlvo?: number;
  coberturaExcesso?: number;
  coberturaRuptura?: number;
}

type PontoGrafico = {
  vendaPlot: number;
  coberturaPlot: number;
  capitalPlot: number;
  item: ItemCoberturaEstoque;
};

const CORES: Record<StatusCoberturaEstoque, string> = {
  normal: '#8195a0',
  rupture: '#ec8171',
  out_of_stock: '#ec8171',
  negative: '#ec8171',
  stalled: '#e2913f',
  excess: '#e2913f',
  no_sales: '#e2913f',
};

function formatarNumero(valor: number, casas = 0): string {
  return Number(valor || 0).toLocaleString('pt-BR', {
    minimumFractionDigits: 0,
    maximumFractionDigits: casas,
  });
}

function TooltipEstoque({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload?: PontoGrafico }>;
}) {
  const ponto = payload?.[0]?.payload;
  if (!active || !ponto) return null;
  const item = ponto.item;
  return (
    <div className="estoque-chart-tooltip">
      <strong>{item.nome}</strong>
      <span>{item.fabricante} · SKU {item.sku}</span>
      <dl>
        <div><dt>Estoque</dt><dd>{formatarNumero(item.estoque)}</dd></div>
        <div><dt>Venda média/mês</dt><dd>{formatarNumero(item.venda_media, 1)}</dd></div>
        <div><dt>Cobertura</dt><dd>{item.cobertura == null ? 'Sem giro' : `${formatarNumero(item.cobertura, 1)} meses`}</dd></div>
        <div><dt>Valor em estoque</dt><dd>{formatCurrency(item.valor_estoque)}</dd></div>
        <div><dt>Variação recente</dt><dd>{item.variacao_pct == null ? '—' : formatPercent(item.variacao_pct, 1)}</dd></div>
      </dl>
    </div>
  );
}

/** Mapa logarítmico: velocidade no eixo X, meses de cobertura no eixo Y. */
export function EstoqueCoberturaChart({
  itens,
  coberturaAlvo = 3,
  coberturaExcesso = 6,
  coberturaRuptura = 0.5,
}: Props) {
  const pontos = useMemo<PontoGrafico[]>(() => itens.map((item) => ({
    // Escala log não aceita zero. Sem giro fica encostado à esquerda; tooltip
    // continua mostrando valor real zero.
    vendaPlot: Math.max(0.1, item.venda_media),
    coberturaPlot: item.cobertura == null
      ? 300
      : Math.min(300, Math.max(0.02, item.cobertura)),
    capitalPlot: Math.max(1, item.valor_estoque),
    item,
  })), [itens]);

  if (!pontos.length) {
    return <p className="estoque-chart-vazio">Nenhum produto válido para exibir.</p>;
  }

  const maxVenda = Math.max(1, ...pontos.map((ponto) => ponto.vendaPlot));
  const maxCobertura = Math.min(300, Math.max(12, ...pontos.map((ponto) => ponto.coberturaPlot)));
  const maxCapital = Math.max(1, ...pontos.map((ponto) => ponto.capitalPlot));

  return (
    <div className="estoque-chart-wrap" role="img" aria-label="Cobertura de estoque contra venda média mensal">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 22, right: 28, bottom: 32, left: 18 }}>
          <CartesianGrid stroke="rgba(255,255,255,0.08)" strokeDasharray="3 3" />
          <ReferenceArea y1={coberturaExcesso} y2={maxCobertura} fill="#e2913f" fillOpacity={0.08} />
          <ReferenceArea y1={0.02} y2={coberturaRuptura} fill="#ec8171" fillOpacity={0.1} />
          <ReferenceLine y={coberturaExcesso} stroke="#e2913f" strokeDasharray="4 4" label={{ value: `${coberturaExcesso} meses`, fill: '#e2913f', fontSize: 10 }} />
          <ReferenceLine y={coberturaAlvo} stroke="#8195a0" strokeDasharray="4 4" label={{ value: `alvo ${coberturaAlvo} meses`, fill: '#8195a0', fontSize: 10 }} />
          <ReferenceLine y={coberturaRuptura} stroke="#ec8171" strokeDasharray="4 4" label={{ value: `${coberturaRuptura} mês`, fill: '#ec8171', fontSize: 10 }} />
          <XAxis
            type="number"
            dataKey="vendaPlot"
            name="Venda média/mês"
            scale="log"
            domain={[0.1, Math.max(1, maxVenda * 1.2)]}
            allowDataOverflow
            tick={{ fill: 'var(--text-secondary)', fontSize: 10 }}
            tickFormatter={(valor) => formatarNumero(Number(valor), Number(valor) < 1 ? 1 : 0)}
            label={{ value: 'venda média por mês (un.) — escala log', position: 'insideBottom', offset: -18, fill: 'var(--text-secondary)', fontSize: 11 }}
          />
          <YAxis
            type="number"
            dataKey="coberturaPlot"
            name="Cobertura"
            scale="log"
            domain={[0.02, maxCobertura]}
            allowDataOverflow
            width={62}
            tick={{ fill: 'var(--text-secondary)', fontSize: 10 }}
            tickFormatter={(valor) => formatarNumero(Number(valor), Number(valor) < 1 ? 2 : 0)}
            label={{ value: 'cobertura em meses — escala log', angle: -90, position: 'insideLeft', fill: 'var(--text-secondary)', fontSize: 11 }}
          />
          <ZAxis type="number" dataKey="capitalPlot" domain={[1, maxCapital]} range={[34, 520]} />
          <Tooltip content={<TooltipEstoque />} cursor={{ stroke: 'rgba(255,255,255,0.18)', strokeDasharray: '3 3' }} />
          <Scatter data={pontos} isAnimationActive={false}>
            {pontos.map((ponto) => (
              <Cell
                key={`${ponto.item.codigo_interno}-${ponto.item.sku}`}
                fill={CORES[ponto.item.status]}
                fillOpacity={0.72}
                stroke="var(--bg-card)"
                strokeWidth={1}
              />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
      <div className="estoque-chart-legenda" aria-label="Legenda do gráfico">
        <span><i className="is-perigo" />Risco de ruptura</span>
        <span><i className="is-atencao" />Excesso, sem giro ou perda de força</span>
        <span><i />Dentro do esperado</span>
        <small>Tamanho da bolha = capital em estoque</small>
      </div>
    </div>
  );
}
