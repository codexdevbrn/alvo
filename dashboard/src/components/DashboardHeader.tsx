import { Loader2 } from 'lucide-react';

interface DashboardHeaderProps {
    clientName?: string;
    isFiltering?: boolean;
    empresa: string;
    empresaLoading?: boolean;
}

export function DashboardHeader({
    clientName, isFiltering = false, empresa, empresaLoading = false,
}: DashboardHeaderProps) {
    return (
        <header className="app-page-header">
            <div>
                <h1>Dashboard</h1>
                <p className="app-page-header-sub">
                    Visão geral de vendas{empresa ? ` — ${empresa}` : ''}
                    {clientName ? ` · ${clientName}` : ''}
                </p>
            </div>
            <div className="app-page-header-actions">
                {(empresaLoading || isFiltering) && (
                    <div className="dashboard-header-filter-loading" aria-live="polite" aria-busy="true">
                        <Loader2 size={16} className="dashboard-filter-spinner" />
                        <span>{empresaLoading ? 'Carregando…' : 'Atualizando…'}</span>
                    </div>
                )}
            </div>
        </header>
    );
}
