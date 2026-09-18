import { Fragment, useEffect, useState, type CSSProperties } from 'react';
import { AlertTriangle, ChevronDown, ChevronUp, Loader2, Target, UsersRound, Wallet } from 'lucide-react';
import { StatCard } from '../StatCard';
import {
  obterPainelClientes,
  type PainelClientesResposta,
  type RankingPotencialPainel,
} from '../../api/client';
import { formatCompacto, formatCurrency, formatNumber, formatPercent } from '../../utils/formatters';
import { useMesesFechados } from '../../hooks/useMesesFechados';
import { useVersaoCortesRelatorios } from '../../hooks/useVersaoCortesRelatorios';
import { useGruposClientesFiltro } from '../../hooks/useGruposClientesFiltro';
import { gruposClientesParam } from '../../utils/gruposClientesFiltro';
import { ClientePotencialDetalhe } from './ClientePotencialDetalhe';

interface Props {
  empresa: string;
  loja?: string | null;
  onCarregandoChange?: (carregando: boolean) => void;
}

/** Ouro do acento para a faixa mais forte, esfriando até o cinza de "Demais"
 *  — mesmo gradiente de Concentração da carteira, são as mesmas faixas ABC. */
const CORES_FAIXA = ['#dabb6c', '#c2a45f', '#8e8a7d', '#5d5d66', '#43434b'];

/** Largura da barra de ranking, em %, relativa ao maior valor da lista.
 *  Raiz quadrada em vez de proporção linear: um outlier (ex.: "CLIENTE
 *  BALCÃO" concentrando venda avulsa) não pode reduzir a barra de todo o
 *  resto a um traço invisível — a ordem se mantém, só a escala comprime. */
function barraRanking(valor: number, maior: number): number {
  if (maior <= 0 || valor <= 0) return 0;
  return Math.max(0, Math.min(100, Math.sqrt(valor / maior) * 100));
}

function textoVariacao(valor: number | null | undefined): string {
  if (valor == null || !Number.isFinite(valor)) return '—';
  return `${valor > 0 ? '+' : ''}${formatPercent(valor, 1)}`;
}

function LinhaPotencialCliente({
  item,
  posicao,
  maiorPotencial,
  aberto,
  onAlternar,
}: {
  item: RankingPotencialPainel;
  posicao: number;
  maiorPotencial: number;
  aberto: boolean;
  onAlternar: (cliente: string) => void;
}) {
  return (
    <li className="clientes-ranking-linha-clicavel">
      <button
        type="button"
        className={`clientes-ranking-linha-btn${aberto ? ' is-aberto' : ''}`}
        onClick={() => onAlternar(item.cliente)}
        aria-expanded={aberto}
        title={aberto ? `Fechar produtos de ${item.cliente}` : `Ver top produtos de ${item.cliente}`}
      >
        <div className="clientes-ranking-topo">
          <span className="clientes-ranking-numero">{posicao}</span>
          <strong title={item.cliente}>{item.cliente}</strong>
          <span className="clientes-ranking-valor">{formatCurrency(item.potencial)}</span>
          {aberto ? <ChevronUp size={14} aria-hidden="true" /> : <ChevronDown size={14} aria-hidden="true" />}
        </div>
        <div className="clientes-ranking-barra" aria-hidden="true">
          <i style={{ width: `${barraRanking(item.potencial, maiorPotencial)}%` }} />
        </div>
        <div className="clientes-ranking-rodape">
          <span>{item.grupo} · atual {formatCurrency(item.atual)}/mês</span>
          {item.variacao != null && (
            // variacao = atual contra o potencial (convenção padrão do
            // projeto): negativo = compra abaixo do que poderia, má notícia.
            <em className={item.variacao >= 0 ? 'is-alta' : 'is-queda'}>
              {textoVariacao(item.variacao)} vs potencial
            </em>
          )}
        </div>
      </button>
    </li>
  );
}

/** Aba "Potencial de compra" da tela de Clientes: média dos 3 meses de maior
 *  receita de cada cliente na janela — capacidade no melhor momento, não o
 *  comportamento típico do dia a dia. Mesmo endpoint das outras abas
 *  (`obterPainelClientes`); o cache por chave evita um request duplicado. */
