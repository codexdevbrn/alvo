import type { GpsPar, RecomendacaoGps, ResumoGps } from '../../api/client';
import { RECOMENDACOES_GPS, faixaTexto, pp } from './gps';
import { formatCurrency, formatPercent } from '../../utils/formatters';

/** GPS (aba Dispersão do Power BI) na tela A precificar: perfil da empresa,
 *  para onde o GPS manda cada par e a régua da distância no painel.
 *  Regras em `backend/gps_dispersao.py`; só as 36 descrições da tabela 2D têm GPS. */

const PERFIS: { id: string; rotulo: string; faixa: string }[] = [
  { id: 'muito_conservador', rotulo: 'Muito cons.', faixa: '≤ 1%' },
  { id: 'conservador', rotulo: 'Conservador', faixa: '1–3,5%' },
  { id: 'moderado', rotulo: 'Moderado', faixa: '3,5–5,5%' },
  { id: 'agressivo', rotulo: 'Agressivo', faixa: '5,5–7,5%' },
  { id: 'muito_agressivo', rotulo: 'Muito agr.', faixa: '> 7,5%' },
];

const ROTULO_PERFIL: Record<string, string> = {
  muito_conservador: 'Muito Conservador',
  conservador: 'Conservador',
  moderado: 'Moderado',
  agressivo: 'Agressivo',
  muito_agressivo: 'Muito Agressivo',
};

const CLASSE: Record<GpsPar['classe'], string> = { abaixo: 'Abaixo', dentro: 'Dentro', acima: 'Acima' };

const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

function rotuloMeses(meses: string[]): string {
  if (meses.length === 0) return '';
  const nome = (iso: string) => MESES[Number(iso.slice(5, 7)) - 1] ?? iso;
  const ultimo = meses[meses.length - 1];
  return `${nome(meses[0])}–${nome(ultimo)}/${ultimo.slice(2, 4)}`;
}

function pct(valor: number | null | undefined, casas = 2): string {
  return valor == null || !Number.isFinite(valor) ? '—' : formatPercent(valor, casas);
}

function moeda(valor: number | null | undefined): string {
  return valor == null || !Number.isFinite(valor) ? '—' : formatCurrency(valor);
}

export function BadgeGps({ recomendacao }: { recomendacao: RecomendacaoGps }) {
  const info = RECOMENDACOES_GPS[recomendacao];
  return (
    <span className={`aprec-gps-badge is-${recomendacao}`} title={info.ajuda}>
      {info.rotulo}
    </span>
  );
}

type Props = {
  gps: ResumoGps;
  recomendacao: RecomendacaoGps | null;
  onEscolher: (recomendacao: RecomendacaoGps | null) => void;
};

