import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AreaChart as AreaChartIcon,
  ArrowDown,
  ArrowUp,
  BarChart3,
  BarChartBig,
  CandlestickChart,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Download,
  GripVertical,
  LineChart as LineChartIcon,
  PieChart as PieChartIcon,
  ScatterChart as ScatterChartIcon,
  X,
} from 'lucide-react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
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
import { formatCompacto, formatCurrency, formatNumber } from '../../utils/formatters';
import { chaveOrdemTemporal, ehDimensaoTemporal, rotuloColuna } from '../../utils/rotulosColuna';
import { ResultTable, type OrdenacaoTabela } from './ResultTable';

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
/** Paleta das séries, derivada da marca. Precisa ter ao menos MAX_SERIES_PIVOT+1
 *  cores (as séries + "Outros"): cor repetida em duas séries torna a legenda
 *  ambígua — foi o que acontecia com 7 séries numa paleta de 6. */
const CORES_SERIE = [
  '#dabb6c', // accent
  '#6f8cc4', // accent-secondary-bright
  '#68818d', // accent-tertiary
  '#cc6300', // alert-warm
  '#8aa3ad', // accent-tertiary-bright
  '#4cae7a', // success
  '#a97fb8', // roxo de apoio
  '#e0645c', // danger
];
const TIPOS_GRAFICO: { id: TipoGrafico; rotulo: string; Icone: typeof BarChart3 }[] = [
  { id: 'barras', rotulo: 'Barras', Icone: BarChart3 },
  { id: 'linhas', rotulo: 'Linhas', Icone: LineChartIcon },
  { id: 'area', rotulo: 'Área', Icone: AreaChartIcon },
  { id: 'pizza', rotulo: 'Pizza', Icone: PieChartIcon },
  { id: 'histograma', rotulo: 'Histograma', Icone: BarChartBig },
  { id: 'dispersao', rotulo: 'Dispersão', Icone: ScatterChartIcon },
  { id: 'boxplot', rotulo: 'Boxplot', Icone: CandlestickChart },
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
  return ROTULOS_METRICA[chave] ?? rotuloColuna(chave);
}

/** Métricas somáveis: dá pra totalizar e calcular participação.
 *  "Clientes" é contagem DISTINTA — somar as linhas não dá o total da base
 *  (o mesmo cliente aparece em várias), então ela fica fora do total e do %. */
const METRICAS_SOMAVEIS = new Set(['Receita', 'QTD']);

const COLUNA_PCT_TOTAL = 'Percentual_Do_Total';
const COLUNA_PCT_ACUM = 'Percentual_Acumulado';
const SUFIXO_ANO_ANTERIOR = '_Ano_Anterior';
const ROTULO_RESTO_SERIE = 'Outros';
/** Séries acima disso viram "Outros". Amarrado ao tamanho da paleta (menos a
 *  cor que sobra para o próprio "Outros") — nunca duas séries com a mesma cor. */
const MAX_SERIES_PIVOT = CORES_SERIE.length - 1;

type SerieGrafico = { chave: string; rotulo: string; moeda: boolean };

