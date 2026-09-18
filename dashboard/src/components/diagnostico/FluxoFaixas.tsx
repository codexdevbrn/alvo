import { useMemo, useRef, useState } from 'react';
import { Sankey, ResponsiveContainer } from 'recharts';
import type { FluxoFaixasDiagnostico } from '../../api/client';
import { formatCurrency, formatNumber } from '../../utils/formatters';

interface Props {
  fluxo: FluxoFaixasDiagnostico;
}

interface NoFaixa {
  name: string;
}

interface LigacaoFaixa {
  source: number;
  target: number;
  value: number;
  clientes: number;
  receita: number | null;
  passo: number;
  pctOrigem: number | null;
  mesmaFaixa: boolean;
  comprimido: boolean;
}

interface NoSankeyProps {
  x: number;
  y: number;
  width: number;
  height: number;
  payload: NoFaixa & { depth: number };
}

interface LigacaoSankeyProps {
  sourceX: number;
  sourceY: number;
  sourceControlX: number;
  targetX: number;
  targetY: number;
  targetControlX: number;
  linkWidth: number;
  index: number;
  payload: LigacaoFaixa;
}

function corPasso(passo: number) {
  if (passo > 0) return 'var(--success)';
  if (passo < 0) return 'var(--danger)';
  return 'var(--border-strong)';
}

function fraseFluxo(origem: string, destino: string, passo: number) {
  if (origem === destino) return `permaneceram em ${origem}`;
  if (passo > 0) return `subiram de ${origem} para ${destino}`;
  return `desceram de ${origem} para ${destino}`;
}

function NoSankey({ x, y, width, height, payload }: NoSankeyProps) {
  const direita = payload.depth > 0;
  return (
    <g>
      <rect x={x} y={y} width={width} height={Math.max(height, 1)} rx={2} fill="var(--surface-4)" />
      <text
        x={direita ? x + width + 8 : x - 8}
        y={y + height / 2}
        dy="0.35em"
        textAnchor={direita ? 'start' : 'end'}
        fontSize={11}
        fill="var(--text-secondary)"
      >
        {payload.name}
      </text>
    </g>
  );
}

/** Traço desenhado mais fino que a espessura calculada — cria um "gap"
 *  visual entre bandas adjacentes em vez de uma parede sólida de cor. A
 *  faixa fantasma (hit area) mantém a largura real, só o visual afina. */
const FATOR_AFINAR = 0.62;

/** Fábrica em vez de componente direto: o Recharts chama `link` como uma
 *  função pura a cada render (não monta como componente React de verdade),
 *  então fechar sobre `hoverIndex` aqui é a forma mais simples de destacar a
 *  banda ativa sem precisar de um Context só para isso. */
function criarLigacaoSankey(hoverIndex: number | null) {
  return function LigacaoSankey(props: LigacaoSankeyProps) {
    const { sourceX, sourceY, sourceControlX, targetX, targetY, targetControlX, linkWidth, index, payload: ligacao } = props;
    const d = `M${sourceX},${sourceY} C${sourceControlX},${sourceY} ${targetControlX},${targetY} ${targetX},${targetY}`;
    const espessuraReal = Math.max(linkWidth, 1);
    const ativo = index === hoverIndex;
    const outraEmFoco = hoverIndex != null && !ativo;
    const espessuraVisual = ativo ? espessuraReal * 1.08 : espessuraReal * FATOR_AFINAR;
    const opacidadeBase = ligacao.mesmaFaixa ? 0.7 : 0.55;
    const opacidade = ativo ? 0.95 : outraEmFoco ? opacidadeBase * 0.3 : opacidadeBase;
    return (
      <>
        {/* Faixa fantasma: só aumenta a área de hover (o hit-test de um path
            `fill="none"` é o traço do stroke, e a faixa visível às vezes some
            num traço de 1-2px) — invisível, não entra no visual.
            `stroke-opacity: 0` por si só faz o navegador tratar a área como
            "não pintada" e ignorar o mouse (pointer-events: auto só reage a
            área pintada) — por isso `pointerEvents: 'stroke'` explícito, que
            testa a geometria do traço e ignora a opacidade. */}
        <path
          d={d}
          fill="none"
          stroke="#000"
          strokeOpacity={0}
          strokeWidth={Math.max(linkWidth, 16)}
          style={{ pointerEvents: 'stroke', cursor: 'pointer' }}
        />
        <path
          d={d}
          fill="none"
          stroke={corPasso(ligacao.passo)}
          strokeWidth={espessuraVisual}
          strokeOpacity={opacidade}
          strokeDasharray={ligacao.comprimido ? '2 3' : undefined}
          style={{ pointerEvents: 'none', transition: 'stroke-width 120ms ease, stroke-opacity 120ms ease' }}
        />
      </>
    );
  };
}

