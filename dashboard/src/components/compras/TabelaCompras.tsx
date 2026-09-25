import { Fragment, type KeyboardEvent } from 'react';
import { ChevronRight } from 'lucide-react';
import type { ItemCompras, ProdutoCompras } from '../../types/compras';
import { chaveProduto, moedaOuTraco, quantidade, type Selecao } from './formatoCompras';

const SEM_CUSTO = 'Sem venda nos últimos 3 meses fechados';

type Props = {
  produtos: ProdutoCompras[];
  abertos: Set<string>;
  selecao: Selecao | null;
  onAlternar: (chave: string) => void;
  onSelecionar: (selecao: Selecao) => void;
};

function aoTeclar(evento: KeyboardEvent<HTMLTableRowElement>, acao: () => void) {
  if (evento.key === 'Enter' || evento.key === ' ') {
    evento.preventDefault();
    acao();
  }
}

function Sugestao({ valor }: { valor: number | null }) {
  return valor != null
    ? <>{valor.toLocaleString('pt-BR')}</>
    : <span className="compras-nr">Não recomendado</span>;
}

/** Uma linha por produto; clicar abre os SKUs embaixo e mostra o produto no painel. */
export function TabelaCompras({ produtos, abertos, selecao, onAlternar, onSelecionar }: Props) {
  return (
    <div className="prec-tabela-rolagem compras-tabela-rolagem">
      <table className="prec-tabela compras-tabela">
        <thead>
          <tr>
            <th>Produto</th>
            <th>Fabricante</th>
            <th className="r">SKUs</th>
            <th className="r">Estoque</th>
            <th className="r">Média mensal</th>
            <th className="r">Estoque alvo</th>
            <th className="r">Sugestão</th>
            <th className="r">Custo médio recente</th>
            <th className="r">Valor</th>
          </tr>
        </thead>
        <tbody>
          {produtos.map((produto) => {
            const chave = chaveProduto(produto);
            const aberto = abertos.has(chave);
            const abrir = () => {
              onAlternar(chave);
              onSelecionar({ tipo: 'produto', chave });
            };
            const selecionado = selecao?.tipo === 'produto' && selecao.chave === chave;
            return (
              <Fragment key={chave}>
                <tr
                  role="button"
                  tabIndex={0}
                  aria-expanded={aberto}
                  className={`compras-linha-produto${selecionado ? ' is-selecionada' : ''}`}
                  onClick={abrir}
                  onKeyDown={(evento) => aoTeclar(evento, abrir)}
                >
                  <td>
                    <span className="compras-produto">
                      <ChevronRight size={14} aria-hidden="true" className={`compras-seta${aberto ? ' is-aberta' : ''}`} />
                      <span className="prec-nome compras-descricao" title={produto.descricao}>{produto.descricao || '—'}</span>
                    </span>
                  </td>
                  <td className="compras-fabricante" title={produto.fabricante}>{produto.fabricante}</td>
                  <td className="r">{produto.skus.length.toLocaleString('pt-BR')}</td>
                  <td className="r">{quantidade(produto.estoque)}</td>
                  <td className="r">{quantidade(produto.media, 2)}</td>
                  <td className="r">
                    {produto.estoque_alvo == null ? '—' : quantidade(produto.estoque_alvo, 1)}
                    {produto.coluna && <BadgeColuna coluna={produto.coluna} />}
                  </td>
                  <td className="r compras-sugestao"><Sugestao valor={produto.sugestao} /></td>
                  <td className="r compras-nr" />
                  <td
                    className="r"
                    title={produto.skus_sem_custo > 0 ? `${produto.skus_sem_custo} SKU(s) sem custo, fora do valor` : undefined}
                  >
                    {moedaOuTraco(produto.valor)}
                    {produto.skus_sem_custo > 0 && <span className="compras-alerta-sku" aria-hidden="true">*</span>}
                  </td>
                </tr>
                {aberto && produto.skus.map((sku) => (
                  <LinhaSku
                    key={sku.codigo}
                    sku={sku}
                    selecionado={selecao?.tipo === 'sku' && selecao.codigo === sku.codigo}
                    onSelecionar={() => onSelecionar({ tipo: 'sku', chave, codigo: sku.codigo })}
                  />
                ))}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function LinhaSku({ sku, selecionado, onSelecionar }: { sku: ItemCompras; selecionado: boolean; onSelecionar: () => void }) {
  return (
    <tr
      role="button"
      tabIndex={0}
      aria-pressed={selecionado}
      className={`compras-linha-sku${selecionado ? ' is-selecionada' : ''}`}
      onClick={onSelecionar}
      onKeyDown={(evento) => aoTeclar(evento, onSelecionar)}
    >
      <td>
        <span className="compras-sku">
          <span className="compras-codigo">{sku.codigo}</span>
          {sku.referencia && <small>{sku.referencia}</small>}
        </span>
      </td>
      <td />
      <td />
      <td className="r">{quantidade(sku.estoque)}</td>
      <td className="r">{quantidade(sku.media, 2)}</td>
      <td className="r">{sku.estoque_alvo == null ? '—' : quantidade(sku.estoque_alvo, 1)}</td>
      <td className="r"><Sugestao valor={sku.sugestao} /></td>
      <td className="r" title={sku.custo == null ? SEM_CUSTO : undefined}>{moedaOuTraco(sku.custo)}</td>
      <td className="r" title={sku.custo == null && sku.sugestao != null ? SEM_CUSTO : undefined}>
        {moedaOuTraco(sku.valor)}
      </td>
    </tr>
  );
}

export function BadgeColuna({ coluna }: { coluna: 'minimo' | 'maximo' }) {
  return (
    <span className={`compras-badge is-${coluna}`} title={coluna === 'minimo' ? 'Estoque mínimo' : 'Estoque máximo'}>
      {coluna === 'minimo' ? 'Mín' : 'Máx'}
    </span>
  );
}

export function TabelaComprasEsqueleto() {
  return (
    <div className="compras-esqueleto" aria-hidden="true">
      {Array.from({ length: 8 }, (_, i) => <span key={i} />)}
    </div>
  );
}
