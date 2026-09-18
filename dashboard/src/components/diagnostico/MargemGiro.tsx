import { CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts';
import type { MargemGiroDiagnostico, ProdutoMargemGiro } from '../../api/client';
import { formatCompacto, formatCurrency, formatNumber, formatPercent } from '../../utils/formatters';
import { CORES_STATUS, ROTULOS_STATUS, textoCobertura } from '../estoque/estoqueStatus';
import { TituloDiagnostico } from './TituloDiagnostico';

interface Props {
  margemGiro: MargemGiroDiagnostico;
}

function TooltipMargemGiro({ active, payload }: { active?: boolean; payload?: Array<{ payload?: ProdutoMargemGiro }> }) {
  const produto = payload?.[0]?.payload;
  if (!active || !produto) return null;
  return (
    <div className="vendedores-chart-tooltip">
      <strong>{produto.descricao}</strong>
      <dl>
        <div><dt>Margem</dt><dd>{produto.margem_pct == null ? '—' : formatPercent(produto.margem_pct, 1)}</dd></div>
        <div><dt>Cobertura</dt><dd>{textoCobertura(produto.cobertura_meses)}</dd></div>
        <div><dt>Estoque</dt><dd>{formatCurrency(produto.valor_estoque ?? 0)}</dd></div>
        <div><dt>Situação</dt><dd>{ROTULOS_STATUS[produto.status]}</dd></div>
      </dl>
    </div>
  );
}

/** ATO III: cruza margem % (o que cada produto deixa) com a cobertura de
 *  estoque em meses (a velocidade de giro) — scatter porque a tabela ordena
 *  por um eixo só, e a decisão certa (descontinuar vs. reajustar preço)
 *  depende dos dois ao mesmo tempo. Quem está parado (cobertura alta) E com
 *  margem baixa trava capital sem devolver lucro; quem gira rápido com
 *  margem baixa só pede reajuste de preço, não corte.
 *
 *  Cor por status de cobertura, não por quadrante — mesma linguagem da tela
 *  de Estoque (`CORES_STATUS`/`ROTULOS_STATUS`), para as duas telas nunca
 *  contarem histórias diferentes sobre o mesmo produto. */
export function MargemGiro({ margemGiro }: Props) {
  // Guarda contra resposta de um backend ainda sem este campo (deploy em
  // andamento, ou cache de requisição antigo no navegador) — sem isso a tela
  // inteira quebra por um bloco que já tem mensagem de indisponível pronta.
  if (!margemGiro?.disponivel || (margemGiro.produtos?.length ?? 0) === 0) {
    return <p className="analisador-hint">{margemGiro?.mensagem || 'Estoque não disponível para cruzar com margem.'}</p>;
  }

  const pontos = margemGiro.produtos
    .filter((item) => item.margem_pct != null)
    .map((item) => ({ ...item, x: item.cobertura_meses ?? 0, y: item.margem_pct ?? 0 }));

  // "Pior canto": parado (excesso/perdendo força/sem giro) e travando capital
  // — o recorte que justifica o card existir, não é decorativo no título.
  const piorCanto = pontos.filter((item) => ['excess', 'stalled', 'no_sales'].includes(item.status));
  const valorPiorCanto = piorCanto.reduce((soma, item) => soma + (item.valor_estoque ?? 0), 0);
  // Sem valor não tem largura na barra — listar mesmo assim na legenda lê como
  // item que "não existe" (cor sem contrapartida visível nenhuma no gráfico).
  const bulletVisivel = margemGiro.bullet.filter((item) => (item.valor_estoque ?? 0) > 0);
  const totalValorEstoque = bulletVisivel.reduce((soma, item) => soma + (item.valor_estoque ?? 0), 0);

  return (
    <section className="glass-card glass-card-flat clientes-visao-card">
      <header className="clientes-visao-card-topo">
        <div>
          <TituloDiagnostico
            texto="Estoque parado com baixa margem"
            destaque={valorPiorCanto > 0 ? formatCompacto(valorPiorCanto, true) : undefined}
            variante="queda"
          />
          <p>
            Margem % (sobre o CMV do período) × cobertura de estoque em meses. Cada ponto é 1
            produto — mesma régua e cor da tela de Estoque.
          </p>
        </div>
      </header>

      <div className="vendedores-chart diagnostico-scatter-chart">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 22, right: 16, left: 4, bottom: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis
              type="number" dataKey="x" domain={[0, 12]} allowDataOverflow
              tick={{ fill: 'var(--text-muted)', fontSize: 11 }} axisLine={false} tickLine={false}
              label={{ value: 'Cobertura (meses)', position: 'insideBottom', offset: -6, fill: 'var(--text-muted)', fontSize: 11 }}
            />
            <YAxis
              type="number" dataKey="y" unit="%" domain={[-50, 100]} allowDataOverflow
              tick={{ fill: 'var(--text-muted)', fontSize: 11 }} axisLine={false} tickLine={false} width={48}
            />
            <ZAxis range={[36, 36]} />
            <ReferenceLine
              x={3} stroke="var(--border-strong)" strokeDasharray="3 3"
              label={{ value: 'alvo 3m', position: 'top', fill: 'var(--text-muted)', fontSize: 10 }}
            />
            <ReferenceLine y={0} stroke="var(--border-strong)" />
            <Tooltip content={<TooltipMargemGiro />} cursor={{ strokeDasharray: '3 3' }} />
            <Scatter data={pontos} isAnimationActive={false}>
              {pontos.map((ponto, indice) => (
                // `descricao` é a descrição harmonizada — vários produtos diferentes
                // (referências distintas) compartilham o mesmo nome de propósito,
                // então não serve de key sozinha (ver DESCRICAO_HARMONIZADA no CLAUDE.md).
                <Cell key={`${ponto.descricao}-${indice}`} fill={CORES_STATUS[ponto.status]} fillOpacity={0.85} />
              ))}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </div>

      {bulletVisivel.length > 0 && (
        <>
          <p className="diagnostico-nota-eixo">Valor em estoque por situação:</p>
          <div className="diagnostico-composicao-barra" role="img" aria-label="Valor em estoque por situação">
            {bulletVisivel.map((item) => {
              const largura = totalValorEstoque > 0 ? ((item.valor_estoque ?? 0) / totalValorEstoque) * 100 : 0;
              return (
                <span
                  key={item.status}
                  style={{ width: `${largura}%`, background: CORES_STATUS[item.status] }}
                  title={`${ROTULOS_STATUS[item.status]}: ${formatCurrency(item.valor_estoque ?? 0)} (${formatNumber(item.produtos)} produtos)`}
                />
              );
            })}
          </div>
          <ul className="diagnostico-composicao-legenda">
            {bulletVisivel.map((item) => (
              <li key={item.status}>
                <span className="diagnostico-composicao-legenda-rotulo">
                  <i style={{ background: CORES_STATUS[item.status] }} />
                  {ROTULOS_STATUS[item.status]}
                </span>
                <span className="diagnostico-composicao-legenda-valor">
                  {formatCompacto(item.valor_estoque ?? 0, true)} <small>· {formatNumber(item.produtos)} prod.</small>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