/** Única métrica em R$ hoje. Isolado porque decide formatação e eixo. */
function ehMetricaMoeda(metrica: string): boolean {
  return metrica.replace(SUFIXO_ANO_ANTERIOR, '') === 'Receita';
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
            {ROTULOS_METRICA[String(entry.value)] ?? String(entry.value)}
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

/**
 * Shape customizado: whiskers + caixa IQR + mediana, na convenção de Tukey.
 *
 * Os bigodes vão até `bigodeAlto`/`bigodeBaixo` (1,5×IQR além do quartil), não até
 * o mínimo/máximo brutos — é o próprio `<Bar dataKey="bigodeAlto">` que referencia
 * essa mesma escala, então o desenho aqui já nasce dentro do que o Recharts
 * calculou para y/height. Ir até o extremo bruto faz um único cliente ou período
 * fora da curva virar o topo da escala do gráfico inteiro, espremendo a caixa —
 * que é o que de fato importa, onde está a maioria dos dados — a poucos % da
 * altura.
 *
 * Quando o extremo real ultrapassa o bigode, um triângulo marca "tem mais aqui,
 * fora de escala"; o valor exato vai só no tooltip.
 */
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
    bigodeAlto?: number;
    bigodeBaixo?: number;
    temOutlierAlto?: boolean;
    temOutlierBaixo?: boolean;
  };
}) {
  const { x = 0, width = 0, y = 0, height = 0, payload } = props;
  const bigodeAlto = Number(payload?.bigodeAlto ?? 0);
  if (!payload || !bigodeAlto || bigodeAlto <= 0) return null;
  const toY = (v: number) => y + height * (1 - Number(v) / bigodeAlto);
  const cx = x + width / 2;
  const boxW = Math.max(width * 0.55, 10);
  const bigodeBaixo = Number(payload.bigodeBaixo ?? 0);
  const yBigodeAlto = toY(bigodeAlto);
  const yBigodeBaixo = toY(bigodeBaixo);
  const yQ3 = toY(Number(payload.q3));
  const yQ1 = toY(Number(payload.q1));
  const yMed = toY(Number(payload.median));
  const marcador = (cyOutlier: number, aponta: 'cima' | 'baixo') => {
    const s = 5;
    const pontas = aponta === 'cima'
      ? `${cx},${cyOutlier - s} ${cx - s},${cyOutlier + s} ${cx + s},${cyOutlier + s}`
      : `${cx},${cyOutlier + s} ${cx - s},${cyOutlier - s} ${cx + s},${cyOutlier - s}`;
    return <polygon points={pontas} fill="#e8a05f" stroke="#0f172a" strokeWidth={1} />;
  };
  return (
    <g>
      <line x1={cx} x2={cx} y1={yBigodeAlto} y2={yBigodeBaixo} stroke="#94a3b8" strokeWidth={1.5} />
      <line x1={cx - boxW / 2} x2={cx + boxW / 2} y1={yBigodeAlto} y2={yBigodeAlto} stroke="#94a3b8" strokeWidth={1.5} />
      <line x1={cx - boxW / 2} x2={cx + boxW / 2} y1={yBigodeBaixo} y2={yBigodeBaixo} stroke="#94a3b8" strokeWidth={1.5} />
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
      {payload.temOutlierAlto && marcador(yBigodeAlto - 6, 'cima')}
      {payload.temOutlierBaixo && marcador(yBigodeBaixo + 6, 'baixo')}
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
  const [ordenacaoManual, setOrdenacaoManual] = useState<OrdenacaoTabela | null>(null);
  /** 2ª dimensão vira série (barras agrupadas/empilhadas) em vez de virar
   *  categoria concatenada no eixo X. */
  /** Dimensao usada como SERIE (cor). null = nenhuma, o eixo carrega todas as
   *  dimensoes concatenadas. Guardar o NOME (e nao "usar a 2a") tira a
   *  dependencia de ordem: o papel de cada dimensao fica explicito. */
  const [dimSerie, setDimSerie] = useState<string | null>(null);
  /** Metrica que alimenta as series do pivo (as outras seguem na tabela). */
  const [metricaSerie, setMetricaSerie] = useState<string | null>(null);
  const [empilhado, setEmpilhado] = useState(false);
  const [agruparResto, setAgruparResto] = useState(false);
  const [compararAno, setCompararAno] = useState(false);
  /** Arrastar-e-soltar da ordem das dimensões: índice de origem e o de destino
   *  sob o cursor (só para o retorno visual). */
  const [arrastando, setArrastando] = useState<number | null>(null);
  const [alvoArraste, setAlvoArraste] = useState<number | null>(null);
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

  /** Ordenação enviada ao backend. Só métrica: ela define QUAIS linhas voltam
   *  (top N). Não depende de `resultado`, para não realimentar o fetch. */
  const ordenacaoServidor = useMemo(() => {
    const manual = ordenacaoManual;
    const ehMetrica = !!manual && metricas.some(
      (m) => manual.coluna === m || manual.coluna === `${m}${SUFIXO_ANO_ANTERIOR}`,
    );
    return ehMetrica && manual
      ? { coluna: manual.coluna, direcao: manual.direcao }
      : { coluna: metricas[0] ?? null, direcao: 'desc' as const };
  }, [ordenacaoManual, metricas]);

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
        // Só manda a ordenação ao backend quando ela é métrica: aí ela decide
        // QUAIS linhas voltam (top N). Ordenar por dimensão é recorte visual e
        // acontece no cliente, senão o top N deixaria de ser "as maiores".
        ordenar_por: ordenacaoServidor.coluna,
        ordem: ordenacaoServidor.direcao,
        modo_viz: modoViz,
        bins,
        agrupar_resto: agruparResto && modoViz === 'agregar',
        comparar_ano_anterior: compararAno && modoViz === 'agregar',
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
  }, [schema, empresa, loja, dimensoes, metricas, aplicarGrupos, limite, tipoGrafico, bins, modo,
      agruparResto, compararAno, ordenacaoServidor]);

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

  /** Ordenação padrão: cronológica quando a 1ª dimensão é tempo, senão a que o
   *  backend já devolveu (maior métrica primeiro). Sem isso uma série mensal sai
   *  embaralhada por valor e deixa de ser leitura de tendência. */
  const ordenacaoPadrao = useMemo<OrdenacaoTabela | null>(() => {
    const primeira = resultado?.dimensoes?.[0];
    if (!primeira || !ehDimensaoTemporal(primeira)) return null;
    return { coluna: primeira, direcao: 'asc' };
  }, [resultado]);

  const ordenacao = ordenacaoManual ?? ordenacaoPadrao;

  /** O que os controles mostram. Sem ordenacao explicita nem padrao temporal,
   *  quem manda e a ordenacao do backend (metrica desc) — o select tem que
   *  mostrar ISSO, e nao a primeira opcao da lista. */
  const ordenacaoExibida = ordenacao ?? {
    coluna: ordenacaoServidor.coluna ?? '',
    direcao: ordenacaoServidor.direcao,
  };

  const linhasOrdenadas = useMemo(() => {
    if (!resultado) return [];
    const modoViz = resultado.modo_viz ?? 'agregar';
    // Histograma/boxplot/dispersão têm ordem própria (bins, quartis) — reordenar
    // quebraria a leitura.
    if (modoViz !== 'agregar' || !ordenacao) return resultado.linhas;
    const indice = resultado.colunas.indexOf(ordenacao.coluna);
    if (indice < 0) return resultado.linhas;
    const fator = ordenacao.direcao === 'asc' ? 1 : -1;
    // Dimensão temporal ordena pela chave cronológica (nome de mês vira número);
    // o resto compara número com número ou texto com texto.
    const temporal = ehDimensaoTemporal(ordenacao.coluna);
    const chave = (linha: unknown[]) =>
      temporal ? chaveOrdemTemporal(linha[indice]) : linha[indice];
    return [...resultado.linhas].sort((a, b) => {
      const va = chave(a);
      const vb = chave(b);
      if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * fator;
      return String(va ?? '').localeCompare(String(vb ?? ''), 'pt-BR', { numeric: true }) * fator;
    });
  }, [resultado, ordenacao]);

  /** Colunas oferecidas no "Ordenar por": dimensões + métricas (e as colunas
   *  extras da comparação anual, quando estão na resposta). */
  const opcoesOrdenacao = useMemo(() => {
    const cols = resultado?.colunas ?? [...dimensoes, ...metricas];
    const extras = [COLUNA_PCT_TOTAL, COLUNA_PCT_ACUM];
    return cols.filter((c) => !extras.includes(c));
  }, [resultado, dimensoes, metricas]);

  const definirOrdenacao = (coluna: string) => {
    const ehMetrica = (resultado?.metricas ?? metricas).some(
      (m) => coluna === m || coluna === `${m}${SUFIXO_ANO_ANTERIOR}`,
    );
    setOrdenacaoManual({ coluna, direcao: ehMetrica ? 'desc' : 'asc' });
  };

  const inverterOrdenacao = () => {
    const base = ordenacaoManual ?? ordenacaoPadrao ?? {
      coluna: ordenacaoServidor.coluna ?? metricas[0] ?? '',
      direcao: ordenacaoServidor.direcao,
    };
    setOrdenacaoManual({ ...base, direcao: base.direcao === 'asc' ? 'desc' : 'asc' });
  };

  /** Reordena as dimensões: a 1ª é o eixo, a 2ª pode virar série. */
  const moverDimensao = (indice: number, passo: number) => {
    setDimensoes((atual) => {
      const destino = indice + passo;
      if (destino < 0 || destino >= atual.length) return atual;
      const copia = [...atual];
      [copia[indice], copia[destino]] = [copia[destino], copia[indice]];
      return copia;
    });
  };

  /** Índice de origem do arraste. Vem do `dataTransfer`, não do estado: o
   *  handler de drop enxerga o estado do render anterior, e num arraste muito
   *  rápido `arrastando` ainda seria null. O estado fica só para o visual. */
  const indiceArrastado = (e: React.DragEvent): number | null => {
    const bruto = e.dataTransfer.getData('text/plain');
    const indice = Number(bruto);
    if (bruto !== '' && Number.isInteger(indice) && indice >= 0) return indice;
    return arrastando;
  };

  /** Escolher o eixo move a dimensao para a 1a posicao — a ordem continua sendo
   *  a fonte da verdade (chips, backend, exportacao), so deixou de ser o unico
   *  jeito de definir papel. */
  const escolherEixo = (coluna: string) => {
    const origem = dimensoes.indexOf(coluna);
    if (origem < 0) return;
    reordenarDimensao(origem, 0);
    // Se a escolhida era a serie, a serie perde o papel (nao pode ser as duas).
    if (dimSerie === coluna) setDimSerie(null);
  };

  const escolherSerie = (coluna: string | null) => {
    setDimSerie(coluna);
    if (!coluna) return;
    const origem = dimensoes.indexOf(coluna);
    if (origem > 1) reordenarDimensao(origem, 1);
  };

  /** Tira da posição de origem e insere na de destino (arrastar e soltar).
   *  Diferente de `moverDimensao`, que troca com o vizinho. */
  const reordenarDimensao = (origem: number, destino: number) => {
    setDimensoes((atual) => {
      if (origem === destino || origem < 0 || destino < 0) return atual;
      if (origem >= atual.length || destino >= atual.length) return atual;
      const copia = [...atual];
      const [movido] = copia.splice(origem, 1);
      copia.splice(destino, 0, movido);
      return copia;
    });
  };

  const alternarOrdenacao = (coluna: string) => {
    setOrdenacaoManual((atual) => {
      const base = atual ?? ordenacaoPadrao;
      if (base?.coluna === coluna) {
        return { coluna, direcao: base.direcao === 'asc' ? 'desc' : 'asc' };
      }
      // Número começa do maior; texto/tempo começa do começo.
      const ehMetrica = (resultado?.metricas ?? []).includes(coluna);
      return { coluna, direcao: ehMetrica ? 'desc' : 'asc' };
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
      return resultado.linhas.map((linha) => {
        const min = Number(linha[idx('min')] ?? 0);
        const q1 = Number(linha[idx('q1')] ?? 0);
        const median = Number(linha[idx('median')] ?? 0);
        const q3 = Number(linha[idx('q3')] ?? 0);
        const max = Number(linha[idx('max')] ?? 0);
        // Convenção de Tukey: bigode vai até 1,5×IQR além do quartil, não até o
        // extremo bruto. Sem isso um único cliente/período fora da curva vira o
        // topo da escala do gráfico inteiro, e a caixa (o que de fato importa —
        // onde está a maioria) fica espremida a poucos % da altura, visualmente
        // indistinguível de uma linha.
        const iqr = q3 - q1;
        const cercaAlta = q3 + 1.5 * iqr;
        const cercaBaixa = q1 - 1.5 * iqr;
        const bigodeAlto = Math.min(max, cercaAlta);
        const bigodeBaixo = Math.max(min, cercaBaixa);
        return {
          name: String(linha[iNome] ?? ''),
          min,
          q1,
          median,
          q3,
          max,
          bigodeAlto,
          bigodeBaixo,
          // Margem de ponto flutuante: sem ela, um max exatamente igual à cerca
          // (IQR=0, poucos registros) marcaria outlier por erro de arredondamento.
          temOutlierAlto: max > cercaAlta + 0.01,
          temOutlierBaixo: min < cercaBaixa - 0.01,
          n: Number(linha[idx('n')] ?? 0),
        };
      });
    }

    const dimCols = resultado.dimensoes;
    const metCols = resultado.metricas;
    return linhasOrdenadas.map((linha) => {
      const nome = dimCols.map((d) => String(linha[cols.indexOf(d)] ?? '')).join(' · ') || 'Total';
      const ponto: Record<string, string | number> = { name: nome };
      for (const m of metCols) {
        const i = cols.indexOf(m);
        ponto[m] = Number(linha[i] ?? 0);
      }
      return ponto;
    });
  }, [resultado, linhasOrdenadas]);

  /** Tabela dinâmica com participação: % da métrica principal sobre o total das
   *  linhas exibidas e % acumulado na ordem atual (leitura tipo ABC). */
  const tabela = useMemo(() => {
    if (!resultado) return { colunas: [] as string[], linhas: [] as unknown[][] };
    const metricaBase = (resultado.metricas ?? []).find((m) => METRICAS_SOMAVEIS.has(m));
    const indiceBase = metricaBase ? resultado.colunas.indexOf(metricaBase) : -1;
    if (modo !== 'tabela' || indiceBase < 0) {
      return { colunas: resultado.colunas, linhas: linhasOrdenadas };
    }
    const total = linhasOrdenadas.reduce((soma, linha) => {
      const valor = linha[indiceBase];
      return soma + (typeof valor === 'number' && Number.isFinite(valor) ? valor : 0);
    }, 0);
    if (total <= 0) return { colunas: resultado.colunas, linhas: linhasOrdenadas };
    let acumulado = 0;
    const linhas = linhasOrdenadas.map((linha) => {
      const valor = linha[indiceBase];
      const numero = typeof valor === 'number' && Number.isFinite(valor) ? valor : 0;
      acumulado += numero;
      return [...linha, (numero / total) * 100, (acumulado / total) * 100];
    });
    return { colunas: [...resultado.colunas, COLUNA_PCT_TOTAL, COLUNA_PCT_ACUM], linhas };
  }, [resultado, linhasOrdenadas, modo]);

  /** Somas das linhas exibidas — só métricas somáveis (ver METRICAS_SOMAVEIS).
   *  Com comparação anual ligada, soma também a coluna do ano anterior. */
  const totaisTabela = useMemo(() => {
    if (!resultado) return [];
    const somaveis = (resultado.metricas ?? []).filter((m) => METRICAS_SOMAVEIS.has(m));
    const colunas = resultado.comparacao
      ? somaveis.flatMap((m) => [`${m}${SUFIXO_ANO_ANTERIOR}`, m])
      : somaveis;
    return colunas
      .filter((coluna) => resultado.colunas.includes(coluna))
      .map((metrica) => {
        const indice = resultado.colunas.indexOf(metrica);
        const soma = linhasOrdenadas.reduce((acc, linha) => {
          const valor = indice >= 0 ? linha[indice] : null;
          return acc + (typeof valor === 'number' && Number.isFinite(valor) ? valor : 0);
        }, 0);
        return { metrica, soma };
      });
  }, [resultado, linhasOrdenadas]);

  /** Tick do eixo em forma curta ("2,4 M"). O valor cheio (R$ 2.400.000,00) não
   *  cabe na faixa do eixo e o recharts corta o texto pela esquerda, exibindo um
   *  número menor e plausível. */
  const formatTickCurto = (v: number, moeda: boolean) => formatCompacto(v, moeda);

  const rotuloEixoX = dimensoes.length ? dimensoes.map(rotuloColuna).join(' · ') : '';

  const tipoAceitaSeries = tipoGrafico === 'barras' || tipoGrafico === 'linhas' || tipoGrafico === 'area';
  /** Só vale se o backend realmente devolveu as colunas do ano anterior. */
  const comparacaoAtiva = Boolean(compararAno && resultado?.comparacao);
  /** Dimensao do eixo = a primeira; a serie e a escolhida no seletor. */
  const dimEixo = dimensoes[0] ?? null;
  const serieValida = !!dimSerie && dimSerie !== dimEixo && dimensoes.includes(dimSerie);
  const pivotAtivo = Boolean(
    serieValida && !comparacaoAtiva && tipoAceitaSeries && modo === 'grafico',
  );
  /** Metrica das series: a escolhida, se ainda estiver marcada. */
  const metricaDoPivo = (metricaSerie && metricas.includes(metricaSerie))
    ? metricaSerie
    : metricas[0];

  /** Séries do gráfico principal.
   *
   *  Três formas, na ordem de precedência:
   *   - comparação anual: mesma métrica nos dois anos;
   *   - 2ª dimensão como série: uma série por valor da 2ª dimensão (barras
   *     agrupadas/empilhadas), no lugar de concatenar as duas no eixo X;
   *   - padrão: uma série por métrica marcada.
   */
  const visao = useMemo(() => {
    const semSerie = { data: chartData, series: [] as SerieGrafico[] };
    if (!resultado || (resultado.modo_viz ?? 'agregar') !== 'agregar') return semSerie;
    const cols = resultado.colunas;
    const metricaBase = metricas[0];
    if (!metricaBase) return semSerie;

    if (comparacaoAtiva) {
      const anterior = `${metricaBase}${SUFIXO_ANO_ANTERIOR}`;
      const iAtual = cols.indexOf(metricaBase);
      const iAnterior = cols.indexOf(anterior);
      if (iAtual < 0 || iAnterior < 0) return semSerie;
      const dims = resultado.dimensoes;
      const data = linhasOrdenadas.map((linha) => ({
        name: dims.map((d) => String(linha[cols.indexOf(d)] ?? '')).join(' · ') || 'Total',
        [anterior]: Number(linha[iAnterior] ?? 0),
        [metricaBase]: Number(linha[iAtual] ?? 0),
      }));
      const anos = resultado.comparacao;
      return {
        data,
        series: [
          { chave: anterior, rotulo: anos ? String(anos.ano_anterior) : 'Ano anterior', moeda: ehMetricaMoeda(metricaBase) },
          { chave: metricaBase, rotulo: anos ? String(anos.ano_atual) : 'Ano atual', moeda: ehMetricaMoeda(metricaBase) },
        ] as SerieGrafico[],
      };
    }

    if (pivotAtivo) {
      // Papeis explicitos: eixo = 1a dimensao, serie = a escolhida no seletor.
      const dim1 = dimEixo;
      const dim2 = dimSerie;
      const metricaPivo = metricaDoPivo;
      const i1 = dim1 ? cols.indexOf(dim1) : -1;
      const i2 = dim2 ? cols.indexOf(dim2) : -1;
      const iMetrica = metricaPivo ? cols.indexOf(metricaPivo) : -1;
      if (i1 < 0 || i2 < 0 || iMetrica < 0 || !metricaPivo) return semSerie;

      // Totais por valor da 2ª dimensão: as maiores viram série, o resto entra
      // em "Outros" — dezenas de séries seriam ilegíveis e sem cor distinta.
      const totalPorSerie = new Map<string, number>();
      for (const linha of linhasOrdenadas) {
        const chave = String(linha[i2] ?? '—');
        totalPorSerie.set(chave, (totalPorSerie.get(chave) ?? 0) + Number(linha[iMetrica] ?? 0));
      }
      const ordenadas = [...totalPorSerie.entries()].sort((a, b) => b[1] - a[1]).map(([k]) => k);
      const principais = ordenadas.slice(0, MAX_SERIES_PIVOT);
      const conjuntoPrincipais = new Set(principais);
      const temResto = ordenadas.length > principais.length;

      const porCategoria = new Map<string, Record<string, string | number>>();
      const ordemCategorias: string[] = [];
      for (const linha of linhasOrdenadas) {
        const categoria = String(linha[i1] ?? '—');
        if (!porCategoria.has(categoria)) {
          porCategoria.set(categoria, { name: categoria });
          ordemCategorias.push(categoria);
        }
        const ponto = porCategoria.get(categoria)!;
        const serie = String(linha[i2] ?? '—');
        const chave = conjuntoPrincipais.has(serie) ? serie : ROTULO_RESTO_SERIE;
        ponto[chave] = (Number(ponto[chave] ?? 0)) + Number(linha[iMetrica] ?? 0);
      }
      const series: SerieGrafico[] = [
        ...principais.map((s) => ({ chave: s, rotulo: s, moeda: ehMetricaMoeda(metricaPivo) })),
        ...(temResto
          ? [{ chave: ROTULO_RESTO_SERIE, rotulo: `${ROTULO_RESTO_SERIE} (${ordenadas.length - principais.length})`, moeda: ehMetricaMoeda(metricaPivo) }]
          : []),
      ];
      return { data: ordemCategorias.map((c) => porCategoria.get(c)!), series };
    }

    return {
      data: chartData,
      series: metricas.map((m) => ({ chave: m, rotulo: rotuloSerie(m), moeda: ehMetricaMoeda(m) })),
    };
  }, [resultado, linhasOrdenadas, chartData, metricas, comparacaoAtiva, pivotAtivo,
      dimEixo, dimSerie, metricaDoPivo]);

  /** Duas escalas quando as séries têm unidades diferentes (R$ e contagem).
   *  Num eixo só, Quantidade (219 mil) ao lado de Receita (14 milhões) vira uma
   *  linha rente ao zero — o dado existe mas não é legível. */
  const eixoDuplo = useMemo(() => {
    const temMoeda = visao.series.some((s) => s.moeda);
    const temContagem = visao.series.some((s) => !s.moeda);
    return temMoeda && temContagem;
  }, [visao]);

  /**
   * Domínios com o ZERO na mesma altura nos dois eixos.
   *
   * Com valores negativos num lado só (quantidade tem devolução, receita não), o
   * recharts dá a cada eixo um domínio independente: o zero da esquerda fica na
   * base e o da direita no meio do gráfico. As barras da 2ª série passam a
   * "flutuar" a partir do meio e viram comparação visual falsa — parecem começar
   * de um piso que não existe.
   *
   * Solução: usar a MESMA fração negativa nos dois eixos, calculada pelo lado que
   * afunda mais.
   */
  const dominios = useMemo(() => {
    if (!eixoDuplo) return null;
    const extremos = (moeda: boolean) => {
      let minimo = 0;
      let maximo = 0;
      for (const ponto of visao.data) {
        for (const serie of visao.series) {
          if (serie.moeda !== moeda) continue;
          const valor = Number((ponto as Record<string, unknown>)[serie.chave] ?? 0);
          if (!Number.isFinite(valor)) continue;
          minimo = Math.min(minimo, valor);
          maximo = Math.max(maximo, valor);
        }
      }
      return { minimo, maximo: maximo || 1 };
    };
    const esquerda = extremos(true);
    const direita = extremos(false);
    const fracao = Math.min(
      esquerda.minimo / esquerda.maximo,
      direita.minimo / direita.maximo,
    );
    // Alinhar custa espaço: o lado sem negativo ganha a mesma sobra negativa. Se
    // um lado afunda muito (devolução alta na quantidade), alinhar comprimiria as
    // barras do outro na metade de cima do gráfico — aí é melhor deixar cada eixo
    // com sua escala. A 2ª unidade é desenhada como LINHA justamente porque linha
    // não sugere "altura desde o piso" como a barra sugere.
    if (fracao < -0.35) return null;
    const folga = 1.05;
    return {
      moeda: [esquerda.maximo * fracao * folga, esquerda.maximo * folga] as [number, number],
      contagem: [direita.maximo * fracao * folga, direita.maximo * folga] as [number, number],
    };
  }, [eixoDuplo, visao]);

  /** Formata CADA série pela unidade dela.
   *
   *  Antes havia um `|| metricas[0] === 'Receita'`: com Receita marcada, toda
   *  série virava R$ e o tooltip mostrava "Quantidade: R$ 219.620,00". A unidade
   *  é da série, não da primeira métrica marcada. */
  const tooltipFormatter = (value: unknown, name: unknown) => {
    const n = Number(value ?? 0);
    const chave = String(name ?? '');
    const serie = visao.series.find((s) => s.chave === chave || s.rotulo === chave);
    const label = serie?.rotulo ?? rotuloSerie(chave);
    if (chave === 'frequencia' || chave === 'n') return [formatNumber(n), label];
    // Quartis do boxplot são da métrica escolhida.
    if (['min', 'q1', 'median', 'q3', 'max'].includes(chave)) {
      return [ehMetricaMoeda(metricas[0] ?? '') ? formatCurrency(n) : formatNumber(n), label];
    }
    const moeda = serie ? serie.moeda : ehMetricaMoeda(chave);
    return [moeda ? formatCurrency(n) : formatNumber(n), label];
  };

  const tooltipStyle = {
    background: '#0f172a',
    border: '1px solid rgba(255,255,255,0.12)',
    borderRadius: 8,
  } as const;

  // Sem isto, o Recharts pinta o texto de cada item na MESMA cor da série/fatia —
  // e várias cores de CORES_SERIE (ex. o azul-acinzentado da paleta) têm contraste
  // baixo demais sobre o fundo escuro do tooltip, ficando quase ilegíveis. O
  // quadradinho de cor já identifica a série; o texto fica sempre nesta cor fixa.
  const tooltipItemStyle = { color: '#e2e8f0' } as const;

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
                itemStyle={tooltipItemStyle}
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
                itemStyle={tooltipItemStyle}
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
                tickFormatter={(v) => formatTickCurto(Number(v), ehMetricaMoeda(metricas[0] ?? ''))}
                width={82}
                label={{
                  value: rotuloSerie(metricas[0] ?? 'Receita'),
                  angle: -90,
                  position: 'insideLeft',
                  fill: 'rgba(255,255,255,0.45)',
                  fontSize: 11,
                }}
              />
              <Tooltip
                content={({ active, payload: pts }) => {
                  if (!active || !pts || !pts.length) return null;
                  const p = pts[0].payload as {
                    name: string; min: number; q1: number; median: number; q3: number; max: number;
                    n: number; temOutlierAlto?: boolean; temOutlierBaixo?: boolean;
                  };
                  const moeda = ehMetricaMoeda(metricas[0] ?? 'Receita');
                  const fmt = (v: number) => (moeda ? formatCurrency(v) : formatNumber(v));
                  return (
                    <div style={{ ...tooltipStyle, padding: '8px 10px', fontSize: 12, color: '#e2e8f0' }}>
                      <div style={{ fontWeight: 600, marginBottom: 4 }}>{p.name}</div>
                      <div>Máximo: {fmt(p.max)}{p.temOutlierAlto ? ' (outlier)' : ''}</div>
                      <div>3º quartil: {fmt(p.q3)}</div>
                      <div>Mediana: {fmt(p.median)}</div>
                      <div>1º quartil: {fmt(p.q1)}</div>
                      <div>Mínimo: {fmt(p.min)}{p.temOutlierBaixo ? ' (outlier)' : ''}</div>
                      <div style={{ color: 'rgba(255,255,255,0.5)', marginTop: 4 }}>n = {p.n}</div>
                    </div>
                  );
                }}
              />
              <Legend
                content={() => (
                  <ul className="analisador-explorar-legend">
                    <li className="analisador-explorar-legend-item">
                      <span className="analisador-explorar-legend-swatch" style={{ background: '#dabb6c' }} />
                      <span className="analisador-explorar-legend-label">
                        Distribuição ({rotuloSerie(metricas[0] ?? 'Receita')}) — caixa = Q1–Q3, bigodes = 1,5×IQR
                      </span>
                    </li>
                    <li className="analisador-explorar-legend-item">
                      <span className="analisador-explorar-legend-swatch" style={{ background: '#e8a05f' }} />
                      <span className="analisador-explorar-legend-label">Outlier além do bigode (valor exato no tooltip)</span>
                    </li>
                  </ul>
                )}
                verticalAlign="top"
                align="right"
                wrapperStyle={{ paddingBottom: 8 }}
              />
              <Bar dataKey="bigodeAlto" name="Distribuição" shape={<BoxPlotShape />} isAnimationActive={false} />
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
                itemStyle={tooltipItemStyle}
                // O 2º argumento do formatter é o nome da FATIA (nameKey), não da
                // métrica — usar rotuloSerie(metricaPizza) aqui, como antes,
                // fazia todo hover mostrar sempre "Clientes : X" (ou o nome da
                // métrica escolhida) em vez de qual categoria estava sob o mouse.
                formatter={(value, name) => {
                  const n = Number(value ?? 0);
                  const formatado = metricaPizza === 'Receita' ? formatCurrency(n) : formatNumber(n);
                  return [formatado, String(name)];
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

    // Com eixo duplo, cada série vai para a escala da sua unidade.
    const idEixo = (moeda: boolean) => (eixoDuplo ? (moeda ? 'moeda' : 'contagem') : 'unico');
    const empilhar = empilhado && (tipoGrafico === 'barras' || tipoGrafico === 'area');

    const series = visao.series.map((serie, i) => {
      const cor = CORES_SERIE[i % CORES_SERIE.length];
      const comum = {
        key: serie.chave,
        dataKey: serie.chave,
        name: serie.rotulo,
        yAxisId: idEixo(serie.moeda),
        isAnimationActive: false as const,
      };
      // O empilhamento só é somável dentro da MESMA unidade.
      const pilha = empilhar ? { stackId: idEixo(serie.moeda) } : {};
      // Combo: com duas escalas, barra contra barra sugere comparação direta que
      // não existe (alturas em unidades diferentes). A 2ª unidade vira linha.
      if (tipoGrafico === 'barras' && eixoDuplo && !serie.moeda) {
        return <Line {...comum} type="monotone" stroke={cor} strokeWidth={2} dot={{ r: 2.5, fill: cor }} />;
      }
      if (tipoGrafico === 'linhas') {
        return <Line {...comum} type="monotone" stroke={cor} strokeWidth={2} dot={false} />;
      }
      if (tipoGrafico === 'area') {
        return <Area {...comum} {...pilha} type="monotone" stroke={cor} fill={cor} fillOpacity={0.25} />;
      }
      return <Bar {...comum} {...pilha} fill={cor} radius={empilhar ? undefined : [4, 4, 0, 0]} />;
    });

    // ComposedChart é o único que aceita Bar + Line no mesmo gráfico.
    const ChartComp = tipoGrafico === 'linhas'
      ? LineChart
      : tipoGrafico === 'area'
        ? AreaChart
        : eixoDuplo ? ComposedChart : BarChart;

    const rotuloEixo = (moeda: boolean) => {
      if (!eixoDuplo) {
        if (pivotAtivo) return rotuloSerie(metricaDoPivo ?? '');
        if (comparacaoAtiva) return rotuloSerie(metricas[0] ?? '');
        return visao.series.map((s) => s.rotulo).join(' · ');
      }
      return moeda ? 'Receita (R$)' : 'Contagem';
    };

    const eixoY = (moeda: boolean, lado: 'left' | 'right') => (
      <YAxis
        key={lado}
        yAxisId={idEixo(moeda)}
        orientation={lado}
        domain={dominios ? (moeda ? dominios.moeda : dominios.contagem) : undefined}
        tick={{ fill: 'rgba(255,255,255,0.65)', fontSize: 11 }}
        tickFormatter={(v) => formatTickCurto(Number(v), moeda)}
        width={82}
        label={{
          value: rotuloEixo(moeda),
          angle: lado === 'left' ? -90 : 90,
          position: lado === 'left' ? 'insideLeft' : 'insideRight',
          fill: 'rgba(255,255,255,0.45)',
          fontSize: 11,
        }}
      />
    );

    return (
      <div className="analisador-explorar-chart">
        <ResponsiveContainer width="100%" height={360}>
          <ChartComp data={visao.data} margin={{ top: 36, right: eixoDuplo ? 4 : 12, left: 8, bottom: 48 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
            <XAxis
              dataKey="name"
              tick={{ fill: 'rgba(255,255,255,0.65)', fontSize: 11 }}
              interval={0}
              angle={-25}
              textAnchor="end"
              height={60}
              label={rotuloEixoX ? {
                value: rotuloEixoX,
                position: 'insideBottom',
                offset: -2,
                fill: 'rgba(255,255,255,0.45)',
                fontSize: 11,
              } : undefined}
            />
            {eixoDuplo
              ? [eixoY(true, 'left'), eixoY(false, 'right')]
              : eixoY(visao.series[0]?.moeda ?? true, 'left')}
            <Tooltip contentStyle={tooltipStyle} itemStyle={tooltipItemStyle} formatter={tooltipFormatter} />
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
          {/* ---- Bloco 1: o que agregar ---- */}
          <fieldset className="analisador-explorar-fieldset analisador-explorar-dimensoes">
            <legend>Dados</legend>

            <p className="analisador-explorar-sublegend">
              Dimensões <span>(máx. {limites.dim})</span>
            </p>
            <div className="analisador-explorar-checks">
              {(schema?.dimensoes ?? []).map((col) => (
                <label key={col} className="analisador-check-linha">
                  <input
                    type="checkbox"
                    checked={dimensoes.includes(col)}
                    onChange={() => toggleDim(col)}
                  />
                  <span title={col}>{rotuloColuna(col)}</span>
                </label>
              ))}
            </div>

            {/* A ORDEM das dimensões decide o que é eixo e o que é série. Antes
                ela era a ordem de clique — invisível. Agora está explícita e
                reordenável. */}
            {dimensoes.length > 0 && (
              <>
                <p className="analisador-explorar-sublegend">
                  Ordem <span>(1ª = eixo{limites.dim > 1 ? ', 2ª = série' : ''})</span>
                </p>
                <ol
                  className="analisador-explorar-ordem"
                  onDragOver={(e) => {
                    // Necessário para o navegador aceitar o drop na lista.
                    e.preventDefault();
                  }}
                  onDrop={(e) => {
                    const origem = indiceArrastado(e);
                    if (origem === null) return;
                    e.preventDefault();
                    // Solto fora de um chip = vai para o fim.
                    reordenarDimensao(origem, alvoArraste ?? dimensoes.length - 1);
                    setArrastando(null);
                    setAlvoArraste(null);
                  }}
                >
                  {dimensoes.map((col, i) => (
                    <li
                      key={col}
                      className={[
                        'analisador-explorar-chip',
                        arrastando === i ? 'is-arrastando' : '',
                        alvoArraste === i && arrastando !== null && arrastando !== i ? 'is-alvo' : '',
                      ].filter(Boolean).join(' ')}
                      draggable={dimensoes.length > 1}
                      onDragStart={(e) => {
                        setArrastando(i);
                        e.dataTransfer.effectAllowed = 'move';
                        // Firefox só inicia o arraste se houver dado no transfer.
                        e.dataTransfer.setData('text/plain', String(i));
                      }}
                      onDragEnter={() => setAlvoArraste(i)}
                      onDragOver={(e) => {
                        e.preventDefault();
                        setAlvoArraste(i);
                      }}
                      onDrop={(e) => {
                        const origem = indiceArrastado(e);
                        if (origem === null) return;
                        e.preventDefault();
                        e.stopPropagation();
                        reordenarDimensao(origem, i);
                        setArrastando(null);
                        setAlvoArraste(null);
                      }}
                      onDragEnd={() => {
                        setArrastando(null);
                        setAlvoArraste(null);
                      }}
                    >
                      {/* Alça: só dica visual — o arraste é do chip inteiro. */}
                      {dimensoes.length > 1 && (
                        <GripVertical
                          size={12}
                          className="analisador-explorar-chip-alca"
                          aria-hidden="true"
                        />
                      )}
                      <span className="analisador-explorar-chip-num">{i + 1}</span>
                      <span className="analisador-explorar-chip-nome" title={col}>
                        {rotuloColuna(col)}
                      </span>
                      {/* As setas ficam: arrastar não funciona por teclado. */}
                      <button
                        type="button"
                        onClick={() => moverDimensao(i, -1)}
                        disabled={i === 0}
                        title="Mover para a esquerda"
                        aria-label={`Mover ${rotuloColuna(col)} para a esquerda`}
                      >
                        <ChevronLeft size={12} />
                      </button>
                      <button
                        type="button"
                        onClick={() => moverDimensao(i, 1)}
                        disabled={i === dimensoes.length - 1}
                        title="Mover para a direita"
                        aria-label={`Mover ${rotuloColuna(col)} para a direita`}
                      >
                        <ChevronRight size={12} />
                      </button>
                      <button
                        type="button"
                        onClick={() => toggleDim(col)}
                        disabled={dimensoes.length === 1}
                        title={dimensoes.length === 1 ? 'É preciso ao menos uma dimensão' : 'Remover'}
                        aria-label={`Remover ${rotuloColuna(col)}`}
                      >
                        <X size={12} />
                      </button>
                    </li>
                  ))}
                </ol>
              </>
            )}

            <p className="analisador-explorar-sublegend">
              Métricas <span>(máx. {limites.met})</span>
            </p>
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

          {/* ---- Bloco 2: como desenhar ---- */}
          <fieldset className="analisador-explorar-fieldset analisador-explorar-visual">
            <legend>{modo === 'grafico' ? 'Visualização' : 'Tabela'}</legend>

            {modo === 'grafico' && (
              <div className="analisador-explorar-tipos" role="radiogroup" aria-label="Tipo de gráfico">
                {TIPOS_GRAFICO.map(({ id, rotulo, Icone }) => (
                  <button
                    key={id}
                    type="button"
                    role="radio"
                    aria-checked={tipoGrafico === id}
                    className={`analisador-explorar-tipo-btn${tipoGrafico === id ? ' is-ativo' : ''}`}
                    onClick={() => setTipoGrafico(id)}
                    title={rotulo}
                  >
                    <Icone size={16} aria-hidden="true" />
                    <span>{rotulo}</span>
                  </button>
                ))}
              </div>
            )}

            {/* A explicação do tipo fica junto do controle que ela explica, não
                solta no fim do card. */}
            {modo === 'grafico' && dicaTipo && (
              <p className="analisador-hint analisador-explorar-dica-tipo">{dicaTipo}</p>
            )}

            {modo === 'grafico' && tipoGrafico === 'histograma' && (
              <label className="analisador-campo">
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

            {/* Papéis explícitos. Antes era "2ª dimensão como série": exigia
                marcar duas dimensões, colocá-las na ordem certa e ainda ligar um
                checkbox — três passos para dizer "X no eixo, Y na cor". */}
            {modo === 'grafico' && tipoAceitaSeries && (
              <div className="analisador-explorar-papeis">
                <label className="analisador-campo">
                  <span>Eixo (X)</span>
                  <select
                    className="custom-select analisador-select"
                    value={dimEixo ?? ''}
                    onChange={(e) => escolherEixo(e.target.value)}
                  >
                    {dimensoes.map((d) => (
                      <option key={d} value={d}>{rotuloColuna(d)}</option>
                    ))}
                  </select>
                </label>

                <label className="analisador-campo">
                  <span>Séries (cor)</span>
                  <select
                    className="custom-select analisador-select"
                    value={pivotAtivo && dimSerie ? dimSerie : ''}
                    disabled={dimensoes.length < 2 || compararAno}
                    title={compararAno
                      ? 'Com a comparação anual, as séries são os dois anos'
                      : dimensoes.length < 2
                        ? 'Marque uma segunda dimensão para usá-la como série'
                        : undefined}
                    onChange={(e) => escolherSerie(e.target.value || null)}
                  >
                    <option value="">
                      {compararAno ? 'Anos (comparação)' : 'Nenhuma'}
                    </option>
                    {dimensoes.filter((d) => d !== dimEixo).map((d) => (
                      <option key={d} value={d}>{rotuloColuna(d)}</option>
                    ))}
                  </select>
                </label>

                {pivotAtivo && metricas.length > 1 && (
                  <label className="analisador-campo">
                    <span>Métrica das séries</span>
                    <select
                      className="custom-select analisador-select"
                      value={metricaDoPivo ?? ''}
                      onChange={(e) => setMetricaSerie(e.target.value)}
                    >
                      {metricas.map((m) => (
                        <option key={m} value={m}>{rotuloSerie(m)}</option>
                      ))}
                    </select>
                  </label>
                )}
              </div>
            )}

            {modo === 'grafico' && (tipoGrafico === 'barras' || tipoGrafico === 'area') && (
              <label
                className="analisador-check-linha"
                title={pivotAtivo || comparacaoAtiva || metricas.length > 1
                  ? 'Empilha as séries da mesma unidade'
                  : 'Precisa de mais de uma série'}
              >
                <input
                  type="checkbox"
                  checked={empilhado}
                  disabled={!(pivotAtivo || comparacaoAtiva || metricas.length > 1)}
                  onChange={(e) => setEmpilhado(e.target.checked)}
                />
                <span>Empilhado</span>
              </label>
            )}

            {modo === 'tabela' && (
              <p className="analisador-hint">
                Clique no cabeçalho para ordenar. As colunas de participação
                (% do total e % acumulado) seguem a ordem atual.
              </p>
            )}
          </fieldset>

          {/* ---- Bloco 3: recorte e ordenação ---- */}
          <fieldset className="analisador-explorar-fieldset analisador-explorar-recorte">
            <legend>Recorte</legend>

            <div className="analisador-explorar-recorte-campos">
              <label className="analisador-campo analisador-explorar-ordenar">
                <span>Ordenar por</span>
                <select
                  className="custom-select analisador-select"
                  value={ordenacaoExibida.coluna}
                  onChange={(e) => definirOrdenacao(e.target.value)}
                >
                  {opcoesOrdenacao.map((col) => (
                    <option key={col} value={col}>{rotuloColuna(col)}</option>
                  ))}
                </select>
              </label>

              <button
                type="button"
                className="analisador-btn analisador-btn-sec analisador-btn-compact"
                onClick={() => inverterOrdenacao()}
                title={ordenacaoExibida.direcao === 'asc' ? 'Crescente — clique para inverter' : 'Decrescente — clique para inverter'}
              >
                {ordenacaoExibida.direcao === 'asc' ? <ArrowUp size={14} /> : <ArrowDown size={14} />}
                {ordenacaoExibida.direcao === 'asc' ? 'Crescente' : 'Decrescente'}
              </button>

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

            <label
              className="analisador-check-linha"
              title="Soma tudo o que ficou fora do limite numa linha/série “Outros” em vez de descartar"
            >
              <input
                type="checkbox"
                checked={agruparResto}
                onChange={(e) => setAgruparResto(e.target.checked)}
              />
              <span>Agrupar o resto em “Outros”</span>
            </label>

            <label
              className="analisador-check-linha"
              title="Traz a mesma agregação no ano anterior, no mesmo recorte de meses, com variação %"
            >
              <input
                type="checkbox"
                checked={compararAno}
                onChange={(e) => setCompararAno(e.target.checked)}
              />
              <span>Comparar com o ano anterior</span>
            </label>

            <label
              className="analisador-check-linha"
              title="Agrega os membros de cada grupo manual numa única linha de Cliente"
            >
              <input
                type="checkbox"
                checked={aplicarGrupos}
                onChange={(e) => setAplicarGrupos(e.target.checked)}
              />
              <span>Aplicar grupos manuais</span>
            </label>

            <p className="analisador-hint analisador-explorar-contagem">
              {carregando
                ? 'Atualizando…'
                : resultado && !erro
                  ? `${resultado.linhas.length.toLocaleString('pt-BR')} de ${resultado.total_linhas.toLocaleString('pt-BR')} linhas agregadas${schema ? ` · base com ${schema.linhas.toLocaleString('pt-BR')} registros` : ''}`
                  : ''}
            </p>
          </fieldset>
        </div>

        {/* Nos dois modos de série o gráfico usa só a métrica principal e as duas
            primeiras dimensões — sem dizer isso, o usuário marca mais coisas e
            não entende por que não aparecem. */}
        {(comparacaoAtiva || pivotAtivo) && metricas.length > 1 && (
          <p className="analisador-hint">
            O gráfico usa a métrica principal ({rotuloSerie(metricas[0])}); as outras
            continuam na tabela e na exportação.
          </p>
        )}
        {pivotAtivo && dimensoes.length > 2 && (
          <p className="analisador-hint">
            Eixo por {rotuloColuna(dimEixo ?? '')} e cor por {rotuloColuna(dimSerie ?? '')};
            {' '}{dimensoes.filter((d) => d !== dimEixo && d !== dimSerie).map(rotuloColuna).join(', ')}
            {' '}entra somado em cada barra.
          </p>
        )}
        {pivotAtivo && !!resultado && resultado.total_linhas > resultado.linhas.length && !agruparResto && (
          <p className="analisador-hint">
            O gráfico soma apenas as {resultado.linhas.length.toLocaleString('pt-BR')} linhas
            do limite (de {resultado.total_linhas.toLocaleString('pt-BR')}). Marque
            “Agrupar o resto em Outros” para não perder o restante.
          </p>
        )}
        {comparacaoAtiva && (
          <p className="analisador-hint">
            Comparando {resultado?.comparacao?.ano_atual} com {resultado?.comparacao?.ano_anterior}
            {resultado?.comparacao?.meses_ignorados?.length
              ? ` nos mesmos meses — ${resultado.comparacao.meses_ignorados.join(', ')} ficam de fora porque ${resultado.comparacao.ano_atual} ainda não tem esses meses.`
              : ' (todos os meses existem nos dois anos).'}
          </p>
        )}
        {resultado?.resto_agrupado && (
          <p className="analisador-hint">
            “Outros” soma as {(resultado.total_linhas - (resultado.linhas.length - 1)).toLocaleString('pt-BR')} linhas
            fora do limite. Clientes não entra nessa soma (contagem distinta não se soma).
          </p>
        )}
        {erro && (
          <p className="analisador-feedback-inline erro" role="alert">{erro}</p>
        )}
      </div>

      <div className="glass-card glass-card-flat">
        {modo === 'grafico' ? (
          <div ref={chartRef}>{renderGrafico()}</div>
        ) : (
          <ResultTable
            tabela={tabela}
            ordenacao={ordenacao}
            onOrdenar={alternarOrdenacao}
            faixaExtra={totaisTabela.length > 0 && tabela.linhas.length > 0 ? (
              <div className="analisador-faixa-totais">
                <span className="analisador-faixa-totais-rotulo">
                  Totais ({tabela.linhas.length.toLocaleString('pt-BR')} linhas exibidas
                  {resultado && resultado.total_linhas > tabela.linhas.length
                    ? ` de ${resultado.total_linhas.toLocaleString('pt-BR')}`
                    : ''})
                </span>
                {totaisTabela.map(({ metrica, soma }) => (
                  <span key={metrica} className="analisador-faixa-totais-item">
                    <span>{rotuloColuna(metrica)}</span>
                    <strong>
                      {ehMetricaMoeda(metrica) ? formatCurrency(soma) : formatNumber(soma)}
                    </strong>
                  </span>
                ))}
                {(resultado?.metricas ?? []).includes('Clientes') && (
                  <span className="analisador-faixa-totais-item">
                    <span>Clientes</span>
                    <strong title="Contagem distinta não se soma entre linhas">—</strong>
                  </span>
                )}
              </div>
            ) : null}
          />
        )}
      </div>
    </div>
  );
}
