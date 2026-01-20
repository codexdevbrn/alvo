import { X, DollarSign, ShoppingCart, Users } from 'lucide-react';
import { PeriodSelector } from './PeriodSelector';
import { HistoryChart } from './HistoryChart';
import type { DashboardData } from '../types/dashboard';

// ==========================================
// Types & Interfaces
// ==========================================

interface RevenueDetailModalProps {
    isOpen: boolean;
    onClose: () => void;
    historyType: 'revenue' | 'mfr' | 'desc';
    data: DashboardData;
    stats: any; // specific type from processed.stats
    modalPeriod: number[];
    setModalPeriod: (period: number[]) => void;
    client: number;
    mfr: number;
    desc: number;
    store: number;
    formatCurrency: (value: number) => string;
    formatNumber: (value: number) => string;
    period: number[]; // main specific period for fallback
}

// ==========================================
// Main Component
// ==========================================

export function RevenueDetailModal({
    isOpen,
    onClose,
    historyType,
    data,
    stats,
    modalPeriod,
    setModalPeriod,
    client,
    mfr,
    desc,
    store,
    formatCurrency,
    formatNumber,
    period
}: RevenueDetailModalProps) {
    if (!isOpen || !stats) return null;

    // ==========================================
    // Render
    // ==========================================

    return (
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
                    onClick={onClose}
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
                    const mData = stats.getStatsForPeriod(modalPeriod);
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
                                        data={data}
                                        onChange={setModalPeriod}
                                    />
                                </div>
                            </div>

                            {/* Summary Cards Row */}
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem', marginBottom: '1.5rem', flexShrink: 0 }}>
                                {(() => {
                                    const periodIndices = modalPeriod.length > 0 ? modalPeriod : (period.length > 0 ? period : data.monthly.map((_, i) => i));
                                    const selectedYears = Array.from(new Set(periodIndices.map(idx => data.monthly[idx].year))).sort((a, b) => a - b);
                                    const isTrend = periodIndices.length > 0 && selectedYears.length === 1;

                                    const getVal = (indices: number[]) => {
                                        let rev = 0, vol = 0, cli = new Set();
                                        const rows = data.rows;
                                        const clientMap = data.maps.c;
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

                                    const format = (v: number) => historyType === 'revenue' ? formatCurrency(v) : formatNumber(Math.round(v));

                                    if (isTrend) {
                                        const sorted = [...periodIndices].sort((a, b) => a - b);
                                        const total = sorted.length;
                                        const currentCount = Math.max(1, Math.min(3, Math.floor(total / 4) || 1));
                                        const sB = sorted.slice(-currentCount);
                                        const sA = sorted.slice(0, -currentCount);

                                        const tA = getVal(sA);
                                        const tB = getVal(sB);
                                        const tTotal = getVal(periodIndices);

                                        const trendPct = tA.rev > 0 ? ((tB.rev - tA.rev) / tA.rev) * 100 : 0;

                                        return (
                                            <>
                                                <div className="glass-card" style={{ padding: '1rem', border: '1px solid var(--accent)' }}>
                                                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.65rem', textTransform: 'uppercase', marginBottom: '0.4rem' }}>Receita Total ({selectedYears[0]})</p>
                                                    <h3 style={{ fontSize: '1.25rem', color: 'white', margin: 0 }}>{format(tTotal.rawRev)}</h3>
                                                </div>
                                                <div className="glass-card" style={{ padding: '1rem' }}>
                                                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.65rem', textTransform: 'uppercase', marginBottom: '0.4rem' }}>Média de Receita ({selectedYears[0]})</p>
                                                    <h3 style={{ fontSize: '1.1rem', color: 'white', opacity: 0.8, margin: 0 }}>{format(tTotal.rev)}</h3>
                                                </div>
                                                <div className="glass-card" style={{ padding: '1rem' }}>
                                                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.65rem', textTransform: 'uppercase', marginBottom: '0.4rem' }}>Tendência</p>
                                                    <span style={{ fontSize: '1.25rem', fontWeight: 'bold', color: trendPct >= 0 ? '#10b981' : '#f43f5e' }}>
                                                        {trendPct >= 0 ? '↑' : '↓'} {isFinite(trendPct) ? Math.abs(trendPct).toFixed(1) : '0.0'}%
                                                    </span>
                                                </div>
                                            </>
                                        );
                                    } else {
                                        // Strict Comparison Mode: Exactly 3 cards
                                        const newestYear = selectedYears[selectedYears.length - 1];
                                        const oldestYear = selectedYears[0];

                                        const indicesOld = periodIndices.filter(idx => data.monthly[idx].year === oldestYear);
                                        const indicesNew = periodIndices.filter(idx => data.monthly[idx].year === newestYear);

                                        const valOld = getVal(indicesOld);
                                        const valNew = getVal(indicesNew);
                                        const trendPct = valOld.rawRev > 0 ? ((valNew.rawRev - valOld.rawRev) / valOld.rawRev) * 100 : 0;

                                        return (
                                            <>
                                                <div className="glass-card" style={{ padding: '1rem' }}>
                                                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.65rem', textTransform: 'uppercase', marginBottom: '0.4rem' }}>
                                                        Receita Total ({oldestYear})
                                                    </p>
                                                    <h3 style={{ fontSize: '1.25rem', color: 'white', margin: 0 }}>{format(valOld.rawRev)}</h3>
                                                </div>
                                                <div className="glass-card" style={{ padding: '1rem' }}>
                                                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.65rem', textTransform: 'uppercase', marginBottom: '0.4rem' }}>
                                                        Receita Total ({newestYear})
                                                    </p>
                                                    <h3 style={{ fontSize: '1.25rem', color: 'white', margin: 0 }}>{format(valNew.rawRev)}</h3>
                                                </div>
                                                <div className="glass-card" style={{ padding: '1rem' }}>
                                                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.65rem', textTransform: 'uppercase', marginBottom: '0.4rem' }}>Performance (Geral)</p>
                                                    <span style={{ fontSize: '1.25rem', fontWeight: 'bold', color: trendPct >= 0 ? '#10b981' : '#f43f5e' }}>
                                                        {trendPct >= 0 ? '↑' : '↓'} {isFinite(trendPct) ? Math.abs(trendPct).toFixed(1) : '0.0'}%
                                                    </span>
                                                </div>
                                            </>
                                        );
                                    }
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
    );
}
