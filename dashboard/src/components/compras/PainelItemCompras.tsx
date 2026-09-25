import type { ItemCompras, LojaItemCompras, ProdutoCompras } from '../../types/compras';
import { mesCurto, mesLongo, moedaOuTraco, quantidade } from './formatoCompras';

type Props = {
  produto: ProdutoCompras | null;
  /** Com SKU, o painel mostra o SKU; sem, o produto inteiro (soma dos SKUs). */
  sku: ItemCompras | null;
  meses: string[];
};

/** Detalhe do produto ou do SKU: 12 meses de venda, sugestão por loja e o resumo
 *  da conta. Na coluna direita acima de 1024px; dentro do drawer abaixo disso. */
export function PainelItemCompras({ produto, sku, meses }: Props) {
  if (!produto) {
    return <p className="prec-painel-vazio">Selecione um item para ver o detalhe</p>;
  }
  const alvo = sku ?? produto;

  return (
    <>
      {sku ? (
        <div>
          <span className="prec-rotulo">{produto.fabricante} · SKU</span>
          <h3>{sku.codigo}</h3>
          <p className="aprec-painel-fabricante">
            {produto.descricao || '—'}{sku.referencia ? ` · ref. ${sku.referencia}` : ''}
          </p>
        </div>
      ) : (
        <div>
          <span className="prec-rotulo">{produto.fabricante}</span>
          <h3>{produto.descricao || '—'}</h3>
          <p className="aprec-painel-fabricante">
            {produto.skus.length.toLocaleString('pt-BR')} SKU{produto.skus.length === 1 ? '' : 's'} · soma dos SKUs
          </p>
        </div>
      )}

      <BarrasMensais vendaMensal={alvo.venda_mensal} media={alvo.media} meses={meses} />
      <TabelaLojas lojas={alvo.lojas} />

      <div>
        <span className="prec-rotulo">Resumo</span>
        <dl className="aprec-dl">
          <div><dt>Média mensal</dt><dd>{quantidade(alvo.media, 2)}</dd></div>
          <div>
            <dt>Estoque alvo{alvo.coluna ? ` (${alvo.coluna === 'minimo' ? 'mínimo' : 'máximo'})` : ''}</dt>
            <dd>{alvo.estoque_alvo == null ? '—' : quantidade(alvo.estoque_alvo, 1)}</dd>
          </div>
          <div>
            <dt>Sugestão</dt>
            <dd><strong>{alvo.sugestao != null ? alvo.sugestao.toLocaleString('pt-BR') : 'Não recomendado'}</strong></dd>
          </div>
          {sku && <div><dt>Custo médio recente</dt><dd>{moedaOuTraco(sku.custo)}</dd></div>}
          <div><dt>Valor</dt><dd>{moedaOuTraco(alvo.valor)}</dd></div>
        </dl>
        {alvo.coluna == null && (
          <p className="prec-mudo">Caixa apertado: itens não impulsionados não são comprados neste cenário.</p>
        )}
        {sku && sku.custo == null && sku.sugestao != null && (
          <p className="prec-mudo">Sem venda nos últimos 3 meses fechados: fica fora do valor do pedido.</p>
        )}
        {!sku && produto.skus_sem_custo > 0 && (
          <p className="prec-mudo">
            {produto.skus_sem_custo} SKU{produto.skus_sem_custo === 1 ? '' : 's'} sem venda nos últimos 3 meses
            fechados: fora do valor.
          </p>
        )}
      </div>
    </>
  );
}

function BarrasMensais({ vendaMensal, media, meses }: { vendaMensal: number[]; media: number; meses: string[] }) {
  const maior = Math.max(...vendaMensal, 0);
  const ultimo = vendaMensal.length - 1;
  return (
    <div>
      <span className="prec-rotulo">Venda mensal, últimos 12 meses</span>
      <div
        className="compras-barras"
        role="img"
        aria-label={`Venda mensal, últimos 12 meses, média ${quantidade(media, 2)}`}
      >
        {vendaMensal.map((qtd, i) => (
          <span
            key={meses[i] ?? i}
            className={i === ultimo ? 'is-parcial' : undefined}
            style={{ height: `${maior > 0 ? Math.max((qtd / maior) * 100, qtd > 0 ? 2 : 0) : 0}%` }}
            title={`${meses[i] ? mesLongo(meses[i]) : ''}: ${quantidade(qtd)}${i === ultimo ? ' (parcial)' : ''}`}
          />
        ))}
      </div>
      <div className="compras-barras-meses" aria-hidden="true">
        {meses.map((mes, i) => <span key={mes}>{mesCurto(mes)}{i === ultimo ? '*' : ''}</span>)}
      </div>
      <p className="prec-mudo">* mês corrente, parcial: fora da média</p>
    </div>
  );
}

function TabelaLojas({ lojas }: { lojas: LojaItemCompras[] }) {
  if (lojas.length === 0) return null;
  return (
    <div>
      <span className="prec-rotulo">Por loja</span>
      <table className="prec-tabela compras-lojas">
        <thead>
          <tr><th>Loja</th><th className="r">Estoque</th><th className="r">Sugestão</th></tr>
        </thead>
        <tbody>
          {lojas.map((loja) => (
            <tr key={loja.loja}>
              <td>{loja.loja}</td>
              <td className="r">{quantidade(loja.estoque)}</td>
              <td className="r">{loja.sugestao != null ? loja.sugestao.toLocaleString('pt-BR') : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
