import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Banknote,
  ContactRound,
  Loader2,
  Search,
} from 'lucide-react';
import { AppShell } from '../components/AppShell';
import { VendedoresComparativoChart } from '../components/vendedores/VendedoresComparativoChart';
import {
  obterFichaVendedor,
  obterRankingVendedores,
  obterTelaVendedores,
  type FichaVendedorResposta,
  type ItemFichaVendedor,
  type ItemRankingVendedor,
  type RankingVendedoresResposta,
} from '../api/client';
import { formatCurrency, formatNumber, formatPercent } from '../utils/formatters';
import { useEscopoAtual } from '../hooks/useEscopoAtual';
import { useMesesFechados } from '../hooks/useMesesFechados';
import { EVENTO_TELA_VENDEDORES } from '../utils/telaVendedores';

function normalizarBusca(valor: string): string {
  return valor.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
}

function textoVariacao(valor: number | null | undefined): string {
  if (valor == null || !Number.isFinite(valor)) return '—';
  const sinal = valor > 0 ? '+' : '';
  return `${sinal}${formatPercent(valor, 1)}`;
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

function pontosFicha(itens: ItemFichaVendedor[]) {
  return itens.slice(0, 6).map((item) => ({
    nome: nomeItem(item),
    atual: item.receita_atual,
    media: item.receita_media,
  }));
}

function LegendaComparativo() {
  return (
    <p className="vendedores-chart-legenda">
      <span><i className="is-mes" aria-hidden="true" /> Mês</span>
      <span><i className="is-media" aria-hidden="true" /> Média 6 meses</span>
    </p>
  );
}

/** Tela de análise de vendedores: ranking do último mês vs média dos 6 anteriores. */
export default function VendedoresPage() {
  const { empresa, loja } = useEscopoAtual();
  const [modoPeriodo] = useMesesFechados();
  const navigate = useNavigate();
  const [liberada, setLiberada] = useState(false);
  const [ranking, setRanking] = useState<RankingVendedoresResposta | null>(null);
  const [ficha, setFicha] = useState<FichaVendedorResposta | null>(null);
  const [vendedor, setVendedor] = useState<string | null>(null);
  const [busca, setBusca] = useState('');
  const [carregando, setCarregando] = useState(false);
  const [carregandoFicha, setCarregandoFicha] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    let cancelado = false;
    void obterTelaVendedores()
      .then((visivel) => {
        if (cancelado) return;
        if (!visivel) navigate('/', { replace: true });
        else setLiberada(true);
      })
      .catch(() => {
        if (!cancelado) navigate('/', { replace: true });
      });
    const aoMudar = (evento: Event) => {
      if (!(evento as CustomEvent<boolean>).detail) navigate('/', { replace: true });
    };
    window.addEventListener(EVENTO_TELA_VENDEDORES, aoMudar);
    return () => {
      cancelado = true;
      window.removeEventListener(EVENTO_TELA_VENDEDORES, aoMudar);
    };
  }, [navigate]);

  useEffect(() => {
    setVendedor(null);
    setFicha(null);
    if (!liberada || !empresa) {
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
  }, [empresa, loja, liberada, modoPeriodo]);

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

  const escolher = (item: ItemRankingVendedor) => {
    setVendedor((atual) => (atual === item.vendedor ? null : item.vendedor));
  };

  if (!liberada) {
    return (
      <AppShell>
        <div className="dashboard-container vendedores-page" />
      </AppShell>
    );
  }

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
              <p>Use o seletor da barra lateral para carregar o ranking de vendedores.</p>
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
              <article className="glass-card vendedores-kpi">
                <ContactRound size={18} />
                <span>Vendedores</span>
                <strong>{ranking.resumo.vendedores.toLocaleString('pt-BR')}</strong>
                <small>{ranking.rotulo_periodo}</small>
              </article>
              <article className="glass-card vendedores-kpi">
                <Banknote size={18} />
                <span>Receita do mês</span>
                <strong>{formatCurrency(ranking.resumo.receita_atual)}</strong>
                <small>vs {rotuloPeriodo(ranking.periodo_media_inicio, ranking.periodo_media_fim)}</small>
              </article>
              <article className="glass-card vendedores-kpi is-alta">
                <ArrowUpRight size={18} />
                <span>Maior alta</span>
                <strong>{ranking.resumo.maior_alta?.vendedor ?? '—'}</strong>
                <small>{textoVariacao(ranking.resumo.maior_alta?.variacao ?? null)}</small>
              </article>
              <article className="glass-card vendedores-kpi is-queda">
                <ArrowDownRight size={18} />
                <span>Maior queda</span>
                <strong>{ranking.resumo.maior_queda?.vendedor ?? '—'}</strong>
                <small>{textoVariacao(ranking.resumo.maior_queda?.variacao ?? null)}</small>
              </article>
            </section>

            <section className="glass-card glass-card-flat vendedores-tabela-card">
              <div className="vendedores-tabela-topo">
                <div>
                  <h2>Ranking</h2>
                  <p>Clique numa linha para abrir clientes, mix e alertas.</p>
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
              {visiveis.length > 0 && (
                <>
                  <LegendaComparativo />
                  <VendedoresComparativoChart
                    pontos={visiveis.slice(0, 12).map((item) => ({
                      nome: item.vendedor,
                      atual: item.receita_atual,
                      media: item.receita_media,
                    }))}
                    modo="colunas"
                    altura={200}
                    ativo={vendedor}
                    onSelect={setVendedor}
                  />
                </>
              )}
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
                        <td className="col-num">{formatCurrency(item.receita_atual)}</td>
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
  if (carregando && !ficha) {
    return (
      <div className="glass-card vendedores-carregando" role="status">
        <Loader2 size={20} className="dashboard-filter-spinner" /> Abrindo ficha de {nome}…
      </div>
    );
  }
  if (!ficha) return null;

  const alertas = [
    ...ficha.alertas.clientes.map((item) => ({ tipo: 'Cliente', nome: nomeItem(item), item })),
    ...ficha.alertas.produtos.map((item) => ({ tipo: 'Produto', nome: nomeItem(item), item })),
  ];

  return (
    <section className="vendedores-ficha" aria-label={`Ficha de ${ficha.vendedor}`}>
      <header className="glass-card glass-card-flat vendedores-ficha-cabeca">
        <div>
          <h2>{ficha.vendedor}</h2>
          <p>{ficha.rotulo_periodo} vs média de {ficha.meses_media} meses</p>
        </div>
        <dl className="vendedores-ficha-numeros">
          <div>
            <dt>Receita</dt>
            <dd>{formatCurrency(ficha.receita_atual)}</dd>
          </div>
          <div>
            <dt>Média</dt>
            <dd>{formatCurrency(ficha.receita_media)}</dd>
          </div>
          <div>
            <dt>Variação</dt>
            <dd className={classeVariacao(ficha.variacao)}>{textoVariacao(ficha.variacao)}</dd>
          </div>
          <div>
            <dt>Clientes</dt>
            <dd>{ficha.clientes_atual.toLocaleString('pt-BR')}</dd>
          </div>
        </dl>
      </header>

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

      <div className="vendedores-ficha-grades">
        <LegendaComparativo />
        <TabelaEntidade titulo="Clientes" itens={ficha.clientes} coluna="Cliente" />
        <TabelaEntidade titulo="Produtos" itens={ficha.produtos} coluna="Produto" />
        <TabelaEntidade titulo="Fabricantes" itens={ficha.fabricantes} coluna="Fabricante" />
      </div>
    </section>
  );
}

function TabelaEntidade({
  titulo,
  itens,
  coluna,
}: {
  titulo: string;
  itens: ItemFichaVendedor[];
  coluna: string;
}) {
  return (
    <section className="glass-card glass-card-flat vendedores-entidade-card">
      <h3>{titulo}</h3>
      <VendedoresComparativoChart
        pontos={pontosFicha(itens)}
        modo="barras"
        altura={Math.min(itens.length, 6) * 28 + 24}
      />
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
    </section>
  );
}
