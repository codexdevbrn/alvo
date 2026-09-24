import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Loader2, Search, Tags } from 'lucide-react';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import {
  obterAPrecificar,
  obterItemAPrecificar,
  type APrecificarResposta,
  type ItemAPrecificar,
  type ProvaPrecificar,
  type SemanaPrecoCusto,
} from '../../api/client';
import { formatCurrency, formatPercent } from '../../utils/formatters';

type Props = { empresa: string };

// Espelha `PROVAS` e os limites de `backend/a_precificar.py` — só para os rótulos.
const PROVAS: { id: ProvaPrecificar; rotulo: string }[] = [
  { id: 'margem', rotulo: 'margem caiu' },
  { id: 'custo', rotulo: 'custo sem repasse' },
  { id: 'volume', rotulo: 'volume caiu' },
  { id: 'alvo', rotulo: 'abaixo do alvo' },
];

const FABRICANTES_VISIVEIS = 6;

function pct(valor: number | null | undefined, casas = 1): string {
  return valor == null || !Number.isFinite(valor) ? '—' : formatPercent(valor, casas);
}

function sinal(valor: number | null | undefined, sufixo: '%' | 'pp' = '%'): string {
  if (valor == null || !Number.isFinite(valor)) return '—';
  const s = valor > 0 ? '+' : valor < 0 ? '−' : '';
  const abs = Math.abs(valor).toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return sufixo === 'pp' ? `${s}${abs} pp` : `${s}${abs}%`;
}

function moeda(valor: number | null | undefined): string {
  return valor == null || !Number.isFinite(valor) ? '—' : formatCurrency(valor);
}

function dataBr(iso: string | null | undefined): string {
  if (!iso) return '—';
  const [ano, mes, dia] = iso.split('-');
  return ano && mes && dia ? `${dia}/${mes}/${ano}` : iso;
}

function dataCurta(iso: string): string {
  const [, mes, dia] = iso.split('-');
  return `${dia}/${mes}`;
}

function normalizar(texto: string): string {
  return texto.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
}

/** O backend responde 404 com esta frase quando a empresa não tem o parquet do PRICE. */
function ehSemMovimentoPrice(erro: string | null): boolean {
  return !!erro && erro.toLowerCase().includes('ainda não tem movimento do price');
}

/** Tela Precificação: quais SKUs precisam de preço novo, a prova de cada um e
 *  quanto pesam na receita. Regras e janelas em `backend/a_precificar.py`. */
