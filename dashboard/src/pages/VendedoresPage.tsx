import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Banknote,
  ContactRound,
  Loader2,
  Percent,
  Search,
  Users,
} from 'lucide-react';
import { AppShell } from '../components/AppShell';
import { StatCard } from '../components/StatCard';
import { VendedorEvolucaoChart } from '../components/vendedores/VendedorEvolucaoChart';
import {
  obterFichaVendedor,
  obterRankingVendedores,
  type FichaVendedorResposta,
  type ItemFichaVendedor,
  type ItemRankingVendedor,
  type RankingVendedoresResposta,
} from '../api/client';
import { formatCurrency, formatNumber, formatPercent } from '../utils/formatters';
import { useEscopoAtual } from '../hooks/useEscopoAtual';
import { useMesesFechados } from '../hooks/useMesesFechados';

function normalizarBusca(valor: string): string {
  return valor.normalize('NFD').replace(/[̀-ͯ]/g, '').toLocaleLowerCase('pt-BR');
}

function textoVariacao(valor: number | null | undefined): string {
  if (valor == null || !Number.isFinite(valor)) return '—';
  const sinal = valor > 0 ? '+' : '';
  return `${sinal}${formatPercent(valor, 1)}`;
}

/** Igual a `textoVariacao`, mas troca o percentual por um rótulo quando a receita
 *  do mês fica negativa (devolução maior que venda) — nesse caso a queda passa
 *  de -100% e o número deixa de comunicar algo útil. */
function textoVariacaoDestaque(item: { variacao: number; receita_atual: number } | null | undefined): string {
  if (item == null) return '—';
  if (item.receita_atual < 0) return 'Receita negativa no mês';
  return textoVariacao(item.variacao);
}

function classeVariacao(valor: number | null | undefined): string {
  if (valor == null) return '';
  if (valor <= -20) return 'is-queda';
  if (valor >= 20) return 'is-alta';
  return '';
}

function rotuloPeriodo(inicio: string | null, fim: string | null): string {
  if (!inicio || !fim) return '6 meses anteriores';
  return `${inicio} a ${fim}`;
}

function nomeItem(item: ItemFichaVendedor): string {
  return item.cliente || item.produto || item.fabricante || item.nome || '—';
}

const ABAS_ENTIDADE = [
  { id: 'clientes', rotulo: 'Clientes' },
  { id: 'produtos', rotulo: 'Produtos' },
  { id: 'fabricantes', rotulo: 'Fabricantes' },
] as const;

type AbaEntidade = (typeof ABAS_ENTIDADE)[number]['id'];

