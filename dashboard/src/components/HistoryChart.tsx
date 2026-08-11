import { useState, useEffect, useMemo, memo, useLayoutEffect, useRef, useCallback, useId } from 'react';
import { TrendingUp } from 'lucide-react';
import {
    AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LabelList, ReferenceLine,
} from 'recharts';
import { formatCurrency, formatNumber } from '../utils/formatters';
import { abrevMesAtual, mesAbrevDeRotulo } from '../utils/periodoFechado';
import { COR_ANO_ANTERIOR, COR_ANO_RECENTE } from '../utils/coresAno';
import type { ChartPoint } from '../types/dashboard';

// ==========================================
// Types & Interfaces
// ==========================================

interface HistoryChartProps {
    chartData: ChartPoint[];
    labelA: string;
    labelB: string;
    showA: boolean;
    showB: boolean;
    isCurrency?: boolean;
    style?: React.CSSProperties;
    /** Quando true (seleção resultou em um único mês), usa um gráfico de
     * barras comparando os dois períodos em vez de área/linha com 1 ponto. */
    singleMonthMode?: boolean;
    /** Quando true, traça linha vertical no último mês fechado considerado nos cálculos. */
    usarMesesFechados?: boolean;
    mesCorteFechado?: string | null;
    /** Quando true, os filtros estão sendo recalculados: o gráfico sai e,
     * quando os novos dados chegam, se redesenha da esquerda pra direita. */
    isLoading?: boolean;
    /** Cor de cada série. Precisa acompanhar o ano que a série representa, pra
     * bater com as cores do dropdown de período (ver `utils/coresAno`): em modo
     * tendência (um ano só) a série B pode ser o ano anterior, e aí ela tem que
     * sair dourada, não azul. */
    corA?: string;
    corB?: string;
}

// ==========================================
// Helper Components/Functions
// ==========================================

// Quando os valores das duas séries num mesmo ponto estão próximos, seus
// rótulos (ambos desenhados ~10px acima da linha) colidem. Para evitar isso,
// olhamos o valor da série "irmã" no mesmo índice (via chartData) e, se a
// diferença for pequena relativo à escala, afastamos os dois rótulos: o de
// maior valor sobe mais, o de menor valor desce para abaixo do ponto.
/** Campos que o recharts efetivamente passa para `LabelList content` neste uso
 * (posição calculada + valor do ponto); "total" não é declarado no tipo público
 * do recharts mas é passado em runtime pela lib para labels de Area/Bar. */
interface LabelRenderProps {
    x?: number | string;
    y?: number | string;
    value?: number | string | Array<number | string> | boolean | null;
    index?: number;
    total?: number;
}

const renderCustomizedLabel = (
    props: LabelRenderProps,
    isCurrency: boolean,
    chartData: ChartPoint[],
    otherKey: 'revenueA' | 'revenueB',
) => {
    const x = Number(props.x) || 0;
    const y = Number(props.y) || 0;
    const value = Number(props.value) || 0;
    const index = props.index ?? 0;
    const total = props.total ?? 0;

    if (!value || value <= 0) return null;

    // denser skip on very small screens
    const trueMobile = window.innerWidth <= 768;
    const skip = trueMobile ? (total > 12 ? 3 : 2) : (total > 20 ? 3 : 2);
    if (index % skip !== 0) return null;

    let textAnchor: "inherit" | "end" | "start" | "middle" | undefined = "middle";
    let dx = 0;
    if (index === 0) {
        textAnchor = "start";
        dx = 4;
    } else if (index === total - 1) {
        textAnchor = "end";
        dx = -10;
    }

    let dy = -10;
    const otherValue = chartData?.[index]?.[otherKey];
    if (typeof otherValue === 'number' && otherValue > 0) {
        const escala = Math.max(value, otherValue, 1);
        const diferencaRelativa = Math.abs(value - otherValue) / escala;
        if (diferencaRelativa < 0.09) {
            dy = value >= otherValue ? -21 : 15;
        }
    }

    return (
        <text
            x={x}
            y={y + dy}
            dx={dx}
            fill="#ffffff"
            fontSize={trueMobile ? 8 : 10}
            fontWeight={700}
            textAnchor={textAnchor}
            style={{ pointerEvents: 'none', opacity: 0.9 }}
        >
            {isCurrency ? formatCurrency(value).replace(',00', '').replace('R$', '').trim() : formatNumber(value)}
        </text>
    );
};

