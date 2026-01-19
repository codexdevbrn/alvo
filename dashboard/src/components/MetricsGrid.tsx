import { DollarSign, TrendingUp, TrendingDown, Users } from 'lucide-react';
import { StatCard } from './StatCard';
import { formatCurrency, formatNumber } from '../utils/formatters';

interface MetricsGridProps {
    stats: any;
}

export function MetricsGrid({ stats }: MetricsGridProps) {
    if (!stats) return null;

    const { statsA, statsB, singleYearMode, labelA, labelB } = stats;

    let titleCurrent = `Receita (${labelB})`;
    let titlePrev = `vs ${labelA}`;
    let showTrend = !!labelA;

    const revA = statsA.rev || 0;
    const revB = statsB.rev || 0;

    // If we have selected multiple months, we might want to show the average monthly revenue
    // to make periods of different lengths comparable.
    let valToShow = revB;
    let trendVal = revB - revA;
    let trendPct = revA > 0 ? ((revB - revA) / revA) * 100 : 0;

    if (singleYearMode) {
        titleCurrent = `Média Mensal (${labelB})`;
        titlePrev = `vs Média ${labelA}`;
    } else if (labelA === "") {
        showTrend = false;
    }

    const avgTicketA = (statsA.rev || 0) / (statsA.cnt || 1);
    const avgTicketB = (statsB.rev || 0) / (statsB.cnt || 1);
    const ticketTrendVal = avgTicketB - avgTicketA;
    const ticketTrendUp = ticketTrendVal >= 0;

    return (
        <div className="stat-grid">
            <StatCard
                title={titleCurrent}
                value={formatCurrency(valToShow)}
                icon={DollarSign}
                trend={showTrend ? formatCurrency(Math.abs(trendVal)) : undefined}
                trendUp={trendVal >= 0}
            />
            <StatCard
                title="Performance (Geral)"
                value={!showTrend ? '-' : (trendPct > 1000 ? '1000%+' : `${trendPct >= 0 ? '+' : ''}${isFinite(trendPct) ? trendPct.toFixed(1) : '0.0'}%`)}
                icon={!showTrend ? TrendingUp : (trendPct >= 0 ? TrendingUp : TrendingDown)}
                trend={showTrend ? titlePrev : undefined}
                trendUp={trendPct >= 0}
                useTrendColor={showTrend}
            />
            <StatCard
                title="Média por Venda"
                value={formatCurrency(avgTicketB)}
                icon={!showTrend ? TrendingUp : (ticketTrendUp ? TrendingUp : TrendingDown)}
                trend={showTrend ? formatCurrency(Math.abs(ticketTrendVal)) : undefined}
                trendUp={ticketTrendUp}
                useTrendColor={showTrend}
            />
            <StatCard
                title="Transações (Total)"
                value={formatNumber(statsB.cnt || 0)}
                icon={Users}
                trend={showTrend ? formatNumber(Math.abs((statsB.cnt || 0) - (statsA.cnt || 0))) : undefined}
                trendUp={(statsB.cnt || 0) >= (statsA.cnt || 0)}
            />
        </div>
    );
}
