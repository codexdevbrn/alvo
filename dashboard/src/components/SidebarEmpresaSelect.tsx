import { useEffect, useState } from 'react';
import { listarEmpresasDashboard } from '../api/client';
import { EVENTO_EMPRESA, escolherEmpresaInicial, selecionarEmpresaGlobal } from '../utils/empresaSelecionada';
import { AnalisadorCombobox } from './analisador/AnalisadorCombobox';

const LS_EMPRESA = 'alvo_empresa';

function lerEmpresa(): string {
  try {
    return localStorage.getItem(LS_EMPRESA) || '';
  } catch {
    return '';
  }
}

/** Combobox de empresa no topo direito (fonte de verdade: localStorage alvo_empresa). */
export function SidebarEmpresaSelect() {
  const [empresa, setEmpresa] = useState(lerEmpresa);
  const [empresas, setEmpresas] = useState<string[]>([]);

  useEffect(() => {
    const carregar = () => {
      listarEmpresasDashboard()
        .then((lista) => {
          setEmpresas(lista);
          if (lerEmpresa()) return;
          // Sem escolha salva: a mockada, ou a primeira da lista se ela não
          // estiver publicada nesta instalação. Deixar vazio não é opção — o
          // seletor não tem mais como voltar a esse estado. Normalmente já
          // resolvida pelo DashboardPage antes deste componente montar (ver
          // comentário lá); herda o valor de lá quando `lerEmpresa()` já
          // retorna algo.
          const inicial = escolherEmpresaInicial(lista);
          if (!inicial) return;
          setEmpresa(inicial);
          selecionarEmpresaGlobal(inicial);
        })
        .catch(() => setEmpresas([]));
    };
    carregar();
    window.addEventListener('focus', carregar);
    return () => window.removeEventListener('focus', carregar);
  }, []);

  useEffect(() => {
    const sync = () => setEmpresa(lerEmpresa());
    window.addEventListener(EVENTO_EMPRESA, sync);
    window.addEventListener('storage', sync);
    window.addEventListener('focus', sync);
    return () => {
      window.removeEventListener(EVENTO_EMPRESA, sync);
      window.removeEventListener('storage', sync);
      window.removeEventListener('focus', sync);
    };
  }, []);

  const onChange = (nome: string) => {
    setEmpresa(nome);
    selecionarEmpresaGlobal(nome);
  };

  return (
    <div className="app-sidebar-empresa">
      <span className="app-sidebar-nav-label">Empresa</span>
      <AnalisadorCombobox
        value={empresa}
        options={empresas}
        onChange={onChange}
        emptyLabel={false}
        searchPlaceholder="Buscar…"
        aria-label="Selecionar empresa"
        direcao="abaixo"
        portal
      />
    </div>
  );
}
