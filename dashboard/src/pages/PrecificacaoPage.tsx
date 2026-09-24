import { useLocation, useNavigate } from 'react-router-dom';
import { Tags } from 'lucide-react';
import { AppShell } from '../components/AppShell';
import { APrecificar } from '../components/precificacao/APrecificar';
import { PosPrecificacaoHistorico } from '../components/precificacao/PosPrecificacaoHistorico';
import { useEscopoAtual } from '../hooks/useEscopoAtual';

type AbaPrecificacao = 'a-precificar' | 'pos';

const ABAS: { id: AbaPrecificacao; rotulo: string }[] = [
  { id: 'a-precificar', rotulo: 'A precificar' },
  { id: 'pos', rotulo: 'Pós-precificação' },
];

const SUBTITULO: Record<AbaPrecificacao, string> = {
  'a-precificar': 'Quais produtos precisam de preço novo, a prova de cada um e quanto pesam na receita.',
  pos: 'Quando cada produto foi precificado, com que alvo, e como vendeu antes e depois.',
};

/** Tela Precificação, em abas como o Estoque. A aba fica na URL (`?aba=pos`)
 *  para o link antigo `/pos-precificacao` cair direto nela. As duas leem o
 *  movimento do PRICE, que soma as lojas — nenhuma usa o seletor de loja. */
export default function PrecificacaoPage() {
  const { empresa } = useEscopoAtual();
  const location = useLocation();
  const navigate = useNavigate();
  const aba: AbaPrecificacao = new URLSearchParams(location.search).get('aba') === 'pos' ? 'pos' : 'a-precificar';

  return (
    <AppShell>
      <div className="dashboard-container estoque-page">
        <header className="app-page-header estoque-page-header">
          <div>
            <h1>Precificação{empresa && <span className="analisador-header-empresa"> · {empresa}</span>}</h1>
            <p>{SUBTITULO[aba]}</p>
          </div>
        </header>

        {!empresa && (
          <div className="glass-card glass-card-flat estoque-vazio">
            <Tags size={24} aria-hidden="true" />
            <div>
              <strong>Selecione uma empresa</strong>
              <p>Use o seletor no topo para carregar as precificações.</p>
            </div>
          </div>
        )}

        {empresa && (
          <>
            <div className="analisador-tabs custom-scrollbar" role="tablist" aria-label="Áreas da tela de precificação">
              {ABAS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  aria-selected={aba === item.id}
                  className={`analisador-tab${aba === item.id ? ' is-ativa' : ''}`}
                  onClick={() => navigate({ search: item.id === 'pos' ? '?aba=pos' : '' }, { replace: true })}
                >
                  {item.rotulo}
                </button>
              ))}
            </div>

            {aba === 'a-precificar'
              ? <APrecificar key={empresa} empresa={empresa} />
              : <PosPrecificacaoHistorico key={empresa} empresa={empresa} />}
          </>
        )}
      </div>
    </AppShell>
  );
}
