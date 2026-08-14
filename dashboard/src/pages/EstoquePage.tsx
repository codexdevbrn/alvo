import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Boxes, Loader2, PackageX, Search, TrendingDown } from 'lucide-react';
import { AppShell } from '../components/AppShell';
import { EstoqueCoberturaChart } from '../components/estoque/EstoqueCoberturaChart';
import {
  obterCoberturaEstoque,
  type CoberturaEstoqueResposta,
  type ItemCoberturaEstoque,
  type StatusCoberturaEstoque,
} from '../api/client';
import { formatCurrency, formatPercent } from '../utils/formatters';
import { EVENTO_EMPRESA } from '../utils/empresaSelecionada';

const LS_EMPRESA = 'alvo_empresa';

const ROTULOS_STATUS: Record<StatusCoberturaEstoque, string> = {
  normal: 'Saudável',
  rupture: 'Risco de ruptura',
  out_of_stock: 'Sem estoque',
  negative: 'Estoque negativo',
  stalled: 'Perdendo força',
  excess: 'Excesso',
  no_sales: 'Sem giro',
};

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

function numero(valor: number, casas = 0): string {
  return valor.toLocaleString('pt-BR', { maximumFractionDigits: casas });
}

function classeStatus(status: StatusCoberturaEstoque): string {
  if (status === 'normal') return 'is-normal';
  if (status === 'rupture' || status === 'out_of_stock' || status === 'negative') return 'is-perigo';
  return 'is-atencao';
}

