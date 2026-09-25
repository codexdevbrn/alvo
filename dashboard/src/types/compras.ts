// Shape de GET /api/compras/{empresa} (backend/compras.py).

export type PrazoEntrega = 'imediato' | 'regular' | 'industria';
export type GiroCompras = 'impulsionado' | 'nao_impulsionado';

/** Prazo e giro próprios de um produto ou SKU; campo ausente = herda. */
export interface ExcecaoCompras {
  prazo?: PrazoEntrega;
  giro?: GiroCompras;
}

export interface ParametrosCompras {
  prazo_entrega: PrazoEntrega;
  giro: GiroCompras;
  caixa_apertado: boolean;
}

export interface LojaItemCompras {
  loja: string;
  estoque: number;
  /** null = "Não recomendado" nesta loja. */
  sugestao: number | null;
}

export interface ItemCompras {
  codigo: string;
  referencia: string | null;
  descricao: string;
  fabricante: string;
  /** 12 QTDs: 11 meses fechados + o corrente (parcial, fora da média). */
  venda_mensal: number[];
  media: number;
  estoque: number;
  /** null quando o cenário nunca compra (não impulsionado + caixa apertado). */
  estoque_alvo: number | null;
  coluna: 'minimo' | 'maximo' | null;
  /** null = "Não recomendado". */
  sugestao: number | null;
  /** Custo médio recente (CMV ÷ QTD dos 3 últimos fechados); null = sem venda neles. */
  custo: number | null;
  valor: number | null;
  lojas: LojaItemCompras[];
  /** Efetivos no SKU (SKU > produto > tela). */
  prazo: PrazoEntrega;
  giro: GiroCompras;
  /** Exceção gravada no próprio SKU. */
  excecao: ExcecaoCompras | null;
}

/** Produto = descrição × fabricante; soma dos SKUs (que já somam as lojas). */
export interface ProdutoCompras {
  descricao: string;
  fabricante: string;
  venda_mensal: number[];
  media: number;
  estoque: number;
  estoque_alvo: number | null;
  coluna: 'minimo' | 'maximo' | null;
  sugestao: number | null;
  /** Σ valor dos SKUs com custo; null se nenhum tem. */
  valor: number | null;
  /** SKUs com sugestão e sem custo (fora do valor). */
  skus_sem_custo: number;
  lojas: LojaItemCompras[];
  /** Efetivos no produto inteiro (produto > tela). */
  prazo: PrazoEntrega;
  giro: GiroCompras;
  excecao: ExcecaoCompras | null;
  skus_com_excecao: number;
  /** Ordenados por valor; com "Somente recomendados", só os que têm sugestão. */
  skus: ItemCompras[];
}

export interface ComprasResposta {
  empresa: string;
  loja: string | null;
  corte: string;
  /** Produtos, cortados em `limite`. */
  itens: ProdutoCompras[];
  total_compra: number;
  /** SKUs com sugestão. */
  itens_a_comprar: number;
  produtos_a_comprar: number;
  produtos_sem_custo: number;
  nao_recomendados: number;
  itens_total: number;
  itens_exibidos: number;
  limitado: boolean;
  fabricantes: string[];
  /** Rótulos AAAA-MM dos 12 meses de `venda_mensal`. */
  meses: string[];
  parametros_aplicados: ParametrosCompras;
}

/** PUT /api/compras/{empresa}/parametros: estado inteiro de um nível (null = herda). */
export type ExcecaoComprasEnvio =
  | { nivel: 'produto'; descricao: string; fabricante: string; prazo: PrazoEntrega | null; giro: GiroCompras | null }
  | { nivel: 'sku'; codigo: string; prazo: PrazoEntrega | null; giro: GiroCompras | null };
