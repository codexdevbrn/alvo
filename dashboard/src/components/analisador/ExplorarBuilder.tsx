import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, Download } from 'lucide-react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts';
import {
  explorarAgregar,
  obterExplorarSchema,
  type ExplorarAgregado,
  type ExplorarSchema,
} from '../../api/client';
import { baixarCsv, baixarSvgComoPng, baixarXlsx } from '../../utils/exportDownload';
import { formatCurrency, formatNumber } from '../../utils/formatters';
import { ResultTable } from './ResultTable';

type Modo = 'grafico' | 'tabela';
type TipoGrafico =
  | 'barras'
  | 'linhas'
  | 'area'
  | 'pizza'
  | 'histograma'
  | 'dispersao'
  | 'boxplot';

type Props = {
  empresa: string | null;
  /** null/omitido = todas as lojas */
  loja?: string | null;
  modo: Modo;
};

const METRICAS_PADRAO = ['Receita', 'QTD', 'Clientes'];
const CORES_SERIE = ['#dabb6c', '#6f8cc4', '#68818d', '#cc6300', '#e8cc86', '#8aa3ad'];
const TIPOS_GRAFICO: { id: TipoGrafico; rotulo: string }[] = [
  { id: 'barras', rotulo: 'Barras' },
  { id: 'linhas', rotulo: 'Linhas' },
  { id: 'area', rotulo: 'Área' },
  { id: 'pizza', rotulo: 'Pizza' },
  { id: 'histograma', rotulo: 'Histograma' },
  { id: 'dispersao', rotulo: 'Dispersão' },
  { id: 'boxplot', rotulo: 'Boxplot' },
];

const ROTULOS_METRICA: Record<string, string> = {
  Receita: 'Receita',
  QTD: 'Quantidade',
  Clientes: 'Clientes',
  frequencia: 'Frequência',
  max: 'Máximo',
  min: 'Mínimo',
  q1: '1º quartil',
  median: 'Mediana',
  q3: '3º quartil',
  n: 'Observações',
  x: 'Eixo X',
  y: 'Eixo Y',
};

function rotuloSerie(chave: string): string {
  return ROTULOS_METRICA[chave] ?? chave.replace(/_/g, ' ');
}

function modoVizDeTipo(tipo: TipoGrafico): 'agregar' | 'histograma' | 'boxplot' | 'dispersao' {
  if (tipo === 'histograma') return 'histograma';
  if (tipo === 'boxplot') return 'boxplot';
  if (tipo === 'dispersao') return 'dispersao';
  return 'agregar';
}

type LegendPayloadItem = {
  value?: string;
  color?: string;
  dataKey?: string | number;
  payload?: { strokeDasharray?: string | number };
};

function ExplorarLegend({
  payload,
  vertical,
}: {
  payload?: readonly LegendPayloadItem[];
  vertical?: boolean;
}) {
  if (!payload?.length) return null;
  const itens = payload.filter((p) => p.value && p.value !== 'max');
  if (itens.length === 0) return null;
  return (
    <ul
      className={`analisador-explorar-legend${vertical ? ' analisador-explorar-legend--vertical' : ''}`}
    >
      {itens.map((entry, i) => (
        <li key={`${entry.value}-${i}`} className="analisador-explorar-legend-item">
          <span
            className="analisador-explorar-legend-swatch"
            style={{ background: entry.color || CORES_SERIE[i % CORES_SERIE.length] }}
          />
          <span className="analisador-explorar-legend-label">
            {rotuloSerie(String(entry.value))}
          </span>
        </li>
      ))}
    </ul>
  );
}

const LEGENDA_PROPS = {
  content: <ExplorarLegend />,
  verticalAlign: 'top' as const,
  align: 'right' as const,
  wrapperStyle: { paddingBottom: 8 },
};

