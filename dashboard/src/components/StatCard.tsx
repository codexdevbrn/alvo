import type { CSSProperties } from 'react';
import type { LucideIcon } from 'lucide-react';

interface StatCardProps {
    title: string;
    value: string | number;
    icon: LucideIcon;
    trend?: string;
    trendUp?: boolean;
    /** Direção da seta do trend. Por padrão segue `trendUp`, que também é a cor.
     *  Em Despesas os dois divergem: queda de gasto é boa (verde) mas o número
     *  caiu, então a seta precisa apontar para baixo enquanto a cor diz "bom". */
    trendArrow?: 'up' | 'down';
    useTrendColor?: boolean;
    /** Classe extra pro valor — usada quando ele é um nome/texto longo em vez
     *  de um número curto, caso em que o nowrap+ellipsis padrão trunca demais. */
    valueClassName?: string;
    onClick?: () => void;
}

export const StatCard = ({ title, value, icon: Icon, trend, trendUp, trendArrow, useTrendColor, valueClassName, onClick }: StatCardProps) => {
    const accentColor = useTrendColor ? (trendUp ? 'var(--success)' : 'var(--danger)') : 'var(--accent)';
    return (
        <div
            className={`glass-card stat-card-container ${onClick ? 'interactive-card' : ''} stat-card-responsive`}
            onClick={onClick}
            style={{ '--stat-accent': accentColor } as CSSProperties}
        >
            <div className="stat-card-content">
                <p className="stat-card-title">{title}</p>
                <h3
                    className={`stat-card-value ${valueClassName ?? ''}`}
                    title={typeof value === 'string' ? value : undefined}
                >{value}</h3>
                {trend && (
                    <p className="stat-card-trend" style={{
                        color: trendUp ? 'var(--success)' : 'var(--danger)'
                    }}>
                        {(trendArrow ?? (trendUp ? 'up' : 'down')) === 'up' ? '↑' : '↓'} {trend}
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
