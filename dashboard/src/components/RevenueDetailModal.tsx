import { useState, useEffect } from 'react';
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
    const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);

    useEffect(() => {
        const handleResize = () => setIsMobile(window.innerWidth <= 768);
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);

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
            padding: isMobile ? '0.5rem' : '1.5rem'
        }}>
            <div className="glass-card custom-scrollbar" style={{
                width: '100%',
                maxWidth: '1000px',
                maxHeight: isMobile ? '95vh' : '90vh',
                display: 'flex',
                flexDirection: 'column',
                overflowY: 'auto',
                position: 'relative',
                padding: isMobile ? '1.25rem 0.75rem' : '2rem'
            }}>
                <button
                    onClick={onClose}
                    style={{
                        position: 'absolute',
                        top: isMobile ? '1rem' : '1.5rem',
                        right: isMobile ? '0.75rem' : '1.5rem',
                        background: 'rgba(255,255,255,0.05)',
                        border: 'none',
                        borderRadius: '50%',
                        width: '32px',
                        height: '32px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: 'white',
                        cursor: 'pointer',
                        zIndex: 10
                    }}
                >
                    <X size={18} />
                </button>

                {(() => {
                    const mData = stats.getStatsForPeriod(modalPeriod);
                    if (!mData) return null;

                    return (
                        <>
                            <div style={{
                                display: 'flex',
                                flexDirection: isMobile ? 'column' : 'row',
                                justifyContent: 'space-between',
                                alignItems: isMobile ? 'flex-start' : 'center',
                                marginBottom: '1.5rem',
                                gap: isMobile ? '1rem' : '2rem',
                                flexShrink: 0,
                                paddingRight: isMobile ? '0' : '40px'
                            }}>
                                <h2 style={{
                                    color: 'white',
                                    margin: 0,
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '12px',
                                    fontSize: isMobile ? '1.15rem' : '1.5rem',
                                    flexWrap: 'wrap'
                                }}>
                                    {historyType === 'revenue' && <><DollarSign color="var(--accent)" size={isMobile ? 18 : 24} /> Receita</>}
                                    {historyType === 'mfr' && <><ShoppingCart color="var(--accent)" size={isMobile ? 18 : 24} /> Volume</>}
                                    {historyType === 'desc' && <><Users color="var(--accent)" size={isMobile ? 18 : 24} /> Clientes</>}
                                    {client !== -1 && <span style={{ color: 'var(--text-secondary)', fontSize: isMobile ? '0.85rem' : '1.1rem', fontWeight: 400 }}>— {data?.maps.c[client]}</span>}
                                </h2>
                                <div style={{ width: isMobile ? '100%' : '250px' }}>
                                    <PeriodSelector
                                        label=""
                                        value={modalPeriod}
                                        data={data}
                                        onChange={setModalPeriod}
                                    />
                                </div>
                            </div>

                            {/* Summary Cards Row */}
                            <div className="summary-grid" style={{
                                display: 'grid',
                                gridTemplateColumns: isMobile ? 'repeat(2, 1fr)' : 'repeat(auto-fit, minmax(180px, 1fr))',
                                gap: '0.75rem',
                                marginBottom: '1.5rem',
                                flexShrink: 0
                            }}>
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
                                        const tTotal = getVal(periodIndices);
                                        const sorted = [...periodIndices].sort((a, b) => a - b);
                                        const totalM = sorted.length;
                                        const currentCount = Math.max(1, Math.min(3, Math.floor(totalM / 4) || 1));
                                        const sB = sorted.slice(-currentCount);
                                        const sA = sorted.slice(0, -currentCount);
                                        const tA = getVal(sA);
                                        const tB = getVal(sB);
                                        const trendPct = tA.rev > 0 ? ((tB.rev - tA.rev) / tA.rev) * 100 : 0;

                                        return (
                                            <>
                                                <div className="glass-card" style={{ padding: isMobile ? '0.75rem' : '1rem', border: '1px solid var(--accent)' }}>
                                                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.65rem', textTransform: 'uppercase', marginBottom: '0.4rem' }}>Total ({selectedYears[0]})</p>
                                                    <h3 style={{ fontSize: isMobile ? '0.9rem' : '1.25rem', color: 'white', margin: 0 }}>{format(tTotal.rawRev)}</h3>
                                                </div>
                                                <div className="glass-card" style={{ padding: isMobile ? '0.75rem' : '1rem' }}>
                                                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.65rem', textTransform: 'uppercase', marginBottom: '0.4rem' }}>Média ({selectedYears[0]})</p>
                                                    <h3 style={{ fontSize: isMobile ? '0.85rem' : '1.1rem', color: 'white', opacity: 0.8, margin: 0 }}>{format(tTotal.rev)}</h3>
                                                </div>
                                                <div className="glass-card" style={{
                                                    padding: isMobile ? '0.75rem' : '1rem',
                                                    display: 'flex',
                                                    flexDirection: 'column'
                                                }}>
                                                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.65rem', textTransform: 'uppercase', marginBottom: '0.4rem' }}>Tendência</p>
                                                    <span style={{ fontSize: isMobile ? '1.1rem' : '1.25rem', fontWeight: 'bold', color: trendPct >= 0 ? '#10b981' : '#f43f5e' }}>
                                                        {trendPct >= 0 ? '↑' : '↓'} {isFinite(trendPct) ? Math.abs(trendPct).toFixed(2) : '0.00'}%
                                                    </span>
                                                </div>
                                            </>
                                        );
                                    } else {
                                        const oldestYear = selectedYears[0];
                                        const newestYear = selectedYears[selectedYears.length - 1];
                                        const valOld = getVal(periodIndices.filter(idx => data.monthly[idx].year === oldestYear));
                                        const valNew = getVal(periodIndices.filter(idx => data.monthly[idx].year === newestYear));
                                        const trendPct = valOld.rawRev > 0 ? ((valNew.rawRev - valOld.rawRev) / valOld.rawRev) * 100 : 0;

                                        return (
                                            <>
                                                {selectedYears.map(year => {
                                                    const v = getVal(periodIndices.filter(idx => data.monthly[idx].year === year));
                                                    return (
                                                        <div key={year} className="glass-card" style={{ padding: isMobile ? '0.75rem' : '1rem', border: year === newestYear ? '1px solid var(--accent)' : undefined }}>
                                                            <p style={{ color: 'var(--text-secondary)', fontSize: '0.65rem', textTransform: 'uppercase', marginBottom: '0.4rem' }}>Total ({year})</p>
                                                            <h3 style={{ fontSize: isMobile ? '0.9rem' : '1.25rem', color: 'white', margin: 0 }}>{format(v.rawRev)}</h3>
                                                        </div>
                                                    );
                                                })}
                                                <div className="glass-card" style={{
                                                    padding: isMobile ? '0.75rem' : '1rem',
                                                    display: 'flex',
                                                    flexDirection: 'column'
                                                }}>
                                                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.65rem', textTransform: 'uppercase', marginBottom: '0.4rem' }}>Perf. Geral</p>
                                                    <span style={{ fontSize: isMobile ? '1.1rem' : '1.25rem', fontWeight: 'bold', color: trendPct >= 0 ? '#10b981' : '#f43f5e' }}>
                                                        {trendPct >= 0 ? '↑' : '↓'} {isFinite(trendPct) ? Math.abs(trendPct).toFixed(2) : '0.00'}%
                                                    </span>
                                                </div>
                                            </>
                                        );
                                    }
                                })()}
                            </div>

                            {/* Main Content Area (Full Width) */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
                                {/* Fixed Chart Container (No redundant glass-card here as HistoryChart provides its own) */}
                                <div style={{ flexShrink: 0 }}>
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
                                        style={{ height: isMobile ? '300px' : '350px', minHeight: isMobile ? '300px' : '350px', width: '100%' }}
                                    />
                                </div>

                                {/* Scrollable Table Area (Expanded to space) */}
                                <div className="custom-scrollbar" style={{
                                    background: 'rgba(255,255,255,0.02)',
                                    borderRadius: '0.75rem',
                                    border: '1px solid var(--border)',
                                    overflowX: 'auto',
                                    marginBottom: isMobile ? '2rem' : '0'
                                }}>
                                    <table style={{ width: '100%', borderCollapse: 'collapse', color: 'white', fontSize: isMobile ? '0.8rem' : '1rem' }}>
                                        <thead style={{ position: 'sticky', top: 0, zIndex: 10, background: '#1a1a1e' }}>
                                            <tr style={{ textAlign: 'left', borderBottom: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
                                                <th style={{ padding: isMobile ? '0.75rem' : '1rem' }}>Mês / Ano</th>
                                                {mData.labelA && !mData.isTrend && <th style={{ padding: isMobile ? '0.75rem' : '1rem' }}>{mData.labelA}</th>}
                                                <th style={{ padding: isMobile ? '0.75rem' : '1rem' }}>{mData.labelB}</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {mData.chartData.map((row: any, i: number) => {
                                                const valA = historyType === 'revenue' ? row.revenueA : (historyType === 'mfr' ? row.cntA : row.clientsA);
                                                const valB = historyType === 'revenue' ? row.revenueB : (historyType === 'mfr' ? row.cntB : row.clientsB);
                                                const format = (v: number) => historyType === 'revenue' ? formatCurrency(v).replace(',00', '') : formatNumber(Math.round(v));
                                                return (
                                                    <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                                                        <td style={{ padding: isMobile ? '0.75rem' : '1rem', fontWeight: 600 }}>{row.name}</td>
                                                        {mData.labelA && !mData.isTrend && <td style={{ padding: isMobile ? '0.75rem' : '1rem' }}>{format(valA)}</td>}
                                                        <td style={{ padding: isMobile ? '0.75rem' : '1rem' }}>{format(valB)}</td>
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