export function ClientesPotencialCompra({ empresa, loja = null, onCarregandoChange }: Props) {
  const [dados, setDados] = useState<PainelClientesResposta | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [clienteSelecionado, setClienteSelecionado] = useState<string | null>(null);
  const [modoPeriodo] = useMesesFechados();
  const versaoCortes = useVersaoCortesRelatorios();
  const gruposClientes = useGruposClientesFiltro();
  const gruposParam = gruposClientesParam(gruposClientes);

  useEffect(() => {
    onCarregandoChange?.(carregando);
  }, [carregando, onCarregandoChange]);

  useEffect(() => {
    let vivo = true;
    setCarregando(true);
    setErro(null);
    void obterPainelClientes(empresa, loja, undefined, modoPeriodo, gruposParam)
      .then((resposta) => {
        if (vivo) setDados(resposta);
      })
      .catch((falha) => {
        if (!vivo) return;
        setDados(null);
        setErro(falha instanceof Error ? falha.message : 'Falha ao carregar o potencial de compra.');
      })
      .finally(() => {
        if (vivo) setCarregando(false);
      });
    return () => {
      vivo = false;
    };
  }, [empresa, loja, modoPeriodo, versaoCortes, gruposParam]);

  const potencialCompra = dados?.potencial_compra;

  if (carregando && !dados) {
    return (
      <div className="glass-card vendedores-carregando" role="status">
        <Loader2 size={20} className="dashboard-filter-spinner" /> Calculando o potencial de compra…
      </div>
    );
  }

  if (erro) {
    return (
      <div className="glass-card glass-card-flat analisador-erro" role="alert">
        <AlertTriangle size={17} /> {erro}
      </div>
    );
  }

  if (!dados || !potencialCompra) return null;

  if (!dados.disponivel) {
    return (
      <div className="glass-card glass-card-flat clientes-vazio" role="status">
        <UsersRound size={24} aria-hidden="true" />
        <div>
          <strong>Sem dados para o painel</strong>
          <p>{dados.mensagem || 'A base desta empresa não tem período mensal utilizável.'}</p>
        </div>
      </div>
    );
  }

  const maiorPotencial = Math.max(1, ...potencialCompra.ranking.map((item) => item.potencial));

  return (
    <div className="clientes-visao">
      <section className="clientes-score-secao">
        <header className="clientes-visao-card-topo">
          <div>
            <h2>Potencial de compra</h2>
            <p>
              Média dos 3 meses de maior receita de cada cliente nos últimos{' '}
              {potencialCompra.janela_meses} meses — capacidade no melhor momento, não o comportamento típico.
            </p>
          </div>
        </header>

        {!potencialCompra.disponivel ? (
          <p className="analisador-hint">Histórico insuficiente para estimar o potencial de compra.</p>
        ) : (
          <>
            <div className="clientes-score-kpis">
              <StatCard
                title="Potencial da carteira"
                value={formatCompacto(potencialCompra.potencial_total, true)}
                icon={Target}
                trend={potencialCompra.variacao_total == null
                  ? undefined
                  : `${textoVariacao(potencialCompra.variacao_total)} vs atual ${formatCurrency(potencialCompra.atual_total)}/mês`}
                trendUp={(potencialCompra.variacao_total ?? 0) >= 0}
                useTrendColor={potencialCompra.variacao_total != null}
              />
              <StatCard
                title="Ticket potencial médio"
                value={formatCurrency(potencialCompra.potencial_medio)}
                icon={Wallet}
              />
            </div>

            <section className="glass-card glass-card-flat clientes-visao-card">
              <header className="clientes-visao-card-topo">
                <div>
                  <h2>Potencial por grupo ABC</h2>
                  <p>Mesmas faixas de Concentração da carteira, média de potencial por cliente do grupo.</p>
                </div>
              </header>
              {potencialCompra.por_grupo.length === 0 ? (
                <p className="analisador-hint">Sem receita na janela.</p>
              ) : (
                // Um cartão por grupo, sem barra: Grupo 1 (11 clientes) e "Demais"
                // (54 mil) têm médias de ordens de grandeza diferentes — uma
                // barra numa escala só deixava 3 dos 4 grupos indistinguíveis
                // entre si. Cada número aqui se lê sozinho, sem competir com os
                // outros por espaço na mesma régua.
                <div className="clientes-visao-tags-grade">
                  {potencialCompra.por_grupo.map((item, indice) => (
                    <article
                      key={item.nome}
                      className="clientes-tag-chip"
                      style={{ '--tag-cor': CORES_FAIXA[indice % CORES_FAIXA.length] } as CSSProperties}
                    >
                      <p className="clientes-tag-chip-topo">
                        <i aria-hidden="true" />
                        <span>{item.nome}</span>
                      </p>
                      <strong>{formatCurrency(item.potencial_medio)}</strong>
                      <small>{formatNumber(item.clientes)} clientes</small>
                    </article>
                  ))}
                </div>
              )}
            </section>

            <section className="glass-card glass-card-flat clientes-visao-card">
              <header className="clientes-visao-card-topo">
                <div>
                  <h2>Maiores potenciais de compra</h2>
                  <p>Até {formatNumber(potencialCompra.ranking.length)} clientes, do maior potencial para o menor.</p>
                </div>
              </header>
              {potencialCompra.ranking.length === 0 ? (
                <p className="analisador-hint">Sem receita na janela.</p>
              ) : (
                <ul className="clientes-eventos-lista custom-scrollbar">
                  {potencialCompra.ranking.map((item, indice) => (
                    <Fragment key={item.cliente}>
                      <LinhaPotencialCliente
                        item={item}
                        posicao={indice + 1}
                        maiorPotencial={maiorPotencial}
                        aberto={clienteSelecionado === item.cliente}
                        onAlternar={(cliente) => setClienteSelecionado((atual) => (atual === cliente ? null : cliente))}
                      />
                      {clienteSelecionado === item.cliente && (
                        <ClientePotencialDetalhe
                          empresa={empresa}
                          cliente={item.cliente}
                          loja={loja}
                          modoPeriodo={modoPeriodo}
                          grupos={gruposParam}
                        />
                      )}
                    </Fragment>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
      </section>
    </div>
  );
}