function formatCompactValue(v: number, isCurrency: boolean): string {
    return isCurrency ? formatCurrency(v).replace(',00', '').replace('R$', '').trim() : formatNumber(v);
}

function formatAxisTick(v: number, isCurrency: boolean): string {
    if (v === 0) return '0';
    if (isCurrency) {
        if (v >= 1000000) return `${(v / 1000000).toFixed(1)}M`;
        if (v >= 1000) return `${(v / 1000).toFixed(0)}k`;
        return v.toString();
    }
    return v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v.toString();
}

interface MonthAxisTickProps {
    x?: number;
    y?: number;
    payload?: { value: string };
    fontSize?: number;
}

function MonthAxisTick({ x = 0, y = 0, payload, fontSize = 9 }: MonthAxisTickProps) {
    const raw = payload?.value ?? '';
    const month = mesAbrevDeRotulo(raw);
    const display = raw.includes('/') ? raw.split('/')[0] : raw;
    const isCurrent = month === abrevMesAtual();

    if (!isCurrent) {
        return (
            <text x={x} y={y} dy={12} textAnchor="middle" fill="#94a3b8" fontSize={fontSize}>
                {display}
            </text>
        );
    }

    return (
        <g transform={`translate(${x},${y})`}>
            <text dy={12} textAnchor="middle" fill="#ffffff" fontSize={fontSize} fontWeight={600}>
                {display}
            </text>
            <line
                x1={-Math.max(10, display.length * 3)}
                y1={16}
                x2={Math.max(10, display.length * 3)}
                y2={16}
                stroke="rgba(255,255,255,0.32)"
                strokeWidth={1}
                strokeLinecap="round"
            />
        </g>
    );
}

function chartMargin(isMobile: boolean) {
    return { top: 28, right: isMobile ? 36 : 52, left: -20, bottom: 12 };
}

const CUTOFF_CHART_LABEL = 'Último período considerado para os cálculos';

interface CutoffDisplay {
    x: string;
    exiting: boolean;
    chartLabel: string;
}

type ChartPhase = 'idle' | 'exiting' | 'entering';

interface AnimatedCutoffGroupProps {
    x1?: number;
    y1?: number;
    x2?: number;
    y2?: number;
    exiting: boolean;
    animKey: number;
    chartLabel: string;
    isMobile: boolean;
    /** Fase do gráfico pai — quando entering/exiting, o corte acompanha o wipe/fade sem animação própria. */
    chartPhase: ChartPhase;
}

/** Durações alinhadas a `.chart-phase-exiting` / `chart-redraw-in` em index.css. */
const CHART_ENTER_MS = 980;

const ENTER_LINE_MS = 520;
const ENTER_LABEL_MS = 420;
const EXIT_LABEL_MS = 360;
const EXIT_LINE_MS = 420;
/** Texto só começa depois da barra subir (toggle de meses fechados, gráfico idle). */
const ENTER_LABEL_DELAY_MS = ENTER_LINE_MS;
/** Barra só desce depois do texto sumir (toggle de meses fechados, gráfico idle). */
const EXIT_LINE_DELAY_MS = EXIT_LABEL_MS;

/** cubic-bezier equivalente ao easeOutCubic. */
const EASE_OUT = 'cubic-bezier(0.33, 1, 0.68, 1)';
/** cubic-bezier equivalente ao easeInOutCubic. */
const EASE_IN_OUT = 'cubic-bezier(0.65, 0, 0.35, 1)';

/** Linha + rótulo: barra↑ → texto sai da barra←; saída: texto→ na barra → barra↓.
 *
 * Animado com transições CSS em transform/opacity, que rodam no compositor:
 * o toggle do corte dispara um re-render pesado do gráfico que trava a main
 * thread por centenas de ms, e qualquer loop de rAF (ou stroke-dasharray/
 * clip-path, que ainda por cima repintam o blur do `.glass-card`) congela ou
 * pula junto com a thread. A transição CSS segue fluida mesmo com JS bloqueado.
 *
 * Quando o gráfico inteiro está em entering/exiting, NÃO rodamos essa sequência:
 * o wipe/fade do `.chart-area` já revela/esconde barra+texto juntos. */
