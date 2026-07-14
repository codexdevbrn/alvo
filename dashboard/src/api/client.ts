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
    const corpo = await res.json().catch(() => ({}));
    throw new Error(corpo.detail || `Erro ${res.status}`);
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
}

export async function obterBase(): Promise<PreviaBase> {
  const res = await fetch('/api/base', { headers: authHeaders() });
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
}

export interface Grupo {
  nome: string;
  ate_percentual: number | null;
  quantidade: number;
}

export interface ItemClientePrevia {
  cliente: string;
  receita: number;
  percentual_receita: number;
  percentual_acumulado: number | null;
  grupo: string;
}

export interface ItemProdutoPrevia {
  produto: string;
  receita: number;
  grupo: string;
  percentual_receita: number;
  percentual_acumulado: number;
}

export interface ParametrosGrupos {
  clientes_excluidos: string[];
  cortes_clientes: [number, number, number];
  desconsiderar_balcao: boolean;
}

export async function obterPreviaGrupos(
  parametros: ParametrosGrupos,
): Promise<{ grupos: Grupo[]; itens: ItemClientePrevia[] }> {
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
}): Promise<{ grupos: Grupo[]; itens: ItemProdutoPrevia[] }> {
  const res = await fetch('/api/produtos/previa', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(parametros),
  });
  return tratarResposta(res);
}

export async function obterCaminhoEmpresas(): Promise<string | null> {
  const res = await fetch('/api/config/caminho-empresas', { headers: authHeaders() });
  const dados = await tratarResposta<{ caminho: string | null }>(res);
  return dados.caminho;
}

export async function definirCaminhoEmpresas(caminho: string): Promise<string> {
  const res = await fetch('/api/config/caminho-empresas', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ caminho }),
  });
  const dados = await tratarResposta<{ caminho: string }>(res);
  return dados.caminho;
}

export async function listarEmpresas(): Promise<string[]> {
  const res = await fetch('/api/empresas', { headers: authHeaders() });
  return tratarResposta(res);
}

export async function salvarConfiguracaoEmpresa(nome: string, dados: unknown): Promise<void> {
  const res = await fetch(`/api/empresas/${encodeURIComponent(nome)}/configuracao`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ dados }),
  });
  await tratarResposta(res);
}

export async function carregarConfiguracaoEmpresa<T>(nome: string): Promise<T> {
  const res = await fetch(`/api/empresas/${encodeURIComponent(nome)}/configuracao`, { headers: authHeaders() });
  return tratarResposta(res);
}

// ---------------------------------------------------------------------------
// Dashboard (rota / pública — endpoints sem autenticação no backend)
// ---------------------------------------------------------------------------

export async function obterCaminhoDadosDashboard(): Promise<string | null> {
  const res = await fetch('/api/dashboard/caminho-dados');
  const dados = await tratarResposta<{ caminho: string | null }>(res);
  return dados.caminho;
}

export async function definirCaminhoDadosDashboard(caminho: string): Promise<string> {
  const res = await fetch('/api/dashboard/caminho-dados', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ caminho }),
  });
  const dados = await tratarResposta<{ caminho: string }>(res);
  return dados.caminho;
}

export async function listarEmpresasDashboard(): Promise<string[]> {
  const res = await fetch('/api/dashboard/empresas');
  return tratarResposta(res);
}

export async function obterSummaryEmpresa(empresa: string): Promise<DashboardData> {
  const res = await fetch(`/api/dashboard/summary/${encodeURIComponent(empresa)}`);
  return tratarResposta(res);
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
