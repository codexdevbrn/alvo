import { useEffect, useState } from 'react';
import { obterAplicarCortesRelatorios, definirAplicarCortesRelatorios } from '../api/client';
import { avisarCortesRelatorios } from '../utils/cortesRelatorios';
import { invalidarSummary } from '../utils/cacheSummary';
import { limparCacheGeral } from '../utils/cacheRequisicoes';

const OPCOES: Array<{ valor: boolean; rotulo: string; titulo: string }> = [
  { valor: false, rotulo: 'Sem corte', titulo: 'Dashboard, Clientes, Vendedores e Estoque usam a base completa' },
  { valor: true, rotulo: 'Com corte', titulo: 'Aplica exclusões e regras de cliente/produto do Relatórios também nessas telas' },
];

/**
 * Controle global (mesma pasta de trabalho, não por empresa): liga/desliga
 * as exclusões e regras de cliente/produto configuradas no Relatórios nas
 * outras telas (Dashboard, Clientes, Vendedores, Estoque). Despesas não
 * entra — fonte é a Controladoria, não a base de vendas.
 */
export function TopoCortesToggle() {
  const [ativo, setAtivo] = useState(false);
  const [salvando, setSalvando] = useState(false);

  useEffect(() => {
    void obterAplicarCortesRelatorios().then(setAtivo).catch(() => setAtivo(false));
  }, []);

  const alternar = async (valor: boolean) => {
    if (valor === ativo || salvando) return;
    const anterior = ativo;
    setAtivo(valor);
    setSalvando(true);
    try {
      const gravada = await definirAplicarCortesRelatorios(valor);
      setAtivo(gravada);
      avisarCortesRelatorios(gravada);
      invalidarSummary();
      limparCacheGeral();
    } catch {
      setAtivo(anterior);
    } finally {
      setSalvando(false);
    }
  };

  return (
    <div className="app-sidebar-empresa">
      <span className="app-sidebar-nav-label">Cortes</span>
      <div className="periodo-segmented" role="radiogroup" aria-label="Aplicar cortes do Relatórios nas outras telas">
        {OPCOES.map((opcao) => (
          <button
            key={String(opcao.valor)}
            type="button"
            role="radio"
            aria-checked={ativo === opcao.valor}
            title={opcao.titulo}
            className={`periodo-segmented-btn${ativo === opcao.valor ? ' is-active' : ''}`}
            disabled={salvando}
            onClick={() => void alternar(opcao.valor)}
          >
            {opcao.rotulo}
          </button>
        ))}
      </div>
    </div>
  );
}
