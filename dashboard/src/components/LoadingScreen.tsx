import { RefreshCw } from 'lucide-react';

// ==========================================
// Main Component
// ==========================================

export function LoadingScreen() {
    return (
        <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-main)' }}>
            <RefreshCw className="animate-spin" size={48} color="var(--accent)" />
            <p style={{ marginTop: '1.5rem', color: 'var(--text-secondary)' }}>Carregando dados...</p>
        </div>
    );
}