export function SecaoGps({ gps, recomendacao, onEscolher }: Props) {
  if (!gps.disponivel) {
    return (
      <section className="glass-card glass-card-flat prec-card aprec-gps-indisponivel">
        <span className="prec-rotulo aprec-gps-rotulo">GPS · dispersão 2D</span>
        <p className="prec-mudo">{gps.motivo}</p>
      </section>
    );
  }
  const { perfil } = gps;
  const totalProdutos = gps.recomendacoes.reduce((soma, r) => soma + r.produtos, 0);
  const totalPerdido = gps.recomendacoes.reduce((soma, r) => soma + (r.perdido_dia ?? 0), 0);
  // Barra pelo lucro em jogo; sem lucro nenhum (tudo só do GPS), pela quantidade de produtos.
  const peso = (r: { produtos: number; perdido_dia: number | null }) =>
    totalPerdido > 0 ? (r.perdido_dia ?? 0) / totalPerdido : totalProdutos > 0 ? r.produtos / totalProdutos : 0;
  const direcoes = (['subir', 'descer', 'manter'] as const).map((direcao) => {
    const itens = gps.recomendacoes.filter((r) => r.direcao === direcao);
    return {
      direcao,
      itens,
      produtos: itens.reduce((s, r) => s + r.produtos, 0),
      perdido: itens.reduce((s, r) => s + (r.perdido_dia ?? 0), 0),
    };
  });
  const cabecalho = { subir: '▲ Subir', descer: '▼ Descer', manter: '● Manter' } as const;

  return (
    <div className="aprec-gps">
      <section className="glass-card glass-card-flat prec-card aprec-gps-perfil">
        <span className="prec-rotulo aprec-gps-rotulo">GPS · perfil da empresa · {rotuloMeses(perfil.meses)}</span>
        <div className="aprec-gps-contas">
          <span>Margem %<b>{pct(perfil.margem)}</b></span>
          <span>− Despesas %<b>{pct(perfil.despesas)}</b></span>
          <span>= Taxa de Retorno<b>{pct(perfil.taxa_retorno)}</b></span>
        </div>
        <div className="aprec-gps-escala" role="list" aria-label={`Perfil ${perfil.rotulo}`}>
          {PERFIS.map((p) => (
            <span
              key={p.id}
              role="listitem"
              className={p.id === perfil.perfil ? 'is-ativo' : undefined}
              title={`${ROTULO_PERFIL[p.id]}: Taxa de Retorno ${p.faixa}`}
            >
              <b>{p.faixa}</b>
              <small>{p.rotulo}</small>
            </span>
          ))}
        </div>
        <p className="prec-mudo">
          Sempre os 3 últimos meses fechados; o perfil é recalculado na virada do mês. Despesa = Controladoria sem Mercadoria Revenda.
        </p>
      </section>

      <section className="glass-card glass-card-flat prec-card aprec-gps-direcoes">
        <div className="aprec-gps-topo">
          <span className="prec-rotulo">
            Para onde o GPS manda · {totalProdutos.toLocaleString('pt-BR')} produtos da tabela 2D
            {gps.cobertura_receita != null && ` (${pct(gps.cobertura_receita, 0)} da receita)`}
          </span>
          <span className="aprec-gps-total">{moeda(totalPerdido)}/dia em jogo</span>
        </div>
        <div className="aprec-gps-barra" aria-hidden="true">
          {gps.recomendacoes.filter((r) => r.produtos > 0).map((r) => (
            <i key={r.id} className={`is-${r.id}`} style={{ width: `${peso(r) * 100}%` }} title={r.rotulo} />
          ))}
        </div>
        <div className="aprec-gps-colunas">
          {direcoes.map((d) => (
            <div key={d.direcao} className="aprec-gps-coluna">
              <div className="aprec-gps-coluna-topo">
                <b className={`is-${d.direcao}`}>{cabecalho[d.direcao]}</b>
                <span>
                  {d.produtos.toLocaleString('pt-BR')} produtos · <strong>{moeda(d.perdido)}/dia</strong>
                </span>
              </div>
              {d.itens.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  aria-pressed={recomendacao === r.id}
                  className={`aprec-gps-linha${recomendacao === r.id ? ' is-ativo' : ''}`}
                  title={RECOMENDACOES_GPS[r.id].ajuda}
                  disabled={r.produtos === 0}
                  onClick={() => onEscolher(recomendacao === r.id ? null : r.id)}
                >
                  <i className={`is-${r.id}`} />
                  <span>{r.rotulo}</span>
                  <em>{r.produtos.toLocaleString('pt-BR')}</em>
                  <strong>{moeda(r.perdido_dia)}</strong>
                </button>
              ))}
            </div>
          ))}
        </div>
        <p className="prec-mudo">
          Calculado por produto (descrição); lucro/dia = o que o A precificar diz que fica na mesa nesses produtos. Clique para filtrar a lista.
          {gps.produtos_fora > 0 &&
            ` ${gps.produtos_fora.toLocaleString('pt-BR')} produtos sinalizados estão fora das 36 descrições da tabela 2D e seguem só com as provas.`}
        </p>
      </section>
    </div>
  );
}

