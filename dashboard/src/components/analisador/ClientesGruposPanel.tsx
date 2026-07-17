import { useEffect, useMemo, useState } from 'react';
import { Plus, Save, Trash2, X } from 'lucide-react';
import {
  buscarClientes,
  type GrupoManualClientes,
  type ItemClienteBusca,
  type TagCatalogoItem,
  type TagCliente,
} from '../../api/client';
import { ClientesAlertaCard } from './ClientesAlertaCard';
import { formatCurrency } from '../../utils/formatters';
import { slugId } from '../../utils/slug';

type ItemCliente = {
  cliente: string;
  receita: number;
  grupo?: string;
};

type Props = {
  empresa: string | null;
  /** null/omitido = todas as lojas */
  loja?: string | null;
  itensClientes: ItemCliente[];
  tagsPorCliente: Record<string, TagCliente[]>;
  tagsCatalogo: TagCatalogoItem[];
  clientesBalcao: string[];
  grupos: GrupoManualClientes[];
  onChangeGrupos: (grupos: GrupoManualClientes[]) => void;
  onSalvarGrupos: () => Promise<void>;
  salvando?: boolean;
};

export function ClientesGruposPanel({
  empresa,
  loja = null,
  itensClientes,
  tagsPorCliente,
  tagsCatalogo,
  clientesBalcao,
  grupos,
  onChangeGrupos,
  onSalvarGrupos,
  salvando = false,
}: Props) {
  const [filtroTags, setFiltroTags] = useState('');
  const [grupoFoco, setGrupoFoco] = useState<string | null>(null);
  const [buscaGrupo, setBuscaGrupo] = useState('');
  const [sugestoes, setSugestoes] = useState<ItemClienteBusca[]>([]);
  const [buscando, setBuscando] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  const balcaoSet = useMemo(() => new Set(clientesBalcao), [clientesBalcao]);
  const idBalcao = 'cliente_balcao';

  const clientesComTag = useMemo(() => {
    const q = filtroTags.trim().toLowerCase();
    const receitaPorCliente = new Map(itensClientes.map((i) => [i.cliente, i.receita]));
    const nomes = new Set([
      ...Object.keys(tagsPorCliente),
      ...itensClientes.map((i) => i.cliente),
    ]);
    return Array.from(nomes)
      .filter((cliente) => {
        if (balcaoSet.has(cliente)) return false;
        const tags = tagsPorCliente[cliente] ?? [];
        if (tags.includes(idBalcao)) return false;
        if (tags.length === 0) return false;
        if (!q) return true;
        return cliente.toLowerCase().includes(q);
      })
      .map((cliente) => ({
        cliente,
        receita: receitaPorCliente.get(cliente) ?? 0,
      }))
      .sort((a, b) => b.receita - a.receita);
  }, [itensClientes, tagsPorCliente, balcaoSet, filtroTags]);

  const rotuloTag = (id: string) =>
    tagsCatalogo.find((t) => t.id === id)?.rotulo ?? id;

  const corTag = (id: string) =>
    tagsCatalogo.find((t) => t.id === id)?.cor ?? '#64748b';

  const clientesJaEmGrupo = useMemo(() => {
    const set = new Set<string>();
    for (const g of grupos) {
      for (const c of g.clientes) set.add(c);
    }
    return set;
  }, [grupos]);

  useEffect(() => {
    if (!empresa || !grupoFoco) {
      setSugestoes([]);
      return;
    }
    let cancelado = false;
    const handle = window.setTimeout(() => {
      setBuscando(true);
      buscarClientes(empresa, buscaGrupo, 40, loja)
        .then((itens) => {
          if (!cancelado) setSugestoes(itens);
        })
        .catch(() => {
          if (!cancelado) setSugestoes([]);
        })
        .finally(() => {
          if (!cancelado) setBuscando(false);
        });
    }, 280);
    return () => {
      cancelado = true;
      window.clearTimeout(handle);
    };
  }, [empresa, loja, grupoFoco, buscaGrupo]);

  const adicionarGrupo = () => {
    const base = 'Novo grupo';
    let nome = base;
    let n = 2;
    const nomes = new Set(grupos.map((g) => g.nome.toLowerCase()));
    while (nomes.has(nome.toLowerCase())) {
      nome = `${base} ${n++}`;
    }
    let id = slugId(nome);
    const ids = new Set(grupos.map((g) => g.id));
    let s = 2;
    while (ids.has(id)) id = `${slugId(nome)}_${s++}`;
    const novo = [...grupos, { id, nome, clientes: [] }];
    onChangeGrupos(novo);
    setGrupoFoco(id);
    setBuscaGrupo('');
  };

  const atualizarGrupo = (id: string, patch: Partial<GrupoManualClientes>) => {
    onChangeGrupos(grupos.map((g) => (g.id === id ? { ...g, ...patch } : g)));
  };

  const excluirGrupo = (id: string) => {
    onChangeGrupos(grupos.filter((g) => g.id !== id));
    if (grupoFoco === id) {
      setGrupoFoco(null);
      setBuscaGrupo('');
    }
  };

  const incluirCliente = (grupoId: string, cliente: string) => {
    onChangeGrupos(
      grupos.map((g) => {
        if (g.id === grupoId) {
          if (g.clientes.includes(cliente)) return g;
          return { ...g, clientes: [...g.clientes, cliente] };
        }
        return { ...g, clientes: g.clientes.filter((c) => c !== cliente) };
      }),
    );
  };

  const removerCliente = (grupoId: string, cliente: string) => {
    onChangeGrupos(
      grupos.map((g) =>
        g.id === grupoId
          ? { ...g, clientes: g.clientes.filter((c) => c !== cliente) }
          : g,
      ),
    );
  };

  const handleSalvar = async () => {
    setFeedback(null);
    try {
      await onSalvarGrupos();
      setFeedback('Grupos salvos. A prévia de cortes agora usa o grupo agregado (indivíduos removidos).');
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : 'Falha ao salvar grupos.');
    }
  };

  if (!empresa) {
    return (
      <div className="glass-card glass-card-flat">
        <p className="analisador-hint" style={{ margin: 0 }}>
          Selecione uma empresa para gerenciar tags e grupos de clientes.
        </p>
      </div>
    );
  }

  return (
    <div className="analisador-stack">
      <ClientesAlertaCard
        empresa={empresa}
        loja={loja}
        itensClientes={itensClientes}
        tagsPorCliente={tagsPorCliente}
        tagsCatalogo={tagsCatalogo}
        clientesBalcao={clientesBalcao}
      />

      <div className="glass-card glass-card-flat analisador-bloco analisador-bloco-coluna">
        <h2 className="analisador-titulo">Clientes com tags</h2>
        <p className="analisador-hint">
          Só visualização (exceto balcão). Para montar grupos, use a busca no card abaixo.
        </p>
        <label className="analisador-campo">
          <span>Filtrar por nome</span>
          <input
            className="analisador-input"
            value={filtroTags}
            onChange={(e) => setFiltroTags(e.target.value)}
            placeholder="Nome do cliente"
          />
        </label>
        {clientesComTag.length === 0 ? (
          <p className="analisador-lista-vazia" role="status">
            Nenhum cliente com tag (fora balcão).
          </p>
        ) : (
          <div className="analisador-clientes-tags-lista custom-scrollbar">
            {clientesComTag.map((item) => {
              const tags = (tagsPorCliente[item.cliente] ?? []).filter((t) => t !== idBalcao);
              const emGrupo = clientesJaEmGrupo.has(item.cliente);
              return (
                <div key={item.cliente} className="analisador-cliente-tag-row">
                  <div className="analisador-cliente-tag-info">
                    <strong>{item.cliente}</strong>
                    <span className="analisador-hint" style={{ margin: 0 }}>
                      {formatCurrency(item.receita)}
                      {emGrupo ? ' · em grupo' : ''}
                    </span>
                  </div>
                  <div className="analisador-cliente-tag-chips">
                    {tags.map((t) => (
                      <span
                        key={t}
                        className="analisador-tag-chip"
                        style={{ borderColor: corTag(t), color: corTag(t) }}
                      >
                        {rotuloTag(t)}
                      </span>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="glass-card glass-card-flat analisador-bloco analisador-bloco-coluna">
        <h2 className="analisador-titulo">Grupos para o concentrado</h2>
        <p className="analisador-hint">
          Busque clientes e inclua no grupo. No concentrado/ABC e na prévia de cortes, os membros
          somam numa linha só (% e faixa recalculados).
        </p>
        <div className="analisador-acoes">
          <button type="button" className="analisador-btn analisador-btn-sec" onClick={adicionarGrupo}>
            <Plus size={16} /> Adicionar grupo
          </button>
          <button
            type="button"
            className="analisador-btn"
            onClick={handleSalvar}
            disabled={salvando}
          >
            <Save size={16} /> {salvando ? 'Salvando...' : 'Salvar grupos'}
          </button>
        </div>
        {feedback && (
          <p className="analisador-feedback-inline ok" role="status">{feedback}</p>
        )}
        <div className="analisador-grupos-lista">
          {grupos.length === 0 && (
            <p className="analisador-lista-vazia">
              Nenhum grupo ainda. Crie um e busque clientes para incluir.
            </p>
          )}
          {grupos.map((g) => {
            const ativo = grupoFoco === g.id;
            const sugestoesFiltradas = sugestoes.filter(
              (s) => !g.clientes.includes(s.cliente),
            );
            return (
              <div
                key={g.id}
                className={`analisador-grupo-card${ativo ? ' is-foco' : ''}`}
                onFocusCapture={() => setGrupoFoco(g.id)}
              >
                <label className="analisador-campo">
                  <span>Nome do grupo</span>
                  <div className="caminho-pasta-row">
                    <input
                      className="analisador-input"
                      value={g.nome}
                      onChange={(e) => atualizarGrupo(g.id, { nome: e.target.value })}
                      onFocus={() => setGrupoFoco(g.id)}
                    />
                    <button
                      type="button"
                      className="analisador-btn analisador-btn-sec"
                      aria-label="Excluir grupo"
                      onClick={() => excluirGrupo(g.id)}
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </label>

                <label className="analisador-campo" style={{ marginTop: 10 }}>
                  <span>Buscar clientes para incluir</span>
                  <input
                    className="analisador-input"
                    value={ativo ? buscaGrupo : ''}
                    onChange={(e) => {
                      setGrupoFoco(g.id);
                      setBuscaGrupo(e.target.value);
                    }}
                    onFocus={() => {
                      setGrupoFoco(g.id);
                      if (!ativo) setBuscaGrupo('');
                    }}
                    placeholder="Digite o nome do cliente…"
                  />
                </label>

                {ativo && (
                  <div className="analisador-grupo-sugestoes custom-scrollbar">
                    {buscando && <p className="analisador-hint">Buscando…</p>}
                    {!buscando && sugestoesFiltradas.length === 0 && (
                      <p className="analisador-hint">
                        {buscaGrupo.trim()
                          ? 'Nenhum cliente encontrado.'
                          : 'Digite para buscar ou veja os principais por receita.'}
                      </p>
                    )}
                    {sugestoesFiltradas.map((item) => (
                      <button
                        key={item.cliente}
                        type="button"
                        className="analisador-grupo-sugestao"
                        onClick={() => incluirCliente(g.id, item.cliente)}
                      >
                        <span className="analisador-grupo-sugestao-nome">{item.cliente}</span>
                        <span className="analisador-hint" style={{ margin: 0 }}>
                          {formatCurrency(item.receita)}
                          {clientesJaEmGrupo.has(item.cliente) ? ' · em outro grupo' : ''}
                        </span>
                      </button>
                    ))}
                  </div>
                )}

                <p className="analisador-hint" style={{ margin: '10px 0 0' }}>
                  {g.clientes.length} cliente(s) no grupo
                </p>
                {g.clientes.length > 0 && (
                  <ul className="analisador-grupo-membros">
                    {g.clientes.map((c) => (
                      <li key={c}>
                        <span>{c}</span>
                        <button
                          type="button"
                          className="analisador-grupo-remover"
                          aria-label={`Remover ${c}`}
                          onClick={() => removerCliente(g.id, c)}
                        >
                          <X size={14} />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
