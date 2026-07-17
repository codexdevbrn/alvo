import { RefreshCw } from 'lucide-react';

export function LoadingScreen() {
  return (
    <div className="loading-screen" role="status" aria-live="polite" aria-busy="true">
      <div className="loading-screen-orb" aria-hidden="true" />
      <RefreshCw className="loading-screen-icon" size={48} strokeWidth={2.25} aria-hidden="true" />
      <p className="loading-screen-text">Carregando dados...</p>
    </div>
  );
}
