import { BadgePercent } from 'lucide-react';
import { AppShell } from '../components/AppShell';
import { PosPrecificacaoVisao } from '../components/precificacao/PosPrecificacaoVisao';
import { useEscopoAtual } from '../hooks/useEscopoAtual';

/** Casca da tela Pós precificação: dump da última rodada + desempenho no movimento.
 *  Fonte `{empresa}_PRECIFICACAO.csv`, opcional — 404 vira estado vazio na visão. */
export default function PosPrecificacaoPage() {
  const { empresa, loja } = useEscopoAtual();

  return (
    <AppShell>
      <div className="dashboard-container estoque-page">
        <header className="app-page-header estoque-page-header">
          <div>
            <h1>Pós precificação{empresa && <span className="analisador-header-empresa"> · {empresa}</span>}</h1>
            <p>Última rodada, lucro bruto / dia e quantidade / dia — clique num produto pra ver a série.</p>
          </div>
        </header>

        {!empresa && (
          <div className="glass-card glass-card-flat estoque-vazio">
            <BadgePercent size={24} aria-hidden="true" />
            <div>
              <strong>Selecione uma empresa</strong>
              <p>Use o seletor no topo para carregar o dump de precificação.</p>
            </div>
          </div>
        )}

        {empresa && <PosPrecificacaoVisao empresa={empresa} loja={loja} />}
      </div>
    </AppShell>
  );
}
