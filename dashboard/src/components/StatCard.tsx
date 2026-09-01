import type { CSSProperties } from 'react';
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
    const accentColor = useTrendColor ? (trendUp ? 'var(--success)' : 'var(--danger)') : 'var(--accent)';
    return (
        <div
            className={`glass-card stat-card-container ${onClick ? 'interactive-card' : ''} stat-card-responsive`}
            onClick={onClick}
            style={{ '--stat-accent': accentColor } as CSSProperties}
        >
            <div className="stat-card-content">
                <p className="stat-card-title">{title}</p>
                <h3 className="stat-card-value">{value}</h3>
                {trend && (
                    <p className="stat-card-trend" style={{
                        color: trendUp ? 'var(--success)' : 'var(--danger)'
                    }}>
                        {trendUp ? '↑' : '↓'} {trend}
                    </p>
                )}
            </div>
            <div className="stat-card-icon-container" style={{
                background: useTrendColor ? (trendUp ? 'var(--success-bg)' : 'var(--danger-bg)') : 'var(--accent)',
                color: useTrendColor ? (trendUp ? 'var(--success)' : 'var(--danger)') : 'var(--accent-contrast)',
            }}>
                <Icon className="stat-icon" />
            </div>
        </div>
    );
};
