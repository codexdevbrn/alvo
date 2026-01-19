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
}

const renderCustomizedLabel = (props: any, isMobile: boolean) => {
    const { x, y, value, index } = props;

    // Mostrando apenas de 2 em 2 meses para não poluir
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
            {formatNumber(Math.round(value))}
        </text>
    );
};

export function HistoryChart({ chartData, labelA, labelB, showA, showB }: HistoryChartProps) {
    const [isMobile, setIsMobile] = useState(window.innerWidth <= 1280);

    useEffect(() => {
        const handleResize = () => setIsMobile(window.innerWidth <= 1280);
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);

    return (
        <div className="glass-card chart-full" style={{ gridColumn: 'span 2', minHeight: isMobile ? '300px' : '380px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: isMobile ? '1rem' : '2rem', flexWrap: 'wrap', gap: '0.5rem' }}>
                <h3 style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', color: 'white', fontSize: isMobile ? '1rem' : '1.25rem' }}>
                    <TrendingUp size={20} color="var(--accent)" /> Histórico
                </h3>
                <div style={{ display: 'flex', gap: '1rem', fontSize: '0.7rem' }}>
                    {showA && <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><div style={{ width: 8, height: 8, borderRadius: '50%', background: '#6366f1' }} /> {labelA}</div>}
                    {showB && <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><div style={{ width: 8, height: 8, borderRadius: '50%', background: '#10b981' }} /> {labelB}</div>}
                </div>
            </div>
            <div style={{ width: '100%', height: isMobile ? '200px' : '280px' }}>
                <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={chartData} margin={{ top: 20, right: 30, left: 10, bottom: 0 }}>
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
                            tick={{ fill: '#94a3b8', fontSize: 10 }}
                            axisLine={false}
                            tickLine={false}
                            padding={{ left: 0, right: 20 }}
                        />
                        <YAxis
                            domain={['auto', 'auto']}
                            tick={{ fill: '#94a3b8', fontSize: 9 }}
                            tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`}
                            axisLine={false}
                            tickLine={false}
                            width={isMobile ? 30 : 40}
                        />
                        <Tooltip
                            contentStyle={{ backgroundColor: '#17171a', border: 'none', borderRadius: '12px', boxShadow: '0 10px 15px -3px rgba(0,0,0,0.3)' }}
                            formatter={(v: any) => formatCurrency(v)}
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
                                <LabelList content={(props) => renderCustomizedLabel(props, isMobile)} />
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
                                <LabelList content={(props) => renderCustomizedLabel(props, isMobile)} />
                            </Area>
                        )}
                    </AreaChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
}
