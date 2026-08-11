import { useState, useMemo, useEffect, useTransition, useRef, useCallback } from 'react';
import { AlertTriangle } from 'lucide-react';
import { FilterBar } from '../components/FilterBar';
import { MetricsGrid } from '../components/MetricsGrid';
import { HistoryChart } from '../components/HistoryChart';
import { BreakdownSection } from '../components/BreakdownSection';
import { RevenueDetailModal } from '../components/RevenueDetailModal';
import { LoadingScreen } from '../components/LoadingScreen';
import {
  jaExibiuSplashTelaCheia,
  marcarSplashTelaCheiaExibida,
} from '../components/splashTelaCheia';
import { gravarSummaryCache, lerSummaryCache } from '../utils/cacheSummary';
import { DashboardHeader } from '../components/DashboardHeader';
import { AppShell } from '../components/AppShell';
import { EVENTO_EMPRESA } from '../utils/empresaSelecionada';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { obterAguardandoBaseDados, obterSummaryEmpresa } from '../api/client';
import { formatCurrency, formatNumber } from '../utils/formatters';
import { COR_ANO_ANTERIOR, COR_ANO_RECENTE, corDoAno } from '../utils/coresAno';
import { descricaoPeriodoPadrao, mesDeRotulo, resolverPeriodoEfetivo, rotuloCorteFechadoParaGrafico } from '../utils/periodoFechado';
import {
  GRANULARIDADES_DASH,
  countBucketsInIndices,
  mediaTaxaYoYPorBucket,
  remapPeriodoParaGranularidade,
  rotuloUnidade,
} from '../utils/granularidade';
import {
  buildComparisonChartData,
  buildTrendChartData,
  rotulosTendencia,
} from '../utils/chartGranularidade';
import type { AggregateResult, ChartPoint, DashboardData, GranularidadeDash, ProductStats, Row, TrendItem } from '../types/dashboard';
import '../index.css';

function parseGranularidade(raw: string | null): GranularidadeDash {
  if (raw && (GRANULARIDADES_DASH as string[]).includes(raw)) return raw as GranularidadeDash;
  return 'Mensal';
}

/** Lê IDs de filtro do localStorage; [] = todos. Aceita legado (número único ou "-1"). */
function lerIdsFiltro(chave: string): number[] {
  const v = localStorage.getItem(chave);
  if (v == null || v === '' || v === '-1') return [];
  try {
    const parsed = JSON.parse(v);
    if (Array.isArray(parsed)) {
      return parsed.map(Number).filter(n => Number.isFinite(n) && n >= 0);
    }
  } catch { /* legado: número único */ }
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? [n] : [];
}

function rotuloFiltroIds(ids: number[], nomes: string[], plural: string): string | undefined {
  if (ids.length === 0) return undefined;
  if (ids.length === 1) return nomes[ids[0]];
  return `${ids.length} ${plural}`;
}

// ==========================================
// Period window helpers
// ==========================================

/** Janelas A (ano anterior) e B (ano atual) do período selecionado.
 *
 *  `alinharMesesYoY` só faz sentido para os cards: eles comparam média por mês
 *  entre os dois anos, então o ano anterior entra apenas com os meses que também
 *  existem no atual. O gráfico usa `false` — ele desenha o que foi selecionado,
 *  inclusive os meses que só existem no ano anterior (ex.: set–dez/2025 quando
 *  2026 só tem até ago). */
function calcPeriodWindows(data: DashboardData, targetPeriod: number[], alinharMesesYoY = true) {
  const availableYears = Array.from(new Set(data.monthly.map(m => m.year))).sort((a, b) => b - a);
  let pA: number[] = [];
  let pB: number[] = [];
  const yearsInSelection = Array.from(
    new Set(targetPeriod.map(idx => data.monthly[idx]?.year).filter((y): y is number => y !== undefined)),
  );
  const isTrendMode = targetPeriod.length > 0 && yearsInSelection.length === 1;

  if (!isTrendMode) {
    const lastYear = availableYears[0];
    const prevYear = availableYears[1] || lastYear;
    targetPeriod.forEach(idx => {
      const m = data.monthly[idx];
      if (!m) return;
      if (m.year === prevYear && lastYear !== prevYear) pA.push(idx);
      if (m.year === lastYear) pB.push(idx);
    });
    // YoY justo: só meses (1–12) presentes nos dois anos — evita 2025 com meses extras.
    if (alinharMesesYoY && lastYear !== prevYear && pA.length > 0 && pB.length > 0) {
      const mesesB = new Set(
        pB.map((idx) => mesDeRotulo(data.monthly[idx]?.name ?? '')).filter((m) => m > 0),
      );
      pA = pA.filter((idx) => mesesB.has(mesDeRotulo(data.monthly[idx]?.name ?? '')));
    }
  } else {
    const sortedPeriod = [...targetPeriod].sort((a, b) => a - b);
    const totalSelected = sortedPeriod.length;
    if (totalSelected === 12) {
      pB = sortedPeriod.slice(-3);
      pA = sortedPeriod.slice(0, -3);
    } else {
      const currentCount = Math.max(1, Math.min(3, Math.floor(totalSelected / 4) || 1));
      pB = sortedPeriod.slice(-currentCount);
      pA = sortedPeriod.slice(0, -currentCount);
    }
  }

  return { pA, pB, isTrendMode, yearsInSelection, availableYears };
}

// ==========================================
// Main Component
// ==========================================

