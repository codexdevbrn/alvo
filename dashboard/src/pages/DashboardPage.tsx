import { useState, useMemo, useEffect, useTransition } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';
import { FilterBar } from '../components/FilterBar';
import { MetricsGrid } from '../components/MetricsGrid';
import { HistoryChart } from '../components/HistoryChart';
import { BreakdownSection } from '../components/BreakdownSection';
import { RevenueDetailModal } from '../components/RevenueDetailModal';
import { LoadingScreen } from '../components/LoadingScreen';
import { DashboardHeader } from '../components/DashboardHeader';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { obterSummaryEmpresa } from '../api/client';
import { formatCurrency, formatNumber } from '../utils/formatters';
import type { DashboardData, ProductStats, TrendItem } from '../types/dashboard';
import '../index.css';

// ==========================================
// Main Component
// ==========================================

export default function DashboardPage() {
  // ==========================================
  // State Definitions
  // ==========================================

  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [historyType, setHistoryType] = useState<null | 'revenue' | 'mfr' | 'desc'>(null);
  const [isComputing, startComputeTransition] = useTransition();

  // Empresa selecionada ('' = summary.json estático, comportamento padrão)
  const [empresa, setEmpresa] = useState<string>(() => localStorage.getItem('alvo_empresa') || '');
  const [empresaLoading, setEmpresaLoading] = useState(false);
  const [empresaError, setEmpresaError] = useState<string | null>(null);

  // Filter States with Persistence (atualizam na hora — a UI responde imediatamente)
  const [client, setClient] = useState<number>(() => { const v = localStorage.getItem('alvo_client'); return v !== null ? Number(v) : -1; });
  const [mfr, setMfr] = useState<number>(() => { const v = localStorage.getItem('alvo_mfr'); return v !== null ? Number(v) : -1; });
  const [desc, setDesc] = useState<number>(() => { const v = localStorage.getItem('alvo_desc'); return v !== null ? Number(v) : -1; });
  const [store, setStore] = useState<number>(() => { const v = localStorage.getItem('alvo_store'); return v !== null ? Number(v) : -1; });
  const [severity, setSeverity] = useState<number>(() => { const v = localStorage.getItem('alvo_severity'); return v !== null ? Number(v) : -1; });
  const [period, setPeriod] = useState<number[]>(() => JSON.parse(localStorage.getItem('alvo_period') || '[]'));
  const [modalPeriod, setModalPeriod] = useState<number[]>(() => JSON.parse(localStorage.getItem('alvo_period_modal') || '[]'));

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
    localStorage.setItem('alvo_client', client.toString());
    localStorage.setItem('alvo_mfr', mfr.toString());
    localStorage.setItem('alvo_desc', desc.toString());
    localStorage.setItem('alvo_store', store.toString());
    localStorage.setItem('alvo_severity', severity.toString());
    localStorage.setItem('alvo_period', JSON.stringify(period));
    localStorage.setItem('alvo_period_modal', JSON.stringify(modalPeriod));
  }, [client, mfr, desc, store, severity, period, modalPeriod]);

  // Carrega os dados: summary.json estático (padrão) ou o summary processado
  // pelo backend para a empresa selecionada. A primeira chamada por empresa
  // pode levar alguns segundos (CSV grande) — o backend cacheia por mtime.
  useEffect(() => {
    localStorage.setItem('alvo_empresa', empresa);

    let cancelado = false;

    const carregarEstatico = async (): Promise<DashboardData> => {
      const res = await fetch('/data/summary.json');
      if (!res.ok) throw new Error(`Erro ${res.status} ao carregar summary.json`);
      return res.json();
    };

    const carregar = async () => {
      setEmpresaError(null);
      if (data === null) setLoading(true);
      else setEmpresaLoading(true);

      try {
        const d = empresa ? await obterSummaryEmpresa(empresa) : await carregarEstatico();
        if (!cancelado) setData(d);
      } catch (err) {
        console.error('Error loading data:', err);
        if (cancelado) return;
        if (empresa) {
          setEmpresaError(err instanceof Error ? err.message : 'Falha ao carregar os dados da empresa.');
          // Sem dados na tela ainda? Cai no summary estático para não quebrar.
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
    return () => { cancelado = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [empresa]);

  const handleEmpresaChange = (nova: string) => {
    // Os filtros são índices nos maps do dataset atual — não valem para outro
    clearFilters();
    setEmpresa(nova);
  };

  // ==========================================
  // Helper Functions
  // ==========================================

  const clearFilters = () => {
    setClient(-1); setMfr(-1); setDesc(-1); setStore(-1); setPeriod([]); setSeverity(-1);
  };

  // ==========================================
  // Data Processing & Business Logic
  // ==========================================

  const processed = useMemo(() => {
    if (!data) return { stats: null, filterOptions: null, noDataMessage: null };

    // Usa filtros já “assentados” (debounce + transition) — cliques rápidos não recalculam a cada mês
    const client = computeFilters.client;
    const mfr = computeFilters.mfr;
    const desc = computeFilters.desc;
    const store = computeFilters.store;
    const severity = computeFilters.severity;
    const period = computeFilters.period;

    // 1. Calculate Period Windows
    const availableYears = Array.from(new Set(data.monthly.map(m => m.year))).sort((a, b) => b - a);
    let pA: number[] = [];
    let pB: number[] = [];
    const yearsInSelection = Array.from(new Set(period.map(idx => data.monthly[idx]?.year).filter(y => y !== undefined)));
    const isTrendMode = period.length > 0 && yearsInSelection.length === 1;

    if (!isTrendMode) {
      // Comparison Mode (YoY): 2025 vs 2024
      const lastYear = availableYears[0];
      const prevYear = availableYears[1] || lastYear;

      const targetIndices = period.length === 0 ? data.monthly.map((_, i) => i) : period;

      targetIndices.forEach(idx => {
        const m = data.monthly[idx];
        if (m.year === prevYear && lastYear !== prevYear) pA.push(idx);
        if (m.year === lastYear) pB.push(idx);
      });
    } else {
      // TREND MODE
      const sortedPeriod = [...period].sort((a, b) => a - b);
      const totalSelected = sortedPeriod.length;

      if (totalSelected === 12) {
        // Specific formula for full year: Last 3 Months (B) / Last 9 Months (A)
        pB = sortedPeriod.slice(-3);
        pA = sortedPeriod.slice(0, -3); // Corrected to take the first 9 months
      } else {
        // Proportional split: ~25% for "Current" (cap at 3), rest for "Baseline"
        // If 12Selected -> 3 vs 9. If 2Selected -> 1 vs 1.
        const currentCount = Math.max(1, Math.min(3, Math.floor(totalSelected / 4) || 1));
        pB = sortedPeriod.slice(-currentCount);
        pA = sortedPeriod.slice(0, -currentCount);
      }
    }

    const pASet = new Set(pA);
    const pBSet = new Set(pB);

    // 2. Population Filtering (Direct Filters)
    const consumerFinalId = data.maps.c.indexOf("Consumidor Final");
    const baseRows = consumerFinalId !== -1
      ? data.rows.filter(r => r[2] !== consumerFinalId)
      : data.rows;

    // Severity Calculation Setup (Needs to happen before client filter to populate client options correctly)
    let validClients: Set<number> | null = null;

    if (severity !== -1) {
      // Calculate validity based on Context (Mfr, Desc, Store) but IGNORING Client filter
      // This ensures the Client Filter Options list correctly reflects clients that match the severity
      let rowsForSev = baseRows;
      // Severity should be based on GLOBAL client performance (per store), 
      // NOT restricted by the specific product/mfr being viewed.
      // mfr/desc filters are removed here so "Critical" means "Critical Overall".
      if (store !== -1) rowsForSev = rowsForSev.filter(r => r[1] === store);

      // Fixed Reference Logic: Use Global Year vs Previous Year
      // Find the two most recent years in the dataset (e.g. 2025 and 2024)
      // This ensures the severity status ("Critical" etc) is a PROPERTY of the client based on Annual Performance
      // and does not change just because the user zoomed into "Jan 2025".
      const refYears = Array.from(new Set(data.monthly.map(m => m.year))).sort((a, b) => b - a);
      if (refYears.length >= 2) {
        const yNew = refYears[0];
        const yOld = refYears[1];

        // Get all month indices for these years (FULL YEAR comparison)
        const refPA = data.monthly.map((m, i) => m.year === yOld ? i : -1).filter(i => i !== -1);
        const refPB = data.monthly.map((m, i) => m.year === yNew ? i : -1).filter(i => i !== -1);

        const perf: Record<number, { vA: number, vB: number }> = {};
        rowsForSev.forEach(r => {
          const pId = r[0], cId = r[2], revVal = r[6];
          if (!perf[cId]) perf[cId] = { vA: 0, vB: 0 };
          if (refPA.includes(pId)) perf[cId].vA += revVal;
          if (refPB.includes(pId)) perf[cId].vB += revVal;
        });

        const vClients = new Set<number>();
        const lenA = refPA.length || 1;
        const lenB = refPB.length || 1;

        Object.entries(perf).forEach(([cId, s]: [string, any]) => {
          // Only clients with baseline sales (previous year) can have dropped
          if (s.vA <= 0) return;

          // Compare Average Monthly Revenue of New Year vs Old Year
          const valA = s.vA / lenA;
          const valB = s.vB / lenB;
          const diff = ((valB / valA) - 1) * 100;

          let cSev = -1;
          if (diff <= -8 && diff > -15) cSev = 0;
          else if (diff <= -15 && diff > -35) cSev = 1;
          else if (diff <= -35 && diff > -60) cSev = 2;
          else if (diff <= -60) cSev = 3;

          if (cSev === severity) vClients.add(Number(cId));
        });
        validClients = vClients;
      } else {
        // Fallback: If not enough data for Global Comparison, show all
        validClients = null;
      }
    }

    let populationRows = baseRows;
    // Apply filters
    if (client !== -1) populationRows = populationRows.filter(r => r[2] === client);
    if (mfr !== -1) populationRows = populationRows.filter(r => r[3] === mfr);
    if (desc !== -1) populationRows = populationRows.filter(r => r[4] === desc);
    if (store !== -1) populationRows = populationRows.filter(r => r[1] === store);

    // Apply Severity Filter (Intersection)
    if (validClients !== null) {
      populationRows = populationRows.filter(r => validClients!.has(r[2]));
    }

    // 5. Aggregation Logic
    const aggregate = (targetRows: any[], targetPeriod: number[], forceAverage?: boolean): any => {
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

      const len = targetPeriod.length || 1;
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
    const statsTotal = aggregate(populationRows, period.length === 0 ? data.monthly.map((_, i) => (data.monthly[i].year === availableYears[0]) ? i : -1).filter(x => x !== -1) : period, isTrendMode);

    const isComparisonMode = !isTrendMode;
    let chartData: any[] = [];

    if (isComparisonMode) {
      const monthMap: any = {};

      [...pA, ...pB].forEach(idx => {
        const m = data.monthly[idx];
        if (!m) return;
        const mName = m.name.split('/')[0];
        if (!monthMap[mName]) monthMap[mName] = { revenueA: 0, revenueB: 0, mfrsA: 0, mfrsB: 0, descsA: 0, descsB: 0, cntA: 0, cntB: 0, clientsA: 0, clientsB: 0 };

        const node = statsA.monthlyNodes[idx] || statsB.monthlyNodes[idx];
        if (node) {
          if (pASet.has(idx)) {
            monthMap[mName].revenueA += node.rev;
            monthMap[mName].mfrsA += node.mfrs.size;
            monthMap[mName].descsA += node.descs.size;
            // For clients/count, we use the raw numbers for comparison
            let kCount = 0;
            populationRows.forEach(r => { if (r[0] === idx) { kCount++; } });
            monthMap[mName].cntA = kCount;
            monthMap[mName].clientsA = node.clients.size;
          }
          if (pBSet.has(idx)) {
            monthMap[mName].revenueB += node.rev;
            monthMap[mName].mfrsB += node.mfrs.size;
            monthMap[mName].descsB += node.descs.size;
            let kCount = 0;
            populationRows.forEach(r => { if (r[0] === idx) { kCount++; } });
            monthMap[mName].cntB = kCount;
            monthMap[mName].clientsB = node.clients.size;
          }
        }
      });

      const uniqueOrder = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
      chartData = uniqueOrder
        .filter(m => monthMap[m])
        .map(m => ({ name: m, ...monthMap[m] }));
    } else {
      // Trend Mode: Continuous line with split colors if possible, but for now single series
      chartData = [...period].sort((a, b) => a - b).map(idx => {
        let cNodes = statsTotal.monthlyNodes[idx];
        const isA = pASet.has(idx);
        const m = data.monthly[idx];
        return {
          name: m?.name || '?',
          revenueA: isA ? (cNodes?.rev || 0) : null,
          revenueB: (cNodes?.rev || 0),
          cntA: isA ? (cNodes?.cnt || 0) : null,
          cntB: (cNodes?.cnt || 0),
          clientsA: isA ? (cNodes?.clients.size || 0) : null,
          clientsB: (cNodes?.clients.size || 0)
        };
      });
    }

    const labelA = isTrendMode
      ? (pA.length > 0 ? (pA.length === 1 ? "Mês Ant." : `Média ${pA.length} Meses Ant.`) : "")
      : (availableYears[1]?.toString() || "Anterior");
    const labelB = isTrendMode
      ? (pB.length === 1 ? "Mês Atual" : `Média últ. ${pB.length} Meses`)
      : (availableYears[0]?.toString() || "Atual");
    const chartLabelA = labelA;
    const chartLabelB = isTrendMode ? "Receita Mensal" : labelB;
    const yearLabel = isTrendMode ? (yearsInSelection[0]?.toString() || "") : (availableYears[0]?.toString() || "");

    // 6. Filter Options (population context - Independent per dimension)
    const clientOpts = new Set<number>(), mfrOpts = new Set<number>(), descOpts = new Set<number>(), storeOpts = new Set<number>();

    // For clients: ignore current client filter
    let rowsC = baseRows;
    if (mfr !== -1) rowsC = rowsC.filter(r => r[3] === mfr);
    if (desc !== -1) rowsC = rowsC.filter(r => r[4] === desc);
    if (store !== -1) rowsC = rowsC.filter(r => r[1] === store);
    // Apply Severity Filter to Client Options
    if (validClients !== null) rowsC = rowsC.filter(r => validClients!.has(r[2]));
    rowsC.forEach(r => clientOpts.add(r[2]));

    // For manufacturers: ignore current mfr filter
    let rowsM = baseRows;
    if (client !== -1) rowsM = rowsM.filter(r => r[2] === client);
    if (desc !== -1) rowsM = rowsM.filter(r => r[4] === desc);
    if (store !== -1) rowsM = rowsM.filter(r => r[1] === store);
    // Apply Severity Filter to Mfr Options
    if (validClients !== null) rowsM = rowsM.filter(r => validClients!.has(r[2]));
    rowsM.forEach(r => mfrOpts.add(r[3]));

    // For descriptions: ignore current desc filter
    let rowsD = baseRows;
    if (client !== -1) rowsD = rowsD.filter(r => r[2] === client);
    if (mfr !== -1) rowsD = rowsD.filter(r => r[3] === mfr);
    if (store !== -1) rowsD = rowsD.filter(r => r[1] === store);
    // Apply Severity Filter to Desc Options
    if (validClients !== null) rowsD = rowsD.filter(r => validClients!.has(r[2]));
    rowsD.forEach(r => descOpts.add(r[4]));

    // For stores: ignore current store filter
    let rowsS = baseRows;
    if (client !== -1) rowsS = rowsS.filter(r => r[2] === client);
    if (mfr !== -1) rowsS = rowsS.filter(r => r[3] === mfr);
    if (desc !== -1) rowsS = rowsS.filter(r => r[4] === desc);
    // Apply Severity Filter to Store Options
    if (validClients !== null) rowsS = rowsS.filter(r => validClients!.has(r[2]));
    rowsS.forEach(r => storeOpts.add(r[1]));

    // 7. Rankings and Charts based on rowsDisplay
    // Single pass over populationRows accumulating client/mfr/desc trend sums
    // together (instead of one full pass per dimension), using Sets for O(1)
    // period membership instead of Array.includes.
    const trendSums: Record<'c' | 'm' | 'd', Record<number, { vA: number, vB: number }>> = { c: {}, m: {}, d: {} };
    populationRows.forEach(r => {
      const pid = r[0], rev = r[6];
      const inA = pASet.has(pid);
      const inB = pBSet.has(pid);
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
      return Object.entries(trendSums[mapType]).map(([id, v]) => {
        const valA = isTrendMode ? (v.vA / (pA.length || 1)) : v.vA;
        const valB = isTrendMode ? (v.vB / (pB.length || 1)) : v.vB;
        if (valA === 0 && valB === 0) return null;
        return {
          id: Number(id),
          name: data.maps[mapType][Number(id)],
          rev24: valA,
          rev25: valB,
          diff: valB - valA,
          up: valB >= valA
        };
      }).filter(x => x !== null).sort((a: any, b: any) => (b.rev24 + b.rev25) - (a.rev24 + a.rev25)) as TrendItem[];
    };

    // Clientes é uma dimensão bem maior que fabricante/categoria (~1300 vs
    // ~300 valores distintos) — limitamos ao top 50 como já é feito para
    // topProducts, para não montar milhares de linhas fora da área visível.
    const topClients = buildTrend('c').slice(0, 50);
    const topMfrs = buildTrend('m');
    const topDescs = buildTrend('d');

    let topProducts: ProductStats[] = [];
    if (desc !== -1) {
      const prodStats: Record<number, { vA: number, vB: number }> = {};
      populationRows.forEach(r => {
        const rId = r[5], pid = r[0], rev = r[6];
        if (!prodStats[rId]) prodStats[rId] = { vA: 0, vB: 0 };
        if (pASet.has(pid)) prodStats[rId].vA += rev;
        if (pBSet.has(pid)) prodStats[rId].vB += rev;
      });
      topProducts = Object.entries(prodStats).map(([id, s]) => ({
        id: Number(id),
        name: data.maps.r[Number(id)],
        avg24: isTrendMode ? (s.vA / (pA.length || 1)) : s.vA,
        avg25: isTrendMode ? (s.vB / (pB.length || 1)) : s.vB,
        total: s.vA + s.vB
      })).sort((a, b) => b.total - a.total).slice(0, 50);
    }

    // Quando a seleção resulta em um único mês no gráfico principal (ex.:
    // duplo clique/"Mês atual" isolando um mês nos dois anos, ou apenas 1 mês
    // selecionado em modo tendência), uma área/linha com 1 ponto não é uma
    // boa visualização — o HistoryChart troca para barras nesse caso.
    const singleMonthMode = chartData.length === 1;

    return {
      stats: {
        statsA, statsB, statsTotal, topClients, topMfrs, topDescs, topProducts, chartData,
        labelA, labelB, chartLabelA, chartLabelB, yearLabel, singleYearMode: isTrendMode, singleMonthMode,
        lenA: pA.length, lenB: pB.length,
        // Helper to get stats for any period (used by modal)
        getStatsForPeriod: (targetPeriod: number[]) => {
          let sA: number[] = [];
          let sB: number[] = [];
          const years = Array.from(new Set(targetPeriod.map(idx => data.monthly[idx].year)));
          const isTrend = targetPeriod.length > 0 && years.length === 1;
          let sorted: number[] = [];

          if (!isTrend) {
            const lastYear = availableYears[0];
            const prevYear = availableYears[1] || lastYear;
            const tIdx = targetPeriod.length === 0 ? data.monthly.map((_, i) => i) : targetPeriod;
            tIdx.forEach(idx => {
              const m = data.monthly[idx];
              if (m.year === prevYear && lastYear !== prevYear) sA.push(idx);
              if (m.year === lastYear) sB.push(idx);
            });
          } else {
            sorted = [...targetPeriod].sort((a, b) => a - b);
            const total = sorted.length;
            const currentCount = Math.max(1, Math.min(3, Math.floor(total / 4) || 1));
            sB = sorted.slice(-currentCount);
            sA = sorted.slice(0, -currentCount);
          }

          const stA = aggregate(populationRows, sA);
          const stB = aggregate(populationRows, sB);

          let cData: any[] = [];
          if (!isTrend) {
            const mMap: any = {};
            const sASet = new Set(sA);
            const sBSet = new Set(sB);
            [...sA, ...sB].forEach(idx => {
              const mName = data.monthly[idx].name.split('/')[0];
              if (!mMap[mName]) mMap[mName] = { revenueA: 0, revenueB: 0, cntA: 0, cntB: 0, clientsA: 0, clientsB: 0 };
              const node = stA.monthlyNodes[idx] || stB.monthlyNodes[idx];
              if (node) {
                if (sASet.has(idx)) {
                  mMap[mName].revenueA += node.rev;
                  mMap[mName].cntA = node.cnt;
                  mMap[mName].clientsA = node.clients.size;
                }
                if (sBSet.has(idx)) {
                  mMap[mName].revenueB += node.rev;
                  mMap[mName].cntB = node.cnt;
                  mMap[mName].clientsB = node.clients.size;
                }
              }
            });
            const uniqueOrder = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
            cData = uniqueOrder.filter(m => mMap[m]).map(m => ({ name: m, ...mMap[m] }));
          } else {
            const sASet = new Set(sA);
            cData = sorted.map((idx: number) => {
              const node = stA.monthlyNodes[idx] || stB.monthlyNodes[idx];
              const isA = sASet.has(idx);
              return {
                name: data.monthly[idx].name,
                revenueA: isA ? (node?.rev || 0) : null,
                revenueB: (node?.rev || 0),
                cntA: isA ? (node?.cnt || 0) : null,
                cntB: (node?.cnt || 0),
                clientsA: isA ? (node?.clients.size || 0) : null,
                clientsB: (node?.clients.size || 0)
              };
            });
          }

          const yearB = isTrend ? (years[0] || '') : (availableYears[0] || '');
          const lA = isTrend ? "Baseline" : (availableYears[1]?.toString() || "Anterior");
          const lB = isTrend
            ? (historyType === 'revenue' ? `Receita ${yearB}` : (historyType === 'mfr' ? `Volume ${yearB}` : `Clientes ${yearB}`))
            : yearB.toString();

          return { chartData: cData, labelA: lA, labelB: lB, isTrend };
        }
      },
      filterOptions: { clientOpts, mfrOpts, descOpts, storeOpts },
      noDataMessage: populationRows.length === 0 ? "Nenhum dado encontrado para os filtros selecionados." : null
    };
  }, [data, computeFilters]);

  // ==========================================
  // Render
  // ==========================================

  if (loading) return <LoadingScreen />;

  // Sem dados (summary estático indisponível e/ou empresa com erro): mantém o
  // header com o seletor/engrenagem visível para o usuário poder corrigir.
  if (!data) {
    return (
      <div className="dashboard-container">
        <DashboardHeader
          empresa={empresa}
          onEmpresaChange={handleEmpresaChange}
          empresaLoading={empresaLoading}
        />
        <div className="glass-card" style={{ padding: '4rem', textAlign: 'center' }}>
          <AlertTriangle size={48} color="#f43f5e" style={{ marginBottom: '1rem' }} />
          <h2 style={{ color: 'white' }}>Não foi possível carregar os dados</h2>
          <p style={{ color: 'var(--text-secondary)' }}>
            {empresaError || 'Verifique se o backend está no ar e se o caminho dos dados está configurado (engrenagem no topo).'}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard-container">
      <DashboardHeader
        updatedAt={data?.updated_at}
        clientName={client !== -1 ? data?.maps.c[client] : undefined}
        isFiltering={isFilterPending}
        empresa={empresa}
        onEmpresaChange={handleEmpresaChange}
        empresaLoading={empresaLoading}
      />

      {empresaError && (
        <div className="glass-card" style={{ padding: '0.85rem 1.25rem', marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <AlertTriangle size={18} color="#f43f5e" style={{ flexShrink: 0 }} />
          <span style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Não foi possível carregar os dados de <strong style={{ color: 'white' }}>{empresa}</strong>: {empresaError}
          </span>
        </div>
      )}

      {empresaLoading && (
        <div className="glass-card" style={{ padding: '0.85rem 1.25rem', marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <Loader2 size={18} className="dashboard-filter-spinner" style={{ color: 'var(--accent)', flexShrink: 0 }} />
          <span style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Processando a base de <strong style={{ color: 'white' }}>{empresa || 'dados padrão'}</strong>… a primeira carga pode levar alguns segundos.
          </span>
        </div>
      )}

      <FilterBar
        data={data!}
        filters={{ client, mfr, desc, store, severity, period }}
        filterOptions={processed.filterOptions}
        setters={{
          setClient, setMfr, setDesc, setStore, setSeverity,
          setPeriod: (newPeriod: number[]) => {
            // Enhanced Period Logic: Sync Months across Years
            if (!data) {
              setPeriod(newPeriod);
              return;
            }

            const allIndices = data.monthly.map((_, i) => i);
            const effectivePrev = period.length === 0 ? allIndices : period;
            const effectiveNew = newPeriod.length === 0 ? allIndices : newPeriod;

            const prevSet = new Set(effectivePrev);
            const newSet = new Set(effectiveNew);

            // Identify changes
            const added = effectiveNew.filter(p => !prevSet.has(p));
            const removed = effectivePrev.filter(p => !newSet.has(p));
            const totalChanges = added.length + removed.length;

            if (totalChanges === 1) {
              const changedIdx = added.length ? added[0] : removed[0];
              const isAdd = added.length > 0;
              const changedMonth = data.monthly[changedIdx];

              if (changedMonth) {
                // Check involved years to see if we are in a multi-year context
                // We consider 'effectivePrev' years as the context.
                const involvedYears = Array.from(new Set(effectivePrev.map(idx => data.monthly[idx].year)));

                // Only sync if we have multiple years involved (Comparison Mode)
                if (involvedYears.length >= 2) {
                  const mName = changedMonth.name.split('/')[0].toLowerCase();

                  involvedYears.forEach(y => {
                    if (y === changedMonth.year) return;

                    // Find corresponding month in this other year
                    const targetIdx = data.monthly.findIndex(m => m.year === y && m.name.split('/')[0].toLowerCase() === mName);

                    if (targetIdx !== -1) {
                      if (isAdd) {
                        // If adding, ensure target is in newPeriod
                        // If newPeriod is [], it implicitly has it, unless we change that?
                        // Actually, if newPeriod is [], it means All, so it HAS it.
                        // We only need to act if newPeriod is NOT empty.
                        if (newPeriod.length > 0) {
                          if (!newPeriod.includes(targetIdx)) {
                            newPeriod.push(targetIdx);
                          }
                        }
                      } else {
                        // If removing, we MUST remove target from newPeriod.
                        // If newPeriod was [] (All), we can't simply remove.
                        // But wait, if we are part of a 'remove' action, newPeriod CANNOT be [] (All),
                        // because we just removed something from effectivePrev. 
                        // So newPeriod IS explicit list (allIndices minus removed).
                        // So we can safely filter.
                        if (newPeriod.length > 0) {
                          newPeriod = newPeriod.filter(idx => idx !== targetIdx);
                        }
                      }
                    }
                  });
                }
              }
            }

            // Safety: if we reconstructed "All", revert to empty array
            if (newPeriod.length === data.monthly.length) {
              newPeriod = [];
            } else {
              // Ensure sorting or uniqueness if needed, but not strictly required by logic
              // newPeriod = Array.from(new Set(newPeriod)).sort((a,b) => a-b);
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
            <HistoryChart
              chartData={processed.stats?.chartData || []}
              labelA={processed.stats?.chartLabelA || ""}
              labelB={processed.stats?.chartLabelB || ""}
              showA={!!processed.stats?.statsA?.rev && !processed.stats?.singleYearMode}
              showB={!!processed.stats?.statsB?.rev}
              singleMonthMode={!!processed.stats?.singleMonthMode}
            />

            <BreakdownSection
              topClients={processed.stats?.topClients || []}
              topMfrs={processed.stats?.topMfrs || []}
              topDescs={processed.stats?.topDescs || []}
              topProducts={processed.stats?.topProducts || []}
              isDescFiltered={desc !== -1}
              selectedDescName={desc !== -1 ? data?.maps.d[desc] : undefined}
              labelA={processed.stats?.labelA || ""}
              labelB={processed.stats?.labelB || ""}
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
      />
    </div>
  );
}
