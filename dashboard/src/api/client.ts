import type { DashboardData } from '../types/dashboard';

const TOKEN_KEY = 'prisma_analisador_token';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

function authHeaders(): HeadersInit {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function tratarResposta<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const texto = await res.text().catch(() => '');
    let corpo: { detail?: unknown } = {};
    if (texto) {
      try {
        corpo = JSON.parse(texto) as { detail?: unknown };
      } catch {
        corpo = {};
      }
    }
    const detail = corpo?.detail;
    let mensagem: string;
    if (typeof detail === 'string') {
      mensagem = detail;
    } else if (Array.isArray(detail)) {
      mensagem = detail
        .map((item) =>
          item && typeof item === 'object' && 'msg' in item
            ? String((item as { msg: unknown }).msg)
            : JSON.stringify(item),
        )
        .join('; ');
    } else if (detail != null) {
      mensagem = JSON.stringify(detail);
    } else if (res.status === 502 || res.status === 503 || res.status === 504 || res.status === 500) {
      mensagem =
        'Backend indisponível (porta 8003). Confira se o uvicorn está rodando: '
        + 'cd backend && python -m uvicorn main:app --reload --port 8003';
    } else {
      mensagem = `Erro ${res.status} ao comunicar com o backend.`;
    }
    throw new Error(mensagem);
  }
  return res.json();
}

export async function login(usuario: string, senha: string): Promise<string> {
  const res = await fetch('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ usuario, senha }),
  });
  const dados = await tratarResposta<{ token: string }>(res);
  setToken(dados.token);
  return dados.token;
}

export interface ItemCatalogo {
  chave: string;
  titulo: string;
}

export interface CategoriaCatalogo {
  categoria: string;
  itens: ItemCatalogo[];
}

export async function obterCatalogo(): Promise<CategoriaCatalogo[]> {
  const res = await fetch('/api/catalogo', { headers: authHeaders() });
  return tratarResposta(res);
}

export interface PreviaBase {
  linhas: number;
  linhas_ignoradas: number;
  qtd_nao_harmonizados: number;
  granularidades: string[];
  empresa?: string | null;
  /** Lojas distintas da base (coluna Loja). */
  lojas?: string[];
  /** Loja ativa no pedido (null/omitido = todas). */
  loja?: string | null;
}

export async function obterBase(
  empresa?: string | null,
  loja?: string | null,
): Promise<PreviaBase> {
  const params = new URLSearchParams();
  if (empresa) params.set('empresa', empresa);
  if (loja) params.set('loja', loja);
  const qs = params.toString() ? `?${params}` : '';
  const res = await fetch(`/api/base${qs}`, { headers: authHeaders() });
  return tratarResposta(res);
}

export interface ParametrosAnalise {
  granularidades: string[];
  chaves_selecionadas: string[];
  clientes_excluidos: string[];
  produtos_excluidos: string[];
  cortes_clientes: [number, number, number];
  corte_produtos: number;
  periodos_queda_consecutiva: number;
  desconsiderar_balcao: boolean;
  excluir_periodo_atual: boolean;
  top_n_produtos: number | null;
  reducao_minima_erosao: number;
  queda_minima_alerta_rs: number;
  queda_minima_erosao_rs: number;
  reducao_minima_sem_venda: number;
  top_n_poder_compra: number | null;
  /** false = erosão/churn sobre a base inteira; true = só produtos em alerta. */
  erosao_somente_produtos_em_alerta: boolean;
  nome_empresa: string;
  nome_usuario: string;
  empresa?: string | null;
  /** Filtra a coluna Loja; null/omitido = todas as lojas. */
  loja?: string | null;
}

export interface Grupo {
  nome: string;
  ate_percentual: number | null;
  quantidade: number;
}

export interface ItemClientePrevia {
  cliente: string;
  receita: number;
  percentual_receita: number | null;
  percentual_acumulado: number | null;
  grupo: string;
}

export interface ItemProdutoPrevia {
  produto: string;
  receita: number;
  grupo: string;
  percentual_receita: number | null;
  percentual_acumulado: number | null;
}

export interface ParametrosGrupos {
  clientes_excluidos: string[];
  cortes_clientes: [number, number, number];
  desconsiderar_balcao: boolean;
  empresa?: string | null;
  loja?: string | null;
  max_itens_por_grupo?: number;
  /** false = usa cortes do pedido (config salva); true = recalcula como sugerir */
  ajustar_cortes?: boolean;
}

