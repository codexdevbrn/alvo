import { DollarSign, Package, Receipt, Scale, TrendingDown, TrendingUp } from 'lucide-react';
import { StatCard } from './StatCard';
import { LeituraFaixa } from './LeituraFaixa';
import { formatCurrency, formatNumber, formatPercent } from '../utils/formatters';
import type { DashboardStats } from '../types/dashboard';

interface MetricsGridProps {
    stats: DashboardStats | null;
    onRevenueClick?: () => void;
    mesAberto?: boolean;
    /** Despesas do período — vêm de uma fonte separada (só existe com empresa
     *  selecionada), por isso chegam como props em vez de fazer parte de `stats`.
     *  `undefined` = sem fonte de despesas; os cards de Despesas/Margem somem
     *  nesse caso, em vez de mostrar zero como se fosse dado real. */
    despesasA?: number;
    despesasB?: number;
}

function textoPct(valor: number): string {
    if (valor > 1000) return '1000%+';
    return `${valor >= 0 ? '+' : ''}${formatPercent(valor)}`;
}

export function MetricsGrid({ stats, onRevenueClick, mesAberto = false, despesasA, despesasB }: MetricsGridProps) {
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
    // Mesma escolha total-vs-B do heroValor: média simples da margem de cada
    // descrição de produto (não a margem do total, que ponderaria as maiores).
    const margemMediaPct = singleYearMode
        ? (stats.statsTotal?.margemMediaPct || 0)
        : (statsB.margemMediaPct || 0);

    const qtyA = singleYearMode ? (statsA.rawQty || 0) : ((statsA.rawQty || 0) / lenA);
    const qtyB = singleYearMode ? (statsB.rawQty || 0) : ((statsB.rawQty || 0) / lenB);
    const qtyTrendPct = qtyA > 0 ? ((qtyB - qtyA) / qtyA) * 100 : 0;

    // Despesas já chegam agregadas no período (não passam por lenA/lenB aqui:
    // quem soma por mês e decide total-vs-média é o DashboardPage, espelhando
    // a mesma regra de singleYearMode usada acima para o lucro bruto).
    const temDespesas = despesasA != null && despesasB != null;
    const despA = despesasA ?? 0;
    const despB = despesasB ?? 0;
    const despTrendPct = despA > 0 ? ((despB - despA) / despA) * 100 : 0;
    const margemA = revA - despA;
    const margemB = revB - despB;

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
        ? `Lucro bruto total (${yearLabel})`
        : `Lucro bruto médio / ${unidade}${labelB ? ` (${labelB})` : ''}`;

    // A leitura é a manchete: resume o achado (lucro bruto e, quando há
    // despesas, a margem resultante) antes de o olho chegar aos cards.
    const leituraMargem = temDespesas
        ? ` Margem do período: ${formatCurrency(margemB)}${margemB < 0 ? ' (negativa)' : ''}.`
        : '';
    const leitura = mesAberto
        ? `Mês corrente ainda em aberto — o último ponto do gráfico não é mês cheio. ${heroRotulo}: ${heroValor}${showTrend ? ` · ${textoPct(trendPct)} vs ${labelA}` : ''}.${leituraMargem}`
        : `${stats.periodoDescricao ?? `Comparação por ${unidade} fechado`}. ${heroRotulo}: ${heroValor}${showTrend ? ` · ${textoPct(trendPct)} vs ${labelA}` : ''}.${leituraMargem}`;

    return (
        <>
            <LeituraFaixa tom={mesAberto ? 'aviso' : (temDespesas && margemB < 0 ? 'aviso' : 'normal')}>{leitura}</LeituraFaixa>
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
                        <p className="despesas-hero-nota">
                            Margem média (por produto): {formatPercent(margemMediaPct)}
                        </p>
                    </div>
                </article>
                {/* Ordem narrativa: cresceu quanto (desempenho) → vendeu
                    quanto (quantidade) → gastou quanto (despesas) → sobrou
                    quanto (margem) — a mesma sequência de um P&L simplificado. */}
                <div className="despesas-kpis-secundarios">
                    <StatCard
                        title={singleYearMode ? `Média de lucro bruto (${yearLabel})` : `Desempenho / ${unidade}`}
                        value={singleYearMode ? formatCurrency(revAvg) : formatPerformance(trendValYoy)}
                        icon={singleYearMode ? DollarSign : (trendValYoy >= 0 ? TrendingUp : TrendingDown)}
                        trendUp={singleYearMode ? undefined : trendValYoy >= 0}
                        useTrendColor={!singleYearMode}
                        onClick={onRevenueClick}
                    />
                    <StatCard
                        title={singleYearMode ? `Quantidade vendida (${yearLabel})` : `Quantidade vendida / ${unidade}`}
                        value={formatNumber(qtyB)}
                        icon={Package}
                        trend={showTrend ? `${textoPct(qtyTrendPct)} vs ${labelA}` : undefined}
                        trendArrow={qtyB >= qtyA ? 'up' : 'down'}
                        useTrendColor={false}
                    />
                    {temDespesas && (
                        <StatCard
                            title={singleYearMode ? `Despesas (${yearLabel})` : `Despesas / ${unidade}`}
                            value={formatCurrency(despB)}
                            icon={Receipt}
                            trend={showTrend ? `${textoPct(despTrendPct)} vs ${labelA}` : undefined}
                            trendUp={despB <= despA}
                            trendArrow={despB >= despA ? 'up' : 'down'}
                            useTrendColor
                        />
                    )}
                    {temDespesas && (
                        <StatCard
                            title={singleYearMode ? `Margem (${yearLabel})` : `Margem / ${unidade}`}
                            value={formatCurrency(margemB)}
                            icon={Scale}
                            trend={showTrend ? `${formatPerformance(margemB - margemA)} vs ${labelA}` : undefined}
                            trendUp={margemB >= 0}
                            trendArrow={margemB >= margemA ? 'up' : 'down'}
                            useTrendColor
                        />
                    )}
                </div>
            </div>
        </>
    );
}