function AnimatedCutoffGroup({
    x1, y1, x2, y2, exiting, animKey, chartLabel, isMobile, chartPhase,
}: AnimatedCutoffGroupProps) {
    const lineRef = useRef<SVGLineElement>(null);
    const labelRef = useRef<SVGTextElement>(null);
    const exitRunningRef = useRef(false);
    const chartDriven = chartPhase === 'entering' || chartPhase === 'exiting';

    // Gráfico pai animando: estado final estático — entra/sai com o wipe/fade.
    useLayoutEffect(() => {
        if (!chartDriven) return;
        if (x1 == null || y1 == null || x2 == null || y2 == null) return;
        const line = lineRef.current;
        const label = labelRef.current;
        if (line == null || label == null) return;

        exitRunningRef.current = false;
        const x = x1;
        const yBottom = Math.max(y1, y2);

        line.style.transition = 'none';
        line.style.transformBox = 'view-box';
        line.style.transformOrigin = `${x}px ${yBottom}px`;
        line.style.transform = 'scaleY(1)';
        label.style.transition = 'none';
        label.style.transform = 'translateX(0)';
        label.style.opacity = '1';
    }, [x1, y1, x2, y2, chartDriven, animKey]);

    // Entrada — só no toggle do corte com gráfico idle
    useLayoutEffect(() => {
        if (chartDriven || exiting) return;
        if (x1 == null || y1 == null || x2 == null || y2 == null) return;
        const line = lineRef.current;
        const label = labelRef.current;
        if (line == null || label == null) return;

        exitRunningRef.current = false;

        const x = x1;
        const yBottom = Math.max(y1, y2);
        const slideIntoBar = isMobile ? 18 : 24;

        line.style.transition = 'none';
        line.style.transformBox = 'view-box';
        line.style.transformOrigin = `${x}px ${yBottom}px`;
        line.style.transform = 'scaleY(0)';
        label.style.transition = 'none';
        label.style.transform = `translateX(${slideIntoBar}px)`;
        label.style.opacity = '0';

        void line.getBoundingClientRect();

        line.style.transition = `transform ${ENTER_LINE_MS}ms ${EASE_OUT}`;
        line.style.transform = 'scaleY(1)';
        label.style.transition = `transform ${ENTER_LABEL_MS}ms ${EASE_OUT} ${ENTER_LABEL_DELAY_MS}ms, opacity ${ENTER_LABEL_MS}ms ${EASE_OUT} ${ENTER_LABEL_DELAY_MS}ms`;
        label.style.transform = 'translateX(0)';
        label.style.opacity = '1';
    }, [x1, y1, x2, y2, animKey, isMobile, exiting, chartDriven]);

    // Saída — só no toggle do corte com gráfico idle
    useLayoutEffect(() => {
        if (chartDriven || !exiting) return;
        if (exitRunningRef.current) return;
        if (x1 == null || y1 == null || x2 == null || y2 == null) return;
        const line = lineRef.current;
        const label = labelRef.current;
        if (line == null || label == null) return;

        exitRunningRef.current = true;

        const x = x1;
        const yBottom = Math.max(y1, y2);
        const slideIntoBar = isMobile ? 18 : 24;

        line.style.transition = 'none';
        line.style.transformBox = 'view-box';
        line.style.transformOrigin = `${x}px ${yBottom}px`;
        line.style.transform = 'scaleY(1)';
        label.style.transition = 'none';
        label.style.transform = 'translateX(0)';
        label.style.opacity = '1';

        void line.getBoundingClientRect();

        label.style.transition = `transform ${EXIT_LABEL_MS}ms ${EASE_IN_OUT}, opacity ${EXIT_LABEL_MS}ms ${EASE_IN_OUT}`;
        label.style.transform = `translateX(${slideIntoBar}px)`;
        label.style.opacity = '0';
        line.style.transition = `transform ${EXIT_LINE_MS}ms ${EASE_OUT} ${EXIT_LINE_DELAY_MS}ms`;
        line.style.transform = 'scaleY(0)';

        return () => {
            exitRunningRef.current = false;
        };
    }, [x1, y1, x2, y2, exiting, animKey, isMobile, chartDriven]);

    if (x1 == null || y1 == null || x2 == null || y2 == null) return null;

    const x = x1;
    const yBottom = Math.max(y1, y2);
    const yTop = Math.min(y1, y2);

    return (
        <g className="chart-cutoff-group">
            <line
                ref={lineRef}
                x1={x}
                y1={yBottom}
                x2={x}
                y2={yTop}
                stroke="rgba(148, 163, 184, 0.42)"
                strokeWidth={1.5}
                strokeLinecap="round"
            />
            <text
                ref={labelRef}
                x={x - 6}
                y={yTop + (isMobile ? 10 : 12)}
                textAnchor="end"
                className="chart-cutoff-chart-label"
            >
                {chartLabel}
            </text>
        </g>
    );
}