export function APrecificar({ empresa }: Props) {
  const [dados, setDados] = useState<APrecificarResposta | null>(null);
  const [resultado, setResultado] = useState<{ chave: string; erro: string | null } | null>(null);
  const [fabricante, setFabricante] = useState<string | null>(null);
  const [busca, setBusca] = useState('');
  const [selecionado, setSelecionado] = useState<string | null>(null);

  // Trocar de empresa remonta o componente (key na página), zerando filtros.
  const chave = empresa;
  const carregando = resultado?.chave !== chave;
  const erro = carregando ? null : resultado?.erro ?? null;

  useEffect(() => {
    const controle = new AbortController();
    obterAPrecificar(empresa, controle.signal)
      .then((resposta) => {
        setDados(resposta);
        setResultado({ chave, erro: null });
      })
      .catch((e: unknown) => {
        if (controle.signal.aborted) return;
        setResultado({ chave, erro: e instanceof Error ? e.message : 'Falha ao carregar os itens a precificar.' });
      });
    return () => controle.abort();
  }, [chave, empresa]);

  const itens = useMemo(() => {
    if (!dados) return [];
    const termo = normalizar(busca.trim());
    return dados.itens.filter((item) => {
      if (fabricante && item.fabricante !== fabricante) return false;
      if (!termo) return true;
      return normalizar(`${item.codigo} ${item.descricao} ${item.fabricante}`).includes(termo);
    });
  }, [dados, fabricante, busca]);

  // Sem clique, o painel mostra o primeiro da lista — o que mais pesa no filtro.
  const itemAtivo = itens.find((item) => item.codigo === selecionado) ?? itens[0] ?? null;

  if (erro && ehSemMovimentoPrice(erro)) {
    return (
      <div className="glass-card glass-card-flat estoque-vazio">
        <Tags size={24} aria-hidden="true" />
        <div>
          <strong>Empresa sem movimento do PRICE</strong>
          <p>A lista usa as vendas por SKU do PRICE, que esta empresa ainda não tem. Ela aparece assim que o CNPJ tiver movimento — a atualização é diária.</p>
        </div>
      </div>
    );
  }

  if (erro && !dados) {
    return (
      <div className="glass-card glass-card-flat estoque-vazio">
        <AlertTriangle size={24} aria-hidden="true" />
        <div>
          <strong>Não foi possível carregar os itens a precificar</strong>
          <p>{erro}</p>
        </div>
      </div>
    );
  }

  if (!dados) {
    return (
      <div className="glass-card glass-card-flat estoque-vazio">
        <Loader2 size={24} className="dashboard-filter-spinner" aria-hidden="true" />
        <div>
          <strong>Procurando o que precificar…</strong>
          <p>Comparando os últimos 30 dias com os 90 anteriores, SKU a SKU.</p>
        </div>
      </div>
    );
  }

  const { resumo, janela } = dados;
  const maxPerdido = Math.max(...dados.fabricantes.map((f) => f.perdido_dia ?? 0), 0);
  const fabricantesVisiveis = dados.fabricantes.slice(0, FABRICANTES_VISIVEIS);
  // Fabricante escolhido fora do top continua visível, senão o filtro some da tela.
  const escolhidoFora = fabricante && !fabricantesVisiveis.some((f) => f.nome === fabricante)
    ? dados.fabricantes.find((f) => f.nome === fabricante)
    : undefined;
  if (escolhidoFora) fabricantesVisiveis.push(escolhidoFora);

  return (
    <div className="prec-hist" aria-busy={carregando}>
      <div className="prec-indicadores">
        <Indicador
          rotulo="SKUs a precificar"
          valor={resumo.skus.toLocaleString('pt-BR')}
          detalhe={`${resumo.curva_a.toLocaleString('pt-BR')} curva A · ${resumo.fabricantes.toLocaleString('pt-BR')} fabricantes`}
          acento="var(--accent)"
        />
        <Indicador
          rotulo="Receita em jogo (90 dias)"
          valor={moeda(resumo.receita_em_jogo)}
          detalhe={`${pct(resumo.part_receita)} da receita da empresa`}
          acento="var(--text-muted)"
        />
        <Indicador
          rotulo="Lucro perdido por dia"
          valor={moeda(resumo.perdido_dia)}
          detalhe={`≈ ${moeda((resumo.perdido_dia ?? 0) * 30)} por mês até a referência`}
          acento="var(--danger)"
        />
        <Indicador
          rotulo="Custo sem repasse"
          valor={resumo.custo_sem_repasse.toLocaleString('pt-BR')}
          detalhe="SKUs com custo subindo mais que o preço"
          acento="var(--warning)"
        />
      </div>

      {dados.fabricantes.length > 0 && (
        <section className="glass-card glass-card-flat prec-card">
          <div className="prec-card-topo">
            <div>
              <h2>Onde está o dinheiro: fabricantes</h2>
              <p className="prec-mudo">
                Lucro por dia que os SKUs sinalizados deixam na mesa e quanto pesam na receita. Clique para filtrar.
              </p>
            </div>
            {fabricante && (
              <button type="button" className="prec-mudo" onClick={() => setFabricante(null)}>
                limpar filtro
              </button>
            )}
          </div>
          <div className="aprec-fabs">
            {fabricantesVisiveis.map((f) => (
              <button
                key={f.nome}
                type="button"
                aria-pressed={fabricante === f.nome}
                className={`aprec-fab${fabricante === f.nome ? ' is-ativo' : ''}`}
                onClick={() => {
                  setFabricante((atual) => (atual === f.nome ? null : f.nome));
                  setSelecionado(null);
                }}
              >
                <span className="aprec-fab-topo">
                  <span className="aprec-fab-nome">{f.nome}</span>
                  <b>− {moeda(f.perdido_dia)}/dia</b>
                </span>
                <span className="aprec-trilho">
                  <i style={{ width: `${maxPerdido > 0 ? ((f.perdido_dia ?? 0) / maxPerdido) * 100 : 0}%` }} />
                </span>
                <small>
                  {f.skus} SKU{f.skus === 1 ? '' : 's'} · {pct(f.part_receita, 2)} da receita
                </small>
              </button>
            ))}
          </div>
        </section>
      )}

      <div className="prec-corpo">
        <section className="glass-card glass-card-flat prec-card">
          <div className="prec-card-topo">
            <div>
              <h2>{fabricante ? `A precificar · ${fabricante}` : 'A precificar'}</h2>
              <p className="prec-mudo">
                {janela
                  ? `Margem, custo e volume de ${dataBr(janela.inicio_base)} a ${dataBr(janela.fim)}: os últimos 30 dias contra os 90 anteriores.`
                  : 'Sem movimento no período.'}
              </p>
            </div>
            <label className="prec-busca">
              <Search size={13} aria-hidden="true" />
              <input
                type="search"
                value={busca}
                onChange={(e) => setBusca(e.target.value)}
                placeholder="Código, descrição ou fabricante"
                aria-label="Buscar SKU"
              />
            </label>
          </div>
          <TabelaAPrecificar itens={itens} selecionado={itemAtivo?.codigo ?? null} onClicar={setSelecionado} />
          <p className="prec-mudo prec-rodape">
            Ordem = lucro por dia perdido até a referência × peso da curva (A 1 · B 0,6 · C 0,3) × quantidade de provas.
            Referência = alvo da última precificação do SKU; sem precificação, a margem dos 90 dias.
            {dados.total_itens > dados.itens.length &&
              ` Mostrando os ${dados.itens.length.toLocaleString('pt-BR')} primeiros de ${dados.total_itens.toLocaleString('pt-BR')}.`}
          </p>
        </section>

        <PainelItem empresa={empresa} item={itemAtivo} />
      </div>
    </div>
  );
}

