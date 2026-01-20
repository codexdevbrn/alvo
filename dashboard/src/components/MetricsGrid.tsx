import { DollarSign, TrendingUp, TrendingDown } from 'lucide-react';
import { StatCard } from './StatCard';
import { formatCurrency } from '../utils/formatters';

// ==========================================
// Types & Interfaces
// ==========================================

interface MetricsGridProps {
    stats: any;
    onRevenueClick?: () => void;
}

// ==========================================
// Main Component
// ==========================================

export function MetricsGrid({ stats, onRevenueClick }: MetricsGridProps) {
    if (!stats) return null;

    const { statsA, statsB, singleYearMode, labelA, labelB, yearLabel } = stats;
    let showTrend = !!labelA;

    const revA = statsA.rawRev || 0;
    const revB = statsB.rawRev || 0;
    const revTotal = stats.statsTotal?.rawRev || 0;
    const revAvg = stats.statsTotal?.rev || 0;

    let trendPct = revA > 0 ? ((revB - revA) / revA) * 100 : 0;
    let trendValYoy = revB - revA;

    if (singleYearMode) {
        const avgA = statsA.rev || 0;
        const avgB = statsB.rev || 0;
        trendPct = avgA > 0 ? ((avgB - avgA) / avgA) * 100 : 0;
    }

    // ==========================================
    // Helper Functions
    // ==========================================

    const formatPerformance = (val: number) => {
        const formatted = formatCurrency(val);
        if (val > 0) return `+ ${formatted}`;
        return formatted;
    };

    // ==========================================
    // Render
    // ==========================================

    return (
        <div className="stat-grid">
            <StatCard
                title={singleYearMode ? `Receita Total (${yearLabel})` : "Desempenho em Receita"}
                value={singleYearMode ? formatCurrency(revTotal) : formatPerformance(trendValYoy)}
                icon={DollarSign}
                trendUp={singleYearMode ? true : trendValYoy >= 0}
                useTrendColor={!singleYearMode}
                onClick={onRevenueClick}
            />

            <StatCard
                title={singleYearMode ? `Média de Receita (${yearLabel})` : `Receita Total (${labelB})`}
                value={formatCurrency(singleYearMode ? revAvg : revB)}
                icon={singleYearMode ? TrendingUp : DollarSign}
                useTrendColor={false}
                onClick={onRevenueClick}
            />

            <StatCard
                title={singleYearMode ? "Tendência" : "Performance (Geral)"}
                value={!showTrend ? '-' : (trendPct > 1000 ? '1000%+' : `${trendPct >= 0 ? '+' : ''}${isFinite(trendPct) ? trendPct.toFixed(1) : '0.0'}%`)}
                icon={!showTrend ? TrendingUp : (trendPct >= 0 ? TrendingUp : TrendingDown)}
                trendUp={trendPct >= 0}
                useTrendColor={showTrend}
            />
        </div>
    );
}
