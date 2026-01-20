import { useState, useMemo, useEffect } from 'react';
import { RefreshCw, AlertTriangle, X, TrendingUp, DollarSign, ShoppingCart, Users } from 'lucide-react';
import { PeriodSelector } from './components/PeriodSelector';
import { FilterBar } from './components/FilterBar';
import { MetricsGrid } from './components/MetricsGrid';
import { HistoryChart } from './components/HistoryChart';
import { BreakdownSection } from './components/BreakdownSection';
import { formatCurrency, formatNumber } from './utils/formatters';
import type { DashboardData, ProductStats, AggregatedStats, TrendItem } from './types/dashboard';
import './index.css';

export default function App() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [historyType, setHistoryType] = useState<null | 'revenue' | 'mfr' | 'desc'>(null);

  // Filter States with Persistence
  const [client, setClient] = useState<number>(() => { const v = localStorage.getItem('alvo_client'); return v !== null ? Number(v) : -1; });
  const [mfr, setMfr] = useState<number>(() => { const v = localStorage.getItem('alvo_mfr'); return v !== null ? Number(v) : -1; });
  const [desc, setDesc] = useState<number>(() => { const v = localStorage.getItem('alvo_desc'); return v !== null ? Number(v) : -1; });
  const [store, setStore] = useState<number>(() => { const v = localStorage.getItem('alvo_store'); return v !== null ? Number(v) : -1; });
  const [severity, setSeverity] = useState<number>(() => { const v = localStorage.getItem('alvo_severity'); return v !== null ? Number(v) : -1; });
  const [period, setPeriod] = useState<number[]>(() => JSON.parse(localStorage.getItem('alvo_period') || '[]'));
  const [modalPeriod, setModalPeriod] = useState<number[]>(() => JSON.parse(localStorage.getItem('alvo_period_modal') || '[]'));

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

  useEffect(() => {
    fetch('/src/data/summary.json')
      .then(res => res.json())
      .then(d => {
        setData(d);
        setLoading(false);
      })
      .catch(err => {
        console.error("Error loading data:", err);
        setLoading(false);
      });
  }, []);

  const clearFilters = () => {
    setClient(-1); setMfr(-1); setDesc(-1); setStore(-1); setPeriod([]); setSeverity(-1);
  };

  const processed = useMemo(() => {
    if (!data) return { stats: null, filterOptions: null, noDataMessage: null };

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
        pA = sortedPeriod.slice(-9);
      } else {
        // Proportional split: ~25% for "Current" (cap at 3), rest for "Baseline"
        // If 12Selected -> 3 vs 9. If 2Selected -> 1 vs 1.
        const currentCount = Math.max(1, Math.min(3, Math.floor(totalSelected / 4) || 1));
        pB = sortedPeriod.slice(-currentCount);
        pA = sortedPeriod.slice(0, -currentCount);
      }
    }

    // 2. Population Filtering (Direct Filters)
    const consumerFinalId = data.maps.c.indexOf("Consumidor Final");
    const baseRows = consumerFinalId !== -1
      ? data.rows.filter(r => r[2] !== consumerFinalId)
      : data.rows;

    let populationRows = baseRows;
    if (client !== -1) populationRows = populationRows.filter(r => r[2] === client);
    if (mfr !== -1) populationRows = populationRows.filter(r => r[3] === mfr);
    if (desc !== -1) populationRows = populationRows.filter(r => r[4] === desc);
    if (store !== -1) populationRows = populationRows.filter(r => r[1] === store);

    if (severity !== -1) {
      const perf: Record<number, { vA: number, vB: number }> = {};
      populationRows.forEach(r => {
        const pId = r[0], cId = r[2], revVal = r[6];
        if (!perf[cId]) perf[cId] = { vA: 0, vB: 0 };
        if (pA.includes(pId)) perf[cId].vA += revVal;
        if (pB.includes(pId)) perf[cId].vB += revVal;
      });

      const validClients = new Set();
      Object.entries(perf).forEach(([cId, s]: [string, any]) => {
        if (s.vA <= 0) return;
        const diff = ((s.vB / (isTrendMode ? (pB.length || 1) : 1)) / (s.vA / (isTrendMode ? (pA.length || 1) : 1)) - 1) * 100;
        let cSev = -1;
        if (diff <= -8 && diff > -15) cSev = 0;
        else if (diff <= -15 && diff > -35) cSev = 1;
        else if (diff <= -35 && diff > -60) cSev = 2;
        else if (diff <= -60) cSev = 3;
        if (cSev === severity) validClients.add(Number(cId));
      });
      populationRows = populationRows.filter(r => validClients.has(r[2]));
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
      const pASet = new Set(pA);
      const pBSet = new Set(pB);

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
      const pASet = new Set(pA); // Added pASet for trend mode
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
    rowsC.forEach(r => clientOpts.add(r[2]));

    // For manufacturers: ignore current mfr filter
    let rowsM = baseRows;
    if (client !== -1) rowsM = rowsM.filter(r => r[2] === client);
    if (desc !== -1) rowsM = rowsM.filter(r => r[4] === desc);
    if (store !== -1) rowsM = rowsM.filter(r => r[1] === store);
    rowsM.forEach(r => mfrOpts.add(r[3]));

    // For descriptions: ignore current desc filter
    let rowsD = baseRows;
    if (client !== -1) rowsD = rowsD.filter(r => r[2] === client);
    if (mfr !== -1) rowsD = rowsD.filter(r => r[3] === mfr);
    if (store !== -1) rowsD = rowsD.filter(r => r[1] === store);
    rowsD.forEach(r => descOpts.add(r[4]));

    // For stores: ignore current store filter
    let rowsS = baseRows;
    if (client !== -1) rowsS = rowsS.filter(r => r[2] === client);
    if (mfr !== -1) rowsS = rowsS.filter(r => r[3] === mfr);
    if (desc !== -1) rowsS = rowsS.filter(r => r[4] === desc);
    rowsS.forEach(r => storeOpts.add(r[1]));

    // 7. Rankings and Charts based on rowsDisplay
    const getTrend = (mapType: 'm' | 'd'): TrendItem[] => {
      const trends: Record<number, { vA: number, vB: number }> = {};
      const idx = mapType === 'm' ? 3 : 4;
      // In trend mode we use the trend windows, in YoY we split 2024/2025
      populationRows.forEach(r => {
        const pid = r[0], id = r[idx], rev = r[6];
        if (!trends[id]) trends[id] = { vA: 0, vB: 0 };
        if (pA.includes(pid)) trends[id].vA += rev;
        if (pB.includes(pid)) trends[id].vB += rev;
      });
      return Object.entries(trends).map(([id, v]) => {
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

    let topProducts: ProductStats[] = [];
    if (desc !== -1) {
      const prodStats: Record<number, { vA: number, vB: number }> = {};
      populationRows.forEach(r => {
        const rId = r[5], pid = r[0], rev = r[6];
        if (!prodStats[rId]) prodStats[rId] = { vA: 0, vB: 0 };
        if (pA.includes(pid)) prodStats[rId].vA += rev;
        if (pB.includes(pid)) prodStats[rId].vB += rev;
      });
      topProducts = Object.entries(prodStats).map(([id, s]) => ({
        id: Number(id),
        name: data.maps.r[Number(id)],
        avg24: isTrendMode ? (s.vA / (pA.length || 1)) : s.vA,
        avg25: isTrendMode ? (s.vB / (pB.length || 1)) : s.vB,
        total: s.vA + s.vB
      })).sort((a, b) => b.total - a.total).slice(0, 50);
    }

    return {
      stats: {
        statsA, statsB, statsTotal, topMfrs: getTrend('m'), topDescs: getTrend('d'), topProducts, chartData,
        labelA, labelB, chartLabelA, chartLabelB, yearLabel, singleYearMode: isTrendMode,
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
  }, [data, client, mfr, desc, store, severity, period]);

  if (loading) return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-main)' }}>
      <RefreshCw className="animate-spin" size={48} color="var(--accent)" />
      <p style={{ marginTop: '1.5rem', color: 'var(--text-secondary)' }}>Carregando dados...</p>
    </div>
  );

  return (
    <div className="dashboard-container">
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem' }}>
        <h1 style={{ color: '#fff', fontSize: '2.5rem', fontWeight: 'bold', margin: 0 }}>Alvo</h1>
        <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', textAlign: 'right' }}>
          Atualizado em: <span style={{ color: 'white', fontWeight: 500 }}>{data?.updated_at || 'Carregando...'}</span>
        </div>
      </header>

      <FilterBar
        data={data!}
        filters={{ client, mfr, desc, store, severity, period }}
        filterOptions={processed.filterOptions}
        setters={{ setClient, setMfr, setDesc, setStore, setSeverity, setPeriod }}
        onClear={clearFilters}
      />

      {processed.noDataMessage ? (
        <div className="glass-card" style={{ padding: '4rem', textAlign: 'center', marginBottom: '2rem' }}>
          <AlertTriangle size={48} color="#f43f5e" style={{ marginBottom: '1rem' }} />
          <h2 style={{ color: 'white' }}>Sem dados para esta seleção</h2>
          <p style={{ color: 'var(--text-secondary)' }}>{processed.noDataMessage}</p>
        </div>
      ) : (
        <>
          <MetricsGrid
            stats={processed.stats}
            onRevenueClick={() => { setHistoryType('revenue'); setModalPeriod(period); }}
            onClientsClick={() => { setHistoryType('desc'); setModalPeriod(period); }}
          />

          <div className="chart-grid">
            <HistoryChart
              chartData={processed.stats?.chartData || []}
              labelA={processed.stats?.chartLabelA || ""}
              labelB={processed.stats?.chartLabelB || ""}
              showA={!!processed.stats?.statsA?.rev && !processed.stats?.singleYearMode}
              showB={!!processed.stats?.statsB?.rev}
            />

            <BreakdownSection
              topMfrs={processed.stats?.topMfrs || []}
              topDescs={processed.stats?.topDescs || []}
              topProducts={processed.stats?.topProducts || []}
              isDescFiltered={desc !== -1}
              selectedDescName={desc !== -1 ? data?.maps.d[desc] : undefined}
              labelA={processed.stats?.labelA || ""}
              labelB={processed.stats?.labelB || ""}
            />
          </div>
        </>
      )}

      <footer style={{ marginTop: '2rem', textAlign: 'center', color: 'var(--text-secondary)', paddingBottom: '2rem' }}>
        <p> 2026</p>
      </footer>

      {historyType && processed.stats && (
        <div style={{
          position: 'fixed',
          inset: 0,
          zIndex: 10000,
          background: 'rgba(0,0,0,0.85)',
          backdropFilter: 'blur(10px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '1.5rem'
        }}>
          <div className="glass-card custom-scrollbar" style={{
            width: '100%',
            maxWidth: '1000px',
            maxHeight: '90vh',
            display: 'flex',
            flexDirection: 'column',
            overflowY: 'auto',
            position: 'relative',
            padding: '2rem'
          }}>
            <button
              onClick={() => {
                setHistoryType(null);
                setModalPeriod([]);
              }}
              style={{
                position: 'absolute',
                top: '1.5rem',
                right: '1.5rem',
                background: 'rgba(255,255,255,0.05)',
                border: 'none',
                borderRadius: '50%',
                width: '36px',
                height: '36px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'white',
                cursor: 'pointer',
                zIndex: 10
              }}
            >
              <X size={20} />
            </button>

            {(() => {
              const mData = processed.stats?.getStatsForPeriod(modalPeriod);
              if (!mData) return null;

              return (
                <>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', gap: '2rem', flexShrink: 0, paddingRight: '40px' }}>
                    <h2 style={{ color: 'white', margin: 0, display: 'flex', alignItems: 'center', gap: '12px', fontSize: '1.5rem', flexWrap: 'wrap' }}>
                      {historyType === 'revenue' && <><DollarSign color="var(--accent)" /> Receita Detalhada</>}
                      {historyType === 'mfr' && <><ShoppingCart color="var(--accent)" /> Volume de Vendas</>}
                      {historyType === 'desc' && <><Users color="var(--accent)" /> Clientes Ativos</>}
                      {client !== -1 && <span style={{ color: 'var(--text-secondary)', fontSize: '1.1rem', fontWeight: 400, marginLeft: '4px' }}>— {data?.maps.c[client]}</span>}
                    </h2>
                    <div style={{ width: '250px' }}>
                      <PeriodSelector
                        label=""
                        value={modalPeriod}
                        data={data!}
                        onChange={setModalPeriod}
                      />
                    </div>
                  </div>

                  {/* Summary Cards Row */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '1rem', marginBottom: '1.5rem', flexShrink: 0 }}>
                    {(() => {
                      const periodIndices = modalPeriod.length > 0 ? modalPeriod : (period.length > 0 ? period : data!.monthly.map((_, i) => i));
                      const availableYears = Array.from(new Set(data!.monthly.map(m => m.year))).sort((a, b) => b - a);

                      let sA: number[] = [];
                      let sB: number[] = [];
                      const years = Array.from(new Set(periodIndices.map(idx => data!.monthly[idx].year)));
                      const isTrend = periodIndices.length > 0 && years.length === 1;

                      if (!isTrend) {
                        const lastYear = availableYears[0];
                        const prevYear = availableYears[1] || lastYear;
                        periodIndices.forEach(idx => {
                          const m = data!.monthly[idx];
                          if (m.year === prevYear && lastYear !== prevYear) sA.push(idx);
                          if (m.year === lastYear) sB.push(idx);
                        });
                      } else {
                        const sorted = [...periodIndices].sort((a, b) => a - b);
                        const total = sorted.length;
                        const currentCount = Math.max(1, Math.min(3, Math.floor(total / 4) || 1));
                        sB = sorted.slice(-currentCount);
                        sA = sorted.slice(0, -currentCount);
                      }

                      const getVal = (indices: number[]) => {
                        let rev = 0, vol = 0, cli = new Set();
                        const rows = data!.rows;
                        const clientMap = data!.maps.c;
                        const consumerFinalId = clientMap.indexOf("Consumidor Final");
                        const indicesSet = new Set(indices);

                        rows.forEach(r => {
                          if (!indicesSet.has(r[0])) return;
                          if (r[2] === consumerFinalId) return;
                          if (client !== -1 && r[2] !== client) return;
                          if (mfr !== -1 && r[3] !== mfr) return;
                          if (desc !== -1 && r[4] !== desc) return;
                          if (store !== -1 && r[1] !== store) return;
                          rev += r[6];
                          vol += 1;
                          cli.add(r[2]);
                        });

                        const len = indices.length || 1;
                        return {
                          rawRev: rev,
                          rawVol: vol,
                          rawCli: cli.size,
                          rev: isTrend ? rev / len : rev,
                          vol: isTrend ? vol / len : vol,
                          cli: isTrend ? cli.size / len : cli.size
                        };
                      };

                      const totalsA = getVal(sA);
                      const totalsB = getVal(sB);
                      const totalsTotal = getVal(periodIndices);

                      const revA = totalsA.rawRev || 0;
                      const revB = totalsB.rawRev || 0;
                      const revTotal = totalsTotal.rawRev || 0;
                      const revAvg = totalsTotal.rev || 0;

                      const avgA = totalsA.rev || 0;
                      const avgB = totalsB.rev || 0;

                      let displayVal1, displayTitle1, displayVal2, displayTitle2, displayTitle3;
                      let trendPct;
                      let trendValYoy = revB - revA;

                      if (isTrend) {
                        displayTitle1 = `Receita Total (${years[0]})`;
                        displayVal1 = revTotal;
                        displayTitle2 = `Média de Receita (${years[0]})`;
                        displayVal2 = revAvg;
                        displayTitle3 = "Tendência";
                        trendPct = avgA > 0 ? ((avgB - avgA) / avgA) * 100 : 0;
                      } else {
                        displayTitle1 = "Desempenho em Receita";
                        displayVal1 = trendValYoy;
                        displayTitle2 = `Receita Total (${availableYears[0]})`;
                        displayVal2 = revB;
                        displayTitle3 = "Performance (Geral)";
                        trendPct = revA > 0 ? ((revB - revA) / revA) * 100 : 0;
                      }

                      const format = (v: number) => historyType === 'revenue' ? formatCurrency(v) : formatNumber(Math.round(v));

                      return (
                        <>
                          <div className="glass-card" style={{ padding: '1rem', border: '1px solid var(--accent)' }}>
                            <p style={{ color: 'var(--text-secondary)', fontSize: '0.65rem', textTransform: 'uppercase', marginBottom: '0.4rem' }}>
                              {displayTitle1}
                            </p>
                            <h3 style={{ fontSize: '1.25rem', color: 'white', margin: 0 }}>{format(displayVal1)}</h3>
                          </div>
                          <div className="glass-card" style={{ padding: '1rem' }}>
                            <p style={{ color: 'var(--text-secondary)', fontSize: '0.65rem', textTransform: 'uppercase', marginBottom: '0.4rem' }}>
                              {displayTitle2}
                            </p>
                            <h3 style={{ fontSize: '1.1rem', color: 'white', opacity: 0.8, margin: 0 }}>{format(displayVal2)}</h3>
                          </div>
                          <div className="glass-card" style={{ padding: '1rem' }}>
                            <p style={{ color: 'var(--text-secondary)', fontSize: '0.65rem', textTransform: 'uppercase', marginBottom: '0.4rem' }}>{displayTitle3}</p>
                            <div style={{ display: 'flex', flexDirection: 'column' }}>
                              <span style={{ fontSize: '1.25rem', fontWeight: 'bold', color: trendPct >= 0 ? '#10b981' : '#f43f5e' }}>
                                {trendPct >= 0 ? '↑' : '↓'} {isFinite(trendPct) ? Math.abs(trendPct).toFixed(1) : '0.0'}%
                              </span>
                            </div>
                          </div>
                        </>
                      );
                    })()}
                  </div>

                  {/* Main Content Area (Full Width) */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
                    {/* Fixed Chart */}
                    <div style={{ flexShrink: 0 }}>
                      <div className="glass-card" style={{ padding: '1.5rem' }}>
                        <HistoryChart
                          chartData={mData.chartData.map((d: any) => ({
                            name: d.name,
                            revenueA: historyType === 'revenue' ? d.revenueA : (historyType === 'mfr' ? d.cntA : d.clientsA),
                            revenueB: historyType === 'revenue' ? d.revenueB : (historyType === 'mfr' ? d.cntB : d.clientsB),
                          }))}
                          labelA={mData.labelA}
                          labelB={mData.labelB}
                          showA={!mData.isTrend}
                          showB={true}
                          isCurrency={historyType === 'revenue'}
                          style={{ height: '280px', minHeight: '280px' }}
                        />
                      </div>
                    </div>

                    {/* Scrollable Table Area (Expanded to space) */}
                    <div className="custom-scrollbar" style={{
                      background: 'rgba(255,255,255,0.02)',
                      borderRadius: '0.75rem',
                      border: '1px solid var(--border)',
                      overflowX: 'auto'
                    }}>
                      <table style={{ width: '100%', borderCollapse: 'collapse', color: 'white' }}>
                        <thead style={{ position: 'sticky', top: 0, zIndex: 10, background: '#1a1a1e' }}>
                          <tr style={{ textAlign: 'left', borderBottom: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
                            <th style={{ padding: '1rem' }}>Mês / Ano</th>
                            {mData.labelA && !mData.isTrend && <th style={{ padding: '1rem' }}>{mData.labelA}</th>}
                            <th style={{ padding: '1rem' }}>{mData.labelB}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {mData.chartData.map((row: any, i: number) => {
                            const valA = historyType === 'revenue' ? row.revenueA : (historyType === 'mfr' ? row.cntA : row.clientsA);
                            const valB = historyType === 'revenue' ? row.revenueB : (historyType === 'mfr' ? row.cntB : row.clientsB);
                            const format = (v: number) => historyType === 'revenue' ? formatCurrency(v) : formatNumber(Math.round(v));
                            return (
                              <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                                <td style={{ padding: '1rem', fontWeight: 600 }}>{row.name}</td>
                                {mData.labelA && !mData.isTrend && <td style={{ padding: '1rem' }}>{format(valA)}</td>}
                                <td style={{ padding: '1rem' }}>{format(valB)}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </>
              );
            })()}
          </div>
        </div>
      )}
    </div>
  );
}
