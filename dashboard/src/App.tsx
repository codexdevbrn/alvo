import { useState, useMemo, useEffect } from 'react';
import { RefreshCw, AlertTriangle } from 'lucide-react';
import { FilterBar } from './components/FilterBar';
import { MetricsGrid } from './components/MetricsGrid';
import { HistoryChart } from './components/HistoryChart';
import { BreakdownSection } from './components/BreakdownSection';
import type { DashboardData, ProductStats, AggregatedStats, TrendItem } from './types/dashboard';
import './index.css';

export default function App() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  // Filter States
  const [client, setClient] = useState<number>(-1);
  const [mfr, setMfr] = useState<number>(-1);
  const [desc, setDesc] = useState<number>(-1);
  const [store, setStore] = useState<number>(-1);
  const [severity, setSeverity] = useState<number>(-1);
  const [period, setPeriod] = useState<number[]>([]);

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
    const yearsInSelection = Array.from(new Set(period.map(idx => data.monthly[idx].year)));
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

      // Proportional split: ~25% for "Current" (cap at 3), rest for "Baseline"
      // If 12Selected -> 3 vs 9. If 2Selected -> 1 vs 1.
      const currentCount = Math.max(1, Math.min(3, Math.floor(totalSelected / 4) || 1));

      pB = sortedPeriod.slice(-currentCount);
      pA = sortedPeriod.slice(0, -currentCount);
    }

    // 2. Population Filtering (Direct Filters)
    let populationRows = data.rows;
    if (client !== -1) populationRows = populationRows.filter(r => r[2] === client);
    if (mfr !== -1) populationRows = populationRows.filter(r => r[3] === mfr);
    if (desc !== -1) populationRows = populationRows.filter(r => r[4] === desc);
    if (store !== -1) populationRows = populationRows.filter(r => r[1] === store);

    // 3. Severity Filter (Requires 2-pass on the population)
    if (severity !== -1) {
      const perf: Record<number, { vA: number, vB: number }> = {};
      populationRows.forEach(r => {
        const cId = r[2], pId = r[0], rev = r[6];
        if (!perf[cId]) perf[cId] = { vA: 0, vB: 0 };
        // For severity, we always use the dashboard's comparison mode (YoY or Trend)
        if (pA.includes(pId)) perf[cId].vA += rev;
        if (pB.includes(pId)) perf[cId].vB += rev;
      });
      const validClients = new Set();
      Object.entries(perf).forEach(([cId, s]) => {
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

    // 4. stats aggregation
    const aggregate = (targetRows: any[], targetPeriod: number[]): AggregatedStats => {
      let rev = 0, qty = 0, cnt = 0;
      const monthly: any = {}, mfrs: any = {}, descs: any = {}, products: any = {};
      const periodSet = new Set(targetPeriod);
      for (const r of targetRows) {
        if (!periodSet.has(r[0])) continue;
        const revVal = r[6], qtyVal = r[7], pId = r[0], mId = r[3], dId = r[4], rId = r[5];
        rev += revVal; qty += qtyVal;
        monthly[pId] = (monthly[pId] || 0) + revVal;
        mfrs[mId] = (mfrs[mId] || 0) + revVal;
        descs[dId] = (descs[dId] || 0) + revVal;
        products[rId] = (products[rId] || 0) + revVal;
        cnt++;
      }
      return { rev, qty, cnt, monthly, mfrs, descs, products };
    };

    const statsA_raw = aggregate(populationRows, pA);
    const statsB_raw = aggregate(populationRows, pB);
    const statsA = isTrendMode ? { ...statsA_raw, rev: statsA_raw.rev / (pA.length || 1), qty: statsA_raw.qty / (pA.length || 1) } : statsA_raw;
    const statsB = isTrendMode ? { ...statsB_raw, rev: statsB_raw.rev / (pB.length || 1), qty: statsB_raw.qty / (pB.length || 1) } : statsB_raw;

    // 5. Display Rows (Strictly respect the User Filter for charts/lists)
    const selection = isTrendMode ? period : [...pA, ...pB];
    const selectionSet = new Set(selection);
    const rowsDisplay = populationRows.filter(r => selectionSet.has(r[0]));

    const labelA = isTrendMode
      ? (pA.length > 0 ? (pA.length === 1 ? "Mês Anterior" : `Média ${pA.length} Meses Ant.`) : "")
      : (availableYears[1]?.toString() || "Anterior");
    const labelB = isTrendMode
      ? (pB.length === 1 ? "Mês Atual" : `Média últ. ${pB.length} Meses`)
      : (availableYears[0]?.toString() || "Atual");
    const chartLabelA = labelA;
    const chartLabelB = isTrendMode ? "Receita Mensal" : labelB;

    // 6. Filter Options (population context)
    const clientOpts = new Set<number>(), mfrOpts = new Set<number>(), descOpts = new Set<number>(), storeOpts = new Set<number>();
    populationRows.forEach(r => {
      const rs = r[1], rc = r[2], rm = r[3], rd = r[4];
      clientOpts.add(rc); mfrOpts.add(rm); descOpts.add(rd); storeOpts.add(rs);
    });

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

    // 8. Chart Data
    let chartData: any[] = [];
    if (!isTrendMode) {
      // Comparison: Map by month name to allow overlapping lines
      const monthMap: Record<string, { revenueA: number, revenueB: number }> = {};
      const pASet = new Set(pA);
      const pBSet = new Set(pB);

      [...pA, ...pB].forEach(idx => {
        const mName = data.monthly[idx].name.split('/')[0];
        if (!monthMap[mName]) monthMap[mName] = { revenueA: 0, revenueB: 0 };

        let rev = 0;
        populationRows.forEach(r => { if (r[0] === idx) rev += r[6]; });

        if (pASet.has(idx)) monthMap[mName].revenueA += rev;
        if (pBSet.has(idx)) monthMap[mName].revenueB += rev;
      });

      // Preserve chronological month order from data.monthly
      const uniqueOrder = Array.from(new Set(data.monthly.map(m => m.name.split('/')[0])));
      chartData = uniqueOrder
        .filter(m => monthMap[m])
        .map(m => ({
          name: m,
          revenueA: monthMap[m].revenueA || 0,
          revenueB: monthMap[m].revenueB || 0
        }));
    } else {
      // Chronological: Single line for the selected trend period
      chartData = [...selection].sort((a, b) => a - b).map(idx => {
        let rev = 0;
        populationRows.forEach(r => { if (r[0] === idx) rev += r[6]; });
        return {
          name: data.monthly[idx].name.split('/')[0],
          revenueB: rev
        };
      });
    }

    return {
      stats: {
        statsA, statsB, topMfrs: getTrend('m'), topDescs: getTrend('d'), topProducts, chartData,
        labelA, labelB, chartLabelA, chartLabelB, singleYearMode: isTrendMode,
        lenA: pA.length, lenB: pB.length
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
          <MetricsGrid stats={processed.stats} />

          <div className="chart-grid">
            <HistoryChart
              chartData={processed.stats?.chartData || []}
              labelA={processed.stats?.chartLabelA || ""}
              labelB={processed.stats?.chartLabelB || ""}
              showA={!!processed.stats?.statsA.rev && !processed.stats?.singleYearMode}
              showB={!!processed.stats?.statsB.rev}
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
    </div>
  );
}
