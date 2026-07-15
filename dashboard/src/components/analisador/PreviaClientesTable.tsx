import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { ItemClientePrevia, TagCliente } from '../../api/client';
import { TAGS_CLIENTE_OPCOES } from '../../api/client';

interface PreviaClientesTableProps {
  itens: ItemClientePrevia[];
  excluidos: Set<string>;
  onToggle: (cliente: string) => void;
  carregando?: boolean;
  tagsPorCliente?: Record<string, TagCliente[]>;
  empresa?: string | null;
  onTagsChange?: (cliente: string, tags: TagCliente[]) => void | Promise<void>;
  desconsiderarBalcao?: boolean;
}

type MenuTags = {
  cliente: string;
  top: number;
  left: number;
};

function formatarMoeda(valor: number): string {
  return valor.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

function formatarPct(valor: number | null): string {
  if (valor == null || Number.isNaN(valor)) return '—';
  return `${valor.toFixed(2)}%`;
}

export function PreviaClientesTable({
  itens,
  excluidos,
  onToggle,
  carregando,
  tagsPorCliente = {},
  empresa,
  onTagsChange,
  desconsiderarBalcao = false,
}: PreviaClientesTableProps) {
  const [busca, setBusca] = useState('');
  const [grupoFiltro, setGrupoFiltro] = useState('');
  const [menu, setMenu] = useState<MenuTags | null>(null);
  const [salvandoTag, setSalvandoTag] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const lista = useMemo(() => {
    const base = itens ?? [];
    if (!desconsiderarBalcao) return base;
    // Espelho do backend: balcão (faixa ou tag) não entra na prévia considerada.
    return base.filter((item) => {
      if (item.grupo === 'Balcão') return false;
      const tags = tagsPorCliente[item.cliente] ?? [];
      return !tags.includes('cliente_balcao');
    });
  }, [itens, desconsiderarBalcao, tagsPorCliente]);

  const gruposDisponiveis = useMemo(() => {
    const nomes = new Set(lista.map((item) => item.grupo));
    return Array.from(nomes).sort((a, b) => a.localeCompare(b, 'pt-BR'));
  }, [lista]);

  const itensFiltrados = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    return lista.filter((item) => {
      if (grupoFiltro && item.grupo !== grupoFiltro) return false;
      if (termo && !item.cliente.toLowerCase().includes(termo)) return false;
      return true;
    });
  }, [lista, busca, grupoFiltro]);

  const consideradosNoFiltro = useMemo(
    () => itensFiltrados.filter((item) => !excluidos.has(item.cliente)).length,
    [itensFiltrados, excluidos],
  );

  const tagsDoMenu = menu ? (tagsPorCliente[menu.cliente] ?? []) : [];

  useEffect(() => {
    if (!menu) return;
    const fechar = () => setMenu(null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') fechar();
    };
    const onPointer = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) fechar();
    };
    const onScroll = () => fechar();
    window.addEventListener('keydown', onKey);
    // delay to avoid closing on the same click that opened
    const t = window.setTimeout(() => window.addEventListener('mousedown', onPointer), 0);
    window.addEventListener('scroll', onScroll, true);
    return () => {
      window.clearTimeout(t);
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('mousedown', onPointer);
      window.removeEventListener('scroll', onScroll, true);
    };
  }, [menu]);

  const abrirMenu = (cliente: string, anchor: HTMLElement) => {
    if (!empresa || !onTagsChange) return;
    const rect = anchor.getBoundingClientRect();
    const larguraMenu = 210;
    const alturaEstimada = 148;
    const gap = 2;
    let top = rect.bottom + gap;
    if (top + alturaEstimada > window.innerHeight - 8) {
      top = Math.max(8, rect.top - alturaEstimada - gap);
    }
    const left = Math.min(
      Math.max(8, rect.left),
      window.innerWidth - larguraMenu - 8,
    );
    setMenu({ cliente, top, left });
  };

  const alternarTag = async (tag: TagCliente) => {
    if (!menu || !onTagsChange || !empresa) return;
    const atuais = new Set(tagsPorCliente[menu.cliente] ?? []);
    if (atuais.has(tag)) atuais.delete(tag);
    else atuais.add(tag);
    const proximas = Array.from(atuais) as TagCliente[];
    setSalvandoTag(true);
    try {
      await onTagsChange(menu.cliente, proximas);
    } finally {
      setSalvandoTag(false);
    }
  };

  if (carregando) {
    return <p className="analisador-hint">Calculando prévia dos grupos...</p>;
  }

  if (lista.length === 0) {
    return (
      <p className="analisador-hint">
        Clique em &quot;Atualizar prévia dos grupos&quot; para ver os clientes por faixa.
      </p>
    );
  }

  return (
    <div className="analisador-previa">
      <div className="analisador-previa-filtros">
        <label className="analisador-campo">
          <span>Buscar</span>
          <input
            className="analisador-input"
            placeholder="Nome do cliente..."
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
          />
        </label>
        <label className="analisador-campo">
          <span>Grupo</span>
          <select
            className="custom-select analisador-select"
            value={grupoFiltro}
            onChange={(e) => setGrupoFiltro(e.target.value)}
          >
            <option value="">Todos</option>
            {gruposDisponiveis.map((grupo) => (
              <option key={grupo} value={grupo}>{grupo}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="analisador-tabela-wrap custom-scrollbar">
        <table className="analisador-tabela">
          <thead>
            <tr>
              <th className="col-check">Incluir?</th>
              <th className="col-nome">Cliente</th>
              <th className="col-tags">Tags</th>
              <th className="col-num">Receita</th>
              <th className="col-pct">% Receita</th>
              <th className="col-pct-acum">% Acumulada</th>
              <th className="col-grupo">Grupo</th>
            </tr>
          </thead>
          <tbody>
            {itensFiltrados.length === 0 && (
              <tr>
                <td colSpan={7} className="analisador-tabela-vazia">Nenhum cliente neste filtro.</td>
              </tr>
            )}
            {itensFiltrados.map((item) => {
              const excluido = excluidos.has(item.cliente);
              const tags = tagsPorCliente[item.cliente] ?? [];
              return (
                <tr key={item.cliente} className={excluido ? 'is-excluido' : undefined}>
                  <td className="col-check">
                    <label className="analisador-check">
                      <input
                        type="checkbox"
                        checked={!excluido}
                        onChange={() => onToggle(item.cliente)}
                      />
                    </label>
                  </td>
                  <td className="col-nome" title={item.cliente}>
                    <button
                      type="button"
                      className="analisador-cliente-nome"
                      onClick={(e) => abrirMenu(item.cliente, e.currentTarget)}
                      disabled={!empresa || !onTagsChange}
                    >
                      {item.cliente}
                    </button>
                  </td>
                  <td className="col-tags">
                    {tags.length > 0 ? (
                      <button
                        type="button"
                        className="analisador-tags-resumo-btn"
                        onClick={(e) => abrirMenu(item.cliente, e.currentTarget)}
                        disabled={!empresa || !onTagsChange}
                        title="Editar tags"
                      >
                        {tags.length}
                      </button>
                    ) : (
                      <span className="analisador-hint" style={{ margin: 0 }}>—</span>
                    )}
                  </td>
                  <td className="col-num">{formatarMoeda(item.receita)}</td>
                  <td className="col-pct">{formatarPct(item.percentual_receita)}</td>
                  <td className="col-pct-acum">{formatarPct(item.percentual_acumulado)}</td>
                  <td className="col-grupo">{item.grupo}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="analisador-hint">
        {consideradosNoFiltro} de {itensFiltrados.length} cliente(s) considerado(s) nas métricas
        {itensFiltrados.length !== lista.length && ` · base completa: ${lista.length} cliente(s)`}
        {excluidos.size > 0 && ` · ${excluidos.size} excluído(s) das métricas no total`}
        {empresa
          ? ' · Clique no nome para tags. Com “Desconsiderar clientes balcão”, tagged/regex saem da prévia.'
          : ' · Selecione uma empresa para editar tags.'}
      </p>

      {menu &&
        createPortal(
          <div
            ref={menuRef}
            className="analisador-tags-context"
            style={{ top: menu.top, left: menu.left }}
            role="menu"
            aria-label={`Tags de ${menu.cliente}`}
          >
            <p className="analisador-tags-context-titulo" title={menu.cliente}>
              {menu.cliente}
            </p>
            {TAGS_CLIENTE_OPCOES.map((opcao) => {
              const marcada = tagsDoMenu.includes(opcao.id);
              return (
                <button
                  key={opcao.id}
                  type="button"
                  role="menuitemcheckbox"
                  aria-checked={marcada}
                  disabled={salvandoTag}
                  className={`analisador-tags-context-item${marcada ? ' is-on' : ''}${opcao.id === 'cliente_balcao' ? ' is-balcao' : ''}`}
                  onClick={() => void alternarTag(opcao.id)}
                >
                  <span className="analisador-tags-context-check" aria-hidden="true">
                    {marcada ? '✓' : ''}
                  </span>
                  {opcao.rotulo}
                </button>
              );
            })}
          </div>,
          document.body,
        )}
    </div>
  );
}