export async function obterPreviaGrupos(
  parametros: ParametrosGrupos,
): Promise<{ cortes_clientes: [number, number, number]; grupos: Grupo[]; itens: ItemClientePrevia[] }> {
  const res = await fetch('/api/grupos/previa', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(parametros),
  });
  return tratarResposta(res);
}

/** Alias: mesma prévia com ajustar_cortes=true. */
export async function sugerirCortesGrupos(
  parametros: ParametrosGrupos,
): Promise<{ cortes_clientes: [number, number, number]; grupos: Grupo[]; itens: ItemClientePrevia[] }> {
  return obterPreviaGrupos({ ...parametros, ajustar_cortes: true });
}

export async function obterPreviaProdutos(parametros: {
  produtos_excluidos: string[];
  corte_produtos: number;
  empresa?: string | null;
  loja?: string | null;
  max_itens_por_grupo?: number;
  ajustar_cortes?: boolean;
}): Promise<{
  corte_produtos: number;
  grupos: Grupo[];
  itens: ItemProdutoPrevia[];
  produtos_demais: string[];
  produtos_nao_harmonizados: string[];
}> {
  const res = await fetch('/api/produtos/previa', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(parametros),
  });
  return tratarResposta(res);
}

export async function obterCaminhoFonteDados(auth = false): Promise<string | null> {
  const res = await fetch(
    auth ? '/api/config/caminho-fonte-dados' : '/api/dashboard/caminho-fonte-dados',
    { headers: auth ? authHeaders() : {} },
  );
  const dados = await tratarResposta<{ caminho: string | null }>(res);
  return dados.caminho;
}

export async function definirCaminhoFonteDados(caminho: string, auth = false): Promise<string> {
  const res = await fetch(
    auth ? '/api/config/caminho-fonte-dados' : '/api/dashboard/caminho-fonte-dados',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(auth ? authHeaders() : {}) },
      body: JSON.stringify({ caminho }),
    },
  );
  const dados = await tratarResposta<{ caminho: string }>(res);
  return dados.caminho;
}

export async function obterCaminhoTrabalho(auth = false): Promise<string | null> {
  const res = await fetch(
    auth ? '/api/config/caminho-trabalho' : '/api/dashboard/caminho-trabalho',
    { headers: auth ? authHeaders() : {} },
  );
  const dados = await tratarResposta<{ caminho: string | null }>(res);
  return dados.caminho;
}

export async function definirCaminhoTrabalho(caminho: string, auth = false): Promise<string> {
  const res = await fetch(
    auth ? '/api/config/caminho-trabalho' : '/api/dashboard/caminho-trabalho',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(auth ? authHeaders() : {}) },
      body: JSON.stringify({ caminho }),
    },
  );
  const dados = await tratarResposta<{ caminho: string }>(res);
  return dados.caminho;
}

/** Público — usado pelo Dashboard para mostrar o aviso de base em montagem. */
export async function obterAguardandoBaseDados(auth = false): Promise<boolean> {
  const res = await fetch(
    auth ? '/api/config/aguardando-base-dados' : '/api/dashboard/aguardando-base-dados',
    { headers: auth ? authHeaders() : {} },
  );
  const dados = await tratarResposta<{ aguardando: boolean }>(res);
  return dados.aguardando;
}

export async function definirAguardandoBaseDados(aguardando: boolean, auth = false): Promise<boolean> {
  const res = await fetch(
    auth ? '/api/config/aguardando-base-dados' : '/api/dashboard/aguardando-base-dados',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(auth ? authHeaders() : {}) },
      body: JSON.stringify({ aguardando }),
    },
  );
  const dados = await tratarResposta<{ aguardando: boolean }>(res);
  return dados.aguardando;
}

export type PastaItem = { nome: string; caminho: string };

export type ListagemPastas = {
  /** null = lista de raízes/unidades do servidor. */
  caminho: string | null;
  /** null = o caminho atual já é uma raiz. */
  pai: string | null;
  pastas: PastaItem[];
};

/**
 * Lista subpastas do sistema de arquivos **do servidor** (somente leitura).
 * O backend roda como serviço sem sessão gráfica, então não há diálogo nativo:
 * a navegação acontece na UI.
 */
export async function listarPastas(
  caminho?: string | null,
  auth = false,
): Promise<ListagemPastas> {
  const base = auth ? '/api/config/listar-pastas' : '/api/dashboard/listar-pastas';
  const qs = caminho ? `?caminho=${encodeURIComponent(caminho)}` : '';
  const res = await fetch(`${base}${qs}`, { headers: auth ? authHeaders() : {} });
  return tratarResposta<ListagemPastas>(res);
}

