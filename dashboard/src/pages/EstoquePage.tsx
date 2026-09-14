import { useEffect, useState } from 'react';
import { Boxes } from 'lucide-react';
import { AppShell } from '../components/AppShell';
import { EstoqueVisaoGeral } from '../components/estoque/EstoqueVisaoGeral';
import { EstoqueEscopo } from '../components/estoque/EstoqueEscopo';
import { useEscopoAtual } from '../hooks/useEscopoAtual';
import { useMesesFechados } from '../hooks/useMesesFechados';
import { obterCoberturaEstoque } from '../api/client';
import { modoParaBooleano } from '../utils/mesesFechados';

type AbaEstoque = 'visao' | 'escopo';

const ABAS: { id: AbaEstoque; rotulo: string }[] = [
  { id: 'visao', rotulo: 'Visão geral' },
  { id: 'escopo', rotulo: 'Mapa geral' },
];

/** Casca da tela de estoque: escopo, janela de venda e abas.
 *  Cada aba busca os próprios dados — a visão geral recebe poucos KB de
 *  agregados e não paga o download dos 1.200 pontos do mapa. */
export default function EstoquePage() {
  const { empresa, loja } = useEscopoAtual();
  const [meses, setMeses] = useState(6);
  const [aba, setAba] = useState<AbaEstoque>('visao');
  const [modoPeriodo] = useMesesFechados();
  const usarMesesFechados = modoParaBooleano(modoPeriodo);

  // Prefetch do mapa enquanto a visão geral está na tela: o primeiro clique
  // em "Mapa geral" não espera o worker do zero.
  useEffect(() => {
    if (!empresa) return;
    void obterCoberturaEstoque(empresa, {
      loja, meses, limite: 1200, usarMesesFechados,
    }).catch(() => { /* a aba trata o erro quando abrir */ });
  }, [empresa, loja, meses, usarMesesFechados]);

  return (
    <AppShell>
      <div className="dashboard-container estoque-page">
        <header className="app-page-header estoque-page-header">
          <div>
            <h1>Estoque{empresa && <span className="analisador-header-empresa"> · {empresa}</span>}</h1>
            <p>Capital parado, risco de ruptura e cobertura por produto.</p>
          </div>
          {empresa && (
            <div className="estoque-header-filtros">
              {/* A janela vale para as duas abas: as duas leem a mesma venda média. */}
              <label className="analisador-campo">
                <span>Venda média</span>
                <select className="custom-select analisador-select" value={meses} onChange={(e) => setMeses(Number(e.target.value))}>
                  <option value={3}>Últimos 3 meses</option>
                  <option value={6}>Últimos 6 meses</option>
                  <option value={12}>Últimos 12 meses</option>
                </select>
              </label>
            </div>
          )}
        </header>

        {!empresa && (
          <div className="glass-card glass-card-flat estoque-vazio">
            <Boxes size={24} aria-hidden="true" />
            <div><strong>Selecione uma empresa</strong><p>Use o seletor no topo da tela para carregar estoque e vendas.</p></div>
          </div>
        )}

        {empresa && (
          <>
            <div className="analisador-tabs custom-scrollbar" role="tablist" aria-label="Áreas da tela de estoque">
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
              ? <EstoqueVisaoGeral empresa={empresa} loja={loja} meses={meses} />
              : <EstoqueEscopo empresa={empresa} loja={loja} meses={meses} />}
          </>
        )}
      </div>
    </AppShell>
  );
}
