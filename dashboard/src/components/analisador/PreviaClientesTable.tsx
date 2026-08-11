import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type {
  GrupoManualClientes,
  ItemClientePrevia,
  TagCatalogoItem,
  TagCliente,
} from '../../api/client';
import { TAGS_CATALOGO_PADRAO } from '../../api/client';
import { formatCurrency, rotuloGrupoCurto } from '../../utils/formatters';

/** Alinha com o backend, que grava tags com cliente.strip(). */
function nomeClienteChave(cliente: string): string {
  return cliente.trim();
}

interface PreviaClientesTableProps {
  itens: ItemClientePrevia[];
  excluidos: Set<string>;
  onToggle: (cliente: string) => void;
  carregando?: boolean;
  tagsPorCliente?: Record<string, TagCliente[]>;
  tagsCatalogo?: TagCatalogoItem[];
  gruposManuais?: GrupoManualClientes[];
  empresa?: string | null;
  onTagsChange?: (cliente: string, tags: TagCliente[]) => void | Promise<void>;
  onToggleGrupoManual?: (cliente: string, grupoId: string) => void | Promise<void>;
  onCriarGrupoManual?: (cliente: string, nome: string) => void | Promise<void>;
  desconsiderarBalcao?: boolean;
  onToggleAll?: (clientes: string[], checkAll: boolean) => void;
}

type MenuTags = {
  cliente: string;
  top: number;
  left: number;
};

