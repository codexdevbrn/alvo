import { useEffect, useState } from 'react';
import { listarEmpresasDashboard } from '../api/client';
import { EVENTO_EMPRESA, selecionarEmpresaGlobal } from '../utils/empresaSelecionada';
import { AnalisadorCombobox } from './analisador/AnalisadorCombobox';

const LS_EMPRESA = 'alvo_empresa';
const ROTULO_PADRAO = 'Dados padrão';

function lerEmpresa(): string {
  try {
    return localStorage.getItem(LS_EMPRESA) || '';
  } catch {
    return '';
  }
}

/** Combobox de empresa no topo da sidebar (fonte de verdade: localStorage alvo_empresa). */
export function SidebarEmpresaSelect() {
  const [empresa, setEmpresa] = useState(lerEmpresa);
  const [empresas, setEmpresas] = useState<string[]>([]);

  useEffect(() => {
    const carregar = () => {
      listarEmpresasDashboard().then(setEmpresas).catch(() => setEmpresas([]));
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
        emptyLabel={ROTULO_PADRAO}
        searchPlaceholder="Buscar…"
        aria-label="Selecionar empresa"
        direcao="abaixo"
        portal
      />
    </div>
  );
}