/** Régua do painel: dispersão hoje, depois desta rodada e a faixa do perfil. */
function Regua({ gps }: { gps: GpsPar }) {
  const [minimo, maximo] = gps.faixa;
  const hoje = gps.dispersao;
  if (hoje == null || maximo == null) return null;
  const depois = hoje + (gps.ajuste_agora ?? 0);
  const inicioFaixa = minimo ?? maximo - Math.max(gps.teto ?? 1, 1);
  const pontos = [hoje, depois, inicioFaixa, maximo];
  const lo = Math.min(...pontos);
  const hi = Math.max(...pontos);
  const margem = Math.max((hi - lo) * 0.12, 0.5);
  const a = lo - margem;
  const b = hi + margem;
  const x = (v: number) => `${((v - a) / (b - a)) * 100}%`;
  const mexe = Math.abs(depois - hoje) > 0.001;
  return (
    <div className="aprec-gps-regua" aria-hidden="true">
      <div className="aprec-gps-regua-trilho" />
      <div className="aprec-gps-regua-faixa" style={{ left: x(inicioFaixa), width: `calc(${x(maximo)} - ${x(inicioFaixa)})` }} />
      {mexe && (
        <div
          className="aprec-gps-regua-passo"
          style={{ left: x(Math.min(hoje, depois)), width: `calc(${x(Math.max(hoje, depois))} - ${x(Math.min(hoje, depois))})` }}
        />
      )}
      <span className="aprec-gps-regua-ponto is-hoje" style={{ left: x(hoje) }} />
      {mexe && <span className="aprec-gps-regua-ponto is-depois" style={{ left: x(depois) }} />}
      <small className="is-cima" style={{ left: x(hoje) }}>hoje {pp(hoje)}</small>
      {mexe && <small style={{ left: x(depois) }}>rodada {pp(depois)}</small>}
      {gps.limite_alvo != null && <small className="is-cima" style={{ left: x(gps.limite_alvo) }}>alvo {pp(gps.limite_alvo)}</small>}
    </div>
  );
}

export function BlocoGpsPainel({ gps, perfil }: { gps: GpsPar; perfil: string | null }) {
  const cortado = gps.distancia != null && gps.aplicado != null && Math.abs(gps.distancia) - Math.abs(gps.aplicado) > 0.005;
  const rodadas = gps.distancia != null && gps.teto != null && gps.teto > 0 && gps.distancia !== 0
    ? Math.ceil(Math.abs(gps.distancia) / gps.teto - 1e-9)
    : null;
  const info = RECOMENDACOES_GPS[gps.recomendacao];
  return (
    <div className="aprec-gps-painel">
      <span className="prec-rotulo aprec-gps-rotulo">GPS · distância da posição correta</span>
      <Regua gps={gps} />
      <dl className="aprec-dl">
        <div><dt>Participação</dt><dd>{pct(gps.participacao)} · {CLASSE[gps.classe]} da Média</dd></div>
        <div><dt>Dispersão (margem − geral)</dt><dd>{pp(gps.dispersao)}</dd></div>
        <div><dt>Preço hoje no perfil</dt><dd>{gps.perfil_item ? ROTULO_PERFIL[gps.perfil_item] : 'fora das faixas'}</dd></div>
        <div><dt>Faixa {perfil ?? ''}</dt><dd>{faixaTexto(gps.faixa)}</dd></div>
        <div><dt>Regra</dt><dd>{gps.regra}{gps.limite_alvo != null ? ` = ${pp(gps.limite_alvo)}` : ''}</dd></div>
        <div><dt>Distância</dt><dd>{pp(gps.distancia)}</dd></div>
        <div><dt>Teto (um degrau)</dt><dd>{pp(gps.teto, false)}</dd></div>
        <div>
          <dt>Ajuste do GPS</dt>
          <dd className={(gps.aplicado ?? 0) > 0 ? 'is-alta' : (gps.aplicado ?? 0) < 0 ? 'is-queda' : undefined}>
            {pp(gps.aplicado)}{cortado ? ' (cortado)' : ''}
          </dd>
        </div>
        {rodadas != null && rodadas > 1 && <div><dt>Rodadas até a posição</dt><dd>≈ {rodadas}</dd></div>}
      </dl>
      <div className={`aprec-gps-decisao is-${info.direcao}`}>
        <BadgeGps recomendacao={gps.recomendacao} />
        <strong>
          {gps.ajuste_agora ? `${pp(gps.ajuste_agora)} pp de margem agora` : 'Sem mudar a margem agora'}
          {gps.margem_alvo != null && gps.ajuste_agora ? ` → ${pct(gps.margem_alvo)}` : ''}
        </strong>
        <span>{info.ajuda}</span>
      </div>
    </div>
  );
}
