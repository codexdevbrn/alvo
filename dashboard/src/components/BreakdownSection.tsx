import { useState, useEffect, useMemo } from 'react';
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react';
import { formatCurrency, formatPercent } from '../utils/formatters';
import type { TrendItem, ProductStats } from '../types/dashboard';

// ==========================================
// Types & Interfaces
// ==========================================

type ProductSortKey = 'name' | 'descricao' | 'avg24' | 'avg25' | 'delta';
type SortDir = 'asc' | 'desc';

interface ProductSortState {
    key: ProductSortKey;
    dir: SortDir;
}

interface SortableThProps {
    label: string;
    column: ProductSortKey;
    sort: ProductSortState;
    onSort: (column: ProductSortKey) => void;
    padding: string;
    align?: 'left' | 'right';
}

function SortableTh({ label, column, sort, onSort, padding, align = 'left' }: SortableThProps) {
    const isActive = sort.key === column;
    const Icon = !isActive ? ArrowUpDown : sort.dir === 'asc' ? ArrowDown : ArrowUp;

    return (
        <th style={{ padding, textAlign: align }}>
            <button
                type="button"
                className="breakdown-sort-btn"
                onClick={() => onSort(column)}
                aria-sort={isActive ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
            >
                <span>{label}</span>
                <Icon size={12} aria-hidden="true" />
            </button>
        </th>
    );
}

function productDelta(p: ProductStats): number {
    return p.avg24 ? ((p.avg25 - p.avg24) / p.avg24) * 100 : 0;
}

function sortProducts(items: ProductStats[], sort: ProductSortState): ProductStats[] {
    const sorted = [...items];
    sorted.sort((a, b) => {
        let cmp = 0;
        if (sort.key === 'name') cmp = a.name.localeCompare(b.name, 'pt-BR', { numeric: true, sensitivity: 'base' });
        else if (sort.key === 'descricao') cmp = a.descricao.localeCompare(b.descricao, 'pt-BR', { sensitivity: 'base' });
        else if (sort.key === 'avg24') cmp = a.avg24 - b.avg24;
        else if (sort.key === 'avg25') cmp = a.avg25 - b.avg25;
        else cmp = productDelta(a) - productDelta(b);
        return sort.dir === 'asc' ? cmp : -cmp;
    });
    return sorted;
}

interface BreakdownSectionProps {
    topClients: TrendItem[];
    topMfrs: TrendItem[];
    topDescs: TrendItem[];
    topProducts: ProductStats[];
    showProductView: boolean;
    selectedDescName?: string;
    labelA: string;
    labelB: string;
}

interface TrendCardProps {
    title: string;
    items: TrendItem[];
    barColor: string;
    barGlow: string;
    isMobile: boolean;
    /** Rótulo do período atual (ex.: "2026") — deixa claro que o R$ é total, não média. */
    labelPeriodo?: string;
}

// ==========================================
// Sub-component: single ranked list card (used for cliente/fabricante/categoria)
// ==========================================

function TrendCard({ title, items, barColor, barGlow, isMobile, labelPeriodo }: TrendCardProps) {
    const maxAtual = Math.max(0, ...items.map((item) => item.rev25));

    return (
        <div className="glass-card">
            <h3 style={{ color: 'white', marginBottom: '0.35rem', fontSize: isMobile ? '1rem' : '1.25rem' }}>{title}</h3>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', margin: '0 0 1.25rem' }}>
              Total em {labelPeriodo || 'período atual'} · % vs mesmo mês do ano anterior · barra proporcional ao valor
            </p>
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
                {items.map((item) => {
                    const percentChange = (item.rev24 && item.rev24 > 0) ? ((item.rev25 - item.rev24) / item.rev24) * 100 : 0;
                    const isPositive = percentChange >= 0;
                    const barPct = maxAtual > 0 ? Math.min(100, Math.max(0, (item.rev25 / maxAtual) * 100)) : 0;
                    return (
                        <div key={item.id}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.4rem', fontSize: isMobile ? '0.7rem' : '0.8rem' }}>
                                <span style={{ color: 'var(--text-primary)', fontWeight: 600, maxWidth: isMobile ? '120px' : 'none', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.name}</span>
                                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                                    <span style={{ color: 'white', fontWeight: 600 }}>{formatCurrency(item.rev25)}</span>
                                    <span style={{
                                        color: isPositive ? '#10b981' : '#ff6f61',
                                        fontSize: '0.65rem',
                                        fontWeight: 'bold'
                                    }}>
                                        {isPositive ? '↑' : '↓'} {formatPercent(Math.abs(percentChange), 1)}
                                    </span>
                                </div>
                            </div>
                            <div style={{ width: '100%', height: '4px', background: 'rgba(255,255,255,0.05)', borderRadius: '2px' }}>
                                <div style={{
                                    width: `${barPct}%`,
                                    height: '100%',
                                    background: barColor,
                                    borderRadius: '2px',
                                    boxShadow: `0 0 8px ${barGlow}`,
                                    transition: 'width 0.5s cubic-bezier(0.22, 0.61, 0.36, 1)'
                                }} />
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

// ==========================================
// Main Component
// ==========================================

export function BreakdownSection({
    topClients,
    topMfrs,
    topDescs,
    topProducts,
    showProductView,
    selectedDescName,
    labelA,
    labelB
}: BreakdownSectionProps) {
    const [isMobile, setIsMobile] = useState(window.innerWidth <= 1280);
    const [productSort, setProductSort] = useState<ProductSortState>({ key: 'avg25', dir: 'desc' });

    const handleProductSort = (column: ProductSortKey) => {
        setProductSort(prev => (
            prev.key === column
                ? { key: column, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
                : { key: column, dir: column === 'name' || column === 'descricao' ? 'asc' : 'desc' }
        ));
    };

    const sortedProducts = useMemo(
        () => sortProducts(topProducts, productSort),
        [topProducts, productSort],
    );

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

    if (showProductView) {
        const title = selectedDescName
            ? `Performance de Produtos em ${selectedDescName}`
            : 'Performance por Produto (códigos internos)';

        return (
            <div className="glass-card" style={{ gridColumn: 'span 2' }}>
                <h3 style={{ color: 'white', marginBottom: '1.5rem', fontSize: isMobile ? '1rem' : '1.25rem' }}>{title}</h3>
                <div className="custom-scrollbar" style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: isMobile ? '0.75rem' : '0.85rem' }}>
                        <thead>
                            <tr style={{ color: 'var(--text-secondary)', borderBottom: '1px solid var(--border)' }}>
                                <SortableTh label="Código de referência" column="name" sort={productSort} onSort={handleProductSort} padding={padding} />
                                <SortableTh label="Descrição" column="descricao" sort={productSort} onSort={handleProductSort} padding={padding} />
                                <SortableTh label={labelA || 'Período A'} column="avg24" sort={productSort} onSort={handleProductSort} padding={padding} align="right" />
                                <SortableTh label={labelB || 'Período B'} column="avg25" sort={productSort} onSort={handleProductSort} padding={padding} align="right" />
                                <SortableTh label="Var." column="delta" sort={productSort} onSort={handleProductSort} padding={padding} align="right" />
                            </tr>
                        </thead>
                        <tbody>
                            {sortedProducts.map((p) => {
                                const delta = productDelta(p);
                                return (
                                    <tr key={p.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                                        <td style={{ padding, color: 'white', fontWeight: 500 }}>
                                            <span style={{ maxWidth: isMobile ? '100px' : 'none', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }}>{p.name}</span>
                                        </td>
                                        <td style={{ padding, color: 'var(--text-secondary)', maxWidth: isMobile ? '140px' : '280px' }}>
                                            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }} title={p.descricao}>{p.descricao}</span>
                                        </td>
                                        <td style={{ padding, color: 'var(--text-secondary)', textAlign: 'right' }}>{formatCurrency(p.avg24)}</td>
                                        <td style={{ padding, color: 'var(--text-secondary)', textAlign: 'right' }}>{formatCurrency(p.avg25)}</td>
                                        <td style={{ padding, textAlign: 'right' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                                                <span style={{ color: delta >= 0 ? '#10b981' : '#f43f5e', fontWeight: 700 }}>
                                                    {delta > 0 ? '+' : ''}{delta > 1000 ? '1k%+' : formatPercent(delta, delta > 100 ? 0 : 1)}
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
        <div className="breakdown-row">
            <TrendCard
                title="Performance por Cliente"
                items={topClients}
                barColor="var(--accent-tertiary)"
                barGlow="rgba(104, 129, 141, 0.28)"
                isMobile={isMobile}
                labelPeriodo={labelB}
            />
            <TrendCard
                title="Performance por Fabricante"
                items={topMfrs}
                barColor="var(--accent)"
                barGlow="rgba(218, 187, 108, 0.25)"
                isMobile={isMobile}
                labelPeriodo={labelB}
            />
            <TrendCard
                title="Performance por Categoria"
                items={topDescs}
                barColor="var(--accent-secondary-bright)"
                barGlow="rgba(48, 67, 115, 0.35)"
                isMobile={isMobile}
                labelPeriodo={labelB}
            />
        </div>
    );
}