function formatarPct(valor: number | null): string {
  if (valor == null || Number.isNaN(valor)) return '—';
  return `${valor.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
}

export function PreviaClientesTable({
  itens,
  excluidos,
  onToggle,
  carregando,
  tagsPorCliente = {},
  tagsCatalogo = TAGS_CATALOGO_PADRAO,
  gruposManuais = [],
  empresa,
  onTagsChange,
  onToggleGrupoManual,
  onCriarGrupoManual,
  desconsiderarBalcao = false,
  onToggleAll,
}: PreviaClientesTableProps) {
  const [busca, setBusca] = useState('');
  const [grupoFiltro, setGrupoFiltro] = useState('');
  const [menu, setMenu] = useState<MenuTags | null>(null);
  const [salvandoTag, setSalvandoTag] = useState(false);
  const [criandoGrupo, setCriandoGrupo] = useState(false);
  const [nomeNovoGrupo, setNomeNovoGrupo] = useState('');
  const inputGrupoRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const lista = useMemo(() => itens ?? [], [itens]);

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

  /** Com “desconsiderar balcão”, faixa Balcão fica fora das métricas (checkbox off). */
  const estaExcluido = (item: ItemClientePrevia) =>
    excluidos.has(item.cliente) || (desconsiderarBalcao && item.grupo === 'Balcão');

  const consideradosNoFiltro = useMemo(
    () =>
      itensFiltrados.filter((item) => {
        if (excluidos.has(item.cliente)) return false;
        if (desconsiderarBalcao && item.grupo === 'Balcão') return false;
        return true;
      }).length,
    [itensFiltrados, excluidos, desconsiderarBalcao],
  );

  const qtdBalcaoFora = useMemo(() => {
    if (!desconsiderarBalcao) return 0;
    return lista.filter((item) => item.grupo === 'Balcão' && !excluidos.has(item.cliente)).length;
  }, [lista, desconsiderarBalcao, excluidos]);

  const todosConsideradosFiltro = itensFiltrados.length > 0 && consideradosNoFiltro === itensFiltrados.length;
  const algumConsideradoFiltro = consideradosNoFiltro > 0;

  const tagsDoMenu = menu ? (tagsPorCliente[nomeClienteChave(menu.cliente)] ?? []) : [];

  const opcoesTags = useMemo(
    () => tagsCatalogo.filter((item) => item.ativa),
    [tagsCatalogo],
  );

  const gruposDoMenu = useMemo(() => {
    if (!menu) return new Set<string>();
    const chave = nomeClienteChave(menu.cliente);
    return new Set(
      gruposManuais
        .filter((g) => g.clientes.some((c) => nomeClienteChave(c) === chave))
        .map((g) => g.id),
    );
  }, [menu, gruposManuais]);

  const menuEditavel = Boolean(empresa && (onTagsChange || onToggleGrupoManual));

  useEffect(() => {
    if (!menu) {
      setCriandoGrupo(false);
      setNomeNovoGrupo('');
      return;
    }
    const fechar = () => setMenu(null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') fechar();
    };
    const onPointer = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) fechar();
    };
    // capture:true pega scroll de qualquer ancestral. Digitar no nome do grupo
    // (ou abrir o campo) pode disparar scrollIntoView / scroll interno — não fechar.
    const onScroll = (e: Event) => {
      const alvo = e.target;
      if (alvo instanceof Node && menuRef.current?.contains(alvo)) return;
      const ativo = document.activeElement;
      if (ativo instanceof Node && menuRef.current?.contains(ativo)) return;
      fechar();
    };
    window.addEventListener('keydown', onKey);
    const t = window.setTimeout(() => window.addEventListener('mousedown', onPointer), 0);
    window.addEventListener('scroll', onScroll, true);
    return () => {
      window.clearTimeout(t);
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('mousedown', onPointer);
      window.removeEventListener('scroll', onScroll, true);
    };
  }, [menu]);

  useEffect(() => {
    if (criandoGrupo) inputGrupoRef.current?.focus();
  }, [criandoGrupo]);

  const abrirMenu = (cliente: string, anchor: HTMLElement) => {
    if (!menuEditavel) return;
    const rect = anchor.getBoundingClientRect();
    const larguraMenu = 220;
    const alturaEstimada =
      80 + opcoesTags.length * 36 + Math.min(gruposManuais.length, 6) * 36 + (onCriarGrupoManual ? 52 : 28);
    const gap = 2;
    let top = rect.bottom + gap;
    if (top + alturaEstimada > window.innerHeight - 8) {
      top = Math.max(8, rect.top - Math.min(alturaEstimada, window.innerHeight - 16) - gap);
    }
    const left = Math.min(
      Math.max(8, rect.left),
      window.innerWidth - larguraMenu - 8,
    );
    setMenu({ cliente: nomeClienteChave(cliente), top, left });
  };

  const alternarTag = async (tag: TagCliente) => {
    if (!menu || !onTagsChange || !empresa) return;
    const cliente = nomeClienteChave(menu.cliente);
    const atuais = new Set(tagsPorCliente[cliente] ?? []);
    if (atuais.has(tag)) atuais.delete(tag);
    else atuais.add(tag);
    const proximas = Array.from(atuais) as TagCliente[];
    setSalvandoTag(true);
    try {
      await onTagsChange(cliente, proximas);
    } finally {
      setSalvandoTag(false);
    }
  };

  const alternarGrupo = async (grupoId: string) => {
    if (!menu || !onToggleGrupoManual || !empresa) return;
    setSalvandoTag(true);
    try {
      await onToggleGrupoManual(nomeClienteChave(menu.cliente), grupoId);
    } finally {
      setSalvandoTag(false);
    }
  };

  const confirmarNovoGrupo = async () => {
    if (!menu || !onCriarGrupoManual || !empresa) return;
    const nome = nomeNovoGrupo.trim();
    if (!nome) return;
    setSalvandoTag(true);
    try {
      await onCriarGrupoManual(nomeClienteChave(menu.cliente), nome);
      setCriandoGrupo(false);
      setNomeNovoGrupo('');
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
              <option key={grupo} value={grupo}>{rotuloGrupoCurto(grupo)}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="analisador-tabela-wrap custom-scrollbar">
        <table className="analisador-tabela">
          <thead>
            <tr>
              <th className="col-check">
                <label className="analisador-check">
                  <input
                    type="checkbox"
                    aria-label="Incluir todos os clientes do filtro"
                    title="Incluir/excluir todos os clientes do filtro"
                    checked={todosConsideradosFiltro}
                    ref={(el) => {
                      if (el) el.indeterminate = algumConsideradoFiltro && !todosConsideradosFiltro;
                    }}
                    onChange={() => {
                      if (onToggleAll) {
                        const checkAll = !todosConsideradosFiltro;
                        const chaves = itensFiltrados.map((i) => i.cliente);
                        onToggleAll(chaves, checkAll);
                      }
                    }}
                  />
                </label>
              </th>
              <th className="col-nome">Cliente</th>
              <th className="col-tags">Tags</th>
              <th className="col-num">Receita</th>
              <th className="col-pct">% Rec.</th>
              <th className="col-pct-acum">% Acum.</th>
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
              const forcaBalcao = desconsiderarBalcao && item.grupo === 'Balcão';
              const excluido = estaExcluido(item);
              const tags = tagsPorCliente[nomeClienteChave(item.cliente)] ?? [];
              return (
                <tr key={item.cliente} className={excluido ? 'is-excluido' : undefined}>
                  <td className="col-check">
                    <label className="analisador-check">
                      <input
                        type="checkbox"
                        checked={!excluido}
                        disabled={forcaBalcao}
                        title={forcaBalcao ? 'Cliente balcão — fora dos cálculos enquanto “Desconsiderar clientes balcão” estiver marcado' : undefined}
                        onChange={() => {
                          if (forcaBalcao) return;
                          onToggle(item.cliente);
                        }}
                      />
                    </label>
                  </td>
                  <td className="col-nome" title={nomeClienteChave(item.cliente)}>
                    <button
                      type="button"
                      className="analisador-cliente-nome"
                      onClick={(e) => abrirMenu(item.cliente, e.currentTarget)}
                      disabled={!menuEditavel}
                    >
                      {nomeClienteChave(item.cliente)}
                    </button>
                  </td>
                  <td className="col-tags">
                    {tags.length > 0 ? (
                      <button
                        type="button"
                        className="analisador-tags-resumo-btn"
                        onClick={(e) => abrirMenu(item.cliente, e.currentTarget)}
                        disabled={!menuEditavel}
                        title="Editar tags e grupos"
                      >
                        {tags.length}
                      </button>
                    ) : (
                      <span className="analisador-hint" style={{ margin: 0 }}>—</span>
                    )}
                  </td>
                  <td className="col-num">{formatCurrency(item.receita)}</td>
                  <td className="col-pct">{formatarPct(item.percentual_receita)}</td>
                  <td className="col-pct-acum">{formatarPct(item.percentual_acumulado)}</td>
                  <td className="col-grupo" title={item.grupo}>{rotuloGrupoCurto(item.grupo)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="analisador-hint">
        {consideradosNoFiltro} de {itensFiltrados.length} cliente(s) considerado(s) nas métricas
        {itensFiltrados.length !== lista.length && ` · base completa: ${lista.length} cliente(s)`}
        {(excluidos.size > 0 || qtdBalcaoFora > 0) &&
          ` · ${excluidos.size + qtdBalcaoFora} excluído(s) das métricas no total`}
        {desconsiderarBalcao && qtdBalcaoFora > 0 && ` · ${qtdBalcaoFora} no grupo Balcão`}
        {empresa
          ? ' · Clique no nome para tags e grupos manuais.'
          : ' · Selecione uma empresa para editar tags e grupos.'}
      </p>

      {menu &&
        createPortal(
          <div
            ref={menuRef}
            className="analisador-tags-context"
            style={{ top: menu.top, left: menu.left }}
            role="menu"
            aria-label={`Tags e grupos de ${menu.cliente}`}
          >
            <p className="analisador-tags-context-titulo" title={menu.cliente}>
              {menu.cliente}
            </p>

            {onTagsChange && (
              <>
                <p className="analisador-tags-context-secao">Tags</p>
                {opcoesTags.map((opcao) => {
                  const marcada = tagsDoMenu.includes(opcao.id);
                  return (
                    <button
                      key={opcao.id}
                      type="button"
                      role="menuitemcheckbox"
                      aria-checked={marcada}
                      disabled={salvandoTag}
                      className={`analisador-tags-context-item${marcada ? ' is-on' : ''}${opcao.id === 'cliente_balcao' ? ' is-balcao' : ''}`}
                      style={marcada ? { borderColor: `${opcao.cor}55`, color: opcao.cor } : undefined}
                      onClick={() => void alternarTag(opcao.id)}
                    >
                      <span
                        className="analisador-tags-context-check"
                        aria-hidden="true"
                        style={marcada ? { color: opcao.cor } : undefined}
                      >
                        {marcada ? '✓' : ''}
                      </span>
                      {opcao.rotulo}
                    </button>
                  );
                })}
                {opcoesTags.length === 0 && (
                  <p className="analisador-hint" style={{ margin: '0.35rem 0.5rem' }}>
                    Nenhuma tag ativa. Ative tags em Configurações.
                  </p>
                )}
              </>
            )}

            {onToggleGrupoManual && (
              <>
                <div className="analisador-tags-context-secao-row">
                  <p className="analisador-tags-context-secao">Grupos</p>
                  {onCriarGrupoManual && (
                    <button
                      type="button"
                      className="analisador-tags-context-add"
                      aria-label="Criar grupo"
                      title={empresa ? 'Criar grupo com este cliente' : 'Selecione uma empresa'}
                      disabled={!empresa || salvandoTag}
                      onClick={() => {
                        if (!empresa) return;
                        setCriandoGrupo((v) => !v);
                        setNomeNovoGrupo('');
                      }}
                    >
                      +
                    </button>
                  )}
                </div>
                {criandoGrupo && onCriarGrupoManual && (
                  <form
                    className="analisador-tags-context-novo-grupo"
                    onSubmit={(e) => {
                      e.preventDefault();
                      void confirmarNovoGrupo();
                    }}
                  >
                    <input
                      ref={inputGrupoRef}
                      className="analisador-tags-context-novo-grupo-input"
                      value={nomeNovoGrupo}
                      placeholder="Nome do grupo"
                      disabled={salvandoTag}
                      maxLength={80}
                      onChange={(e) => setNomeNovoGrupo(e.target.value)}
                      onKeyDown={(e) => {
                        // Evita que Escape/setas borbulhem e fechem o modal inteiro
                        e.stopPropagation();
                        if (e.key === 'Escape') {
                          setCriandoGrupo(false);
                          setNomeNovoGrupo('');
                        }
                      }}
                    />
                    <button
                      type="submit"
                      className="analisador-tags-context-novo-grupo-ok"
                      disabled={salvandoTag || !nomeNovoGrupo.trim()}
                      aria-label="Criar grupo"
                    >
                      ✓
                    </button>
                  </form>
                )}
                {gruposManuais.length === 0 && !criandoGrupo && (
                  <p className="analisador-hint" style={{ margin: '0.35rem 0.5rem' }}>
                    Nenhum grupo. Use + para criar.
                  </p>
                )}
                {gruposManuais.map((grupo) => {
                  const marcada = gruposDoMenu.has(grupo.id);
                  return (
                    <button
                      key={grupo.id}
                      type="button"
                      role="menuitemcheckbox"
                      aria-checked={marcada}
                      disabled={salvandoTag}
                      className={`analisador-tags-context-item${marcada ? ' is-on' : ''}`}
                      onClick={() => void alternarGrupo(grupo.id)}
                    >
                      <span className="analisador-tags-context-check" aria-hidden="true">
                        {marcada ? '✓' : ''}
                      </span>
                      {grupo.nome}
                    </button>
                  );
                })}
              </>
            )}
          </div>,
          document.body,
        )}
    </div>
  );
}