export async function listarEmpresas(): Promise<string[]> {
  const res = await fetch('/api/empresas', { headers: authHeaders() });
  return tratarResposta(res);
}

function queryLoja(loja?: string | null): string {
  const params = new URLSearchParams();
  if (loja) params.set('loja', loja);
  const q = params.toString();
  return q ? `?${q}` : '';
}

export async function salvarConfiguracaoEmpresa(
  nome: string,
  dados: unknown,
  loja?: string | null,
): Promise<{ ok: boolean; caminho: string; loja?: string | null }> {
  const res = await fetch(
    `/api/empresas/${encodeURIComponent(nome)}/configuracao${queryLoja(loja)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ dados }),
    },
  );
  return tratarResposta(res);
}

/** Regras salvas em config.json da pasta de trabalho da empresa (por escopo de loja). */
export type ConfigEmpresaSalva = {
  cortesClientes?: [number, number, number];
  corteProdutos?: number;
  periodosQueda?: number;
  desconsiderarBalcao?: boolean;
  desconsiderarDemaisProdutos?: boolean;
  desconsiderarNaoHarmonizados?: boolean;
  excluirPeriodoAtual?: boolean;
  nomeEmpresa?: string;
  topNProdutos?: number | '';
  reducaoMinimaErosao?: number;
  maxPorGrupo?: number;
  quedaMinimaAlertaRs?: number | '';
  quedaMinimaErosaoRs?: number | '';
  reducaoMinimaSemVenda?: number;
  topNPoderCompra?: number | '';
  erosaoSomenteProdutosEmAlerta?: boolean;
  clientesExcluidos?: string[];
  produtosExcluidos?: string[];
  chavesSelecionadas?: string[];
  granularidade?: string;
};

export async function carregarConfiguracaoEmpresa<T = ConfigEmpresaSalva>(
  nome: string,
  loja?: string | null,
): Promise<T> {
  const res = await fetch(
    `/api/empresas/${encodeURIComponent(nome)}/configuracao${queryLoja(loja)}`,
    { headers: authHeaders() },
  );
  return tratarResposta(res);
}

/** Retorna null se o escopo (loja / todas) ainda não tem config.json salvo. */
export async function tentarCarregarConfiguracaoEmpresa(
  nome: string,
  loja?: string | null,
): Promise<ConfigEmpresaSalva | null> {
  const res = await fetch(
    `/api/empresas/${encodeURIComponent(nome)}/configuracao${queryLoja(loja)}`,
    { headers: authHeaders() },
  );
  // Compatibilidade com backends antigos que ainda sinalizam ausência com 404.
  if (res.status === 404) return null;
  return tratarResposta<ConfigEmpresaSalva | null>(res);
}

export type TagCliente = string;

export type TagCatalogoItem = {
  id: string;
  rotulo: string;
  ativa: boolean;
  cor: string;
};

export const TAGS_CATALOGO_PADRAO: TagCatalogoItem[] = [
  { id: 'alerta', rotulo: 'Alerta', ativa: true, cor: '#ec1818' },
  { id: 'inadimplente', rotulo: 'Inadimplente', ativa: true, cor: '#f43f5e' },
  { id: 'cliente_balcao', rotulo: 'Cliente Balcão', ativa: true, cor: '#f59e0b' },
  { id: 'encerrou_operacao', rotulo: 'Encerrou operação', ativa: true, cor: '#64748b' },
];

export type TagsClientesResposta = {
  tags: Record<string, TagCliente[]>;
  clientes_balcao: string[];
  catalogo?: TagCatalogoItem[];
  grupos?: GrupoManualClientes[];
  caminho?: string;
  loja?: string | null;
};

export type GrupoManualClientes = {
  id: string;
  nome: string;
  clientes: string[];
};

export async function obterTagsClientes(
  empresa: string,
  loja?: string | null,
): Promise<TagsClientesResposta> {
  const res = await fetch(
    `/api/empresas/${encodeURIComponent(empresa)}/clientes-tags${queryLoja(loja)}`,
    { headers: authHeaders() },
  );
  return tratarResposta(res);
}

export async function salvarCatalogoTags(
  empresa: string,
  catalogo: TagCatalogoItem[],
  loja?: string | null,
): Promise<TagsClientesResposta> {
  const res = await fetch(
    `/api/empresas/${encodeURIComponent(empresa)}/clientes-tags/catalogo${queryLoja(loja)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ catalogo }),
    },
  );
  return tratarResposta(res);
}

