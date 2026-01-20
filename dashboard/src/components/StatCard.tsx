import type { LucideIcon } from 'lucide-react';

interface StatCardProps {
    title: string;
    value: string | number;
    icon: LucideIcon;
    trend?: string;
    trendUp?: boolean;
    useTrendColor?: boolean;
    onClick?: () => void;
}

export const StatCard = ({ title, value, icon: Icon, trend, trendUp, useTrendColor, onClick }: StatCardProps) => {
    return (
        <div
            className={`glass-card ${onClick ? 'interactive-card' : ''}`}
            onClick={onClick}
            style={{
                display: 'flex',
                alignItems: 'flex-start',
                justifyContent: 'space-between',
                gap: '1rem',
                cursor: onClick ? 'pointer' : 'default'
            }}
        >
            <div style={{ flex: 1, minWidth: 0 }}>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', marginBottom: '0.4rem', textTransform: 'uppercase', letterSpacing: '0.02em' }}>{title}</p>
                <h3 style={{ fontSize: '1.5rem', fontWeight: 'bold', color: 'white', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{value}</h3>
                {trend && (
                    <p style={{
                        fontSize: '0.75rem',
                        marginTop: '0.5rem',
                        color: trendUp ? '#10b981' : '#f43f5e',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '4px',
                        fontWeight: 600
                    }}>
                        {trendUp ? '↑' : '↓'} {trend}
                    </p>
                )}
            </div>
            <div style={{
                padding: '0.65rem',
                background: useTrendColor ? (trendUp ? 'rgba(16, 185, 129, 0.1)' : 'rgba(255, 99, 71, 0.1)') : 'rgba(99, 102, 241, 0.1)',
                borderRadius: '0.9rem',
                color: useTrendColor ? (trendUp ? '#10b981' : '#ff6f61') : 'var(--accent)',
                flexShrink: 0
            }}>
                <Icon size={20} />
            </div>
        </div>
    );
};
