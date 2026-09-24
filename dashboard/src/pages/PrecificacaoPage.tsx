import { useLocation, useNavigate } from 'react-router-dom';
import { Tags } from 'lucide-react';
import { AppShell } from '../components/AppShell';
import { PosPrecificacaoHistorico } from '../components/precificacao/PosPrecificacaoHistorico';
import { PosPrecificacaoVisao } from '../components/precificacao/PosPrecificacaoVisao';
import { useEscopoAtual } from '../hooks/useEscopoAtual';
import { useModoGraficoPrecificacao } from '../hooks/useModoGraficoPrecificacao';
import { abaPrecificacao, type AbaPrecificacao } from '../utils/abaPrecificacao';

const ABAS: { id: AbaPrecificacao; rotulo: string }[] = [
  { id: 'pos', rotulo: 'Pós-precificação' },
  { id: 'historico', rotulo: 'Histórico' },
];

const SUBTITULO: Record<AbaPrecificacao, string> = {
  pos: 'Lucro bruto / dia e quantidade / dia depois da precificação — clique num produto pra ver a série.',
  historico: 'Quando cada produto foi precificado, com que alvo, e como vendeu antes e depois.',
};

/** Tela Precificação, em duas abas (`?aba=`, ver `utils/abaPrecificacao`):
 *  - "Pós-precificação": uma rodada do dump + desempenho no movimento. Fonte
 *    `{empresa}_PRECIFICACAO.parquet`, opcional — 404 vira estado vazio na visão.
 *    Rodada, itens e Sintética/Detalhada vivem na topbar (AppShell);
 *  - "Histórico": todas as rodadas por SKU, sem prender a uma. */
export default function PrecificacaoPage() {
  const { empresa, loja } = useEscopoAtual();
  const [modoGrafico] = useModoGraficoPrecificacao();
  const location = useLocation();
  const navigate = useNavigate();
  const aba = abaPrecificacao(location.search);

  return (
    <AppShell>
      <div className="dashboard-container estoque-page">
        <header className="app-page-header estoque-page-header prec-cabecalho">
          <div>
            <h1>Precificação{empresa && <span className="analisador-header-empresa"> · {empresa}</span>}</h1>
            <p>{SUBTITULO[aba]}</p>
          </div>
          <div className="periodo-segmented prec-abas" role="tablist" aria-label="Precificação">
            {ABAS.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={aba === item.id}
                className={`periodo-segmented-btn${aba === item.id ? ' is-active' : ''}`}
                onClick={() => navigate({ search: `?aba=${item.id}` }, { replace: true })}
              >
                {item.rotulo}
              </button>
            ))}
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

        {empresa && aba === 'pos' && <PosPrecificacaoVisao empresa={empresa} loja={loja} modoGrafico={modoGrafico} />}
        {empresa && aba === 'historico' && <PosPrecificacaoHistorico key={empresa} empresa={empresa} />}
      </div>
    </AppShell>
  );
}