export async function salvarGruposManuais(
  empresa: string,
  grupos: GrupoManualClientes[],
  loja?: string | null,
): Promise<TagsClientesResposta> {
  const res = await fetch(
    `/api/empresas/${encodeURIComponent(empresa)}/clientes-grupos${queryLoja(loja)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ grupos }),
    },
  );
  return tratarResposta(res);
}

export type ItemClienteBusca = {
  cliente: string;
  receita: number;
};

export async function buscarClientes(
  empresa: string | null | undefined,
  q: string,
  limite = 40,
  loja?: string | null,
): Promise<ItemClienteBusca[]> {
  const params = new URLSearchParams();
  if (empresa) params.set('empresa', empresa);
  if (loja) params.set('loja', loja);
  if (q.trim()) params.set('q', q.trim());
  params.set('limite', String(limite));
  const res = await fetch(`/api/clientes/buscar?${params}`, { headers: authHeaders() });
  const dados = await tratarResposta<{ itens: ItemClienteBusca[] }>(res);
  return Array.isArray(dados.itens) ? dados.itens : [];
}

export async function salvarTagsUmCliente(
  empresa: string,
  cliente: string,
  tags: TagCliente[],
  loja?: string | null,
): Promise<TagsClientesResposta> {
  const res = await fetch(
    `/api/empresas/${encodeURIComponent(empresa)}/clientes-tags/cliente${queryLoja(loja)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ cliente, tags }),
    },
  );
  return tratarResposta(res);
}

export type ExplorarSchema = {
  dimensoes: string[];
  metricas: string[];
  linhas: number;
  empresa?: string | null;
  loja?: string | null;
};

export type ParametrosExplorar = {
  empresa?: string | null;
  loja?: string | null;
  dimensoes: string[];
  metricas: string[];
  filtros?: Record<string, string[]>;
  aplicar_grupos?: boolean;
  limite?: number;
  ordenar_por?: string | null;
  ordem?: 'asc' | 'desc';
  modo_viz?: 'agregar' | 'histograma' | 'boxplot' | 'dispersao';
  bins?: number;
  /** Soma o que ficou fora do top N numa linha "Outros". */
  agrupar_resto?: boolean;
  /** Traz também o ano anterior (colunas `<métrica>_Ano_Anterior` + variação). */
  comparar_ano_anterior?: boolean;
};

export type ExplorarAgregado = {
  colunas: string[];
  linhas: unknown[][];
  total_linhas: number;
  limite: number;
  dimensoes: string[];
  metricas: string[];
  modo_viz?: string;
  eixos?: { x: string; y: string };
  escala?: string;
  /** true quando o backend acrescentou a linha "Outros" com o que ficou fora do top N. */
  resto_agrupado?: boolean;
  /** Anos usados quando `comparar_ano_anterior` está ligado. */
  comparacao?: { ano_atual: number; ano_anterior: number; meses_ignorados?: string[] };
};

export async function obterExplorarSchema(
  empresa?: string | null,
  loja?: string | null,
  signal?: AbortSignal,
): Promise<ExplorarSchema> {
  const params = new URLSearchParams();
  if (empresa) params.set('empresa', empresa);
  if (loja) params.set('loja', loja);
  const q = params.toString() ? `?${params}` : '';
  const res = await fetch(`/api/explorar/schema${q}`, { headers: authHeaders(), signal });
  return tratarResposta(res);
}

export async function explorarAgregar(
  parametros: ParametrosExplorar,
  signal?: AbortSignal,
): Promise<ExplorarAgregado> {
  const res = await fetch('/api/explorar/agregar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(parametros),
    signal,
  });
  return tratarResposta(res);
}

export async function ensureBaseEmpresa(nome: string): Promise<void> {
  const res = await fetch(`/api/empresas/${encodeURIComponent(nome)}/ensure-base`, {
    method: 'POST',
    headers: authHeaders(),
  });
  await tratarResposta(res);
}

// ---------------------------------------------------------------------------
// Dashboard (rota / pública — endpoints sem autenticação no backend)
// ---------------------------------------------------------------------------

export async function listarEmpresasDashboard(): Promise<string[]> {
  const res = await fetch('/api/dashboard/empresas');
  return tratarResposta(res);
}

/** Força renormalizar BI → Base.csv e limpar cache da empresa. */
export async function regenerarBaseEmpresa(
  empresa: string,
  auth = false,
): Promise<{ ok: boolean; empresa: string; caminho: string }> {
  const url = auth
    ? `/api/empresas/${encodeURIComponent(empresa)}/regenerar-base`
    : `/api/dashboard/empresas/${encodeURIComponent(empresa)}/regenerar-base`;
  const res = await fetch(url, {
    method: 'POST',
    headers: auth ? authHeaders() : undefined,
  });
  return tratarResposta(res);
}

