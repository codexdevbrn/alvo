import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { AlertTriangle, Search, Tag, UsersRound } from 'lucide-react';
import { AppShell } from '../components/AppShell';
import { ClientesAlertaCard } from '../components/analisador/ClientesAlertaCard';
import { ClientesRitmoAlertas } from '../components/clientes/ClientesRitmoAlertas';
import {
  obterBase,
  obterBaseClientes,
  obterTagsClientes,
  salvarTagsUmCliente,
  TAGS_CATALOGO_PADRAO,
  type ItemClienteBusca,
  type TagCatalogoItem,
  type TagCliente,
} from '../api/client';
import { formatCurrency } from '../utils/formatters';
import { EVENTO_EMPRESA } from '../utils/empresaSelecionada';

const LS_EMPRESA = 'alvo_empresa';

function lerEmpresa(): string {
  try {
    return localStorage.getItem(LS_EMPRESA) || '';
  } catch {
    return '';
  }
}

function normalizarBusca(valor: string): string {
  return valor.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
}

/** Tela operacional: acompanha clientes e edita tags sem carregar regras de relatórios/produtos. */
export default function ClientesPage() {
  const [empresa, setEmpresa] = useState(lerEmpresa);
  const [loja, setLoja] = useState('');
  const [lojas, setLojas] = useState<string[]>([]);
  const [clientes, setClientes] = useState<ItemClienteBusca[]>([]);
  const [totalClientes, setTotalClientes] = useState(0);
  const [baseLimitada, setBaseLimitada] = useState(false);
  const [tagsPorCliente, setTagsPorCliente] = useState<Record<string, TagCliente[]>>({});
  const [catalogo, setCatalogo] = useState<TagCatalogoItem[]>(TAGS_CATALOGO_PADRAO);
  const [clientesBalcao, setClientesBalcao] = useState<string[]>([]);
  const [busca, setBusca] = useState('');
  const [tagFiltro, setTagFiltro] = useState('');
  const [carregando, setCarregando] = useState(false);
  const [salvandoCliente, setSalvandoCliente] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    const sincronizar = (evento: Event) => {
      const detalhe = evento instanceof CustomEvent ? evento.detail : null;
      setEmpresa(typeof detalhe === 'string' ? detalhe : lerEmpresa());
      setLoja('');
    };
    window.addEventListener(EVENTO_EMPRESA, sincronizar);
    window.addEventListener('storage', sincronizar);
    return () => {
      window.removeEventListener(EVENTO_EMPRESA, sincronizar);
      window.removeEventListener('storage', sincronizar);
    };
  }, []);

  useEffect(() => {
    if (!empresa) {
      setClientes([]);
      setLojas([]);
      setTagsPorCliente({});
      return;
    }
    let cancelado = false;
    setCarregando(true);
    setErro(null);
    Promise.all([
      obterBase(empresa, loja || null),
      obterBaseClientes(empresa, loja || null),
      obterTagsClientes(empresa, loja || null),
    ])
      .then(([base, respostaClientes, respostaTags]) => {
        if (cancelado) return;
        setLojas(base.lojas ?? []);
        setClientes(respostaClientes.itens);
        setTotalClientes(respostaClientes.total);
        setBaseLimitada(respostaClientes.limitado);
        setTagsPorCliente(respostaTags.tags ?? {});
        setCatalogo(respostaTags.catalogo ?? TAGS_CATALOGO_PADRAO);
        setClientesBalcao(respostaTags.clientes_balcao ?? []);
      })
      .catch((e) => {
        if (!cancelado) setErro(e instanceof Error ? e.message : 'Falha ao carregar clientes.');
      })
      .finally(() => {
        if (!cancelado) setCarregando(false);
      });
    return () => { cancelado = true; };
  }, [empresa, loja]);

  const clientesCompletos = useMemo(() => {
    const mapa = new Map(clientes.map((item) => [item.cliente.trim(), item]));
    Object.keys(tagsPorCliente).forEach((nome) => {
      const chave = nome.trim();
      if (chave && !mapa.has(chave)) mapa.set(chave, { cliente: chave, receita: 0 });
    });
    return Array.from(mapa.values()).sort((a, b) => b.receita - a.receita);
  }, [clientes, tagsPorCliente]);

  const clientesVisiveis = useMemo(() => {
    const termo = normalizarBusca(busca.trim());
    return clientesCompletos.filter((item) => {
      const tags = tagsPorCliente[item.cliente.trim()] ?? [];
      if (tagFiltro && !tags.includes(tagFiltro)) return false;
      return !termo || normalizarBusca(item.cliente).includes(termo);
    });
  }, [busca, clientesCompletos, tagFiltro, tagsPorCliente]);

  const totaisTags = useMemo(() => {
    const totais: Record<string, number> = {};
    Object.values(tagsPorCliente).forEach((tags) => {
      new Set(tags).forEach((tag) => { totais[tag] = (totais[tag] ?? 0) + 1; });
    });
    return totais;
  }, [tagsPorCliente]);

  const alternarTag = async (cliente: string, tag: string) => {
    if (!empresa || salvandoCliente) return;
    const chave = cliente.trim();
    const anteriores = tagsPorCliente[chave] ?? [];
    const proximas = anteriores.includes(tag)
      ? anteriores.filter((item) => item !== tag)
      : [...anteriores, tag];
    setTagsPorCliente((atual) => ({ ...atual, [chave]: proximas }));
    setSalvandoCliente(chave);
    setErro(null);
    try {
      const resposta = await salvarTagsUmCliente(empresa, chave, proximas, loja || null);
      setTagsPorCliente(resposta.tags ?? {});
      setClientesBalcao(resposta.clientes_balcao ?? []);
    } catch (e) {
      setTagsPorCliente((atual) => ({ ...atual, [chave]: anteriores }));
      setErro(e instanceof Error ? e.message : `Falha ao salvar tags de ${chave}.`);
    } finally {
      setSalvandoCliente(null);
    }
  };

  const tagsAtivas = catalogo.filter((tag) => tag.ativa && tag.id !== 'cliente_balcao');

  return (
    <AppShell>
      <div className="dashboard-container clientes-page">
        <header className="app-page-header clientes-page-header">
          <div>
            <h1>Clientes{empresa && <span className="analisador-header-empresa"> · {empresa}</span>}</h1>
            <p>Acompanhamento de atenção, inadimplência e demais tags comerciais.</p>
          </div>
          {lojas.length > 1 && (
            <label className="analisador-campo clientes-loja">
              <span>Loja</span>
              <select className="custom-select analisador-select" value={loja} onChange={(e) => setLoja(e.target.value)}>
                <option value="">Todas as lojas</option>
                {lojas.map((nome) => <option key={nome} value={nome}>{nome}</option>)}
              </select>
            </label>
          )}
        </header>

        {!empresa && (
          <div className="glass-card glass-card-flat clientes-vazio">
            <UsersRound size={24} aria-hidden="true" />
            <div><strong>Selecione uma empresa</strong><p>Use seletor da barra lateral para carregar base de clientes.</p></div>
          </div>
        )}

        {erro && <div className="glass-card glass-card-flat analisador-erro" role="alert"><AlertTriangle size={17} /> {erro}</div>}

        {empresa && (
          <>
            <section className="clientes-tag-resumo" aria-label="Resumo por tag">
              <button type="button" className={`glass-card clientes-tag-card${tagFiltro === '' ? ' is-ativo' : ''}`} onClick={() => setTagFiltro('')}>
                <UsersRound size={18} /><span>Base de clientes</span><strong>{totalClientes.toLocaleString('pt-BR')}</strong>
              </button>
              {tagsAtivas.map((tag) => (
                <button key={tag.id} type="button" className={`glass-card clientes-tag-card${tagFiltro === tag.id ? ' is-ativo' : ''}`} style={{ '--tag-cor': tag.cor } as CSSProperties} onClick={() => setTagFiltro((atual) => atual === tag.id ? '' : tag.id)}>
                  <Tag size={17} /><span>{tag.rotulo}</span><strong>{totaisTags[tag.id] ?? 0}</strong>
                </button>
              ))}
            </section>

            <ClientesRitmoAlertas empresa={empresa} loja={loja || null} catalogo={catalogo} />

            <ClientesAlertaCard empresa={empresa} loja={loja || null} itensClientes={clientesCompletos} tagsPorCliente={tagsPorCliente} tagsCatalogo={catalogo} clientesBalcao={clientesBalcao} />

            <section className="glass-card glass-card-flat clientes-base-card">
              <div className="clientes-base-topo">
                <div><h2>Base de clientes</h2><p>Busque cliente e clique nas tags para marcar ou desmarcar.</p></div>
                <label className="analisador-campo clientes-busca">
                  <span>Buscar cliente</span>
                  <span className="monitor-input-icon-wrap"><Search size={15} /><input className="analisador-input" type="search" value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="Nome do cliente" /></span>
                </label>
              </div>

              {carregando ? <p className="analisador-hint">Carregando base de clientes…</p> : (
                <div className="clientes-tabela-wrap custom-scrollbar">
                  <table className="analisador-tabela clientes-tabela">
                    <thead><tr><th>Cliente</th><th>Tags de acompanhamento</th><th className="col-num">Receita</th></tr></thead>
                    <tbody>
                      {clientesVisiveis.length === 0 && <tr><td colSpan={3} className="analisador-tabela-vazia">Nenhum cliente encontrado.</td></tr>}
                      {clientesVisiveis.map((item) => {
                        const chave = item.cliente.trim();
                        const tagsCliente = tagsPorCliente[chave] ?? [];
                        return (
                          <tr key={chave}>
                            <td className="col-nome" title={chave}>{chave}</td>
                            <td><div className="clientes-tags-acoes">{tagsAtivas.map((tag) => {
                              const ativa = tagsCliente.includes(tag.id);
                              return <button key={tag.id} type="button" className={`clientes-tag-toggle${ativa ? ' is-ativo' : ''}`} style={{ '--tag-cor': tag.cor } as CSSProperties} aria-pressed={ativa} disabled={salvandoCliente === chave} onClick={() => void alternarTag(chave, tag.id)}>{tag.rotulo}</button>;
                            })}</div></td>
                            <td className="col-num">{formatCurrency(item.receita)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="analisador-hint clientes-base-rodape">
                {clientesVisiveis.length.toLocaleString('pt-BR')} exibido(s) · {totalClientes.toLocaleString('pt-BR')} na base
                {baseLimitada && ' · limite operacional de 5.000; use busca para refinar'}
              </p>
            </section>
          </>
        )}
      </div>
    </AppShell>
  );
}
