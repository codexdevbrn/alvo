import { Tags } from 'lucide-react';
import { AppShell } from '../components/AppShell';
import { APrecificar } from '../components/precificacao/APrecificar';
import { useEscopoAtual } from '../hooks/useEscopoAtual';

/** Tela Precificação: SKUs que precisam de preço novo (`backend/a_precificar.py`).
 *  O que já foi precificado e como andou fica na tela Pós-precificação. */
export default function PrecificacaoPage() {
  const { empresa } = useEscopoAtual();

  return (
    <AppShell>
      <div className="dashboard-container estoque-page">
        <header className="app-page-header estoque-page-header prec-cabecalho">
          <div>
            <h1>Precificação{empresa && <span className="analisador-header-empresa"> · {empresa}</span>}</h1>
            <p>Quais produtos precisam de preço novo, a prova de cada um e quanto pesam na receita.</p>
          </div>
        </header>

        {!empresa && (
          <div className="glass-card glass-card-flat estoque-vazio">
            <Tags size={24} aria-hidden="true" />
            <div>
              <strong>Selecione uma empresa</strong>
              <p>Use o seletor no topo para ver o que precisa de preço novo.</p>
            </div>
          </div>
        )}

        {empresa && <APrecificar key={empresa} empresa={empresa} />}
      </div>
    </AppShell>
  );
}
