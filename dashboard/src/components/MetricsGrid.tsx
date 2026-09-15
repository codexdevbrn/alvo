import { DollarSign, TrendingDown, TrendingUp } from 'lucide-react';
import { StatCard } from './StatCard';
import { LeituraFaixa } from './LeituraFaixa';
import { formatCurrency, formatPercent } from '../utils/formatters';
import type { DashboardStats } from '../types/dashboard';

interface MetricsGridProps {
    stats: DashboardStats | null;
    onRevenueClick?: () => void;
    mesAberto?: boolean;
}

function textoPct(valor: number): string {
    if (valor > 1000) return '1000%+';
    return `${valor >= 0 ? '+' : ''}${formatPercent(valor)}`;
}

export function MetricsGrid({ stats, onRevenueClick, mesAberto = false }: MetricsGridProps) {
    if (!stats) return null;

    const { statsA, statsB, singleYearMode, labelA, labelB, yearLabel, unidadePeriodo } = stats;
    const showTrend = !!labelA;
    const lenA = stats.lenA || 1;
    const lenB = stats.lenB || 1;
    const unidade = unidadePeriodo || 'mês';

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

    const formatPerformance = (val: number) => {
        const formatted = formatCurrency(val);
        if (val > 0) return `+ ${formatted}`;
        return formatted;
    };

    const heroValor = formatCurrency(singleYearMode ? revTotal : revB);
    const heroRotulo = singleYearMode
        ? `Receita total (${yearLabel})`
        : `Receita média / ${unidade}${labelB ? ` (${labelB})` : ''}`;

    const leitura = mesAberto
        ? `Mês corrente ainda em aberto — o último ponto do gráfico não é mês cheio. ${heroRotulo}: ${heroValor}${showTrend ? ` · ${textoPct(trendPct)} vs ${labelA}` : ''}.`
        : `${stats.periodoDescricao ?? `Comparação por ${unidade} fechado`}. ${heroRotulo}: ${heroValor}${showTrend ? ` · ${textoPct(trendPct)} vs ${labelA}` : ''}.`;

    return (
        <>
            <LeituraFaixa tom={mesAberto ? 'aviso' : 'normal'}>{leitura}</LeituraFaixa>
            <div className="despesas-kpis dashboard-kpis">
                <article className="glass-card glass-card-flat vendedores-hero">
                    <div className="despesas-hero-texto">
                        <p className="despesas-hero-rotulo">
                            <DollarSign size={14} aria-hidden="true" /> {heroRotulo}
                        </p>
                        <strong className="despesas-hero-valor">{heroValor}</strong>
                        <p className={`despesas-hero-nota${showTrend ? (trendPct >= 0 ? ' is-alta' : ' is-queda') : ''}`}>
                            {showTrend
                                ? `${textoPct(trendPct)} vs ${labelA}`
                                : 'sem período anterior para comparar'}
                        </p>
                    </div>
                </article>
                <StatCard
                    title={singleYearMode ? `Média de receita (${yearLabel})` : `Desempenho / ${unidade}`}
                    value={singleYearMode ? formatCurrency(revAvg) : formatPerformance(trendValYoy)}
                    icon={singleYearMode ? DollarSign : (trendValYoy >= 0 ? TrendingUp : TrendingDown)}
                    trendUp={singleYearMode ? undefined : trendValYoy >= 0}
                    useTrendColor={!singleYearMode}
                    onClick={onRevenueClick}
                />
            </div>
        </>
    );
}