/** Shape customizado: whiskers + caixa IQR + mediana. */
function BoxPlotShape(props: {
  x?: number;
  width?: number;
  height?: number;
  y?: number;
  payload?: {
    min?: number;
    q1?: number;
    median?: number;
    q3?: number;
    max?: number;
  };
}) {
  const { x = 0, width = 0, y = 0, height = 0, payload } = props;
  if (!payload || !payload.max || payload.max <= 0) return null;
  const maxV = Number(payload.max) || 1;
  const toY = (v: number) => y + height * (1 - Number(v) / maxV);
  const cx = x + width / 2;
  const boxW = Math.max(width * 0.55, 10);
  const yMax = toY(Number(payload.max));
  const yMin = toY(Number(payload.min));
  const yQ3 = toY(Number(payload.q3));
  const yQ1 = toY(Number(payload.q1));
  const yMed = toY(Number(payload.median));
  return (
    <g>
      <line x1={cx} x2={cx} y1={yMax} y2={yMin} stroke="#94a3b8" strokeWidth={1.5} />
      <line x1={cx - boxW / 2} x2={cx + boxW / 2} y1={yMax} y2={yMax} stroke="#94a3b8" strokeWidth={1.5} />
      <line x1={cx - boxW / 2} x2={cx + boxW / 2} y1={yMin} y2={yMin} stroke="#94a3b8" strokeWidth={1.5} />
      <rect
        x={cx - boxW / 2}
        y={Math.min(yQ3, yQ1)}
        width={boxW}
        height={Math.max(Math.abs(yQ1 - yQ3), 1)}
        fill="#dabb6c"
        fillOpacity={0.75}
        stroke="#e8cc86"
      />
      <line x1={cx - boxW / 2} x2={cx + boxW / 2} y1={yMed} y2={yMed} stroke="#fff" strokeWidth={2} />
    </g>
  );
}