// ==========================================
// Main Component
// ==========================================

function chartDataEqual(a: ChartPoint[], b: ChartPoint[]): boolean {
    if (a === b) return true;
    if (a.length !== b.length) return false;
    return a.every((p, i) => {
        const q = b[i];
        return p.name === q.name && p.revenueA === q.revenueA && p.revenueB === q.revenueB;
    });
}

/** Nome do @keyframes em index.css — usado pra filtrar o evento de término
 * (o elemento é pai do SVG inteiro do recharts, então `animationend`/
 * `transitionend` de qualquer coisa lá dentro borbulha até aqui). */
const CHART_REDRAW_ANIMATION_NAME = 'chart-redraw-in';
/** Duração do keyframe em index.css. Rede de segurança — ver comentário no efeito abaixo. */
const CHART_ENTER_MS_SAFE = CHART_ENTER_MS;

function HistoryChartInner({
    chartData, labelA, labelB, showA, showB, isCurrency = true, style,
    singleMonthMode = false, usarMesesFechados = false, mesCorteFechado = null,
    isLoading = false, corA = COR_ANO_ANTERIOR, corB = COR_ANO_RECENTE,
}: HistoryChartProps) {
    const [isMobile, setIsMobile] = useState(window.innerWidth <= 1280);
    // Ids de gradiente únicos por instância: o Dashboard e o modal de detalhe
    // renderizam dois HistoryChart ao mesmo tempo, e ids de SVG são globais no
    // documento — com cores agora variáveis, ids fixos pintariam um com o
    // gradiente do outro.
    const gradSufixo = useId().replace(/[^a-zA-Z0-9]/g, '');
    const gradA = `chartGradA-${gradSufixo}`;
    const gradB = `chartGradB-${gradSufixo}`;

    // Saída ao começar a recalcular; redesenho (wipe) quando os dados novos
    // chegam. Ajuste de estado durante o render (padrão React p/ reagir a
    // mudança de prop) em vez de setState síncrono dentro de efeito.
    const [chartPhase, setChartPhase] = useState<ChartPhase>('idle');
    const [prevIsLoading, setPrevIsLoading] = useState(isLoading);
    if (isLoading !== prevIsLoading) {
        setPrevIsLoading(isLoading);
        setChartPhase(isLoading ? 'exiting' : 'entering');
    }

    // Fecha a fase 'entering' no fim real da animação (evento nativo) — mas
    // com uma rede de segurança por timer: navegadores pausam a animação CSS
    // (e nunca disparam `animationend`) quando a aba fica em segundo plano
    // (document.hidden), o que travaria o gráfico invisível pra sempre se só
    // dependêssemos do evento. O que disparar primeiro resolve; o outro vira
    // no-op porque a fase já não é mais 'entering'.
    const endChartEntering = useCallback(() => {
        setChartPhase((p) => (p === 'entering' ? 'idle' : p));
    }, []);

    const handleChartAreaAnimationEnd = (e: React.AnimationEvent<HTMLDivElement>) => {
        if (e.target !== e.currentTarget) return;
        if (e.animationName !== CHART_REDRAW_ANIMATION_NAME) return;
        endChartEntering();
    };

    useEffect(() => {
        if (chartPhase !== 'entering') return;
        const t = window.setTimeout(endChartEntering, CHART_ENTER_MS_SAFE + 150);
        return () => window.clearTimeout(t);
    }, [chartPhase, endChartEntering]);

    const mesCorteX = useMemo(() => {
        if (!usarMesesFechados || !mesCorteFechado || chartData.length === 0) return null;
        const alvo = mesCorteFechado.toLowerCase();
        const ponto = chartData.find(
            (d) => d.name.toLowerCase() === alvo || d.name.split('/')[0].toLowerCase() === alvo,
        );
        return ponto?.name ?? null;
    }, [chartData, usarMesesFechados, mesCorteFechado]);

    const [displayCorte, setDisplayCorte] = useState<CutoffDisplay | null>(
        mesCorteX ? { x: mesCorteX, exiting: false, chartLabel: CUTOFF_CHART_LABEL } : null,
    );
    const [cutoffAnimKey, setCutoffAnimKey] = useState(0);
    const [prevMesCorteX, setPrevMesCorteX] = useState(mesCorteX);

    // Ajuste de estado durante o render (padrão React p/ reagir a mudança de
    // prop/valor derivado) em vez de setState síncrono dentro de efeito.
    if (mesCorteX !== prevMesCorteX) {
        setPrevMesCorteX(mesCorteX);
        if (mesCorteX) {
            setCutoffAnimKey((k) => k + 1);
            setDisplayCorte({ x: mesCorteX, exiting: false, chartLabel: CUTOFF_CHART_LABEL });
        } else {
            setDisplayCorte((prev) => (prev ? { ...prev, exiting: true } : null));
        }
    }

    // Só o timer (efeito colateral de verdade) fica no efeito.
    useEffect(() => {
        if (mesCorteX) return;
        // Folga generosa: a animação usa tempo acumulado com delta limitado
        // (MAX_FRAME_DELTA_MS), então travamentos da main thread a alongam em
        // tempo de parede — desmontar cedo demais cortaria o final dela.
        const t = window.setTimeout(() => setDisplayCorte(null), EXIT_LINE_DELAY_MS + EXIT_LINE_MS + 700);
        return () => window.clearTimeout(t);
    }, [mesCorteX]);

    // ==========================================
    // Effects
    // ==========================================

    useEffect(() => {
        const handleResize = () => setIsMobile(window.innerWidth <= 1280);
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);

    const containerStyle: React.CSSProperties = {
        gridColumn: 'span 2',
        width: '100%',
        height: isMobile ? '380px' : '450px',
        minHeight: isMobile ? '380px' : '450px',
        background: style ? 'transparent' : undefined,
        border: style ? 'none' : undefined,
        boxShadow: style ? 'none' : undefined,
        padding: style ? '0' : (isMobile ? '1.25rem 0.75rem' : '1.5rem'),
        display: 'flex',
        flexDirection: 'column',
        boxSizing: 'border-box',
        ...style
    };

    // ==========================================
    // Render
    // ==========================================

    return (
        <div className="glass-card chart-full" style={containerStyle}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: isMobile ? '1rem' : '1.5rem', flexWrap: 'wrap', gap: '0.5rem' }}>
                <h3 style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', color: 'white', fontSize: isMobile ? '1rem' : '1.1rem' }}>
                    <TrendingUp size={20} color="var(--accent)" /> Histórico
                </h3>
                <div style={{ display: 'flex', gap: '1rem', fontSize: '0.7rem', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                    {showA && <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><div style={{ width: 8, height: 8, borderRadius: '50%', background: corA }} /> {labelA}</div>}
                    {showB && <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><div style={{ width: 8, height: 8, borderRadius: '50%', background: corB }} /> {labelB}</div>}
                </div>
            </div>
            <div
                className={`chart-area chart-phase-${chartPhase}`}
                style={{ flex: 1, width: '100%', minHeight: isMobile ? '250px' : '300px' }}
                onAnimationEnd={handleChartAreaAnimationEnd}
            >
                <ResponsiveContainer width="100%" height="100%">
                    {singleMonthMode ? (
                        <BarChart data={chartData} margin={chartMargin(isMobile)} barGap={8} accessibilityLayer={false}>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(255,255,255,0.05)" />
                            <XAxis
                                dataKey="name"
                                axisLine={false}
                                tickLine={false}
                                height={isMobile ? 30 : 40}
                                tick={(props) => <MonthAxisTick {...props} fontSize={11} />}
                            />
                            <YAxis
                                domain={[0, (dataMax: number) => dataMax * 1.2]}
                                tick={{ fill: '#94a3b8', fontSize: 10 }}
                                tickFormatter={(v) => formatAxisTick(v, isCurrency)}
                                axisLine={false}
                                tickLine={false}
                                width={window.innerWidth <= 768 ? 40 : 60}
                            />
                            <Tooltip
                                contentStyle={{ backgroundColor: '#17171a', border: 'none', borderRadius: '12px', boxShadow: '0 10px 15px -3px rgba(0,0,0,0.3)' }}
                                formatter={(v: unknown) => isCurrency ? formatCurrency(Number(v)) : formatNumber(Number(v))}
                                cursor={{ fill: 'rgba(255,255,255,0.04)', radius: 8 }}
                            />
                            {showA && (
                                <Bar name={labelA} dataKey="revenueA" fill={corA} radius={[6, 6, 0, 0]} maxBarSize={72} isAnimationActive={false}>
                                    <LabelList
                                        dataKey="revenueA"
                                        position="top"
                                        formatter={(v: unknown) => formatCompactValue(Number(v) || 0, isCurrency)}
                                        fill="#ffffff"
                                        fontSize={11}
                                        fontWeight={700}
                                    />
                                </Bar>
                            )}
                            {showB && (
                                <Bar name={labelB} dataKey="revenueB" fill={corB} radius={[6, 6, 0, 0]} maxBarSize={72} isAnimationActive={false}>
                                    <LabelList
                                        dataKey="revenueB"
                                        position="top"
                                        formatter={(v: unknown) => formatCompactValue(Number(v) || 0, isCurrency)}
                                        fill="#ffffff"
                                        fontSize={11}
                                        fontWeight={700}
                                    />
                                </Bar>
                            )}
                        </BarChart>
                    ) : (
                        <AreaChart data={chartData} margin={chartMargin(isMobile)} accessibilityLayer={false}>
                            <defs>
                                <linearGradient id={gradA} x1="0" y1="0" x2="0" y2="1">
                                    <stop offset="5%" stopColor={corA} stopOpacity={0.3} />
                                    <stop offset="95%" stopColor={corA} stopOpacity={0} />
                                </linearGradient>
                                <linearGradient id={gradB} x1="0" y1="0" x2="0" y2="1">
                                    <stop offset="5%" stopColor={corB} stopOpacity={0.35} />
                                    <stop offset="95%" stopColor={corB} stopOpacity={0} />
                                </linearGradient>
                            </defs>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(255,255,255,0.05)" />
                            <XAxis
                                dataKey="name"
                                axisLine={false}
                                tickLine={false}
                                height={isMobile ? 30 : 40}
                                interval={0}
                                minTickGap={0}
                                tick={(props) => <MonthAxisTick {...props} fontSize={9} />}
                            />
                            <YAxis
                                domain={[0, (dataMax: number) => dataMax * 1.2]}
                                tick={{ fill: '#94a3b8', fontSize: 10 }}
                                tickFormatter={(v) => formatAxisTick(v, isCurrency)}
                                axisLine={false}
                                tickLine={false}
                                width={window.innerWidth <= 768 ? 40 : 60}
                                hide={false}
                            />
                            <Tooltip
                                contentStyle={{ backgroundColor: '#17171a', border: 'none', borderRadius: '12px', boxShadow: '0 10px 15px -3px rgba(0,0,0,0.3)' }}
                                formatter={(v: unknown) => isCurrency ? formatCurrency(Number(v)) : formatNumber(Number(v))}
                            />
                            {showA && (
                                <Area
                                    name={labelA}
                                    type="monotone"
                                    dataKey="revenueA"
                                    stroke={corA}
                                    fill={`url(#${gradA})`}
                                    strokeWidth={2}
                                    isAnimationActive={false}
                                    connectNulls={false}
                                >
                                    <LabelList content={(props) => renderCustomizedLabel(props, isCurrency, chartData, 'revenueB')} />
                                </Area>
                            )}
                            {showB && (
                                <Area
                                    name={labelB}
                                    type="monotone"
                                    dataKey="revenueB"
                                    stroke={corB}
                                    fill={`url(#${gradB})`}
                                    strokeWidth={2}
                                    isAnimationActive={false}
                                    connectNulls={false}
                                >
                                    <LabelList content={(props) => renderCustomizedLabel(props, isCurrency, chartData, 'revenueA')} />
                                </Area>
                            )}
                            {displayCorte && (
                                <ReferenceLine
                                    x={displayCorte.x}
                                    stroke="none"
                                    ifOverflow="extendDomain"
                                    shape={(props) => (
                                        <AnimatedCutoffGroup
                                            {...props}
                                            exiting={displayCorte.exiting}
                                            animKey={cutoffAnimKey}
                                            chartLabel={displayCorte.chartLabel}
                                            isMobile={isMobile}
                                            chartPhase={chartPhase}
                                        />
                                    )}
                                />
                            )}
                        </AreaChart>
                    )}
                </ResponsiveContainer>
            </div>
        </div>
    );
}

export const HistoryChart = memo(HistoryChartInner, (prev, next) => (
    chartDataEqual(prev.chartData, next.chartData)
    && prev.labelA === next.labelA
    && prev.labelB === next.labelB
    && prev.showA === next.showA
    && prev.showB === next.showB
    && prev.singleMonthMode === next.singleMonthMode
    && prev.isCurrency === next.isCurrency
    && prev.usarMesesFechados === next.usarMesesFechados
    && prev.mesCorteFechado === next.mesCorteFechado
    && prev.isLoading === next.isLoading
    && prev.corA === next.corA
    && prev.corB === next.corB
));
