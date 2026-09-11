import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Loader2, PackageX, Search } from 'lucide-react';
import { EstoqueCoberturaChart } from './EstoqueCoberturaChart';
import {
  ROTULOS_STATUS,
  classeStatus,
  normalizarBusca,
  numero,
  textoCobertura,
} from './estoqueStatus';
import {
  obterCoberturaEstoque,
  type CoberturaEstoqueResposta,
  type ItemCoberturaEstoque,
} from '../../api/client';
import { formatCurrency, formatPercent } from '../../utils/formatters';
import { useMesesFechados } from '../../hooks/useMesesFechados';
import { modoParaBooleano } from '../../utils/mesesFechados';

type Props = {
  empresa: string;
  loja: string | null;
  meses: number;
};

/** Aba Escopo: o mapa produto a produto em foco, com os filtros que o alimentam.
 *  Busca própria — a visão geral não carrega os 1.200 pontos do mapa. */
export function EstoqueEscopo({ empresa, loja, meses }: Props) {
  const [dados, setDados] = useState<CoberturaEstoqueResposta | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [busca, setBusca] = useState('');
  const [fabricante, setFabricante] = useState('');
  const [status, setStatus] = useState('');
  const [modoPeriodo] = useMesesFechados();
  const usarMesesFechados = modoParaBooleano(modoPeriodo);

  useEffect(() => {
    const controller = new AbortController();
    setCarregando(true);
    setErro(null);
    void obterCoberturaEstoque(
      empresa, { loja, meses, limite: 1200, usarMesesFechados }, controller.signal,
    )
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
  }, [empresa, loja, meses, usarMesesFechados]);

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

  if (erro) {
    return (
      <div className="glass-card glass-card-flat estoque-aviso" role="alert">
        <AlertTriangle size={18} /><span>{erro}</span>
      </div>
    );
  }

  if (carregando && !dados) {
    return (
      <div className="glass-card estoque-carregando" role="status">
        <Loader2 size={20} className="dashboard-filter-spinner" /> Calculando cobertura de estoque…
      </div>
    );
  }

  if (dados && !dados.disponivel) {
    return (
      <div className="glass-card glass-card-flat estoque-vazio" role="status">
        <PackageX size={24} aria-hidden="true" />
        <div>
          <strong>Dados de estoque ainda não disponíveis</strong>
          <p>{dados.mensagem || 'A tela será preenchida automaticamente quando a base receber os dados necessários.'}</p>
        </div>
      </div>
    );
  }

  if (!dados) return null;

  return (
    <div className="estoque-escopo">
      <section className="glass-card glass-card-flat estoque-grafico-card">
        <header className="estoque-grafico-topo">
          <div>
            <h2>Mapa de cobertura</h2>
            <p>{periodo} · {numero(itensFiltrados.length)} pontos exibidos</p>
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
        </header>
        <EstoqueCoberturaChart itens={itensFiltrados} />
        {dados.limitado && <p className="analisador-hint estoque-limite">Gráfico prioriza 1.200 produtos com maior valor em estoque.</p>}
      </section>

      <section className="glass-card glass-card-flat estoque-tabela-card">
        <header className="estoque-card-topo">
          <div><h2>Itens críticos por capital</h2><p>Excesso, perda de força, sem giro e risco de ruptura.</p></div>
        </header>
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
                  <td className="col-num">{textoCobertura(item.cobertura)}</td>
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
    </div>
  );
}