export default function DashboardPage() {
  // ==========================================
  // State Definitions
  // ==========================================

  // Empresa selecionada ('' = summary.json estático, comportamento padrão).
  // Declarada aqui em cima porque o estado inicial de `data` depende dela.
  const [empresa, setEmpresa] = useState<string>(() => localStorage.getItem('alvo_empresa') || '');
  /** Espelho de `empresa` pro listener do evento da sidebar, que roda com deps []. */
  const empresaRef = useRef(empresa);
  useEffect(() => {
    empresaRef.current = empresa;
  }, [empresa]);

  const [data, setData] = useState<DashboardData | null>(() => lerSummaryCache(empresa));
  const [loading, setLoading] = useState(() => lerSummaryCache(empresa) === null);
  /**
   * O que mostrar enquanto os dados não chegam:
   *  - `splash-inicial`: primeira entrada no site — prisma em tela cheia;
   *  - `troca-de-base`: trocou a empresa — prisma só na área de conteúdo;
   *  - `silencioso`: troca de tela — nada, igual ao Analisador (com o cache,
   *    normalmente nem chega a aparecer).
   */
  const [modoCarregamento, setModoCarregamento] = useState<
    'splash-inicial' | 'troca-de-base' | 'silencioso'
  >(() => (jaExibiuSplashTelaCheia() ? 'silencioso' : 'splash-inicial'));
  // Só sai da tela de loading quando dados E 1º ciclo do traçado terminarem
  // (mesmo que os dados cheguem antes) — evita flash do desenho pela metade.
  // Só a splash de tela cheia depende do fim do traçado. Nos outros modos já
  // nasce true, senão os cálculos ficariam esperando um callback que nunca vem.
  const [introDone, setIntroDone] = useState(() => jaExibiuSplashTelaCheia());
  const handleFirstLoopDone = useCallback(() => {
    // A partir daqui a splash de tela cheia já foi vista nesta carga da
    // página: as próximas trocas de rota animam só a área de conteúdo.
    marcarSplashTelaCheiaExibida();
    setIntroDone(true);
  }, []);
  const [historyType, setHistoryType] = useState<null | 'revenue' | 'mfr' | 'desc'>(null);
  const [isComputing, startComputeTransition] = useTransition();

  const [empresaLoading, setEmpresaLoading] = useState(false);
  const [empresaError, setEmpresaError] = useState<string | null>(null);
  const [aguardandoBaseDados, setAguardandoBaseDados] = useState(false);

  // Filter States with Persistence (atualizam na hora — a UI responde imediatamente)
  // number[] vazio = todos (mesmo padrão do período)
  const [client, setClient] = useState<number[]>(() => lerIdsFiltro('alvo_client'));
  const [mfr, setMfr] = useState<number[]>(() => lerIdsFiltro('alvo_mfr'));
  const [desc, setDesc] = useState<number[]>(() => lerIdsFiltro('alvo_desc'));
  const [store, setStore] = useState<number[]>(() => lerIdsFiltro('alvo_store'));
  const [severity, setSeverity] = useState<number[]>(() => lerIdsFiltro('alvo_severity'));
  const [period, setPeriod] = useState<number[]>(() => JSON.parse(localStorage.getItem('alvo_period') || '[]'));
  const [modalPeriod, setModalPeriod] = useState<number[]>(() => JSON.parse(localStorage.getItem('alvo_period_modal') || '[]'));
  const [usarMesesFechados, setUsarMesesFechados] = useState(() => {
    const v = localStorage.getItem('alvo_meses_fechados');
    return v === null ? true : v === 'true';
  });
  const [granularidade, setGranularidade] = useState<GranularidadeDash>(() =>
    parseGranularidade(localStorage.getItem('alvo_granularidade')),
  );
  // Cálculos dos cards/breakdowns seguem em transition; o gráfico só ganha/perde a linha de corte.
  const [computeUsarMesesFechados, setComputeUsarMesesFechados] = useState(usarMesesFechados);
  const [computeGranularidade, setComputeGranularidade] = useState(granularidade);
  const chartSnapshotRef = useRef<{
    key: string;
    chartData: ChartPoint[];
    chartLabelA: string;
    chartLabelB: string;
    chartHasA: boolean;
    chartHasB: boolean;
    singleMonthMode: boolean;
  } | null>(null);
  const [visaoDetalhada, setVisaoDetalhada] = useState(() => {
    const v = localStorage.getItem('alvo_visao_detalhada');
    return v === 'true';
  });

  // Debounce: só recalcula depois que o usuário para de clicar (~300ms)
  const debouncedClient = useDebouncedValue(client, 300);
  const debouncedMfr = useDebouncedValue(mfr, 300);
  const debouncedDesc = useDebouncedValue(desc, 300);
  const debouncedStore = useDebouncedValue(store, 300);
  const debouncedSeverity = useDebouncedValue(severity, 300);
  const debouncedPeriod = useDebouncedValue(period, 300);

  // Estado de cálculo (atualizado em transition após o debounce)
  const [computeFilters, setComputeFilters] = useState({
    client: debouncedClient,
    mfr: debouncedMfr,
    desc: debouncedDesc,
    store: debouncedStore,
    severity: debouncedSeverity,
    period: debouncedPeriod,
  });

  useEffect(() => {
    startComputeTransition(() => {
      setComputeFilters({
        client: debouncedClient,
        mfr: debouncedMfr,
        desc: debouncedDesc,
        store: debouncedStore,
        severity: debouncedSeverity,
        period: debouncedPeriod,
      });
    });
  }, [debouncedClient, debouncedMfr, debouncedDesc, debouncedStore, debouncedSeverity, debouncedPeriod]);

  useEffect(() => {
    startComputeTransition(() => {
      setComputeUsarMesesFechados(usarMesesFechados);
    });
  }, [usarMesesFechados]);

  useEffect(() => {
    startComputeTransition(() => {
      setComputeGranularidade(granularidade);
    });
  }, [granularidade]);

  const filtersSettled =
    computeFilters.client === client &&
    computeFilters.mfr === mfr &&
    computeFilters.desc === desc &&
    computeFilters.store === store &&
    computeFilters.severity === severity &&
    computeFilters.period === period;

  const isFilterPending = !filtersSettled || isComputing;

  // ==========================================
  // Effects (Persistence & Data Loading)
  // ==========================================

  // Sync to LocalStorage
  useEffect(() => {
    localStorage.setItem('alvo_client', JSON.stringify(client));
    localStorage.setItem('alvo_mfr', JSON.stringify(mfr));
    localStorage.setItem('alvo_desc', JSON.stringify(desc));
    localStorage.setItem('alvo_store', JSON.stringify(store));
    localStorage.setItem('alvo_severity', JSON.stringify(severity));
    localStorage.setItem('alvo_period', JSON.stringify(period));
    localStorage.setItem('alvo_period_modal', JSON.stringify(modalPeriod));
    localStorage.setItem('alvo_meses_fechados', String(usarMesesFechados));
    localStorage.setItem('alvo_granularidade', granularidade);
    localStorage.setItem('alvo_visao_detalhada', String(visaoDetalhada));
  }, [client, mfr, desc, store, severity, period, modalPeriod, usarMesesFechados, granularidade, visaoDetalhada]);

  // Carrega os dados: summary.json estático (padrão) ou o summary processado
  // pelo backend para a empresa selecionada (lê Base.csv existente; não regenera
  // o BI automaticamente). O backend cacheia o summary por mtime do CSV.
  useEffect(() => {
    localStorage.setItem('alvo_empresa', empresa);

    let cancelado = false;

    const carregarEstatico = async (): Promise<DashboardData> => {
      const res = await fetch('/data/summary.json');
      if (!res.ok) throw new Error(`Erro ${res.status} ao carregar summary.json`);
      return res.json();
    };

    const controller = new AbortController();

    const carregar = async () => {
      setEmpresaError(null);

      // Já baixado nesta sessão: volta instantâneo, sem animação nenhuma.
      const emCache = lerSummaryCache(empresa);
      if (emCache) {
        setData(emCache);
        setLoading(false);
        setEmpresaLoading(false);
        return;
      }

      setLoading(true);
      if (modoCarregamento === 'splash-inicial') setIntroDone(false);
      if (data !== null) setEmpresaLoading(true);

      try {
        const d = empresa
          ? await obterSummaryEmpresa(empresa, controller.signal)
          : await carregarEstatico();
        if (!cancelado) {
          gravarSummaryCache(empresa, d);
          setData(d);
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        console.error('Error loading data:', err);
        if (cancelado) return;
        if (empresa) {
          setEmpresaError(err instanceof Error ? err.message : 'Falha ao carregar os dados da empresa.');
          if (data === null) {
            try {
              const d = await carregarEstatico();
              if (!cancelado) setData(d);
            } catch { /* fica na tela de erro amigável abaixo */ }
          }
        }
      } finally {
        if (!cancelado) {
          setLoading(false);
          setEmpresaLoading(false);
        }
      }
    };

    carregar();
    return () => {
      cancelado = true;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [empresa]);

  useEffect(() => {
    obterAguardandoBaseDados(false).then(setAguardandoBaseDados).catch(() => { /* mantém false */ });
  }, []);

  // Empresa da sidebar (localStorage + evento) — limpa filtros ao trocar.
  useEffect(() => {
    const aplicar = (atual: string) => {
      // Compara pelo ref (e não dentro de um updater de setEmpresa): disparar
      // outros setStates de dentro de um updater é atualização em fase de
      // render — o React pode reexecutar/descartar, e era por isso que o modo
      // de carregamento não chegava a mudar.
      if (empresaRef.current === atual) return;
      empresaRef.current = atual;
      // Trocar a base é a única transição que mostra o prisma na área de
      // conteúdo — é o carregamento pesado, o usuário precisa do retorno.
      setModoCarregamento('troca-de-base');
      setEmpresa(atual);
      setClient([]);
      setMfr([]);
      setDesc([]);
      setStore([]);
      setPeriod([]);
      setSeverity([]);
    };
    const onEvento = (e: Event) => {
      const detalhe = (e as CustomEvent<string>).detail;
      const scrollY = window.scrollY;
      aplicar(typeof detalhe === 'string' ? detalhe : localStorage.getItem('alvo_empresa') || '');
      requestAnimationFrame(() => {
        window.scrollTo({ top: scrollY, left: 0, behavior: 'auto' });
      });
    };
    const onStorageFocus = () => {
      aplicar(localStorage.getItem('alvo_empresa') || '');
    };
    window.addEventListener(EVENTO_EMPRESA, onEvento);
    window.addEventListener('storage', onStorageFocus);
    // Não escuta 'focus' da janela — ao fechar o combobox isso relia LS e podia remexer a página.
    return () => {
      window.removeEventListener(EVENTO_EMPRESA, onEvento);
      window.removeEventListener('storage', onStorageFocus);
    };
  }, []);

  // ==========================================
  // Helper Functions
  // ==========================================

  const clearFilters = () => {
    setClient([]); setMfr([]); setDesc([]); setStore([]); setPeriod([]); setSeverity([]);
    setUsarMesesFechados(true);
    setGranularidade('Mensal');
    setVisaoDetalhada(false);
  };

  const handleGranularidadeChange = (nova: GranularidadeDash) => {
    if (nova === granularidade) return;
    setGranularidade(nova);
    if (data && period.length > 0) {
      setPeriod(remapPeriodoParaGranularidade(data, period, nova));
    }
  };

  // ==========================================
  // Data Processing & Business Logic
  // ==========================================

  const processed = useMemo(() => {
    if (!data || loading || !introDone) return { stats: null, filterOptions: null, noDataMessage: null } as any;

    // Usa filtros já “assentados” (debounce + transition) — cliques rápidos não recalculam a cada mês
    const client = computeFilters.client;
    const mfr = computeFilters.mfr;
    const desc = computeFilters.desc;
    const store = computeFilters.store;
    const severity = computeFilters.severity;
    const periodoManual = computeFilters.period;
    const period = resolverPeriodoEfetivo(data, periodoManual, computeUsarMesesFechados, new Date(), computeGranularidade);
    const periodChart = resolverPeriodoEfetivo(data, periodoManual, false, new Date(), computeGranularidade);

    const { pA, pB, isTrendMode, yearsInSelection, availableYears } = calcPeriodWindows(data, period);
    const {
      pA: pAChart,
      pB: pBChart,
      isTrendMode: isTrendModeChart,
      yearsInSelection: yearsInSelectionChart,
      availableYears: availableYearsChart,
    } = calcPeriodWindows(data, periodChart, false);

    const pASet = new Set(pA);
    const pBSet = new Set(pB);
    const pAChartSet = new Set(pAChart);

    // 2. Population Filtering (Direct Filters)
    const consumerFinalId = data.maps.c.indexOf("Consumidor Final");
    const baseRows = consumerFinalId !== -1
      ? data.rows.filter(r => r[2] !== consumerFinalId)
      : data.rows;

    // Severity Calculation Setup (Needs to happen before client filter to populate client options correctly)
    let validClients: Set<number> | null = null;
    const clientSet = client.length ? new Set(client) : null;
    const mfrSet = mfr.length ? new Set(mfr) : null;
    const descSet = desc.length ? new Set(desc) : null;
    const storeSet = store.length ? new Set(store) : null;
    const severitySet = severity.length ? new Set(severity) : null;

    if (severitySet) {
      // Calculate validity based on Context (Mfr, Desc, Store) but IGNORING Client filter
      // This ensures the Client Filter Options list correctly reflects clients that match the severity
      let rowsForSev = baseRows;
      // Severity should be based on GLOBAL client performance (per store), 
      // NOT restricted by the specific product/mfr being viewed.
      // mfr/desc filters are removed here so "Critical" means "Critical Overall".
      if (storeSet) rowsForSev = rowsForSev.filter(r => storeSet.has(r[1]));

      // Fixed Reference Logic: Use Global Year vs Previous Year
      // Find the two most recent years in the dataset (e.g. 2025 and 2024)
      // This ensures the severity status ("Critical" etc) is a PROPERTY of the client based on Annual Performance
      // and does not change just because the user zoomed into "Jan 2025".
      const refYears = Array.from(new Set(data.monthly.map(m => m.year))).sort((a, b) => b - a);
      if (refYears.length >= 2) {
        const yNew = refYears[0];
        const yOld = refYears[1];

        // Referência de gravidade usa o mesmo recorte de período efetivo
        // (meses fechados por padrão, ou seleção manual).
        const refPA = data.monthly.map((m, i) => m.year === yOld && period.includes(i) ? i : -1).filter(i => i !== -1);
        const refPB = data.monthly.map((m, i) => m.year === yNew && period.includes(i) ? i : -1).filter(i => i !== -1);

        const perf: Record<number, { vA: number, vB: number }> = {};
        rowsForSev.forEach(r => {
          const pId = r[0], cId = r[2], revVal = r[6];
          if (!perf[cId]) perf[cId] = { vA: 0, vB: 0 };
          if (refPA.includes(pId)) perf[cId].vA += revVal;
          if (refPB.includes(pId)) perf[cId].vB += revVal;
        });

        const vClients = new Set<number>();
        const lenA = countBucketsInIndices(data, refPA, computeGranularidade) || 1;
        const lenB = countBucketsInIndices(data, refPB, computeGranularidade) || 1;

        Object.entries(perf).forEach(([cId, s]) => {
          // Only clients with baseline sales (previous year) can have dropped
          if (s.vA <= 0) return;

          // Compara receita média por unidade da granularidade (mês/trimestre/…)
          const valA = s.vA / lenA;
          const valB = s.vB / lenB;
          const diff = ((valB / valA) - 1) * 100;

          let cSev = -1;
          if (diff <= -8 && diff > -15) cSev = 0;
          else if (diff <= -15 && diff > -35) cSev = 1;
          else if (diff <= -35 && diff > -60) cSev = 2;
          else if (diff <= -60) cSev = 3;

          if (severitySet.has(cSev)) vClients.add(Number(cId));
        });
        validClients = vClients;
      } else {
        // Fallback: If not enough data for Global Comparison, show all
        validClients = null;
      }
    }

    let populationRows = baseRows;
    // Apply filters (OR dentro da dimensão; AND entre dimensões)
    if (clientSet) populationRows = populationRows.filter(r => clientSet.has(r[2]));
    if (mfrSet) populationRows = populationRows.filter(r => mfrSet.has(r[3]));
    if (descSet) populationRows = populationRows.filter(r => descSet.has(r[4]));
    if (storeSet) populationRows = populationRows.filter(r => storeSet.has(r[1]));

    // Apply Severity Filter (Intersection)
    if (validClients !== null) {
      populationRows = populationRows.filter(r => validClients!.has(r[2]));
    }

    // 5. Aggregation Logic
    const aggregate = (targetRows: Row[], targetPeriod: number[], forceAverage?: boolean): AggregateResult => {
      let rev = 0, cnt = 0;
      const monthlyNodes: Record<number, { rev: number, mfrs: Set<number>, descs: Set<number>, products: Record<number, number>, clients: Set<number>, cnt: number }> = {};
      const mfrs_all = new Set<number>();
      const descs_all = new Set<number>();
      const products_all: Record<number, number> = {};

      const periodSet = new Set(targetPeriod);
      for (const r of targetRows) {
        if (!periodSet.has(r[0])) continue;
        const pId = r[0], mId = r[3], dId = r[4], rId = r[5], revVal = r[6];
        rev += revVal;
        cnt++;
        mfrs_all.add(mId);
        descs_all.add(dId);
        products_all[rId] = (products_all[rId] || 0) + revVal;

        if (!monthlyNodes[pId]) monthlyNodes[pId] = { rev: 0, mfrs: new Set(), descs: new Set(), products: {}, clients: new Set(), cnt: 0 };
        monthlyNodes[pId].rev += revVal;
        monthlyNodes[pId].cnt++;
        monthlyNodes[pId].mfrs.add(mId);
        monthlyNodes[pId].descs.add(dId);
        monthlyNodes[pId].products[rId] = (monthlyNodes[pId].products[rId] || 0) + revVal;
        monthlyNodes[pId].clients.add(r[2]);
      }

      const clients_all = new Set();
      for (const r of targetRows) {
        if (periodSet.has(r[0])) clients_all.add(r[2]);
      }

      const len = countBucketsInIndices(data, targetPeriod, computeGranularidade) || 1;
      const useAvg = forceAverage ?? (targetPeriod.length > 0 && Array.from(new Set(targetPeriod.map(idx => data.monthly[idx]?.year).filter(y => y !== undefined))).length === 1);

      return {
        rawRev: rev,
        rawCnt: cnt,
        rawClientCount: clients_all.size,
        rev: useAvg ? rev / len : rev,
        cnt: useAvg ? cnt / len : cnt,
        mfrCount: useAvg ? (Object.values(monthlyNodes).reduce((acc, m) => acc + m.mfrs.size, 0) / len) : mfrs_all.size,
        descCount: useAvg ? (Object.values(monthlyNodes).reduce((acc, m) => acc + m.descs.size, 0) / len) : descs_all.size,
        clientCount: useAvg ? (Object.values(monthlyNodes).reduce((acc, m) => acc + m.clients.size, 0) / len) : clients_all.size,
        products: products_all,
        monthlyNodes,
        len
      };
    };

    const statsA = aggregate(populationRows, pA, isTrendMode);
    const statsB = aggregate(populationRows, pB, isTrendMode);
    const statsTotal = aggregate(populationRows, period, isTrendMode);
    const statsAChart = aggregate(populationRows, pAChart, isTrendModeChart);
    const statsBChart = aggregate(populationRows, pBChart, isTrendModeChart);
    const statsTotalChart = aggregate(populationRows, periodChart, isTrendModeChart);

    let chartData: ChartPoint[] = [];

    if (!isTrendModeChart) {
      chartData = buildComparisonChartData(
        data, populationRows, pAChart, pBChart, statsAChart, statsBChart, computeGranularidade,
      );
    } else {
      chartData = buildTrendChartData(
        data, periodChart, pAChartSet, statsTotalChart, computeGranularidade,
      );
    }

    const bucketsA = countBucketsInIndices(data, pA, computeGranularidade);
    const bucketsB = countBucketsInIndices(data, pB, computeGranularidade);
    const bucketsAChart = countBucketsInIndices(data, pAChart, computeGranularidade);
    const bucketsBChart = countBucketsInIndices(data, pBChart, computeGranularidade);
    const trendLabels = rotulosTendencia(computeGranularidade, bucketsA, bucketsB);
    const trendLabelsChart = rotulosTendencia(computeGranularidade, bucketsAChart, bucketsBChart);
    const labelA = isTrendMode
      ? trendLabels.labelA
      : (availableYears[1]?.toString() || "Anterior");
    const labelB = isTrendMode
      ? trendLabels.labelB
      : (availableYears[0]?.toString() || "Atual");
    const chartLabelA = isTrendModeChart
      ? trendLabelsChart.labelA
      : (availableYearsChart[1]?.toString() || "Anterior");
    const chartLabelB = isTrendModeChart
      ? (computeGranularidade === 'Mensal' ? "Receita Mensal"
        : computeGranularidade === 'Trimestral' ? "Receita Trimestral"
        : computeGranularidade === 'Semestral' ? "Receita Semestral"
        : "Receita Anual")
      : (availableYearsChart[0]?.toString() || "Atual");
    const yearLabel = isTrendMode ? (yearsInSelection[0]?.toString() || "") : (availableYears[0]?.toString() || "");

    // Cores do gráfico seguem o ano de cada série, igual ao dropdown de período:
    // em modo tendência a série única pode ser um ano anterior (dourado), não o
    // mais recente (azul).
    const anoRecenteDataset = availableYearsChart[0] ?? new Date().getFullYear();
    const chartCorA = COR_ANO_ANTERIOR;
    const chartCorB = isTrendModeChart
      ? corDoAno(yearsInSelectionChart[0] ?? anoRecenteDataset, anoRecenteDataset)
      : COR_ANO_RECENTE;

    // 6. Filter Options (population context - Independent per dimension)
    const clientOpts = new Set<number>(), mfrOpts = new Set<number>(), descOpts = new Set<number>(), storeOpts = new Set<number>();

    // For clients: ignore current client filter
    let rowsC = baseRows;
    if (mfrSet) rowsC = rowsC.filter(r => mfrSet.has(r[3]));
    if (descSet) rowsC = rowsC.filter(r => descSet.has(r[4]));
    if (storeSet) rowsC = rowsC.filter(r => storeSet.has(r[1]));
    // Apply Severity Filter to Client Options
    if (validClients !== null) rowsC = rowsC.filter(r => validClients!.has(r[2]));
    rowsC.forEach(r => clientOpts.add(r[2]));

    // For manufacturers: ignore current mfr filter
    let rowsM = baseRows;
    if (clientSet) rowsM = rowsM.filter(r => clientSet.has(r[2]));
    if (descSet) rowsM = rowsM.filter(r => descSet.has(r[4]));
    if (storeSet) rowsM = rowsM.filter(r => storeSet.has(r[1]));
    // Apply Severity Filter to Mfr Options
    if (validClients !== null) rowsM = rowsM.filter(r => validClients!.has(r[2]));
    rowsM.forEach(r => mfrOpts.add(r[3]));

    // For descriptions: ignore current desc filter
    let rowsD = baseRows;
    if (clientSet) rowsD = rowsD.filter(r => clientSet.has(r[2]));
    if (mfrSet) rowsD = rowsD.filter(r => mfrSet.has(r[3]));
    if (storeSet) rowsD = rowsD.filter(r => storeSet.has(r[1]));
    // Apply Severity Filter to Desc Options
    if (validClients !== null) rowsD = rowsD.filter(r => validClients!.has(r[2]));
    rowsD.forEach(r => descOpts.add(r[4]));

    // For stores: ignore current store filter
    let rowsS = baseRows;
    if (clientSet) rowsS = rowsS.filter(r => clientSet.has(r[2]));
    if (mfrSet) rowsS = rowsS.filter(r => mfrSet.has(r[3]));
    if (descSet) rowsS = rowsS.filter(r => descSet.has(r[4]));
    // Apply Severity Filter to Store Options
    if (validClients !== null) rowsS = rowsS.filter(r => validClients!.has(r[2]));
    rowsS.forEach(r => storeOpts.add(r[1]));

    // 7. Rankings: total do ÚLTIMO mês do período B (e o mesmo mês no ano A),
    // para bater com o BI/mês que o usuário está conferindo (ex.: jun/26 =
    // 90.681), em vez da média do YTD (ex.: 81.998).
    const pBSorted = [...pB].sort((a, b) => a - b);
    const rankBIdx = pBSorted.length > 0 ? pBSorted[pBSorted.length - 1] : -1;
    const mesRank = rankBIdx >= 0 ? mesDeRotulo(data.monthly[rankBIdx]?.name ?? '') : 0;
    const rankAIdx = mesRank > 0
      ? (pA.find((i) => mesDeRotulo(data.monthly[i]?.name ?? '') === mesRank) ?? -1)
      : -1;
    const rankBSet = rankBIdx >= 0 ? new Set([rankBIdx]) : pBSet;
    const rankASet = rankAIdx >= 0 ? new Set([rankAIdx]) : new Set<number>();
    const rankLabel = rankBIdx >= 0 ? (data.monthly[rankBIdx]?.name ?? labelB) : labelB;

    const trendSums: Record<'c' | 'm' | 'd', Record<number, { vA: number, vB: number }>> = { c: {}, m: {}, d: {} };
    populationRows.forEach(r => {
      const pid = r[0], rev = r[6];
      const inA = rankASet.has(pid);
      const inB = rankBSet.has(pid);
      if (!inA && !inB) return;
      const ids = { c: r[2], m: r[3], d: r[4] } as const;
      (Object.keys(trendSums) as Array<'c' | 'm' | 'd'>).forEach(key => {
        const id = ids[key];
        const bucket = trendSums[key];
        if (!bucket[id]) bucket[id] = { vA: 0, vB: 0 };
        if (inA) bucket[id].vA += rev;
        if (inB) bucket[id].vB += rev;
      });
    });

    const buildTrend = (mapType: 'c' | 'm' | 'd'): TrendItem[] => {
      return Object.entries(trendSums[mapType]).map(([id, v]): TrendItem | null => {
        const valA = v.vA;
        const valB = v.vB;
        if (valA === 0 && valB === 0) return null;
        return {
          id: Number(id),
          name: data.maps[mapType][Number(id)],
          rev24: valA,
          rev25: valB,
          diff: valB - valA,
          up: valB >= valA
        };
      }).filter((x): x is TrendItem => x !== null).sort((a, b) => b.rev25 - a.rev25);
    };

    // Clientes é uma dimensão bem maior que fabricante/categoria (~1300 vs
    // ~300 valores distintos) — limitamos ao top 50 como já é feito para
    // topProducts, para não montar milhares de linhas fora da área visível.
    const topClients = buildTrend('c').slice(0, 50);
    const topMfrs = buildTrend('m');
    const topDescs = buildTrend('d');

    let topProducts: ProductStats[] = [];
    const showProductView = visaoDetalhada || desc.length > 0;
    if (showProductView) {
      const prodStats: Record<number, { vA: number; vB: number; descRev: Record<number, number> }> = {};
      populationRows.forEach(r => {
        const rId = r[5], dId = r[4], pid = r[0], rev = r[6];
        if (!prodStats[rId]) prodStats[rId] = { vA: 0, vB: 0, descRev: {} };
        if (pASet.has(pid)) prodStats[rId].vA += rev;
        if (pBSet.has(pid)) prodStats[rId].vB += rev;
        prodStats[rId].descRev[dId] = (prodStats[rId].descRev[dId] || 0) + rev;
      });
      topProducts = Object.entries(prodStats).map(([id, s]) => {
        const descId = Number(
          Object.entries(s.descRev).sort(([, a], [, b]) => b - a)[0]?.[0] ?? -1,
        );
        const divA = bucketsA || 1;
        const divB = bucketsB || 1;
        return {
          id: Number(id),
          name: data.maps.r[Number(id)],
          descricao: descId >= 0 ? data.maps.d[descId] : '—',
          avg24: s.vA / divA,
          avg25: s.vB / divB,
          total: s.vA + s.vB,
        };
      }).sort((a, b) => b.total - a.total).slice(0, 50);
    }

    // Quando a seleção resulta em um único mês no gráfico principal (ex.:
    // duplo clique/"Mês atual" isolando um mês nos dois anos, ou apenas 1 mês
    // selecionado em modo tendência), uma área/linha com 1 ponto não é uma
    // boa visualização — o HistoryChart troca para barras nesse caso.
    const singleMonthMode = chartData.length === 1;

    const chartKey = JSON.stringify({ ...computeFilters, gran: computeGranularidade });
    const chartHasA = !!statsAChart.rev && !isTrendModeChart;
    const chartHasB = !!statsBChart.rev;
    let stableChart = {
      chartData,
      chartLabelA,
      chartLabelB,
      chartHasA,
      chartHasB,
      singleMonthMode,
    };
    const cached = chartSnapshotRef.current;
    if (
      cached
      && cached.key === chartKey
      && cached.chartLabelA === chartLabelA
      && cached.chartLabelB === chartLabelB
      && cached.chartHasA === chartHasA
      && cached.chartHasB === chartHasB
      && cached.singleMonthMode === singleMonthMode
      && cached.chartData.length === chartData.length
      && cached.chartData.every((p, i) => (
        p.name === chartData[i].name
        && p.revenueA === chartData[i].revenueA
        && p.revenueB === chartData[i].revenueB
      ))
    ) {
      stableChart = cached;
    } else {
      chartSnapshotRef.current = { key: chartKey, ...stableChart };
    }

    return {
      stats: {
        statsA, statsB, statsTotal, topClients, topMfrs, topDescs, topProducts,
        chartData: stableChart.chartData,
        labelA, labelB,
        rankLabel,
        chartLabelA: stableChart.chartLabelA,
        chartLabelB: stableChart.chartLabelB,
        yearLabel, singleYearMode: isTrendMode,
        singleMonthMode: stableChart.singleMonthMode,
        chartHasA: stableChart.chartHasA,
        chartHasB: stableChart.chartHasB,
        chartCorA, chartCorB,
        lenA: bucketsA, lenB: bucketsB,
        granularidade: computeGranularidade,
        unidadePeriodo: rotuloUnidade(computeGranularidade).singular,
        performancePct: isTrendMode
          ? undefined
          : mediaTaxaYoYPorBucket(
            data,
            pA,
            pB,
            (idx) => statsA.monthlyNodes[idx]?.rev || 0,
            (idx) => statsB.monthlyNodes[idx]?.rev || 0,
            computeGranularidade,
          ),
        usarMesesFechados: computeUsarMesesFechados,
        periodoDescricao: computeUsarMesesFechados
          ? descricaoPeriodoPadrao(data, new Date(), computeGranularidade)
          : undefined,
        getStatsForPeriod: (targetPeriod: number[]) => {
          const resolved = resolverPeriodoEfetivo(data, targetPeriod, false, new Date(), computeGranularidade);
          const { pA: sA, pB: sB, isTrendMode: isTrend } = calcPeriodWindows(data, resolved, false);
          const sASet = new Set(sA);

          const stA = aggregate(populationRows, sA, isTrend);
          const stB = aggregate(populationRows, sB, isTrend);

          let cData: ChartPoint[] = [];
          if (!isTrend) {
            cData = buildComparisonChartData(
              data, populationRows, sA, sB, stA, stB, computeGranularidade,
            );
          } else {
            const statsTotalModal = aggregate(populationRows, resolved, isTrend);
            cData = buildTrendChartData(
              data, resolved, sASet, statsTotalModal, computeGranularidade,
            );
          }

          const years = Array.from(new Set(resolved.map(idx => data.monthly[idx].year)));
          const yearB = isTrend ? (years[0] || '') : (availableYears[0] || '');
          const lA = isTrend ? "Baseline" : (availableYears[1]?.toString() || "Anterior");
          const lB = isTrend
            ? (historyType === 'revenue' ? `Receita ${yearB}` : (historyType === 'mfr' ? `Volume ${yearB}` : `Clientes ${yearB}`))
            : yearB.toString();

          return {
            chartData: cData,
            labelA: lA,
            labelB: lB,
            isTrend,
            corA: COR_ANO_ANTERIOR,
            corB: isTrend
              ? corDoAno(Number(yearB) || anoRecenteDataset, anoRecenteDataset)
              : COR_ANO_RECENTE,
          };
        }
      },
      filterOptions: { clientOpts, mfrOpts, descOpts, storeOpts },
      noDataMessage: populationRows.length === 0 ? "Nenhum dado encontrado para os filtros selecionados." : null
    };
  }, [data, computeFilters, historyType, computeUsarMesesFechados, computeGranularidade, visaoDetalhada, loading, introDone]);

  // ==========================================
  // Render
  // ==========================================

  // Primeira entrada no site: prisma em tela cheia, sem sidebar.
  if (modoCarregamento === 'splash-inicial' && (loading || !introDone)) {
    return <LoadingScreen onFirstLoopDone={handleFirstLoopDone} />;
  }

  // Troca de base: prisma só na área de conteúdo, sidebar viva e navegável.
  if (modoCarregamento === 'troca-de-base' && loading) {
    return (
      <AppShell>
        <LoadingScreen variante="conteudo" />
      </AppShell>
    );
  }

  // Troca de tela: nada de prisma — o Dashboard aparece quando os dados
  // chegam, igual ao Analisador. Com o cache em memória isso é instantâneo;
  // o shell vazio só aparece na 1ª visita à rota dentro da sessão.
  if (loading && !data) {
    return <AppShell><div className="dashboard-container" /></AppShell>;
  }

  const avisoBaseDados = aguardandoBaseDados ? (
    <div className="glass-card" style={{ padding: '0.85rem 1.25rem', marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
      <AlertTriangle size={18} color="#f59e0b" style={{ flexShrink: 0 }} />
      <span style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
        <strong style={{ color: 'white' }}>Base de dados em montagem.</strong> Os números abaixo podem estar incompletos ou desatualizados até a base ficar pronta.
      </span>
    </div>
  ) : null;

  // Sem dados (summary estático indisponível e/ou empresa com erro): mantém o
  // shell com Configurações na sidebar para o usuário poder corrigir.
  if (!data) {
    return (
      <AppShell>
        <div className="dashboard-container">
          <DashboardHeader
            empresa={empresa}
          />
          {avisoBaseDados}
          <div className="glass-card" style={{ padding: '4rem', textAlign: 'center' }}>
            <AlertTriangle size={48} color="#f43f5e" style={{ marginBottom: '1rem' }} />
            <h2 style={{ color: 'white' }}>Não foi possível carregar os dados</h2>
            <p style={{ color: 'var(--text-secondary)' }}>
              {aguardandoBaseDados
                ? 'A base de dados ainda está sendo montada. Volte em breve.'
                : (empresaError || 'Verifique se o backend está no ar e se as pastas fonte/trabalho estão configuradas em Configurações.')}
            </p>
          </div>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell ultimoMovimento={data?.updated_at}>
      <div className="dashboard-container">
      <DashboardHeader
        clientName={data ? rotuloFiltroIds(client, data.maps.c, 'clientes') : undefined}
        isFiltering={isFilterPending}
        empresa={empresa}
        empresaLoading={empresaLoading}
      />

      {avisoBaseDados}

      {empresaError && (
        <div className="glass-card" style={{ padding: '0.85rem 1.25rem', marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <AlertTriangle size={18} color="#f43f5e" style={{ flexShrink: 0 }} />
          <span style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Não foi possível carregar os dados de <strong style={{ color: 'white' }}>{empresa}</strong>: {empresaError}
          </span>
        </div>
      )}

      <FilterBar
        data={data!}
        filters={{ client, mfr, desc, store, severity, period, usarMesesFechados, visaoDetalhada, granularidade }}
        filterOptions={processed.filterOptions}
        setters={{
          setClient, setMfr, setDesc, setStore, setSeverity, setUsarMesesFechados, setVisaoDetalhada,
          setGranularidade: handleGranularidadeChange,
          setPeriod: (newPeriod: number[]) => {
            if (!data) {
              setPeriod(newPeriod);
              return;
            }

            const effectivePrev = resolverPeriodoEfetivo(data, period, usarMesesFechados, new Date(), granularidade);
            const effectiveNew = resolverPeriodoEfetivo(data, newPeriod, usarMesesFechados, new Date(), granularidade);

            const prevSet = new Set(effectivePrev);
            const newSet = new Set(effectiveNew);

            const added = effectiveNew.filter(p => !prevSet.has(p));
            const removed = effectivePrev.filter(p => !newSet.has(p));
            const totalChanges = added.length + removed.length;

            if (totalChanges === 1 && granularidade === 'Mensal') {
              const changedIdx = added.length ? added[0] : removed[0];
              const isAdd = added.length > 0;
              const changedMonth = data.monthly[changedIdx];

              if (changedMonth) {
                const involvedYears = Array.from(new Set(effectivePrev.map(idx => data.monthly[idx].year)));

                if (involvedYears.length >= 2) {
                  const mName = changedMonth.name.split('/')[0].toLowerCase();
                  let synced = [...newPeriod];

                  involvedYears.forEach(y => {
                    if (y === changedMonth.year) return;
                    const targetIdx = data.monthly.findIndex(m => m.year === y && m.name.split('/')[0].toLowerCase() === mName);
                    if (targetIdx === -1) return;
                    if (isAdd) {
                      if (synced.length > 0 && !synced.includes(targetIdx)) synced.push(targetIdx);
                    } else if (synced.length > 0) {
                      synced = synced.filter(idx => idx !== targetIdx);
                    }
                  });
                  setPeriod(synced);
                  return;
                }
              }
            }

            setPeriod(newPeriod);
          }
        }}
        onClear={clearFilters}
      />

      {processed.noDataMessage ? (
        <div className="glass-card" style={{ padding: '4rem', textAlign: 'center', marginBottom: '2rem' }}>
          <AlertTriangle size={48} color="#f43f5e" style={{ marginBottom: '1rem' }} />
          <h2 style={{ color: 'white' }}>Sem dados para esta seleção</h2>
          <p style={{ color: 'var(--text-secondary)' }}>{processed.noDataMessage}</p>
        </div>
      ) : (
        <div className={`dashboard-results${isFilterPending ? ' is-filtering' : ''}`}>
          <MetricsGrid
            stats={processed.stats}
            onRevenueClick={() => { setHistoryType('revenue'); setModalPeriod(period); }}
          />

          <div className="chart-grid">
            {/* A linha de corte de meses fechados só é verdade quando o recorte
                automático está valendo: com seleção manual de período os cards
                usam exatamente o que foi marcado. */}
            <HistoryChart
              chartData={processed.stats?.chartData || []}
              labelA={processed.stats?.chartLabelA || ""}
              labelB={processed.stats?.chartLabelB || ""}
              showA={!!processed.stats?.chartHasA}
              showB={!!processed.stats?.chartHasB}
              singleMonthMode={!!processed.stats?.singleMonthMode}
              corA={processed.stats?.chartCorA}
              corB={processed.stats?.chartCorB}
              usarMesesFechados={usarMesesFechados && period.length === 0}
              mesCorteFechado={usarMesesFechados && period.length === 0
                ? rotuloCorteFechadoParaGrafico(granularidade)
                : null}
              isLoading={isFilterPending}
            />

            <BreakdownSection
              key={`${visaoDetalhada ? 'det' : 'sin'}-${desc}`}
              topClients={processed.stats?.topClients || []}
              topMfrs={processed.stats?.topMfrs || []}
              topDescs={processed.stats?.topDescs || []}
              topProducts={processed.stats?.topProducts || []}
              showProductView={visaoDetalhada || desc.length > 0}
              selectedDescName={data ? rotuloFiltroIds(desc, data.maps.d, 'descrições') : undefined}
              labelA={processed.stats?.labelA || ""}
              labelB={processed.stats?.rankLabel || processed.stats?.labelB || ""}
            />
          </div>
        </div>
      )}

      <footer style={{ marginTop: '2rem', textAlign: 'center', color: 'var(--text-secondary)', paddingBottom: '2rem' }}>
        <p> 2026</p>
      </footer>

      <RevenueDetailModal
        isOpen={!!historyType && !!processed.stats}
        onClose={() => {
          setHistoryType(null);
          setModalPeriod([]);
        }}
        historyType={historyType as 'revenue' | 'mfr' | 'desc'}
        data={data!}
        stats={processed.stats}
        modalPeriod={modalPeriod}
        setModalPeriod={setModalPeriod}
        client={client}
        mfr={mfr}
        desc={desc}
        store={store}
        formatCurrency={formatCurrency}
        formatNumber={formatNumber}
        period={period}
        usarMesesFechados={usarMesesFechados}
        granularidade={granularidade}
      />
      </div>
    </AppShell>
  );
}