export async function obterSummaryEmpresa(empresa: string, signal?: AbortSignal): Promise<DashboardData> {
  try {
    const res = await fetch(`/api/dashboard/summary/${encodeURIComponent(empresa)}`, { signal });
    const data = await tratarResposta<DashboardData>(res);
    const ultimo = res.headers.get('X-Ultimo-Movimento');
    if (ultimo) {
      data.updated_at = ultimo;
    }
    return data;
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    // fetch só lança TypeError em falha de rede (proxy/backend fora).
    // Erros HTTP (400/500 com detail) já vêm de tratarResposta — não mascarar.
    if (err instanceof TypeError) {
      throw new Error(
        'Não foi possível conectar ao backend (porta 8003). Verifique se o servidor está rodando e tente novamente.',
      );
    }
    throw err;
  }
}

export interface TabelaResultado {
  colunas: string[];
  linhas: unknown[][];
}

export type ResultadoAnalise = Record<string, Record<string, TabelaResultado>>;

export interface RespostaAnalise {
  resultados: ResultadoAnalise;
  /** Token opaco e temporário: permite exportar exatamente o resultado já calculado. */
  resultadoId: string | null;
}

export async function analisar(parametros: ParametrosAnalise): Promise<RespostaAnalise> {
  const res = await fetch('/api/analisar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(parametros),
  });
  const resultados = await tratarResposta<ResultadoAnalise>(res);
  return {
    resultados,
    resultadoId: res.headers.get('X-Resultado-Analise'),
  };
}

/** Formatos aceitos por POST /api/exportar/{formato}. */
export type FormatoExportacao = 'excel' | 'pdf' | 'html';

export async function exportarRelatorio(
  formato: FormatoExportacao,
  parametros: ParametrosAnalise,
  resultadoId?: string | null,
): Promise<Blob> {
  const res = await fetch(`/api/exportar/${formato}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...(resultadoId ? { 'X-Resultado-Analise': resultadoId } : {}),
    },
    body: JSON.stringify(parametros),
  });
  if (!res.ok) {
    const corpo = await res.json().catch(() => ({}));
    throw new Error(corpo.detail || `Erro ${res.status}`);
  }
  return res.blob();
}

// ---------------------------------------------------------------------------
// Monitoramento de empresas
// ---------------------------------------------------------------------------

export type MetricaMonitor = 'receita' | 'qtd' | 'clientes' | 'receita_dia';

/** Um card da tela de monitoramento. `estado` diferente de 'ok' vem sem serie:
 *  empresa sem base gerada ou com summary ilegivel entra na lista mesmo assim,
 *  para o usuario saber que ela existe e esta pendente. */
export type EmpresaMonitor = {
  empresa: string;
  estado: 'ok' | 'sem_base' | 'erro';
  detalhe?: string;
  metrica?: MetricaMonitor;
  rotulos?: (string | null)[];
  valores?: number[];
  total?: number | null;
  media?: number;
  variacao_pct?: number | null;
  /** false = base anterior menor que 1% da atual; percentual seria enganoso. */
  base_comparavel?: boolean | null;
  /** Lados da comparacao anual — cobrem so os meses do ano mais recente. */
  total_comparado?: number | null;
  total_ano_anterior?: number | null;
  ano_comparado?: number | null;
  meses_comparados?: number;
  updated_at?: string | null;
  ultimo_periodo?: number | null;
  ultimo_periodo_parcial?: boolean;
  dias_uteis_janela?: number | null;
  meses_serie?: number;
};

export type MonitorResposta = {
  metrica: MetricaMonitor;
  meses: number;
  empresas: EmpresaMonitor[];
  favoritas: string[];
};

export async function obterMonitorEmpresas(
  parametros: { metrica?: MetricaMonitor; meses?: number; forcar?: boolean } = {},
  signal?: AbortSignal,
): Promise<MonitorResposta> {
  const query = new URLSearchParams();
  if (parametros.metrica) query.set('metrica', parametros.metrica);
  if (parametros.meses) query.set('meses', String(parametros.meses));
  if (parametros.forcar) query.set('forcar', 'true');
  const res = await fetch(`/api/monitor/empresas?${query}`, { headers: authHeaders(), signal });
  return tratarResposta(res);
}

export async function salvarFavoritas(empresas: string[]): Promise<{ empresas: string[] }> {
  const res = await fetch('/api/monitor/favoritas', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ empresas }),
  });
  return tratarResposta(res);
}
