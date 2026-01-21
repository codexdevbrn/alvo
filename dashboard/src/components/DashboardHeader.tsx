// ==========================================
// Types & Interfaces
// ==========================================

interface DashboardHeaderProps {
    updatedAt?: string;
    clientName?: string;
}

// ==========================================
// Main Component
// ==========================================

export function DashboardHeader({ updatedAt, clientName }: DashboardHeaderProps) {
    return (
        <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem', flexWrap: 'wrap', gap: '1rem' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <h1 style={{ color: '#fff', fontSize: '2.5rem', fontWeight: 'bold', margin: 0, lineHeight: 1 }}>Alvo</h1>
                {clientName && (
                    <span style={{ fontSize: '0.9rem', fontWeight: 600, letterSpacing: '0.5px', textTransform: 'uppercase', color: 'rgba(255,255,255,0.9)' }}>
                        {clientName}
                    </span>
                )}
            </div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', textAlign: 'right' }}>
                Atualizado em: <span style={{ color: 'white', fontWeight: 500 }}>{updatedAt || 'Carregando...'}</span>
            </div>
        </header>
    );
}
