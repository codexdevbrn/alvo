import { BadgePercent } from 'lucide-react';
import { AppShell } from '../components/AppShell';
import { PosPrecificacaoHistorico } from '../components/precificacao/PosPrecificacaoHistorico';
import { useEscopoAtual } from '../hooks/useEscopoAtual';

/** Tela Pós-precificação: quando cada produto foi precificado, com que alvo, e
 *  como vendeu antes e depois — todas as rodadas, sem prender a uma. */
export default function PosPrecificacaoPage() {
  const { empresa } = useEscopoAtual();

  return (
    <AppShell>
      <div className="dashboard-container estoque-page">
        <header className="app-page-header estoque-page-header prec-cabecalho">
          <div>
            <h1>Pós-precificação{empresa && <span className="analisador-header-empresa"> · {empresa}</span>}</h1>
            <p>Quando cada produto foi precificado, com que alvo, e como vendeu antes e depois.</p>
          </div>
        </header>

        {!empresa && (
          <div className="glass-card glass-card-flat estoque-vazio">
            <BadgePercent size={24} aria-hidden="true" />
            <div>
              <strong>Selecione uma empresa</strong>
              <p>Use o seletor no topo para carregar as precificações.</p>
            </div>
          </div>
        )}

        {empresa && <PosPrecificacaoHistorico key={empresa} empresa={empresa} />}
      </div>
    </AppShell>
  );
}