/** Tela dedicada ao capital parado, excesso de cobertura e risco de ruptura. */
export default function EstoquePage() {
  const [empresa, setEmpresa] = useState(lerEmpresa);
  const [loja, setLoja] = useState('');
  const [meses, setMeses] = useState(6);
  const [dados, setDados] = useState<CoberturaEstoqueResposta | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [busca, setBusca] = useState('');
  const [fabricante, setFabricante] = useState('');
  const [status, setStatus] = useState('');

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
      setDados(null);
      setErro(null);
      return;
    }
    const controller = new AbortController();
    setCarregando(true);
    setErro(null);
    void obterCoberturaEstoque(empresa, { loja: loja || null, meses, limite: 1200 }, controller.signal)
      .then(setDados)
      .catch((falha) => {
        if (falha instanceof DOMException && falha.name === 'AbortError') return;
        setDados(null);
        setErro(falha instanceof Error ? falha.message : 'Falha ao carregar estoque.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setCarregando(false);
      });
    return () => controller.abort();
  }, [empresa, loja, meses]);

  const fabricantes = useMemo(() => Array.from(new Set(
    (dados?.itens ?? []).map((item) => item.fabricante).filter(Boolean),
  )).sort((a, b) => a.localeCompare(b, 'pt-BR')), [dados]);

  const itensFiltrados = useMemo(() => {
    const termo = normalizarBusca(busca.trim());
    return (dados?.itens ?? []).filter((item) => {
      if (fabricante && item.fabricante !== fabricante) return false;
      if (status && item.status !== status) return false;
      if (!termo) return true;
      return normalizarBusca(`${item.nome} ${item.sku} ${item.codigo_interno} ${item.fabricante}`).includes(termo);
    });
  }, [busca, dados, fabricante, status]);

  const itensCriticos = useMemo(() => itensFiltrados
    .filter((item) => item.status !== 'normal')
    .sort((a, b) => b.valor_estoque - a.valor_estoque)
    .slice(0, 30), [itensFiltrados]);

  const periodo = dados?.periodo_inicio && dados.periodo_fim
    ? `${dados.periodo_inicio} a ${dados.periodo_fim}`
    : 'sem histórico de vendas';

  return (
    <AppShell>
      <div className="dashboard-container estoque-page">
        <header className="app-page-header estoque-page-header">
          <div>
            <h1>Estoque × velocidade de venda{empresa && <span className="analisador-header-empresa"> · {empresa}</span>}</h1>
            <p>Cobertura, capital parado e risco de ruptura por produto.</p>
          </div>
          {empresa && (
            <div className="estoque-header-filtros">
              {dados && dados.lojas.length > 1 && (
                <label className="analisador-campo">
                  <span>Loja</span>
                  <select className="custom-select analisador-select" value={loja} onChange={(e) => setLoja(e.target.value)}>
                    <option value="">Todas as lojas</option>
                    {dados.lojas.map((nome) => <option key={nome} value={nome}>{nome}</option>)}
                  </select>
                </label>
              )}
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
            <div><strong>Selecione uma empresa</strong><p>Use seletor da barra lateral para carregar estoque e vendas.</p></div>
          </div>
        )}

        {erro && (
          <div className="glass-card glass-card-flat estoque-aviso" role="alert">
            <AlertTriangle size={18} /><span>{erro}</span>
          </div>
        )}

        {carregando && !dados && (
          <div className="glass-card estoque-carregando" role="status">
            <Loader2 size={20} className="dashboard-filter-spinner" /> Calculando cobertura de estoque…
          </div>
        )}

        {dados && !dados.disponivel && (
          <div className="glass-card glass-card-flat estoque-vazio" role="status">
            <PackageX size={24} aria-hidden="true" />
            <div>
              <strong>Dados de estoque ainda não disponíveis</strong>
              <p>{dados.mensagem || 'A tela será preenchida automaticamente quando a base receber os dados necessários.'}</p>
            </div>
          </div>
        )}

        {dados?.disponivel && (
          <>
            <section className="estoque-kpis" aria-label="Resumo do estoque">
              <article className="glass-card estoque-kpi"><Boxes size={18} /><span>Capital em estoque</span><strong>{formatCurrency(dados.resumo.valor_estoque)}</strong><small>{dados.resumo.produtos.toLocaleString('pt-BR')} produtos</small></article>
              <article className="glass-card estoque-kpi is-perigo"><PackageX size={18} /><span>Risco de ruptura</span><strong>{dados.resumo.ruptura.toLocaleString('pt-BR')}</strong><small>inclui sem estoque e negativo</small></article>
              <article className="glass-card estoque-kpi is-atencao"><TrendingDown size={18} /><span>Excesso / perda de força</span><strong>{dados.resumo.excesso.toLocaleString('pt-BR')}</strong><small>acima de 6 meses</small></article>
              <article className="glass-card estoque-kpi is-atencao"><AlertTriangle size={18} /><span>Sem giro</span><strong>{dados.resumo.sem_giro.toLocaleString('pt-BR')}</strong><small>sem venda na janela</small></article>
            </section>

            <section className="glass-card glass-card-flat estoque-grafico-card">
              <div className="estoque-grafico-topo">
                <div>
                  <h2>Mapa de cobertura</h2>
                  <p>{periodo} · {itensFiltrados.length.toLocaleString('pt-BR')} pontos exibidos</p>
                </div>
                <div className="estoque-grafico-filtros">
                  <label className="monitor-input-icon-wrap estoque-busca">
                    <Search size={15} />
                    <input className="analisador-input" type="search" value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="Produto, SKU ou fabricante" aria-label="Buscar produto" />
                  </label>
                  <select className="custom-select analisador-select" value={fabricante} onChange={(e) => setFabricante(e.target.value)} aria-label="Filtrar fabricante">
                    <option value="">Todos os fabricantes</option>
                    {fabricantes.map((nome) => <option key={nome} value={nome}>{nome}</option>)}
                  </select>
                  <select className="custom-select analisador-select" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filtrar situação">
                    <option value="">Todas as situações</option>
                    {Object.entries(ROTULOS_STATUS).map(([chave, rotulo]) => <option key={chave} value={chave}>{rotulo}</option>)}
                  </select>
                </div>
              </div>
              <EstoqueCoberturaChart itens={itensFiltrados} />
              {dados.limitado && <p className="analisador-hint estoque-limite">Gráfico prioriza 1.200 produtos com maior valor em estoque.</p>}
            </section>

            <section className="glass-card glass-card-flat estoque-tabela-card">
              <div><h2>Itens críticos por capital</h2><p>Excesso, perda de força, sem giro e risco de ruptura.</p></div>
              <div className="estoque-tabela-wrap custom-scrollbar">
                <table className="analisador-tabela estoque-tabela">
                  <thead><tr><th>Produto</th><th>Fabricante</th><th>Situação</th><th className="col-num">Estoque</th><th className="col-num">Venda/mês</th><th className="col-num">Cobertura</th><th className="col-num">Capital</th></tr></thead>
                  <tbody>
                    {itensCriticos.length === 0 && <tr><td colSpan={7} className="analisador-tabela-vazia">Nenhum item crítico neste filtro.</td></tr>}
                    {itensCriticos.map((item: ItemCoberturaEstoque) => (
                      <tr key={`${item.codigo_interno}-${item.sku}`}>
                        <td className="col-nome"><strong>{item.nome}</strong><small>{item.sku}</small></td>
                        <td>{item.fabricante}</td>
                        <td><span className={`estoque-status ${classeStatus(item.status)}`}>{ROTULOS_STATUS[item.status]}</span></td>
                        <td className="col-num">{numero(item.estoque)}</td>
                        <td className="col-num">{numero(item.venda_media, 1)}</td>
                        <td className="col-num">{item.cobertura == null ? '—' : `${numero(item.cobertura, 1)} meses`}</td>
                        <td className="col-num">{formatCurrency(item.valor_estoque)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {itensCriticos.some((item) => item.variacao_pct != null) && (
                <p className="analisador-hint estoque-tabela-nota">
                  “Perdendo força” usa últimos 3 meses contra 3 anteriores. Variação disponível no tooltip da bolha, ex.: {formatPercent(itensCriticos.find((item) => item.variacao_pct != null)?.variacao_pct ?? 0, 1)}.
                </p>
              )}
            </section>
          </>
        )}
      </div>
    </AppShell>
  );
}
