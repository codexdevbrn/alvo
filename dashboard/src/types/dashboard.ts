export interface ProductStats {
    id: number;
    name: string;
    descricao: string;
    avg24: number;
    avg25: number;
    total: number;
}

export interface MonthlyData {
    year: number;
    name: string;
}

/** Uma linha de `rows`: [período, loja, cliente, fabricante, descrição, referência, receita, qtd] — cada posição é um índice nos `maps` correspondentes, exceto receita/qtd que são valores diretos. */
export type Row = [number, number, number, number, number, number, number, number];

export interface DashboardData {
    rows: Row[];
    monthly: MonthlyData[];
    maps: {
        c: string[];
        s: string[];
        m: string[];
        d: string[];
        r: string[];
    };
    updated_at?: string;
}

export interface AggregatedStats {
    rev: number;
    qty: number;
    cnt: number;
    monthly: Record<number, number>;
    mfrs: Record<number, number>;
    descs: Record<number, number>;
    products: Record<number, number>;
}

export interface TrendItem {
    id: number;
    name: string;
    rev24: number;
    rev25: number;
    diff: number;
    up: boolean;
}

/** Ponto do gráfico de histórico (HistoryChart) — campos além de revenueA/B são
 * usados só no modo comparação (YoY), o modo tendência preenche um subconjunto. */
export interface ChartPoint {
    name: string;
    revenueA?: number | null;
    revenueB?: number | null;
    mfrsA?: number | null;
    mfrsB?: number | null;
    descsA?: number | null;
    descsB?: number | null;
    cntA?: number | null;
    cntB?: number | null;
    clientsA?: number | null;
    clientsB?: number | null;
}

export interface AggregateResult {
    rawRev: number;
    rawCnt: number;
    rawClientCount: number;
    rev: number;
    cnt: number;
    mfrCount: number;
    descCount: number;
    clientCount: number;
    products: Record<number, number>;
    monthlyNodes: Record<number, {
        rev: number;
        mfrs: Set<number>;
        descs: Set<number>;
        products: Record<number, number>;
        clients: Set<number>;
        cnt: number;
    }>;
    len: number;
}

/** Shape de `processed.stats` em DashboardPage — consumido por MetricsGrid,
 * BreakdownSection e RevenueDetailModal. */
export interface DashboardStats {
    statsA: AggregateResult;
    statsB: AggregateResult;
    statsTotal: AggregateResult;
    topClients: TrendItem[];
    topMfrs: TrendItem[];
    topDescs: TrendItem[];
    topProducts: ProductStats[];
    chartData: ChartPoint[];
    labelA: string;
    labelB: string;
    chartLabelA: string;
    chartLabelB: string;
    yearLabel: string;
    singleYearMode: boolean;
    singleMonthMode: boolean;
    chartHasA?: boolean;
    chartHasB?: boolean;
    /** Cor de cada série do gráfico, seguindo o ano que ela representa
     * (ver `utils/coresAno`) — mesma convenção do dropdown de período. */
    chartCorA?: string;
    chartCorB?: string;
    lenA: number;
    lenB: number;
  /** Granularidade usada nos cálculos dos cards. */
  granularidade?: GranularidadeDash;
  /** Ex.: "mês" | "trimestre" — para títulos de média. */
  unidadePeriodo?: string;
  /** Performance geral = média das taxas YoY por bucket (undefined em modo tendência). */
  performancePct?: number;
  /** true quando a opção "meses fechados" está ativa nos cálculos */
  usarMesesFechados?: boolean;
  periodoDescricao?: string;
  getStatsForPeriod: (targetPeriod: number[]) => {
    chartData: ChartPoint[];
    labelA: string;
    labelB: string;
    isTrend: boolean;
    corA: string;
    corB: string;
  };
}

export type GranularidadeDash = 'Mensal' | 'Trimestral' | 'Semestral' | 'Anual';
