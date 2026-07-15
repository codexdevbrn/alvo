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
    const corpo = await res.json().catch(() => ({} as { detail?: unknown }));
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
    } else {
      mensagem = `Erro ${res.status}`;
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
}

export async function obterBase(empresa?: string | null): Promise<PreviaBase> {
  const qs = empresa ? `?empresa=${encodeURIComponent(empresa)}` : '';
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
  nome_empresa: string;
  nome_usuario: string;
  empresa?: string | null;
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

export async function sugerirCortesGrupos(
  parametros: ParametrosGrupos & { max_por_grupo: number },
): Promise<{ cortes_clientes: [number, number, number]; grupos: Grupo[]; itens: ItemClientePrevia[] }> {
  const res = await fetch('/api/grupos/sugerir-cortes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(parametros),
  });
  return tratarResposta(res);
}

export async function obterPreviaProdutos(parametros: {
  produtos_excluidos: string[];
  corte_produtos: number;
  empresa?: string | null;
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

/** @deprecated use obterCaminhoTrabalho — alias legado */
export async function obterCaminhoEmpresas(): Promise<string | null> {
  return obterCaminhoTrabalho(true);
}

/** @deprecated use definirCaminhoTrabalho — alias legado */
export async function definirCaminhoEmpresas(caminho: string): Promise<string> {
  return definirCaminhoTrabalho(caminho, true);
}

export async function listarEmpresas(): Promise<string[]> {
  const res = await fetch('/api/empresas', { headers: authHeaders() });
  return tratarResposta(res);
}

export async function salvarConfiguracaoEmpresa(
  nome: string,
  dados: unknown,
): Promise<{ ok: boolean; caminho: string }> {
  const res = await fetch(`/api/empresas/${encodeURIComponent(nome)}/configuracao`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ dados }),
  });
  return tratarResposta(res);
}

/** Regras salvas em config.json da pasta de trabalho da empresa. */
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
  clientesExcluidos?: string[];
  produtosExcluidos?: string[];
  chavesSelecionadas?: string[];
  granularidade?: string;
};

export async function carregarConfiguracaoEmpresa<T = ConfigEmpresaSalva>(nome: string): Promise<T> {
  const res = await fetch(`/api/empresas/${encodeURIComponent(nome)}/configuracao`, { headers: authHeaders() });
  return tratarResposta(res);
}

/** Retorna null se a empresa não tem config.json (404). */
export async function tentarCarregarConfiguracaoEmpresa(nome: string): Promise<ConfigEmpresaSalva | null> {
  const res = await fetch(`/api/empresas/${encodeURIComponent(nome)}/configuracao`, { headers: authHeaders() });
  if (res.status === 404) return null;
  return tratarResposta(res);
}

export type TagCliente = 'inadimplente' | 'cliente_balcao' | 'encerrou_operacao';

export const TAGS_CLIENTE_OPCOES: { id: TagCliente; rotulo: string }[] = [
  { id: 'inadimplente', rotulo: 'Inadimplente' },
  { id: 'cliente_balcao', rotulo: 'Cliente Balcão' },
  { id: 'encerrou_operacao', rotulo: 'Encerrou operação' },
];

export type TagsClientesResposta = {
  tags: Record<string, TagCliente[]>;
  clientes_balcao: string[];
  caminho?: string;
};

export async function obterTagsClientes(empresa: string): Promise<TagsClientesResposta> {
  const res = await fetch(`/api/empresas/${encodeURIComponent(empresa)}/clientes-tags`, {
    headers: authHeaders(),
  });
  return tratarResposta(res);
}

export async function salvarTagsUmCliente(
  empresa: string,
  cliente: string,
  tags: TagCliente[],
): Promise<TagsClientesResposta> {
  const res = await fetch(`/api/empresas/${encodeURIComponent(empresa)}/clientes-tags/cliente`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ cliente, tags }),
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

/** @deprecated use obterCaminhoFonteDados — alias legado */
export async function obterCaminhoDadosDashboard(): Promise<string | null> {
  return obterCaminhoFonteDados(false);
}

/** @deprecated use definirCaminhoFonteDados — alias legado */
export async function definirCaminhoDadosDashboard(caminho: string): Promise<string> {
  return definirCaminhoFonteDados(caminho, false);
}

export async function listarEmpresasDashboard(): Promise<string[]> {
  const res = await fetch('/api/dashboard/empresas');
  return tratarResposta(res);
}

export async function obterSummaryEmpresa(empresa: string, signal?: AbortSignal): Promise<DashboardData> {
  try {
    const res = await fetch(`/api/dashboard/summary/${encodeURIComponent(empresa)}`, { signal });
    return tratarResposta(res);
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    if (err instanceof Error && err.message.startsWith('Erro ')) throw err;
    throw new Error(
      'Não foi possível conectar ao backend (porta 8002). Verifique se o servidor está rodando e tente novamente.',
    );
  }
}

export interface TabelaResultado {
  colunas: string[];
  linhas: unknown[][];
}

export type ResultadoAnalise = Record<string, Record<string, TabelaResultado>>;

export async function analisar(parametros: ParametrosAnalise): Promise<ResultadoAnalise> {
  const res = await fetch('/api/analisar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(parametros),
  });
  return tratarResposta(res);
}

export async function exportarRelatorio(formato: 'excel' | 'pdf', parametros: ParametrosAnalise): Promise<Blob> {
  const res = await fetch(`/api/exportar/${formato}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(parametros),
  });
  if (!res.ok) {
    const corpo = await res.json().catch(() => ({}));
    throw new Error(corpo.detail || `Erro ${res.status}`);
  }
  return res.blob();
}
