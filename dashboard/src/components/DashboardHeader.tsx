import { BarChart3, Loader2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { getToken } from '../api/client';
import { EmpresaSelector } from './EmpresaSelector';

// ==========================================
// Types & Interfaces
// ==========================================

interface DashboardHeaderProps {
    updatedAt?: string;
    clientName?: string;
    isFiltering?: boolean;
    empresa: string;
    onEmpresaChange: (empresa: string) => void;
    empresaLoading?: boolean;
}

function PrismaLogo() {
    return (
        <svg
            className="prisma-logo"
            viewBox="0 0 32 32"
            aria-hidden="true"
            fill="none"
        >
            {/* Face esquerda */}
            <path
                d="M16 5 L6 27 H16 Z"
                fill="currentColor"
                opacity="0.18"
            />
            {/* Face direita */}
            <path
                d="M16 5 L26 27 H16 Z"
                fill="currentColor"
                opacity="0.08"
            />
            {/* Contorno do prisma */}
            <path
                d="M16 5 L26 27 H6 Z"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinejoin="round"
            />
            {/* Aresta central */}
            <path
                d="M16 5 V27"
                stroke="currentColor"
                strokeWidth="1.35"
                strokeLinecap="round"
                opacity="0.7"
            />
            {/* Corte de refração */}
            <path
                d="M9.2 20 H22.8"
                stroke="currentColor"
                strokeWidth="1.25"
                strokeLinecap="round"
                opacity="0.45"
            />
        </svg>
    );
}

// ==========================================
// Main Component
// ==========================================

export function DashboardHeader({
    updatedAt, clientName, isFiltering = false, empresa, onEmpresaChange, empresaLoading = false,
}: DashboardHeaderProps) {
    const navigate = useNavigate();

    return (
        <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem', flexWrap: 'wrap', gap: '1rem' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <div className="prisma-brand">
                    <PrismaLogo />
                    <h1 className="prisma-wordmark">Prisma</h1>
                </div>
                {clientName && (
                    <span style={{ fontSize: '0.9rem', fontWeight: 600, letterSpacing: '0.5px', textTransform: 'uppercase', color: 'rgba(255,255,255,0.9)', paddingLeft: '2.45rem' }}>
                        {clientName}
                    </span>
                )}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem', flexWrap: 'wrap' }}>
                {isFiltering && (
                    <div className="dashboard-header-filter-loading" aria-live="polite" aria-busy="true">
                        <Loader2 size={16} className="dashboard-filter-spinner" />
                        <span>Atualizando…</span>
                    </div>
                )}
                <EmpresaSelector empresa={empresa} onChange={onEmpresaChange} loading={empresaLoading} />
                <button
                    onClick={() => navigate(getToken() ? '/analisador' : '/login')}
                    style={{
                        display: 'inline-flex', alignItems: 'center', gap: '0.5rem', background: 'rgba(99,102,241,0.15)',
                        color: '#fff', border: '1px solid var(--border)', borderRadius: '0.65rem', padding: '0.55rem 1rem',
                        fontSize: '0.85rem', fontWeight: 600, cursor: 'pointer',
                    }}
                >
                    <BarChart3 size={16} /> Analisador de Monitoria
                </button>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', textAlign: 'right' }}>
                    Atualizado em: <span style={{ color: 'white', fontWeight: 500 }}>{updatedAt || 'Carregando...'}</span>
                </div>
            </div>
        </header>
    );
}
