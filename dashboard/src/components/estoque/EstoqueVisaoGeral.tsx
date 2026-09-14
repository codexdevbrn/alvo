import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Boxes, Clock, Loader2, PackageX, Snowflake, TrendingDown } from 'lucide-react';
import { Cell, Label, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';
import { DonutFuro } from '../DonutFuro';
import { StatCard } from '../StatCard';
import { CORES_STATUS, ROTULOS_STATUS, classeStatus, numero, textoCobertura } from './estoqueStatus';
import {
  obterResumoEstoque,
  type ItemResumoEstoque,
  type ResumoEstoqueResposta,
  type StatusCoberturaEstoque,
} from '../../api/client';
import { formatCurrency, formatPercent } from '../../utils/formatters';
import { useMesesFechados } from '../../hooks/useMesesFechados';
import { modoParaBooleano } from '../../utils/mesesFechados';

type Props = {
  empresa: string;
  loja: string | null;
  meses: number;
};

type FatiaSituacao = {
  status: StatusCoberturaEstoque;
  nome: string;
  cor: string;
  produtos: number;
  valor: number;
  participacao: number;
};

/** Tooltip do donut: o Recharts entrega o payload cru, e o card precisa do R$. */
function TooltipSituacao({ active, payload }: { active?: boolean; payload?: { payload: FatiaSituacao }[] }) {
  if (!active || !payload?.length) return null;
  const fatia = payload[0].payload;
  return (
    <div className="vendedores-chart-tooltip">
      <strong>{fatia.nome}</strong>
      <dl>
        <div><dt>Capital</dt><dd>{formatCurrency(fatia.valor)}</dd></div>
        <div><dt>Produtos</dt><dd>{numero(fatia.produtos)}</dd></div>
        <div><dt>Participação</dt><dd>{formatPercent(fatia.participacao, 1)}</dd></div>
      </dl>
    </div>
  );
}

/** "parado há 4 meses" / "nunca vendeu" — nulo não pode virar zero na tela. */
function textoParado(meses: number | null): string {
  if (meses == null) return 'nunca vendeu';
  if (meses <= 0) return 'vendeu no último mês';
  return `parado há ${numero(meses)} ${meses === 1 ? 'mês' : 'meses'}`;
}

function ListaProdutos({ itens, vazio, detalhe }: {
  itens: ItemResumoEstoque[];
  vazio: string;
  detalhe: (item: ItemResumoEstoque) => string;
}) {
  if (itens.length === 0) return <p className="analisador-hint">{vazio}</p>;
  return (
    <ul className="estoque-lista custom-scrollbar">
      {itens.map((item) => (
        <li key={`${item.codigo_interno}-${item.sku}`}>
          <div className="estoque-lista-nome">
            <strong title={item.nome}>{item.nome}</strong>
            <span>{item.fabricante} · {detalhe(item)}</span>
          </div>
          <span className={`estoque-status ${classeStatus(item.status)}`}>{ROTULOS_STATUS[item.status]}</span>
          <em>{formatCurrency(item.valor_estoque)}</em>
        </li>
      ))}
    </ul>
  );
}

/** Aba Visão geral: para onde o dinheiro do estoque foi e o que trava primeiro.
 *  Números vêm agregados da base inteira, não do recorte do mapa. */
export function EstoqueVisaoGeral({ empresa, loja, meses }: Props) {
  const [dados, setDados] = useState<ResumoEstoqueResposta | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [modoPeriodo] = useMesesFechados();
  const usarMesesFechados = modoParaBooleano(modoPeriodo);

  useEffect(() => {
    let vivo = true;
    setCarregando(true);
    setErro(null);
    void obterResumoEstoque(empresa, { loja, meses, usarMesesFechados })
      .then((resposta) => {
        if (vivo) setDados(resposta);
      })
      .catch((falha) => {
        if (!vivo) return;
        setDados(null);
        setErro(falha instanceof Error ? falha.message : 'Falha ao carregar o resumo de estoque.');
      })
      .finally(() => {
        if (vivo) setCarregando(false);
      });
    return () => {
      vivo = false;
    };
  }, [empresa, loja, meses, usarMesesFechados]);

  const fatias = useMemo<FatiaSituacao[]>(() => {
    const total = dados?.resumo.valor_estoque ?? 0;
    return (dados?.por_situacao ?? [])
      .filter((item) => item.valor_estoque > 0)
      .map((item) => ({
        status: item.status,
        nome: ROTULOS_STATUS[item.status] ?? item.status,
        cor: CORES_STATUS[item.status] ?? 'var(--text-muted)',
        produtos: item.produtos,
        valor: item.valor_estoque,
        participacao: total > 0 ? (item.valor_estoque / total) * 100 : 0,
      }));
  }, [dados]);

  const maiorFabricante = dados?.capital_parado_fabricante[0]?.valor_estoque ?? 0;

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
        <Loader2 size={20} className="dashboard-filter-spinner" /> Somando capital em estoque…
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

  const { resumo } = dados;
  const parte_parada = resumo.valor_estoque > 0 ? (resumo.valor_parado / resumo.valor_estoque) * 100 : 0;
  const periodo = dados.periodo_inicio && dados.periodo_fim
    ? `${dados.periodo_inicio} a ${dados.periodo_fim}`
    : 'sem histórico de vendas';

  return (
    <div className="estoque-visao">
      <p className="estoque-visao-referencia">
        Venda média de <strong>{periodo}</strong> · {numero(resumo.produtos)} produtos em estoque.
      </p>

      <section className="estoque-visao-kpis" aria-label="Indicadores de estoque">
        <StatCard
          title="Capital em estoque"
          value={formatCurrency(resumo.valor_estoque)}
          icon={Boxes}
        />
        <StatCard
          title="Capital parado"
          value={formatCurrency(resumo.valor_parado)}
          icon={Snowflake}
          trend={`${formatPercent(parte_parada, 1)} do estoque · excesso e sem giro`}
          trendUp={false}
          useTrendColor
        />
        <StatCard
          title="Risco de ruptura"
          value={numero(resumo.ruptura)}
          icon={PackageX}
          trend="produtos sem cobertura para o mês"
          trendUp={false}
          useTrendColor
        />
        <StatCard
          title="Cobertura média"
          value={resumo.cobertura_media == null ? '—' : `${numero(resumo.cobertura_media, 1)} meses`}
          icon={Clock}
          trend="capital ÷ saída mensal, a custo"
        />
      </section>

      <div className="estoque-visao-grade">
        <section className="glass-card glass-card-flat estoque-visao-card">
          <header className="estoque-card-topo">
            <div>
              <h2>Capital por situação</h2>
              <p>Onde o dinheiro do estoque está hoje.</p>
            </div>
            <span className="estoque-card-nota">{numero(resumo.produtos)} produtos</span>
          </header>
          {fatias.length === 0 ? (
            <p className="analisador-hint">Sem capital em estoque nesta seleção.</p>
          ) : (
            <div className="donut-linha">
              <div className="donut">
                <ResponsiveContainer width="100%" height={168}>
                  <PieChart>
                    <Pie
                      data={fatias}
                      dataKey="valor"
                      nameKey="nome"
                      cx="50%"
                      cy="50%"
                      innerRadius={52}
                      outerRadius={78}
                      paddingAngle={2}
                      stroke="var(--bg-card)"
                      strokeWidth={2}
                    >
                      {fatias.map((fatia) => <Cell key={fatia.status} fill={fatia.cor} />)}
                    </Pie>
                    <Label
                      content={(props) => (
                        <DonutFuro
                          valor={formatPercent(parte_parada, 0)}
                          legenda="está parado"
                          viewBox={props.viewBox as { cx?: number; cy?: number } | undefined}
                        />
                      )}
                    />
                    <Tooltip content={<TooltipSituacao />} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <ul className="donut-legenda">
                {fatias.map((fatia) => (
                  <li key={fatia.status}>
                    <i style={{ background: fatia.cor }} aria-hidden="true" />
                    <span>{fatia.nome}</span>
                    <strong>{numero(fatia.produtos)}</strong>
                    <em>{formatPercent(fatia.participacao, 1)}</em>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>

        <section className="glass-card glass-card-flat estoque-visao-card">
          <header className="estoque-card-topo">
            <div>
              <h2>Para de vender primeiro</h2>
              <p>Sem cobertura para o mês, ordenado por quem mais sai.</p>
            </div>
            <span className="estoque-card-nota">{numero(resumo.ruptura)} em risco</span>
          </header>
          <ListaProdutos
            itens={dados.ruptura_iminente}
            vazio="Nenhum produto em risco de ruptura nesta seleção."
            detalhe={(item) => `${numero(item.venda_media, 1)}/mês · ${numero(item.estoque)} em estoque`}
          />
        </section>

        <section className="glass-card glass-card-flat estoque-visao-card">
          <header className="estoque-card-topo">
            <div>
              <h2>Capital parado por fabricante</h2>
              <p>Excesso e sem giro somados, os 10 maiores.</p>
            </div>
            <span className="estoque-card-nota">{formatCurrency(resumo.valor_parado)}</span>
          </header>
          {dados.capital_parado_fabricante.length === 0 ? (
            <p className="analisador-hint">Nenhum capital parado nesta seleção.</p>
          ) : (
            <ul className="estoque-barras">
              {dados.capital_parado_fabricante.map((linha) => (
                <li key={linha.fabricante}>
                  <span title={linha.fabricante}>{linha.fabricante}</span>
                  <i aria-hidden="true">
                    <b style={{ width: `${maiorFabricante > 0 ? (linha.valor_estoque / maiorFabricante) * 100 : 0}%` }} />
                  </i>
                  <strong>{formatCurrency(linha.valor_estoque)}</strong>
                  <em>{numero(linha.produtos)} itens</em>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="glass-card glass-card-flat estoque-visao-card">
          <header className="estoque-card-topo">
            <div>
              <h2>Dinheiro dormindo</h2>
              <p>Maior capital em excesso ou sem giro, item a item.</p>
            </div>
            <span className="estoque-card-nota"><TrendingDown size={14} aria-hidden="true" /> {numero(resumo.excesso + resumo.sem_giro)} produtos</span>
          </header>
          <ListaProdutos
            itens={dados.dinheiro_dormindo}
            vazio="Nenhum item parado nesta seleção."
            detalhe={(item) => `${textoCobertura(item.cobertura)} de cobertura · ${textoParado(item.meses_sem_venda)}`}
          />
        </section>
      </div>
    </div>
  );
}
