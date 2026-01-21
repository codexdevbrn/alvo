import { useState, useEffect } from 'react';
import { formatCurrency } from '../utils/formatters';
import type { TrendItem, ProductStats } from '../types/dashboard';

// ==========================================
// Types & Interfaces
// ==========================================

interface BreakdownSectionProps {
    topMfrs: TrendItem[];
    topDescs: TrendItem[];
    topProducts: ProductStats[];
    isDescFiltered: boolean;
    selectedDescName?: string;
    labelA: string;
    labelB: string;
}

// ==========================================
// Main Component
// ==========================================

export function BreakdownSection({
    topMfrs,
    topDescs,
    topProducts,
    isDescFiltered,
    selectedDescName,
    labelA,
    labelB
}: BreakdownSectionProps) {
    const [isMobile, setIsMobile] = useState(window.innerWidth <= 1280);

    // ==========================================
    // Effects
    // ==========================================

    useEffect(() => {
        const handleResize = () => setIsMobile(window.innerWidth <= 1280);
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);

    const padding = isMobile ? '0.6rem 0.4rem' : '1rem';

    // ==========================================
    // Sub-renders (Conditionals)
    // ==========================================

    if (isDescFiltered) {
        return (
            <div className="glass-card" style={{ gridColumn: 'span 2' }}>
                <h3 style={{ color: 'white', marginBottom: '1.5rem', fontSize: isMobile ? '1rem' : '1.25rem' }}>Performance de Produtos em {selectedDescName}</h3>
                <div className="custom-scrollbar" style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: isMobile ? '0.75rem' : '0.85rem' }}>
                        <thead>
                            <tr style={{ color: 'var(--text-secondary)', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>
                                <th style={{ padding }}>Referência / Produto</th>
                                <th style={{ padding }}>{labelA || "Período A"}</th>
                                <th style={{ padding }}>{labelB || "Período B"}</th>
                                <th style={{ padding }}>Var.</th>
                            </tr>
                        </thead>
                        <tbody>
                            {topProducts.map((p, i) => {
                                const delta = p.avg24 ? ((p.avg25 - p.avg24) / p.avg24) * 100 : 0;
                                return (
                                    <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                                        <td style={{ padding, color: 'white', fontWeight: 500 }}>
                                            <div style={{ display: 'flex', flexDirection: 'column' }}>
                                                <span style={{ maxWidth: isMobile ? '120px' : 'none', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</span>
                                                <span style={{ fontSize: '0.65rem', color: 'var(--text-secondary)' }}>Ref: {p.id}</span>
                                            </div>
                                        </td>
                                        <td style={{ padding, color: 'var(--text-secondary)' }}>{formatCurrency(p.avg24)}</td>
                                        <td style={{ padding, color: 'var(--text-secondary)' }}>{formatCurrency(p.avg25)}</td>
                                        <td style={{ padding }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                                                <span style={{ color: delta >= 0 ? '#10b981' : '#f43f5e', fontWeight: 700 }}>
                                                    {delta > 0 ? '+' : ''}{delta > 1000 ? '1k%+' : delta.toFixed(delta > 100 ? 0 : 1)}%
                                                </span>
                                            </div>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            </div>
        );
    }

    // ==========================================
    // Render (Default)
    // ==========================================

    return (
        <>
            <div className="glass-card">
                <h3 style={{ color: 'white', marginBottom: '1.25rem', fontSize: isMobile ? '1rem' : '1.25rem' }}>Performance por Fabricante</h3>
                <div
                    className="custom-scrollbar"
                    style={{
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '1.25rem',
                        maxHeight: '400px',
                        overflowY: 'auto',
                        paddingRight: '8px'
                    }}
                >
                    {topMfrs.map((item, i) => {
                        const totalRevenue = item.rev24 + item.rev25;
                        const maxTotal = topMfrs[0] ? (topMfrs[0].rev24 + topMfrs[0].rev25) : 1;
                        const percentChange = (item.rev24 && item.rev24 > 0) ? ((item.rev25 - item.rev24) / item.rev24) * 100 : 0;
                        const isPositive = percentChange >= 0;
                        return (
                            <div key={i}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.4rem', fontSize: isMobile ? '0.7rem' : '0.8rem' }}>
                                    <span style={{ color: 'var(--text-secondary)', fontWeight: 500, maxWidth: isMobile ? '120px' : 'none', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.name}</span>
                                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                                        <span style={{ color: 'white', fontWeight: 600 }}>{formatCurrency(item.rev25)}</span>
                                        <span style={{
                                            color: isPositive ? '#10b981' : '#ff6f61',
                                            fontSize: '0.65rem',
                                            fontWeight: 'bold'
                                        }}>
                                            {isPositive ? '↑' : '↓'} {isFinite(percentChange) ? Math.abs(percentChange).toFixed(1) : '0.0'}%
                                        </span>
                                    </div>
                                </div>
                                <div style={{ width: '100%', height: '4px', background: 'rgba(255,255,255,0.05)', borderRadius: '2px' }}>
                                    <div style={{
                                        width: `${Math.min(100, Math.max(0, (totalRevenue / (maxTotal || 1)) * 100))}%`,
                                        height: '100%',
                                        background: 'var(--accent)',
                                        borderRadius: '2px',
                                        boxShadow: '0 0 8px var(--accent-glow)'
                                    }} />
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>
            <div className="glass-card">
                <h3 style={{ color: 'white', marginBottom: '1.25rem', fontSize: isMobile ? '1rem' : '1.25rem' }}>Performance por Categoria</h3>
                <div
                    className="custom-scrollbar"
                    style={{
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '1.25rem',
                        maxHeight: '400px',
                        overflowY: 'auto',
                        paddingRight: '8px'
                    }}
                >
                    {topDescs.map((item, i) => {
                        const totalRevenue = item.rev24 + item.rev25;
                        const maxTotal = topDescs[0] ? (topDescs[0].rev24 + topDescs[0].rev25) : 1;
                        const percentChange = (item.rev24 && item.rev24 > 0) ? ((item.rev25 - item.rev24) / item.rev24) * 100 : 0;
                        const isPositive = percentChange >= 0;
                        return (
                            <div key={i}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.4rem', fontSize: isMobile ? '0.7rem' : '0.8rem' }}>
                                    <span style={{ color: 'var(--text-secondary)', fontWeight: 500, maxWidth: isMobile ? '120px' : 'none', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.name}</span>
                                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                                        <span style={{ color: 'white', fontWeight: 600 }}>{formatCurrency(item.rev25)}</span>
                                        <span style={{
                                            color: isPositive ? '#10b981' : '#ff6f61',
                                            fontSize: '0.65rem',
                                            fontWeight: 'bold'
                                        }}>
                                            {isPositive ? '↑' : '↓'} {isFinite(percentChange) ? Math.abs(percentChange).toFixed(1) : '0.0'}%
                                        </span>
                                    </div>
                                </div>
                                <div style={{ width: '100%', height: '4px', background: 'rgba(255,255,255,0.05)', borderRadius: '2px' }}>
                                    <div style={{
                                        width: `${Math.min(100, Math.max(0, (totalRevenue / (maxTotal || 1)) * 100))}%`,
                                        height: '100%',
                                        background: '#ec4899',
                                        borderRadius: '2px',
                                        boxShadow: '0 0 8px rgba(236, 72, 153, 0.2)'
                                    }} />
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>
        </>
    );
}
