import { useState, useEffect } from 'react';
import { TrendingUp } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LabelList } from 'recharts';
import { formatCurrency, formatNumber } from '../utils/formatters';

// ==========================================
// Types & Interfaces
// ==========================================

interface HistoryChartProps {
    chartData: any[];
    labelA: string;
    labelB: string;
    showA: boolean;
    showB: boolean;
    isCurrency?: boolean;
    style?: React.CSSProperties;
}

// ==========================================
// Helper Components/Functions
// ==========================================

const renderCustomizedLabel = (props: any, isCurrency: boolean) => {
    const { x, y, value, index, total } = props;

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
        dx = -4;
    }

    return (
        <text
            x={x}
            y={y - 10}
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

// ==========================================
// Main Component
// ==========================================

export function HistoryChart({ chartData, labelA, labelB, showA, showB, isCurrency = true, style }: HistoryChartProps) {
    const [isMobile, setIsMobile] = useState(window.innerWidth <= 1280);

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
                <div style={{ display: 'flex', gap: '1rem', fontSize: '0.7rem' }}>
                    {showA && <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><div style={{ width: 8, height: 8, borderRadius: '50%', background: '#6366f1' }} /> {labelA}</div>}
                    {showB && <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><div style={{ width: 8, height: 8, borderRadius: '50%', background: '#10b981' }} /> {labelB}</div>}
                </div>
            </div>
            <div style={{ flex: 1, width: '100%', minHeight: isMobile ? '250px' : '300px' }}>
                <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={chartData} margin={{ top: 25, right: isMobile ? 10 : 20, left: -20, bottom: 10 }}>
                        <defs>
                            <linearGradient id="colorA" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                                <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                            </linearGradient>
                            <linearGradient id="colorB" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                                <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                            </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(255,255,255,0.05)" />
                        <XAxis
                            dataKey="name"
                            tick={{ fill: '#94a3b8', fontSize: 9 }}
                            axisLine={false}
                            tickLine={false}
                            height={isMobile ? 30 : 40}
                            interval={chartData.length > 20 ? 3 : (chartData.length > 10 ? 1 : 0)}
                        />
                        <YAxis
                            domain={[0, (dataMax: number) => dataMax * 1.2]}
                            tick={{ fill: '#94a3b8', fontSize: 10 }}
                            tickFormatter={(v) => {
                                if (v === 0) return '0';
                                if (isCurrency) {
                                    if (v >= 1000000) return `${(v / 1000000).toFixed(1)}M`;
                                    if (v >= 1000) return `${(v / 1000).toFixed(0)}k`;
                                    return v.toString();
                                }
                                return v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v.toString();
                            }}
                            axisLine={false}
                            tickLine={false}
                            width={window.innerWidth <= 768 ? 40 : 60}
                            hide={false}
                        />
                        <Tooltip
                            contentStyle={{ backgroundColor: '#17171a', border: 'none', borderRadius: '12px', boxShadow: '0 10px 15px -3px rgba(0,0,0,0.3)' }}
                            formatter={(v: any) => isCurrency ? formatCurrency(v) : formatNumber(v)}
                        />
                        {showA && (
                            <Area
                                name={labelA}
                                type="monotone"
                                dataKey="revenueA"
                                stroke="#6366f1"
                                fill="url(#colorA)"
                                strokeWidth={2}
                                animationDuration={1000}
                            >
                                <LabelList content={(props) => renderCustomizedLabel(props, isCurrency)} />
                            </Area>
                        )}
                        {showB && (
                            <Area
                                name={labelB}
                                type="monotone"
                                dataKey="revenueB"
                                stroke="#10b981"
                                fill="url(#colorB)"
                                strokeWidth={2}
                                animationDuration={1000}
                            >
                                <LabelList content={(props) => renderCustomizedLabel(props, isCurrency)} />
                            </Area>
                        )}
                    </AreaChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
}