interface HoverLigacao {
  x: number;
  y: number;
  indice: number;
  ligacao: LigacaoFaixa & { source: NoFaixa; target: NoFaixa };
}

function ConteudoTooltip({ ligacao }: { ligacao: HoverLigacao['ligacao'] }) {
  return (
    <>
      <strong>{formatNumber(ligacao.clientes)} cliente(s) {fraseFluxo(ligacao.source.name, ligacao.target.name, ligacao.passo)}</strong>
      <dl>
        <div><dt>Receita</dt><dd>{formatCurrency(ligacao.receita ?? 0)}</dd></div>
        {ligacao.pctOrigem != null && (
          <div><dt>Do grupo de origem</dt><dd>{ligacao.pctOrigem.toFixed(0)}%</dd></div>
        )}
      </dl>
    </>
  );
}

/** ATO II: para onde foram os clientes entre um trimestre móvel e o anterior —
 *  aluvial porque a pergunta é fluxo de PESSOAS entre faixas, não só o saldo
 *  final de cada uma. Barra (Cascata/Tornado) mostra o efeito em R$; aqui a
 *  mesma migração aparece em contagem de clientes, por isso a espessura da
 *  banda usa `clientes`, não `receita`.
 *
 *  Cor da banda repete a semântica de Cascata/Tornado (verde subiu, vermelho
 *  desceu), sempre com a direção escrita no tooltip — cor sozinha não carrega
 *  a informação. */
