import { useState } from 'react';
import { Receipt } from 'lucide-react';
import { AppShell } from '../components/AppShell';
import { DespesasVisaoGeral } from '../components/despesas/DespesasVisaoGeral';
import { DespesasLancamentos } from '../components/despesas/DespesasLancamentos';
import { useEscopoAtual } from '../hooks/useEscopoAtual';

type AbaDespesas = 'visao' | 'lancamentos';

const ABAS: { id: AbaDespesas; rotulo: string }[] = [
  { id: 'visao', rotulo: 'Visão geral' },
  { id: 'lancamentos', rotulo: 'Lançamentos' },
];

/** Casca da tela de despesas: escopo, janela de meses e abas.
 *  Fonte é `{empresa}_CONTROLADORIA.csv`, opcional — empresa sem o arquivo
 *  recebe 404 do backend e cada aba mostra o próprio estado vazio. */
export default function DespesasPage() {
  const { empresa, loja } = useEscopoAtual();
  const [meses, setMeses] = useState(12);
  const [aba, setAba] = useState<AbaDespesas>('visao');

  return (
    <AppShell>
      <div className="dashboard-container estoque-page">
        <header className="app-page-header estoque-page-header">
          <div>
            <h1>Despesas{empresa && <span className="analisador-header-empresa"> · {empresa}</span>}</h1>
            <p>Lançamentos da Controladoria: total, evolução mensal e categorias.</p>
          </div>
          {empresa && (
            <div className="estoque-header-filtros">
              <label className="analisador-campo">
                <span>Período</span>
                <select className="custom-select analisador-select" value={meses} onChange={(e) => setMeses(Number(e.target.value))}>
                  <option value={6}>Últimos 6 meses</option>
                  <option value={12}>Últimos 12 meses</option>
                  <option value={24}>Últimos 24 meses</option>
                </select>
              </label>
            </div>
          )}
        </header>

        {!empresa && (
          <div className="glass-card glass-card-flat estoque-vazio">
            <Receipt size={24} aria-hidden="true" />
            <div><strong>Selecione uma empresa</strong><p>Use o seletor da barra lateral para carregar as despesas.</p></div>
          </div>
        )}

        {empresa && (
          <>
            <div className="analisador-tabs custom-scrollbar" role="tablist" aria-label="Áreas da tela de despesas">
              {ABAS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  aria-selected={aba === item.id}
                  className={`analisador-tab${aba === item.id ? ' is-ativa' : ''}`}
                  onClick={() => setAba(item.id)}
                >
                  {item.rotulo}
                </button>
              ))}
            </div>

            {aba === 'visao'
              ? <DespesasVisaoGeral empresa={empresa} loja={loja} meses={meses} />
              : <DespesasLancamentos empresa={empresa} loja={loja} />}
          </>
        )}
      </div>
    </AppShell>
  );
}
