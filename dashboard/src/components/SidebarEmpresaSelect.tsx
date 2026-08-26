import { useEffect, useState } from 'react';
import { listarEmpresasDashboard } from '../api/client';
import { EVENTO_EMPRESA, selecionarEmpresaGlobal } from '../utils/empresaSelecionada';
import { AnalisadorCombobox } from './analisador/AnalisadorCombobox';

const LS_EMPRESA = 'alvo_empresa';

/**
 * Empresa usada quando nada foi escolhido nesta máquina. É uma pasta de verdade
 * na fonte e no trabalho, como qualquer outra empresa — não o modo estático.
 *
 * O seletor não oferece mais a opção vazia ("Dados padrão", que lia o
 * summary.json embutido): base de demonstração passa a ser uma empresa da
 * lista. Quem já tinha a opção vazia salva cai aqui na primeira carga.
 */
const EMPRESA_MOCK = 'Dados Mockados';

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
      listarEmpresasDashboard()
        .then((lista) => {
          setEmpresas(lista);
          if (lerEmpresa() || !lista.length) return;
          // Sem escolha salva: a mockada, ou a primeira da lista se ela não
          // estiver publicada nesta instalação. Deixar vazio não é opção — o
          // seletor não tem mais como voltar a esse estado.
          const inicial = lista.includes(EMPRESA_MOCK) ? EMPRESA_MOCK : lista[0];
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