/** Tela de análise de vendedores: ranking do último mês vs média dos 6 anteriores. */
export default function VendedoresPage() {
  const { empresa, loja } = useEscopoAtual();
  const [modoPeriodo] = useMesesFechados();
  const [ranking, setRanking] = useState<RankingVendedoresResposta | null>(null);
  const [ficha, setFicha] = useState<FichaVendedorResposta | null>(null);
  const [vendedor, setVendedor] = useState<string | null>(null);
  const [busca, setBusca] = useState('');
  const [carregando, setCarregando] = useState(false);
  const [carregandoFicha, setCarregandoFicha] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    setVendedor(null);
    setFicha(null);
    if (!empresa) {
      setRanking(null);
      setErro(null);
      return;
    }
    const controller = new AbortController();
    setCarregando(true);
    setErro(null);
    void obterRankingVendedores(empresa, loja, controller.signal, modoPeriodo)
      .then(setRanking)
      .catch((falha) => {
        if (falha instanceof DOMException && falha.name === 'AbortError') return;
        setRanking(null);
        setErro(falha instanceof Error ? falha.message : 'Falha ao carregar vendedores.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setCarregando(false);
      });
    return () => controller.abort();
  }, [empresa, loja, modoPeriodo]);

  useEffect(() => {
    if (!empresa || !vendedor) {
      setFicha(null);
      return;
    }
    const controller = new AbortController();
    setCarregandoFicha(true);
    void obterFichaVendedor(empresa, vendedor, loja, controller.signal, modoPeriodo)
      .then(setFicha)
      .catch((falha) => {
        if (falha instanceof DOMException && falha.name === 'AbortError') return;
        setFicha(null);
        setErro(falha instanceof Error ? falha.message : 'Falha ao carregar ficha.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setCarregandoFicha(false);
      });
    return () => controller.abort();
  }, [empresa, loja, vendedor, modoPeriodo]);

  const visiveis = useMemo(() => {
    const termo = normalizarBusca(busca.trim());
    const itens = ranking?.itens ?? [];
    if (!termo) return itens;
    return itens.filter((item) => normalizarBusca(item.vendedor).includes(termo));
  }, [busca, ranking]);
  const maiorReceita = visiveis.reduce((maximo, item) => Math.max(maximo, item.receita_atual), 0);

  const escolher = (item: ItemRankingVendedor) => {
    setVendedor((atual) => (atual === item.vendedor ? null : item.vendedor));
  };

  return (
    <AppShell>
      <div className="dashboard-container vendedores-page">
        <header className="app-page-header vendedores-page-header">
          <div>
            <h1>Vendedores{empresa && <span className="analisador-header-empresa"> · {empresa}</span>}</h1>
            <p>
              Último mês da base contra a média dos 6 anteriores.
              {ranking?.rotulo_periodo && ` Referência: ${ranking.rotulo_periodo}.`}
            </p>
          </div>
        </header>

        {!empresa && (
          <div className="glass-card glass-card-flat vendedores-vazio">
            <ContactRound size={24} aria-hidden="true" />
            <div>
              <strong>Selecione uma empresa</strong>
              <p>Use o seletor no topo da tela para carregar o ranking de vendedores.</p>
            </div>
          </div>
        )}

        {erro && (
          <div className="glass-card glass-card-flat vendedores-aviso" role="alert">
            <AlertTriangle size={18} />
            <span>{erro}</span>
          </div>
        )}

        {carregando && !ranking && (
          <div className="glass-card vendedores-carregando" role="status">
            <Loader2 size={20} className="dashboard-filter-spinner" /> Calculando ranking de vendedores…
          </div>
        )}

        {ranking && !ranking.disponivel && (
          <div className="glass-card glass-card-flat vendedores-vazio" role="status">
            <ContactRound size={24} aria-hidden="true" />
            <div>
              <strong>Coluna de vendedor ainda não disponível</strong>
              <p>{ranking.mensagem || 'A tela preenche sozinha quando a base passar a trazer o vendedor em cada movimento.'}</p>
            </div>
          </div>
        )}

        {ranking?.disponivel && (
          <>
            <section className="vendedores-kpis" aria-label="Resumo de vendedores">
              <article className="glass-card glass-card-flat vendedores-hero">
                <p className="despesas-hero-rotulo">
                  <Banknote size={14} aria-hidden="true" /> Receita do mês
                </p>
                <strong className="despesas-hero-valor">{formatCurrency(ranking.resumo.receita_atual)}</strong>
                <p className="despesas-hero-nota">
                  {ranking.resumo.vendedores.toLocaleString('pt-BR')} vendedor(es) · vs {rotuloPeriodo(ranking.periodo_media_inicio, ranking.periodo_media_fim)}
                </p>
              </article>
              <div className="vendedores-kpis-secundarios">
                <StatCard
                  title="Vendedores no período"
                  value={ranking.resumo.vendedores.toLocaleString('pt-BR')}
                  icon={Users}
                />
                <StatCard
                  title="Maior alta"
                  value={ranking.resumo.maior_alta?.vendedor ?? '—'}
                  valueClassName="vendedores-kpi-nome"
                  icon={ArrowUpRight}
                  trend={textoVariacaoDestaque(ranking.resumo.maior_alta)}
                  trendUp
                  useTrendColor={ranking.resumo.maior_alta != null}
                />
                <StatCard
                  title="Maior queda"
                  value={ranking.resumo.maior_queda?.vendedor ?? '—'}
                  valueClassName="vendedores-kpi-nome"
                  icon={ArrowDownRight}
                  trend={textoVariacaoDestaque(ranking.resumo.maior_queda)}
                  trendUp={false}
                  useTrendColor={ranking.resumo.maior_queda != null}
                />
              </div>
            </section>

            <section className="glass-card glass-card-flat vendedores-tabela-card">
              <div className="vendedores-tabela-topo">
                <div>
                  <h2>Ranking</h2>
                  <p>Clique numa linha para ver o caminhar de vendas, clientes, mix e alertas.</p>
                </div>
                <label className="analisador-campo vendedores-busca">
                  <span>Buscar vendedor</span>
                  <span className="monitor-input-icon-wrap">
                    <Search size={15} />
                    <input
                      className="analisador-input"
                      type="search"
                      value={busca}
                      onChange={(e) => setBusca(e.target.value)}
                      placeholder="Nome do vendedor"
                    />
                  </span>
                </label>
              </div>
              <div className="vendedores-tabela-wrap custom-scrollbar">
                <table className="analisador-tabela vendedores-tabela">
                  <thead>
                    <tr>
                      <th className="col-nome">Vendedor</th>
                      <th className="col-num">Receita</th>
                      <th className="col-num">Média 6 meses</th>
                      <th className="col-num">Variação</th>
                      <th className="col-num">Qtd</th>
                      <th className="col-num">Clientes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visiveis.length === 0 && (
                      <tr>
                        <td colSpan={6} className="analisador-tabela-vazia">Nenhum vendedor neste filtro.</td>
                      </tr>
                    )}
                    {visiveis.map((item) => (
                      <tr
                        key={item.vendedor}
                        className={`${item.vendedor === vendedor ? 'is-ativo' : ''}${item.alerta ? ' is-alerta' : ''}`}
                        onClick={() => escolher(item)}
                      >
                        <td className="col-nome">{item.vendedor}</td>
                        <td className="col-num">
                          <span className="vendedores-celula-barra">
                            <i aria-hidden="true">
                              <b style={{ width: `${maiorReceita > 0 ? (item.receita_atual / maiorReceita) * 100 : 0}%` }} />
                            </i>
                            {formatCurrency(item.receita_atual)}
                          </span>
                        </td>
                        <td className="col-num">{formatCurrency(item.receita_media)}</td>
                        <td className={`col-num ${classeVariacao(item.variacao)}`}>{textoVariacao(item.variacao)}</td>
                        <td className="col-num">{formatNumber(item.qtd_atual)}</td>
                        <td className="col-num">{item.clientes_atual.toLocaleString('pt-BR')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            {vendedor && (
              <FichaPainel
                nome={vendedor}
                ficha={ficha}
                carregando={carregandoFicha}
              />
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}

function FichaPainel({
  nome,
  ficha,
  carregando,
}: {
  nome: string;
  ficha: FichaVendedorResposta | null;
  carregando: boolean;
}) {
  const [aba, setAba] = useState<AbaEntidade>('clientes');
  const ancora = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ancora.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [nome]);

  if (carregando && !ficha) {
    return (
      <div ref={ancora} className="glass-card vendedores-carregando" role="status">
        <Loader2 size={20} className="dashboard-filter-spinner" /> Abrindo ficha de {nome}…
      </div>
    );
  }
  if (!ficha) return null;

  const alertas = [
    ...(ficha.alertas?.clientes ?? []).map((item) => ({ tipo: 'Cliente', nome: nomeItem(item), item })),
    ...(ficha.alertas?.produtos ?? []).map((item) => ({ tipo: 'Produto', nome: nomeItem(item), item })),
  ];

  const itensPorAba: Record<AbaEntidade, { itens: ItemFichaVendedor[]; coluna: string }> = {
    clientes: { itens: ficha.clientes ?? [], coluna: 'Cliente' },
    produtos: { itens: ficha.produtos ?? [], coluna: 'Produto' },
    fabricantes: { itens: ficha.fabricantes ?? [], coluna: 'Fabricante' },
  };
  const abaAtual = itensPorAba[aba];
  const receitaCaiu = (ficha.variacao ?? 0) < 0;

  return (
    <div ref={ancora}>
    <section className="vendedores-ficha" aria-label={`Ficha de ${ficha.vendedor}`}>
      <header className="glass-card glass-card-flat vendedores-ficha-cabeca">
        <div>
          <h2>{ficha.vendedor}</h2>
          <p>{ficha.rotulo_periodo} vs média de {ficha.meses_media} meses</p>
        </div>
      </header>

      <div className="glass-card glass-card-flat vendedores-evolucao-card">
        <header className="estoque-card-topo">
          <div>
            <h3>Caminhar de vendas</h3>
            <p>Receita de {ficha.vendedor} mês a mês, com a régua da média dos {ficha.meses_media} meses anteriores.</p>
          </div>
        </header>
        <VendedorEvolucaoChart pontos={ficha.serie_mensal ?? []} media={ficha.receita_media} />
      </div>

      <div className="vendedores-ficha-kpis">
        <StatCard title="Receita do mês" value={formatCurrency(ficha.receita_atual)} icon={Banknote} />
        <StatCard title="Média 6 meses" value={formatCurrency(ficha.receita_media)} icon={Banknote} />
        <StatCard
          title="Variação"
          value={textoVariacao(ficha.variacao)}
          icon={receitaCaiu ? ArrowDownRight : ArrowUpRight}
          trendUp={!receitaCaiu}
          useTrendColor={ficha.variacao != null}
        />
        <StatCard title="Clientes atendidos" value={ficha.clientes_atual.toLocaleString('pt-BR')} icon={Percent} />
      </div>

      <div className="glass-card glass-card-flat vendedores-alertas-card">
        <h3>Alertas de queda</h3>
        <p>Clientes e produtos com variação de {formatPercent(-20, 0)} ou pior contra a média.</p>
        {alertas.length === 0 ? (
          <p className="analisador-hint">Nenhum alerta neste recorte.</p>
        ) : (
          <>
            <ul className="vendedores-alertas-lista">
              {alertas.map((alerta) => (
                <li key={`${alerta.tipo}-${alerta.nome}`}>
                  <span className="vendedores-alerta-tipo">{alerta.tipo}</span>
                  <strong>{alerta.nome}</strong>
                  <span className="is-queda">{textoVariacao(alerta.item.variacao)}</span>
                  <span>{formatCurrency(alerta.item.receita_atual)}</span>
                </li>
              ))}
            </ul>
            {(ficha.alertas.clientes_total || ficha.alertas.produtos_total) && (
              <p className="analisador-hint">
                {ficha.alertas.clientes_total ?? ficha.alertas.clientes.length} cliente(s) e {ficha.alertas.produtos_total ?? ficha.alertas.produtos.length} produto(s) em queda — lista mostra os maiores desvios.
              </p>
            )}
          </>
        )}
      </div>

      <div className="glass-card glass-card-flat vendedores-entidade-card">
        <div className="estoque-card-topo">
          <div>
            <h3>{itensPorAba[aba].coluna}s</h3>
            <p>Mesmo recorte: mês contra a média de {ficha.meses_media} meses.</p>
          </div>
          <div className="periodo-segmented segmented-compacto" role="tablist" aria-label="Escolher entidade">
            {ABAS_ENTIDADE.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={aba === item.id}
                className={`periodo-segmented-btn${aba === item.id ? ' is-active' : ''}`}
                onClick={() => setAba(item.id)}
              >
                {item.rotulo}
              </button>
            ))}
          </div>
        </div>
        <TabelaEntidade itens={abaAtual.itens} coluna={abaAtual.coluna} />
      </div>
    </section>
    </div>
  );
}

function TabelaEntidade({
  itens,
  coluna,
}: {
  itens: ItemFichaVendedor[];
  coluna: string;
}) {
  return (
    <div className="vendedores-tabela-wrap custom-scrollbar">
      <table className="analisador-tabela vendedores-tabela">
          <thead>
            <tr>
              <th className="col-nome">{coluna}</th>
              <th className="col-num">Receita</th>
              <th className="col-num">Média</th>
              <th className="col-var">Var.</th>
            </tr>
          </thead>
          <tbody>
            {itens.length === 0 && (
              <tr>
                <td colSpan={4} className="analisador-tabela-vazia">Sem movimento neste recorte.</td>
              </tr>
            )}
            {itens.map((item) => (
              <tr key={nomeItem(item)} className={item.alerta ? 'is-alerta' : ''}>
                <td className="col-nome" title={nomeItem(item)}>{nomeItem(item)}</td>
                <td className="col-num">{formatCurrency(item.receita_atual)}</td>
                <td className="col-num">{formatCurrency(item.receita_media)}</td>
                <td className={`col-var ${classeVariacao(item.variacao)}`}>{textoVariacao(item.variacao)}</td>
              </tr>
            ))}
          </tbody>
        </table>
    </div>
  );
}
