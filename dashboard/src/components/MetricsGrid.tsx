import { DollarSign, TrendingUp, TrendingDown } from 'lucide-react';
import { StatCard } from './StatCard';
import { formatCurrency, formatPercent } from '../utils/formatters';
import type { DashboardStats } from '../types/dashboard';

// ==========================================
// Types & Interfaces
// ==========================================

interface MetricsGridProps {
    stats: DashboardStats | null;
    onRevenueClick?: () => void;
}

// ==========================================
// Main Component
// ==========================================

export function MetricsGrid({ stats, onRevenueClick }: MetricsGridProps) {
    if (!stats) return null;

    const { statsA, statsB, singleYearMode, labelA, labelB, yearLabel, unidadePeriodo } = stats;
    const showTrend = !!labelA;
    const lenA = stats.lenA || 1;
    const lenB = stats.lenB || 1;
    const unidade = unidadePeriodo || 'mês';

    // YoY multi-ano: média por bucket da grain (valores mudam ao trocar Mensal/T/S/Anual).
    const revA = singleYearMode ? (statsA.rawRev || 0) : ((statsA.rawRev || 0) / lenA);
    const revB = singleYearMode ? (statsB.rawRev || 0) : ((statsB.rawRev || 0) / lenB);
    const revTotal = stats.statsTotal?.rawRev || 0;
    const revAvg = stats.statsTotal?.rev || 0;

    let trendPct = revA > 0 ? ((revB - revA) / revA) * 100 : 0;
    const trendValYoy = revB - revA;

    if (singleYearMode) {
        const avgA = statsA.rev || 0;
        const avgB = statsB.rev || 0;
        trendPct = avgA > 0 ? ((avgB - avgA) / avgA) * 100 : 0;
    } else if (typeof stats.performancePct === 'number') {
        trendPct = stats.performancePct;
    }

    // ==========================================
    // Helper Functions
    // ==========================================

    const formatPerformance = (val: number) => {
        const formatted = formatCurrency(val);
        if (val > 0) return `+ ${formatted}`;
        return formatted;
    };

    const tituloDesempenho = singleYearMode
        ? `Receita Total (${yearLabel})`
        : `Desempenho / ${unidade}`;

    const tituloReceita = singleYearMode
        ? `Média de Receita (${yearLabel})`
        : `Receita média / ${unidade} (${labelB})`;

    // ==========================================
    // Render
    // ==========================================

    return (
        <div className="stat-grid">
            <StatCard
                title={tituloDesempenho}
                value={singleYearMode ? formatCurrency(revTotal) : formatPerformance(trendValYoy)}
                icon={DollarSign}
                trendUp={singleYearMode ? true : trendValYoy >= 0}
                useTrendColor={!singleYearMode}
                onClick={onRevenueClick}
            />

            <StatCard
                title={tituloReceita}
                value={formatCurrency(singleYearMode ? revAvg : revB)}
                icon={singleYearMode ? TrendingUp : DollarSign}
                useTrendColor={false}
                onClick={onRevenueClick}
            />

            <StatCard
                title={singleYearMode ? "Tendência" : "Performance (média da variação)"}
                value={!showTrend ? '-' : (trendPct > 1000 ? '1000%+' : `${trendPct >= 0 ? '+' : ''}${formatPercent(trendPct)}`)}
                icon={!showTrend ? TrendingUp : (trendPct >= 0 ? TrendingUp : TrendingDown)}
                trendUp={trendPct >= 0}
                useTrendColor={showTrend}
            />
        </div>
    );
}