export function ExplorarBuilder({ empresa, loja = null, modo }: Props) {
  const [schema, setSchema] = useState<ExplorarSchema | null>(null);
  const [dimensoes, setDimensoes] = useState<string[]>(['Periodo_Mensal']);
  const [metricas, setMetricas] = useState<string[]>(['Receita']);
  const [aplicarGrupos, setAplicarGrupos] = useState(true);
  const [limite, setLimite] = useState(50);
  const [tipoGrafico, setTipoGrafico] = useState<TipoGrafico>('barras');
  const [bins, setBins] = useState(20);
  const [resultado, setResultado] = useState<ExplorarAgregado | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [exportando, setExportando] = useState(false);
  const [menuExportAberto, setMenuExportAberto] = useState(false);
  const menuExportRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuExportAberto) return;
    const fechar = (e: MouseEvent) => {
      if (menuExportRef.current && !menuExportRef.current.contains(e.target as Node)) {
        setMenuExportAberto(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuExportAberto(false);
    };
    document.addEventListener('mousedown', fechar);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', fechar);
      document.removeEventListener('keydown', onKey);
    };
  }, [menuExportAberto]);

  useEffect(() => {
    setMenuExportAberto(false);
  }, [modo]);

  useEffect(() => {
    const controller = new AbortController();
    setSchema(null);
    setResultado(null);
    obterExplorarSchema(empresa, loja, controller.signal)
      .then((s) => {
        setSchema(s);
        const dims = s.dimensoes.includes('Periodo_Mensal')
          ? ['Periodo_Mensal']
          : s.dimensoes.slice(0, 1);
        setDimensoes(dims);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        setErro(err instanceof Error ? err.message : 'Falha ao carregar schema.');
      });
    return () => {
      controller.abort();
    };
  }, [empresa, loja]);

  useEffect(() => {
    if (!schema) return;
    const controller = new AbortController();
    const handle = window.setTimeout(() => {
      setCarregando(true);
      setErro(null);
      const modoViz = modo === 'grafico' ? modoVizDeTipo(tipoGrafico) : 'agregar';
      explorarAgregar({
        empresa,
        loja,
        dimensoes,
        metricas,
        aplicar_grupos: aplicarGrupos,
        limite,
        ordenar_por: metricas[0] ?? null,
        ordem: 'desc',
        modo_viz: modoViz,
        bins,
      }, controller.signal)
        .then((dados) => {
          setResultado(dados);
        })
        .catch((err) => {
          if (controller.signal.aborted) return;
          setResultado(null);
          setErro(err instanceof Error ? err.message : 'Falha ao agregar.');
        })
        .finally(() => {
          if (!controller.signal.aborted) setCarregando(false);
        });
    }, 500);
    return () => {
      controller.abort();
      window.clearTimeout(handle);
    };
  }, [schema, empresa, loja, dimensoes, metricas, aplicarGrupos, limite, tipoGrafico, bins, modo]);

  const limites = useMemo(() => {
    if (modo === 'tabela') return { dim: 4, met: 4 };
    switch (tipoGrafico) {
      case 'pizza':
      case 'histograma':
      case 'boxplot':
        return { dim: 1, met: 1 };
      case 'dispersao':
        return { dim: 1, met: 2 };
      default:
        return { dim: 4, met: 4 };
    }
  }, [modo, tipoGrafico]);

  useEffect(() => {
    setDimensoes((d) => (d.length > limites.dim ? d.slice(0, Math.max(1, limites.dim)) : d));
    setMetricas((m) => (m.length > limites.met ? m.slice(0, Math.max(1, limites.met)) : m));
  }, [limites]);

  const toggleDim = (col: string) => {
    setDimensoes((atual) => {
      if (atual.includes(col)) {
        const next = atual.filter((c) => c !== col);
        return next.length ? next : atual;
      }
      if (limites.dim === 1) return [col];
      if (atual.length >= limites.dim) return atual;
      return [...atual, col];
    });
  };

  const toggleMet = (m: string) => {
    setMetricas((atual) => {
      if (atual.includes(m)) {
        const next = atual.filter((x) => x !== m);
        return next.length ? next : atual;
      }
      if (limites.met === 1) return [m];
      if (atual.length >= limites.met) return atual;
      return [...atual, m];
    });
  };

  const chartData = useMemo(() => {
    if (!resultado || resultado.linhas.length === 0) return [];
    const cols = resultado.colunas;
    const modoViz = resultado.modo_viz ?? 'agregar';

    if (modoViz === 'histograma') {
      const iBin = cols.indexOf('bin');
      const iFreq = cols.indexOf('frequencia');
      const iFaixa = cols.indexOf('faixa');
      return resultado.linhas.map((linha) => ({
        name: String(linha[iBin] ?? ''),
        frequencia: Number(linha[iFreq] ?? 0),
        faixa: iFaixa >= 0 ? String(linha[iFaixa] ?? '') : String(linha[iBin] ?? ''),
      }));
    }

    if (modoViz === 'dispersao') {
      const iNome = cols.indexOf('nome');
      const iX = cols.indexOf('x');
      const iY = cols.indexOf('y');
      return resultado.linhas.map((linha) => ({
        name: String(linha[iNome] ?? ''),
        x: Number(linha[iX] ?? 0),
        y: Number(linha[iY] ?? 0),
      }));
    }

    if (modoViz === 'boxplot') {
      const dim = resultado.dimensoes[0];
      const iNome = cols.indexOf(dim);
      const idx = (c: string) => cols.indexOf(c);
      return resultado.linhas.map((linha) => ({
        name: String(linha[iNome] ?? ''),
        min: Number(linha[idx('min')] ?? 0),
        q1: Number(linha[idx('q1')] ?? 0),
        median: Number(linha[idx('median')] ?? 0),
        q3: Number(linha[idx('q3')] ?? 0),
        max: Number(linha[idx('max')] ?? 0),
        n: Number(linha[idx('n')] ?? 0),
      }));
    }

    const dimCols = resultado.dimensoes;
    const metCols = resultado.metricas;
    return resultado.linhas.map((linha) => {
      const nome = dimCols.map((d) => String(linha[cols.indexOf(d)] ?? '')).join(' · ') || 'Total';
      const ponto: Record<string, string | number> = { name: nome };
      for (const m of metCols) {
        const i = cols.indexOf(m);
        ponto[m] = Number(linha[i] ?? 0);
      }
      return ponto;
    });
  }, [resultado]);

  const tabela = useMemo(() => {
    if (!resultado) return { colunas: [] as string[], linhas: [] as unknown[][] };
    return { colunas: resultado.colunas, linhas: resultado.linhas };
  }, [resultado]);

  const formatTick = (v: number) => {
    const m = metricas[0];
    if (m === 'Receita' || tipoGrafico === 'boxplot') return formatCurrency(v);
    return formatNumber(v);
  };

  const tooltipFormatter = (value: unknown, name: unknown) => {
    const n = Number(value ?? 0);
    const label = rotuloSerie(String(name ?? ''));
    const chave = String(name ?? '');
    if (
      chave === 'Receita' ||
      ['min', 'q1', 'median', 'q3', 'max'].includes(chave) ||
      metricas[0] === 'Receita'
    ) {
      if (chave === 'frequencia') return [formatNumber(n), label];
      return [formatCurrency(n), label];
    }
    return [formatNumber(n), label];
  };

  const tooltipStyle = {
    background: '#0f172a',
    border: '1px solid rgba(255,255,255,0.12)',
    borderRadius: 8,
  } as const;

  const renderGrafico = () => {
    if (chartData.length === 0) {
      return <p className="analisador-hint">Sem dados para o gráfico.</p>;
    }

    if (tipoGrafico === 'histograma') {
      const n = chartData.length;
      const tickInterval = n > 16 ? 2 : n > 10 ? 1 : 0;
      return (
        <div className="analisador-explorar-chart">
          <ResponsiveContainer width="100%" height={360}>
            <BarChart data={chartData} margin={{ top: 36, right: 16, left: 8, bottom: 28 }} barCategoryGap="8%">
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
              <XAxis
                dataKey="name"
                tick={{ fill: 'rgba(255,255,255,0.7)', fontSize: 11 }}
                interval={tickInterval}
                angle={0}
                textAnchor="middle"
                height={36}
                tickMargin={8}
                label={{
                  value: resultado?.escala === 'log' ? 'Valor (escala log · início do bin)' : 'Valor (início do bin)',
                  position: 'insideBottom',
                  offset: -2,
                  fill: 'rgba(255,255,255,0.45)',
                  fontSize: 11,
                }}
              />
              <YAxis
                tick={{ fill: 'rgba(255,255,255,0.65)', fontSize: 11 }}
                label={{
                  value: 'Frequência',
                  angle: -90,
                  position: 'insideLeft',
                  fill: 'rgba(255,255,255,0.45)',
                  fontSize: 11,
                }}
              />
              <Tooltip
                contentStyle={tooltipStyle}
                formatter={(v) => [formatNumber(Number(v)), 'Frequência']}
                labelFormatter={(_, payload) => {
                  const p = payload?.[0]?.payload as { faixa?: string; name?: string } | undefined;
                  return p?.faixa || p?.name || '';
                }}
              />
              <Legend {...LEGENDA_PROPS} />
              <Bar
                dataKey="frequencia"
                name="Frequência"
                fill="#10b981"
                radius={[3, 3, 0, 0]}
                isAnimationActive={false}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      );
    }

    if (tipoGrafico === 'dispersao') {
      const eixos = resultado?.eixos ?? { x: 'X', y: 'Y' };
      const nomeSerie = `${rotuloSerie(eixos.x)} × ${rotuloSerie(eixos.y)}`;
      return (
        <div className="analisador-explorar-chart">
          <ResponsiveContainer width="100%" height={360}>
            <ScatterChart margin={{ top: 36, right: 16, left: 8, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
              <XAxis
                type="number"
                dataKey="x"
                name={rotuloSerie(eixos.x)}
                tick={{ fill: 'rgba(255,255,255,0.65)', fontSize: 11 }}
                tickFormatter={(v) => (eixos.x === 'Receita' ? formatCurrency(Number(v)) : formatNumber(Number(v)))}
                label={{
                  value: rotuloSerie(eixos.x),
                  position: 'insideBottom',
                  offset: -4,
                  fill: 'rgba(255,255,255,0.45)',
                  fontSize: 11,
                }}
              />
              <YAxis
                type="number"
                dataKey="y"
                name={rotuloSerie(eixos.y)}
                tick={{ fill: 'rgba(255,255,255,0.65)', fontSize: 11 }}
                tickFormatter={(v) => (eixos.y === 'Receita' ? formatCurrency(Number(v)) : formatNumber(Number(v)))}
                label={{
                  value: rotuloSerie(eixos.y),
                  angle: -90,
                  position: 'insideLeft',
                  fill: 'rgba(255,255,255,0.45)',
                  fontSize: 11,
                }}
              />
              <ZAxis range={[40, 40]} />
              <Tooltip
                contentStyle={tooltipStyle}
                cursor={{ strokeDasharray: '3 3' }}
                formatter={(value, name) => {
                  const chave = String(name) === 'x' ? eixos.x : String(name) === 'y' ? eixos.y : String(name);
                  const n = Number(value ?? 0);
                  if (chave === 'Receita') return [formatCurrency(n), rotuloSerie(chave)];
                  return [formatNumber(n), rotuloSerie(chave)];
                }}
                labelFormatter={(_, payload) => {
                  const p = payload?.[0]?.payload as { name?: string } | undefined;
                  return p?.name ?? '';
                }}
              />
              <Legend {...LEGENDA_PROPS} />
              <Scatter name={nomeSerie} data={chartData} fill="#dabb6c" isAnimationActive={false} />
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      );
    }

    if (tipoGrafico === 'boxplot') {
      return (
        <div className="analisador-explorar-chart">
          <ResponsiveContainer width="100%" height={360}>
            <BarChart data={chartData} margin={{ top: 36, right: 12, left: 8, bottom: 48 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
              <XAxis dataKey="name" tick={{ fill: 'rgba(255,255,255,0.65)', fontSize: 11 }} interval={0} angle={-25} textAnchor="end" height={60} />
              <YAxis
                tick={{ fill: 'rgba(255,255,255,0.65)', fontSize: 11 }}
                tickFormatter={(v) => formatTick(Number(v))}
                label={{
                  value: rotuloSerie(metricas[0] ?? 'Receita'),
                  angle: -90,
                  position: 'insideLeft',
                  fill: 'rgba(255,255,255,0.45)',
                  fontSize: 11,
                }}
              />
              <Tooltip
                contentStyle={tooltipStyle}
                formatter={(value, name) => {
                  const n = Number(value ?? 0);
                  const chave = String(name);
                  if (['min', 'q1', 'median', 'q3', 'max'].includes(chave)) {
                    return [formatCurrency(n), rotuloSerie(chave)];
                  }
                  return [formatNumber(n), rotuloSerie(chave)];
                }}
              />
              <Legend
                content={() => (
                  <ul className="analisador-explorar-legend">
                    <li className="analisador-explorar-legend-item">
                      <span className="analisador-explorar-legend-swatch" style={{ background: '#dabb6c' }} />
                      <span className="analisador-explorar-legend-label">
                        Distribuição ({rotuloSerie(metricas[0] ?? 'Receita')}) — min / Q1 / mediana / Q3 / máx
                      </span>
                    </li>
                  </ul>
                )}
                verticalAlign="top"
                align="right"
                wrapperStyle={{ paddingBottom: 8 }}
              />
              <Bar dataKey="max" name="Distribuição" shape={<BoxPlotShape />} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      );
    }

    if (tipoGrafico === 'pizza') {
      const metricaPizza = metricas[0] ?? 'Receita';
      const dadosPizza = chartData.slice(0, 12).map((ponto) => ({
        ...ponto,
        name: String(ponto.name).length > 28
          ? `${String(ponto.name).slice(0, 26)}…`
          : String(ponto.name),
      }));
      return (
        <div className="analisador-explorar-chart">
          <ResponsiveContainer width="100%" height={380}>
            <PieChart margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
              <Pie
                data={dadosPizza}
                dataKey={metricaPizza}
                nameKey="name"
                cx="42%"
                cy="50%"
                outerRadius={110}
                isAnimationActive={false}
              >
                {dadosPizza.map((_, i) => (
                  <Cell key={i} fill={CORES_SERIE[i % CORES_SERIE.length]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={tooltipStyle}
                formatter={(value) => {
                  const n = Number(value ?? 0);
                  return metricaPizza === 'Receita'
                    ? [formatCurrency(n), rotuloSerie(metricaPizza)]
                    : [formatNumber(n), rotuloSerie(metricaPizza)];
                }}
              />
              <Legend
                layout="vertical"
                verticalAlign="middle"
                align="right"
                content={<ExplorarLegend vertical />}
                wrapperStyle={{ maxHeight: 320, overflow: 'auto', paddingLeft: 8 }}
              />
            </PieChart>
          </ResponsiveContainer>
          {chartData.length > 12 && (
            <p className="analisador-hint" style={{ marginTop: 8 }}>
              Legenda mostra as 12 maiores fatias de {chartData.length} categorias.
            </p>
          )}
        </div>
      );
    }

    const series = metricas.map((m, i) => {
      const cor = CORES_SERIE[i % CORES_SERIE.length];
      const nome = rotuloSerie(m);
      if (tipoGrafico === 'linhas') {
        return (
          <Line key={m} type="monotone" dataKey={m} name={nome} stroke={cor} strokeWidth={2} dot={false} isAnimationActive={false} />
        );
      }
      if (tipoGrafico === 'area') {
        return (
          <Area key={m} type="monotone" dataKey={m} name={nome} stroke={cor} fill={cor} fillOpacity={0.25} isAnimationActive={false} />
        );
      }
      return (
        <Bar key={m} dataKey={m} name={nome} fill={cor} radius={[4, 4, 0, 0]} isAnimationActive={false} />
      );
    });

    const ChartComp =
      tipoGrafico === 'linhas' ? LineChart : tipoGrafico === 'area' ? AreaChart : BarChart;

    return (
      <div className="analisador-explorar-chart">
        <ResponsiveContainer width="100%" height={360}>
          <ChartComp data={chartData} margin={{ top: 36, right: 12, left: 8, bottom: 48 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
            <XAxis dataKey="name" tick={{ fill: 'rgba(255,255,255,0.65)', fontSize: 11 }} interval={0} angle={-25} textAnchor="end" height={60} />
            <YAxis tick={{ fill: 'rgba(255,255,255,0.65)', fontSize: 11 }} tickFormatter={(v) => formatTick(Number(v))} />
            <Tooltip contentStyle={tooltipStyle} formatter={tooltipFormatter} />
            <Legend {...LEGENDA_PROPS} />
            {series}
          </ChartComp>
        </ResponsiveContainer>
      </div>
    );
  };

  const dicaTipo =
    tipoGrafico === 'histograma'
      ? 'Histograma: distribuição da métrica > 0 por cliente/entidade (bins log se a base for muito assimétrica; ignora devoluções/zeros).'
      : tipoGrafico === 'boxplot'
        ? 'Boxplot: distribuição por entidade dentro da 1ª dimensão.'
        : tipoGrafico === 'dispersao'
          ? 'Dispersão: marque Receita e QTD (ou uma delas) + dimensão.'
          : null;

  const podeExportar =
    !!resultado && resultado.linhas.length > 0 && !carregando && !exportando;

  const handleExportar = async (formatoTabela: 'csv' | 'xlsx' = 'csv') => {
    if (!resultado || resultado.linhas.length === 0) return;
    setMenuExportAberto(false);
    setExportando(true);
    setErro(null);
    try {
      const stamp = new Date().toISOString().slice(0, 10);
      if (modo === 'tabela') {
        const base = `explorar-tabela-${stamp}`;
        if (formatoTabela === 'xlsx') {
          baixarXlsx(resultado.colunas, resultado.linhas, `${base}.xlsx`);
        } else {
          baixarCsv(resultado.colunas, resultado.linhas, `${base}.csv`);
        }
      } else {
        const el = chartRef.current;
        if (!el) throw new Error('Área do gráfico indisponível.');
        await baixarSvgComoPng(el, `explorar-grafico-${stamp}.png`);
      }
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Falha ao exportar.');
    } finally {
      setExportando(false);
    }
  };

  return (
    <div className="analisador-stack">
      <div className="glass-card glass-card-flat analisador-explorar-card">
        <div className="analisador-titulo-linha">
          <h2 className="analisador-titulo">
            {modo === 'grafico' ? 'Gráficos personalizados' : 'Tabelas dinâmicas'}
          </h2>
          <div className="analisador-titulo-linha-acoes">
            {modo === 'grafico' ? (
              <button
                type="button"
                className="analisador-btn analisador-btn-pri analisador-btn-compact"
                disabled={!podeExportar}
                onClick={() => void handleExportar()}
                title="Exportar o gráfico visível como PNG"
              >
                <Download size={14} />
                {exportando ? 'Exportando…' : 'Exportar PNG'}
              </button>
            ) : (
              <div className="analisador-export-menu" ref={menuExportRef}>
                <button
                  type="button"
                  className="analisador-btn analisador-btn-pri analisador-btn-compact"
                  disabled={!podeExportar}
                  aria-haspopup="menu"
                  aria-expanded={menuExportAberto}
                  onClick={() => setMenuExportAberto((v) => !v)}
                  title="Exportar a tabela visível (CSV ou XLSX)"
                >
                  <Download size={14} />
                  {exportando ? 'Exportando…' : 'Exportar'}
                  <ChevronDown size={14} />
                </button>
                {menuExportAberto && !exportando && (
                  <div className="analisador-export-menu-panel dropdown-menu-panel" role="menu">
                    <button
                      type="button"
                      role="menuitem"
                      className="dropdown-menu-item"
                      onClick={() => void handleExportar('csv')}
                    >
                      CSV
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      className="dropdown-menu-item"
                      onClick={() => void handleExportar('xlsx')}
                    >
                      XLSX
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
        <p className="analisador-hint">
          {modo === 'grafico'
            ? 'Agregações em tempo real a partir das colunas da base da empresa.'
            : 'Tabela pivô/agregada em tempo real. Marque dimensões e métricas.'}
        </p>

        <div className="analisador-explorar-builder">
          <fieldset className="analisador-explorar-fieldset analisador-explorar-dimensoes">
            <legend>Dimensões (máx. {limites.dim})</legend>
            <div className="analisador-explorar-checks">
              {(schema?.dimensoes ?? []).map((col) => (
                <label key={col} className="analisador-check-linha">
                  <input
                    type="checkbox"
                    checked={dimensoes.includes(col)}
                    onChange={() => toggleDim(col)}
                  />
                  <span>{col}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset className="analisador-explorar-fieldset analisador-explorar-metricas">
            <legend>Métricas (máx. {limites.met})</legend>
            <div className="analisador-explorar-checks analisador-explorar-checks-metricas">
              {(schema?.metricas ?? METRICAS_PADRAO).map((m) => (
                <label key={m} className="analisador-check-linha">
                  <input
                    type="checkbox"
                    checked={metricas.includes(m)}
                    onChange={() => toggleMet(m)}
                  />
                  <span>{rotuloSerie(m)}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <div className="analisador-explorar-opcoes-linha">
            <div className="analisador-explorar-grupos-bloco">
              <label className="analisador-check-linha">
                <input
                  type="checkbox"
                  checked={aplicarGrupos}
                  onChange={(e) => setAplicarGrupos(e.target.checked)}
                />
                <span>Aplicar grupos manuais (agrega membros no campo Cliente)</span>
              </label>
              {carregando && <p className="analisador-hint">Atualizando…</p>}
              {resultado && !erro && !carregando && (
                <p className="analisador-hint">
                  {resultado.linhas.length.toLocaleString('pt-BR')} de{' '}
                  {resultado.total_linhas.toLocaleString('pt-BR')} linhas agregadas
                  {schema ? ` · base com ${schema.linhas.toLocaleString('pt-BR')} registros` : ''}
                </p>
              )}
            </div>

            {modo === 'grafico' && (
              <label className="analisador-campo analisador-explorar-tipo">
                <span>Tipo de gráfico</span>
                <select
                  className="custom-select analisador-select"
                  value={tipoGrafico}
                  onChange={(e) => setTipoGrafico(e.target.value as TipoGrafico)}
                >
                  {TIPOS_GRAFICO.map((t) => (
                    <option key={t.id} value={t.id}>{t.rotulo}</option>
                  ))}
                </select>
              </label>
            )}

            {modo === 'grafico' && tipoGrafico === 'histograma' && (
              <label className="analisador-campo analisador-explorar-limite">
                <span>Bins</span>
                <input
                  className="analisador-input"
                  type="number"
                  min={5}
                  max={60}
                  value={bins}
                  onChange={(e) => setBins(Math.max(5, Math.min(60, Number(e.target.value) || 20)))}
                />
              </label>
            )}

            <label className="analisador-campo analisador-explorar-limite">
              <span>Limite de linhas</span>
              <input
                className="analisador-input"
                type="number"
                min={1}
                max={500}
                value={limite}
                onChange={(e) => setLimite(Math.max(1, Math.min(500, Number(e.target.value) || 1)))}
              />
            </label>
          </div>
        </div>

        {dicaTipo && <p className="analisador-hint">{dicaTipo}</p>}
        {erro && (
          <p className="analisador-feedback-inline erro" role="alert">{erro}</p>
        )}
      </div>

      <div className="glass-card glass-card-flat">
        {modo === 'grafico' ? (
          <div ref={chartRef}>{renderGrafico()}</div>
        ) : (
          <ResultTable tabela={tabela} />
        )}
      </div>
    </div>
  );
}
