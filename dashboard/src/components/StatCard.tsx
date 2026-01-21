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
            className={`glass-card stat-card-container ${onClick ? 'interactive-card' : ''} stat-card-responsive`}
            onClick={onClick}
        >
            <div className="stat-card-content">
                <p className="stat-card-title">{title}</p>
                <h3 className="stat-card-value">{value}</h3>
                {trend && (
                    <p className="stat-card-trend" style={{
                        color: trendUp ? '#10b981' : '#f43f5e'
                    }}>
                        {trendUp ? '↑' : '↓'} {trend}
                    </p>
                )}
            </div>
            <div className="stat-card-icon-container" style={{
                background: useTrendColor ? (trendUp ? 'rgba(16, 185, 129, 0.1)' : 'rgba(255, 99, 71, 0.1)') : 'rgba(99, 102, 241, 0.1)',
                color: useTrendColor ? (trendUp ? '#10b981' : '#ff6f61') : 'var(--accent)',
            }}>
                <Icon className="stat-icon" />
            </div>
        </div>
    );
};
