import { useState, useEffect } from 'react';
import { TrendingUp } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LabelList } from 'recharts';
import { formatCurrency, formatNumber } from '../utils/formatters';

interface HistoryChartProps {
    chartData: any[];
    labelA: string;
    labelB: string;
    showA: boolean;
    showB: boolean;
    isCurrency?: boolean;
    style?: React.CSSProperties;
}

const renderCustomizedLabel = (props: any, isMobile: boolean, isCurrency: boolean) => {
    const { x, y, value, index } = props;

    if (!value || value <= 0 || index % 2 !== 0) return null;

    return (
        <text
            x={x}
            y={y - 12}
            dx={index === 0 ? 5 : 0}
            fill="var(--text-secondary)"
            fontSize={isMobile ? 8 : 11}
            fontWeight={600}
            textAnchor={index === 0 ? "start" : "middle"}
        >
            {isCurrency ? formatCurrency(value) : formatNumber(value)}
        </text>
    );
};

export function HistoryChart({ chartData, labelA, labelB, showA, showB, isCurrency = true, style }: HistoryChartProps) {
    const [isMobile, setIsMobile] = useState(window.innerWidth <= 1280);

    useEffect(() => {
        const handleResize = () => setIsMobile(window.innerWidth <= 1280);
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);

    // If style is provided, we might be inside a modal, so we disable some card styles
    const containerStyle: React.CSSProperties = {
        gridColumn: 'span 2',
        minHeight: isMobile ? '300px' : '380px',
        background: style ? 'transparent' : undefined,
        border: style ? 'none' : undefined,
        boxShadow: style ? 'none' : undefined,
        padding: style ? '0' : undefined,
        ...style
    };

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
            <div style={{ width: '100%', height: style?.height ? `calc(${style.height} - 60px)` : (isMobile ? '200px' : '280px') }}>
                <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={chartData} margin={{ top: 20, right: 30, left: 10, bottom: 20 }}>
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
                            height={40}
                            interval={chartData.length > 12 ? (chartData.length > 24 ? 3 : 1) : 0}
                        />
                        <YAxis
                            domain={['auto', 'auto']}
                            tick={{ fill: '#94a3b8', fontSize: 9 }}
                            tickFormatter={(v) => {
                                if (!isCurrency) return v.toLocaleString();
                                if (v >= 1000000) return `${(v / 1000000).toFixed(1)}M`;
                                if (v >= 1000) return `${(v / 1000).toFixed(0)}k`;
                                return v.toString();
                            }}
                            axisLine={false}
                            tickLine={false}
                            width={isMobile ? 35 : 50}
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
                                <LabelList content={(props) => renderCustomizedLabel(props, isMobile, isCurrency)} />
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
                                <LabelList content={(props) => renderCustomizedLabel(props, isMobile, isCurrency)} />
                            </Area>
                        )}
                    </AreaChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
}