export function FluxoFaixas({ fluxo }: Props) {
  const [hover, setHover] = useState<HoverLigacao | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const { nodes, links, pisoAplicado, fatorCompressao } = useMemo(() => {
    if (!fluxo.disponivel || fluxo.faixas.length === 0) {
      return { nodes: [] as NoFaixa[], links: [] as LigacaoFaixa[], pisoAplicado: false, fatorCompressao: 1 };
    }
    const faixas = fluxo.faixas;
    const fluxosComClientes = fluxo.fluxos.filter((item) => item.clientes > 0);
    const maiorFluxo = Math.max(1, ...fluxosComClientes.map((item) => item.clientes));
    const piso = Math.max(1, Math.round(maiorFluxo * 0.04));
    const totalPorOrigem = new Map<string, number>();
    fluxosComClientes.forEach((item) => {
      totalPorOrigem.set(item.de, (totalPorOrigem.get(item.de) ?? 0) + item.clientes);
    });

    // Quem manteve a mesma faixa é, disparado, a maior massa de clientes —
    // mas é o dado menos interessante pra ação (não mudou nada). Sem
    // comprimir, essas bandas dominam quase toda a altura do gráfico e
    // espremem as migrações reais (Grupo->Grupo) em traços de 1-2px no topo.
    // Fator único aplicado a TODAS as bandas "mesma faixa" — preserva a
    // proporção relativa entre elas, só reduz a escala geral desse grupo até
    // que ele não passe de 1,2x o total das migrações reais.
    const totalCruzamento = fluxosComClientes
      .filter((item) => item.de !== item.para)
      .reduce((acc, item) => acc + item.clientes, 0);
    const totalMesmaFaixa = fluxosComClientes
      .filter((item) => item.de === item.para)
      .reduce((acc, item) => acc + item.clientes, 0);
    const fator = totalMesmaFaixa > 0 && totalCruzamento > 0
      ? Math.min(1, (totalCruzamento * 1.2) / totalMesmaFaixa)
      : 1;

    let algumPiso = false;
    const ligacoes: LigacaoFaixa[] = [];
    fluxosComClientes.forEach((item) => {
      const origem = faixas.indexOf(item.de);
      const destino = faixas.indexOf(item.para);
      if (origem === -1 || destino === -1) return;
      const mesmaFaixa = item.de === item.para;
      const valorEscalado = mesmaFaixa ? item.clientes * fator : item.clientes;
      const valor = Math.max(valorEscalado, piso);
      if (valor > item.clientes) algumPiso = true;
      const totalOrigem = totalPorOrigem.get(item.de) ?? 0;
      ligacoes.push({
        source: origem,
        target: faixas.length + destino,
        value: valor,
        clientes: item.clientes,
        receita: item.receita,
        passo: item.passo,
        pctOrigem: totalOrigem > 0 ? (item.clientes / totalOrigem) * 100 : null,
        mesmaFaixa,
        comprimido: mesmaFaixa && fator < 1,
      });
    });
    const nos: NoFaixa[] = [...faixas.map((nome) => ({ name: nome })), ...faixas.map((nome) => ({ name: nome }))];
    return { nodes: nos, links: ligacoes, pisoAplicado: algumPiso, fatorCompressao: fator };
  }, [fluxo]);

  if (!fluxo.disponivel) {
    return <p className="analisador-hint">{fluxo.mensagem || 'Sem trimestre anterior para comparar.'}</p>;
  }
  if (links.length === 0) {
    return <p className="analisador-hint">Sem migração de clientes entre faixas nesse período.</p>;
  }

  const resumo = fluxo.resumo;
  const titulo = resumo
    ? `${resumo.desceram} cliente(s) desceram de faixa · ${resumo.subiram} subiram`
    : 'Migração de clientes entre faixas ABC';

  // O <Tooltip> do Recharts não funciona pra Sankey nesta versão (3.6.0): o
  // dispatch do hover roda, mas o componente Tooltip nunca lê o estado ativo
  // — bug de integração confirmado por teste isolado, não uma regressão
  // nossa. Tooltip próprio, via os mesmos onMouseEnter/onMouseLeave que o
  // <Sankey> já expõe (e que o teste confirmou disparando).
  //
  // Posição em coordenadas RELATIVAS ao container (não `clientX/Y` direto
  // com `position: fixed`) porque `.app-shell-main` tem `will-change:
  // transform` — isso cria um novo containing block pra `fixed` em qualquer
  // descendente, e o tooltip aparecia longe do cursor.
  const aoEntrarLigacao = (item: unknown, tipo: string, e: { clientX: number; clientY: number }) => {
    if (tipo !== 'link') return;
    const item2 = item as { index?: number; payload?: LigacaoFaixa & { source?: NoFaixa; target?: NoFaixa } };
    const payload = item2?.payload;
    if (!payload?.source || !payload?.target || item2.index == null) return;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setHover({ x: e.clientX - rect.left, y: e.clientY - rect.top, indice: item2.index, ligacao: payload as HoverLigacao['ligacao'] });
  };
  const aoSairLigacao = () => setHover(null);

  return (
    <section className="glass-card glass-card-flat clientes-visao-card">
      <header className="clientes-visao-card-topo">
        <div>
          <h2>{titulo}</h2>
          <p>
            {resumo ? `${resumo.mantiveram} mantiveram a faixa. ` : ''}
            Só clientes que compraram nos dois trimestres migram — quem entrou ou saiu fica fora da banda.
          </p>
        </div>
        <span className="diagnostico-base-chip">{fluxo.rotulo_anterior} → {fluxo.rotulo_atual} · trimestre móvel</span>
      </header>

      <div ref={containerRef} className="vendedores-chart diagnostico-fluxo-chart" style={{ position: 'relative' }}>
        <ResponsiveContainer width="100%" height="100%">
          <Sankey
            data={{ nodes, links }}
            nodeWidth={14}
            nodePadding={28}
            margin={{ top: 8, right: 88, bottom: 8, left: 88 }}
            link={criarLigacaoSankey(hover?.indice ?? null) as never}
            node={NoSankey as never}
            onMouseEnter={aoEntrarLigacao as never}
            onMouseLeave={aoSairLigacao as never}
          />
        </ResponsiveContainer>
        {hover && (
          <div
            className="vendedores-chart-tooltip diagnostico-fluxo-tooltip"
            style={{ position: 'absolute', left: hover.x + 14, top: hover.y + 14 }}
          >
            <ConteudoTooltip ligacao={hover.ligacao} />
          </div>
        )}
      </div>
      <p className="diagnostico-nota-eixo">
        Passe o mouse sobre uma banda para ver de/para, clientes e receita.{' '}
        {resumo && `${resumo.entraram} cliente(s) entraram e ${resumo.sairam} saíram da carteira no período — fora do aluvial. `}
        {pisoAplicado && 'Bandas muito finas recebem espessura mínima para ficarem legíveis. '}
        {fatorCompressao < 1 && (
          <>Bandas tracejadas (quem manteve a mesma faixa) tiveram a escala reduzida em {(1 / fatorCompressao).toFixed(1)}x — sem isso, dominariam o gráfico e escondariam as migrações reais.</>
        )}
      </p>
    </section>
  );
}