function Indicador({ rotulo, valor, detalhe, acento }: { rotulo: string; valor: string; detalhe: string; acento: string }) {
  return (
    <div className="glass-card glass-card-flat prec-indicador" style={{ ['--prec-acento' as string]: acento }}>
      <span className="prec-rotulo">{rotulo}</span>
      <strong>{valor}</strong>
      <em>{detalhe}</em>
    </div>
  );
}

function BolasProvas({ provas }: { provas: ProvaPrecificar[] }) {
  const rotulo = PROVAS.filter((p) => provas.includes(p.id)).map((p) => p.rotulo).join(', ');
  return (
    <span className="aprec-provas" title={rotulo} aria-label={rotulo}>
      {PROVAS.map((p) => (
        <i key={p.id} className={provas.includes(p.id) ? `is-${p.id}` : undefined} />
      ))}
    </span>
  );
}

function TabelaAPrecificar({
  itens,
  selecionado,
  onClicar,
}: {
  itens: ItemAPrecificar[];
  selecionado: string | null;
  onClicar: (codigo: string) => void;
}) {
  if (itens.length === 0) return <p className="prec-vazio">Nenhum SKU a precificar neste filtro.</p>;
  return (
    <div className="prec-tabela-rolagem">
      <table className="prec-tabela">
        <thead>
          <tr>
            <th className="r">#</th>
            <th>SKU</th>
            <th>Curva</th>
            <th>Provas</th>
            <th className="r">Part. receita</th>
            <th className="r">Margem 90d → 30d</th>
            <th className="r">Gap</th>
            <th className="r">Custo × preço</th>
            <th className="r">Qtd / dia</th>
            <th className="r">Perdido / dia</th>
          </tr>
        </thead>
        <tbody>
          {itens.map((item, indice) => (
            <tr
              key={item.codigo}
              className={selecionado === item.codigo ? 'is-selecionada' : undefined}
              onClick={() => onClicar(item.codigo)}
            >
              <td className="r prec-mudo">{indice + 1}</td>
              <td>
                <span className="prec-nome">
                  {item.codigo}
                  <small>{item.descricao} · {item.fabricante}</small>
                </span>
              </td>
              <td><span className={`aprec-curva is-${item.curva}`}>{item.curva}</span></td>
              <td><BolasProvas provas={item.provas} /></td>
              <td className="r">{pct(item.part_receita, 2)}</td>
              <td className="r">
                {pct(item.margem_base)}<span className="prec-seta">→</span>{pct(item.margem_recente)}
              </td>
              <td className={`r${(item.gap ?? 0) < 0 ? ' is-queda' : ''}`}>{sinal(item.gap, 'pp')}</td>
              <td className="r">{sinal(item.var_custo)} × {sinal(item.var_preco)}</td>
              <td className={`r${(item.var_qtd ?? 0) < 0 ? ' is-queda' : ' is-alta'}`}>
                {item.var_qtd == null ? '—' : `${item.var_qtd < 0 ? '▼' : '▲'} ${pct(Math.abs(item.var_qtd))}`}
              </td>
              <td className="r is-queda">− {moeda(item.perdido_dia)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function textoProva(prova: ProvaPrecificar, item: ItemAPrecificar): string {
  switch (prova) {
    case 'margem':
      return `margem ${pct(item.margem_base)} → ${pct(item.margem_recente)} nos últimos 30 dias`;
    case 'custo':
      return `custo ${sinal(item.var_custo)}, preço ${sinal(item.var_preco)}`;
    case 'volume':
      return `qtd/dia ${sinal(item.var_qtd)} contra os 90 dias anteriores`;
    case 'alvo':
      return `margem ${pct(item.margem_recente)} contra alvo de ${pct(item.alvo)} (${dataBr(item.dia_alvo)})`;
  }
}

function PainelItem({ empresa, item }: { empresa: string; item: ItemAPrecificar | null }) {
  const chave = item ? `${empresa}|${item.codigo}` : null;
  const [resultado, setResultado] = useState<{ chave: string; semanas: SemanaPrecoCusto[]; erro: string | null } | null>(null);
  const atual = resultado && resultado.chave === chave ? resultado : null;
  const codigo = item?.codigo ?? null;

  useEffect(() => {
    if (chave == null || codigo == null) return;
    const controle = new AbortController();
    obterItemAPrecificar(empresa, codigo, controle.signal)
      .then((resposta) => setResultado({ chave, semanas: resposta.semanas, erro: null }))
      .catch((e: unknown) => {
        if (controle.signal.aborted) return;
        setResultado({ chave, semanas: [], erro: e instanceof Error ? e.message : 'Falha ao carregar a série.' });
      });
    return () => controle.abort();
  }, [chave, empresa, codigo]);

  if (!item) {
    return (
      <aside className="glass-card glass-card-flat prec-painel">
        <p className="prec-painel-vazio">Nenhum SKU a precificar neste filtro.</p>
      </aside>
    );
  }

  const ganho = item.perdido_dia;
  return (
    <aside className="glass-card glass-card-flat prec-painel" aria-label={`Detalhe de ${item.codigo}`}>
      <div>
        <span className="prec-rotulo">{item.fabricante} · curva {item.curva}</span>
        <h3>{item.codigo}</h3>
        <p className="prec-mudo">{item.descricao}</p>
      </div>

      <div>
        <span className="prec-rotulo">Preço × custo por semana</span>
        {atual == null ? (
          <p className="prec-vazio"><Loader2 size={14} className="dashboard-filter-spinner" aria-hidden="true" /> Carregando…</p>
        ) : atual.erro ? (
          <p className="prec-vazio">{atual.erro}</p>
        ) : (
          <GraficoPrecoCusto semanas={atual.semanas} />
        )}
      </div>

      <div>
        <span className="prec-rotulo">Provas</span>
        <ul className="aprec-prova-lista">
          {PROVAS.filter((p) => item.provas.includes(p.id)).map((p) => (
            <li key={p.id}>
              <span className={`aprec-tag is-${p.id}`}>{p.rotulo}</span>
              {textoProva(p.id, item)}
            </li>
          ))}
        </ul>
      </div>

      <div>
        <span className="prec-rotulo">Peso na receita</span>
        <dl className="aprec-dl">
          <div><dt>Receita 90 dias</dt><dd>{moeda(item.receita_base)}</dd></div>
          <div><dt>Da empresa</dt><dd>{pct(item.part_receita, 2)}</dd></div>
          <div><dt>Do fabricante {item.fabricante}</dt><dd>{pct(item.part_fabricante)}</dd></div>
        </dl>
      </div>

      <div>
        <span className="prec-rotulo">
          {item.alvo != null ? `Se precificar no alvo (${pct(item.referencia)})` : `Se voltar à margem de antes (${pct(item.referencia)})`}
        </span>
        <dl className="aprec-dl">
          <div><dt>Preço atual</dt><dd>{moeda(item.preco_atual)}</dd></div>
          <div><dt>Preço sugerido</dt><dd><strong>{moeda(item.preco_sugerido)}</strong></dd></div>
          <div><dt>Reajuste</dt><dd>{sinal(item.reajuste)}</dd></div>
          <div><dt>Lucro/dia a mais</dt><dd className="is-alta">▲ {moeda(ganho)}</dd></div>
        </dl>
        <p className="prec-mudo">Mesma quantidade dos últimos 30 dias; o reajuste pode mexer no volume.</p>
      </div>
    </aside>
  );
}

function GraficoPrecoCusto({ semanas }: { semanas: SemanaPrecoCusto[] }) {
  if (semanas.length === 0) return <p className="prec-vazio">Sem vendas nas últimas semanas.</p>;
  const pontos = semanas.map((s) => ({ ...s, rotulo: dataCurta(s.semana) }));
  return (
    <>
      <ResponsiveContainer width="100%" height={130}>
        <LineChart data={pontos} margin={{ top: 8, right: 6, left: 6, bottom: 0 }}>
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis
            dataKey="rotulo"
            tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            interval="preserveStartEnd"
            minTickGap={16}
          />
          <YAxis hide domain={['auto', 'auto']} />
          <Tooltip
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              const ponto = payload[0].payload as SemanaPrecoCusto;
              return (
                <div className="vendedores-chart-tooltip">
                  <strong>Semana de {label}</strong>
                  <dl>
                    <div><dt>Preço</dt><dd>{moeda(ponto.preco)}</dd></div>
                    <div><dt>Custo</dt><dd>{moeda(ponto.custo)}</dd></div>
                    <div><dt>Qtd</dt><dd>{ponto.qtd?.toLocaleString('pt-BR') ?? '—'}</dd></div>
                  </dl>
                </div>
              );
            }}
          />
          <Line type="monotone" dataKey="preco" stroke="var(--accent)" strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="custo" stroke="var(--danger)" strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
      <div className="prec-legenda">
        <span><i style={{ background: 'var(--accent)' }} />preço</span>
        <span><i style={{ background: 'var(--danger)' }} />custo</span>
      </div>
    </>
  );
}
