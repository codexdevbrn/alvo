// ==========================================
// Types & Interfaces
// ==========================================

interface DashboardHeaderProps {
    updatedAt?: string;
}

// ==========================================
// Main Component
// ==========================================

export function DashboardHeader({ updatedAt }: DashboardHeaderProps) {
    return (
        <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem' }}>
            <h1 style={{ color: '#fff', fontSize: '2.5rem', fontWeight: 'bold', margin: 0 }}>Alvo</h1>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', textAlign: 'right' }}>
                Atualizado em: <span style={{ color: 'white', fontWeight: 500 }}>{updatedAt || 'Carregando...'}</span>
            </div>
        </header>
    );
}
