import type { DashboardData } from '../types/dashboard';
import type { ModoPeriodo } from '../utils/mesesFechados';
import { comCache, limparCacheGeral } from '../utils/cacheRequisicoes';
import { invalidarSummary } from '../utils/cacheSummary';
import { perfLog, perfTimer } from '../utils/perfDebug';

function nomeEndpoint(url: string): string {
  try {
    const base = typeof window !== 'undefined' ? window.location.origin : 'http://localhost';
    return new URL(url, base).pathname.replace(/^\/api\//, '');
  } catch {
    return url;
  }
}

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

/**
 * `fetch` com mensagem legível quando a requisição não chega ao backend.
 *
 * O `fetch` nativo lança `TypeError: Failed to fetch` para qualquer falha de rede,
 * e esse texto vazava para a tela sem dizer nada ao usuário. Acontece de verdade em
 * dois casos: o 2D Prisma foi encerrado (pela bandeja ou pelo Gerenciador de Tarefas)
 * e a aba continuou aberta; ou ele está reiniciando no meio de uma atualização.
 *
 * `AbortError` é repassado como está — cancelamento é fluxo normal de quem troca de
 * empresa antes de a requisição anterior terminar, e virar mensagem de erro seria
 * ruído.
 */
async function chamar(url: string, init?: RequestInit): Promise<Response> {
  const t = perfTimer();
  try {
    const res = await fetch(url, init);
    perfLog(nomeEndpoint(url), 'fetch', t(), String(res.status));
    return res;
  } catch (erro) {
    perfLog(nomeEndpoint(url), 'fetch (falhou)', t());
    if (erro instanceof DOMException && erro.name === 'AbortError') throw erro;
    throw new Error(
      'O 2D Prisma não respondeu. Ele pode ter sido encerrado ou estar reiniciando '
      + 'após uma atualização — recarregue a página.',
    );
  }
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
  const t = perfTimer();
  const dados = await res.json();
  perfLog(nomeEndpoint(res.url), 'parse json', t());
  return dados as T;
}

export async function login(usuario: string, senha: string): Promise<string> {
  const res = await chamar('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ usuario, senha }),
  });
  const dados = await tratarResposta<{ token: string }>(res);
  setToken(dados.token);
  return dados.token;
}

export interface ChatIAMensagem {
  role: 'user' | 'assistant';
  content: string;
}

export interface DocumentoContextoIA {
  disponivel: boolean;
  atualizado_em: string | null;
  status?: string | null;
}

export interface ContextoChatIA {
  client_id: string;
  empresa: string;
  pronto: boolean;
  provisorio: boolean;
  crm: DocumentoContextoIA;
  analise: DocumentoContextoIA;
  /** Fatos numéricos da base da empresa; opcional, não bloqueia a conversa. */
  dados: DocumentoContextoIA & { motivo?: string | null };
}

export interface RespostaChatIA {
  resposta: string;
  empresa: string;
  client_id: string;
  modelo: string;
}

/** Metadados dos MDs; o conteúdo integral nunca é enviado ao navegador. */
export async function obterContextoChatIA(
  empresa: string,
  signal?: AbortSignal,
): Promise<ContextoChatIA> {
  const params = new URLSearchParams({ empresa });
  const res = await chamar(`/api/ia/contexto?${params}`, {
    headers: authHeaders(),
    signal,
  });
  return tratarResposta(res);
}

/** Envia somente pergunta/histórico. Backend acrescenta os MDs e guarda a chave. */
export async function conversarChatIA(
  empresa: string,
  mensagens: ChatIAMensagem[],
): Promise<RespostaChatIA> {
  const res = await chamar('/api/ia/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ empresa, mensagens }),
  });
  return tratarResposta(res);
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
  const res = await chamar('/api/catalogo', { headers: authHeaders() });
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
  /** Lojas efetivamente filtradas; vazio = todas. */
  lojas_selecionadas?: string[];
}

export async function obterBase(
  empresa?: string | null,
  loja?: string | null,
): Promise<PreviaBase> {
  const params = new URLSearchParams();
  if (empresa) params.set('empresa', empresa);
  if (loja) params.set('loja', loja);
  const qs = params.toString() ? `?${params}` : '';
  return comCache(`base_${empresa || ''}_${loja || ''}`, async () => {
    const res = await chamar(`/api/base${qs}`, { headers: authHeaders() });
    return tratarResposta(res);
  });
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
  /** Tira do relatório quem ficou abaixo do corte de produtos. */
  desconsiderar_demais_produtos: boolean;
  desconsiderar_nao_harmonizados: boolean;
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
  /** Fora dos relatórios por regra, não por desmarcação manual. */
  fora_por_regra: 'demais' | 'nao_harmonizado' | null;
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
  const res = await chamar('/api/grupos/previa', {
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
  desconsiderar_demais_produtos?: boolean;
  desconsiderar_nao_harmonizados?: boolean;
}): Promise<{
  corte_produtos: number;
  grupos: Grupo[];
  itens: ItemProdutoPrevia[];
  /** Nomes que as regras tiram — usado só para limpar exclusões legadas. */
  produtos_fora_por_regra: string[];
}> {
  const res = await chamar('/api/produtos/previa', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(parametros),
  });
  return tratarResposta(res);
}

/** Alias: mesma prévia, com o corte do alto giro recalculado para caber em
 *  max_itens_por_grupo produtos. O corte devolvido vai para o campo da tela. */
export async function sugerirCorteProdutos(parametros: {
  produtos_excluidos: string[];
  corte_produtos: number;
  empresa?: string | null;
  loja?: string | null;
  desconsiderar_demais_produtos?: boolean;
  desconsiderar_nao_harmonizados?: boolean;
  max_itens_por_grupo: number;
}): Promise<{
  corte_produtos: number;
  grupos: Grupo[];
  itens: ItemProdutoPrevia[];
  produtos_fora_por_regra: string[];
}> {
  const res = await chamar('/api/produtos/sugerir-corte', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(parametros),
  });
  return tratarResposta(res);
}

export async function obterCaminhoFonteDados(auth = false): Promise<string | null> {
  const res = await chamar(
    auth ? '/api/config/caminho-fonte-dados' : '/api/dashboard/caminho-fonte-dados',
    { headers: auth ? authHeaders() : {} },
  );
  const dados = await tratarResposta<{ caminho: string | null }>(res);
  return dados.caminho;
}

export async function definirCaminhoFonteDados(caminho: string, auth = false): Promise<string> {
  const res = await chamar(
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
  const res = await chamar(
    auth ? '/api/config/caminho-trabalho' : '/api/dashboard/caminho-trabalho',
    { headers: auth ? authHeaders() : {} },
  );
  const dados = await tratarResposta<{ caminho: string | null }>(res);
  return dados.caminho;
}

export async function definirCaminhoTrabalho(caminho: string, auth = false): Promise<string> {
  const res = await chamar(
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
  const res = await chamar(
    auth ? '/api/config/aguardando-base-dados' : '/api/dashboard/aguardando-base-dados',
    { headers: auth ? authHeaders() : {} },
  );
  const dados = await tratarResposta<{ aguardando: boolean }>(res);
  return dados.aguardando;
}

export async function definirAguardandoBaseDados(aguardando: boolean, auth = false): Promise<boolean> {
  const res = await chamar(
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
  const res = await chamar(`${base}${qs}`, { headers: auth ? authHeaders() : {} });
  return tratarResposta<ListagemPastas>(res);
}

export async function listarEmpresas(): Promise<string[]> {
  const res = await chamar('/api/empresas', { headers: authHeaders() });
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
  const res = await chamar(
    `/api/empresas/${encodeURIComponent(nome)}/configuracao${queryLoja(loja)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ dados }),
    },
  );
  const resposta = await tratarResposta<{ ok: boolean; caminho: string; loja?: string | null }>(res);
  // tentarCarregarConfiguracaoEmpresa agora é cacheada (prefetch da tela Cortes) —
  // sem isto, Relatórios/Cortes releriam os cortes antigos até trocar de empresa.
  limparCacheGeral();
  // `cacheSummary` (Dashboard) é um módulo à parte de `cacheRequisicoes` — sem
  // isto, salvar um novo corte/exclusão aqui deixava o Dashboard da mesma
  // empresa com o summary antigo até um F5 ou até religar o toggle "Cortes".
  invalidarSummary(nome);
  return resposta;
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
  /** Modo de entrada usado na tela Cortes — os cortes % acima são sempre o que
   *  vale (config.json e backend só entendem %); isto é só pra reabrir a tela
   *  já no modo Quantidade, com os números que a pessoa digitou. */
  modoClientes?: 'percentual' | 'quantidade';
  quantidadesClientes?: [number, number, number];
  modoProdutos?: 'percentual' | 'quantidade';
  quantidadeProdutos?: number;
};

export async function carregarConfiguracaoEmpresa<T = ConfigEmpresaSalva>(
  nome: string,
  loja?: string | null,
): Promise<T> {
  const res = await chamar(
    `/api/empresas/${encodeURIComponent(nome)}/configuracao${queryLoja(loja)}`,
    { headers: authHeaders() },
  );
  return tratarResposta(res);
}

/** Retorna null se o escopo (loja / todas) ainda não tem config.json salvo. */
export async function tentarCarregarConfiguracaoEmpresa(
  nome: string,
  loja?: string | null,
  /** true = ignora o cache (botão "Carregar configuração": recarregar do disco
   *  precisa valer mesmo que outra máquina tenha editado o config.json). */
  forcarNovo = false,
): Promise<ConfigEmpresaSalva | null> {
  return comCache(`config_empresa_${nome}_${loja || ''}`, async () => {
    const res = await chamar(
      `/api/empresas/${encodeURIComponent(nome)}/configuracao${queryLoja(loja)}`,
      { headers: authHeaders() },
    );
    // Compatibilidade com backends antigos que ainda sinalizam ausência com 404.
    if (res.status === 404) return null;
    return tratarResposta<ConfigEmpresaSalva | null>(res);
  }, forcarNovo);
}

export type TagCliente = string;

export type TagCatalogoItem = {
  id: string;
  rotulo: string;
  ativa: boolean;
  /** Define se tag aparece nas opções de tag dentro do Analisador. */
  entra_na_analise: boolean;
  cor: string;
};

export const TAGS_CATALOGO_PADRAO: TagCatalogoItem[] = [
  { id: 'alerta', rotulo: 'Alerta', ativa: true, entra_na_analise: true, cor: '#ec1818' },
  { id: 'inadimplente', rotulo: 'Inadimplente', ativa: true, entra_na_analise: true, cor: '#f43f5e' },
  { id: 'cliente_balcao', rotulo: 'Cliente Balcão', ativa: true, entra_na_analise: true, cor: '#f59e0b' },
  { id: 'encerrou_operacao', rotulo: 'Encerrou operação', ativa: true, entra_na_analise: true, cor: '#64748b' },
];

export type TagsClientesResposta = {
  tags: Record<string, TagCliente[]>;
  clientes_balcao: string[];
  catalogo?: TagCatalogoItem[];
  grupos?: GrupoManualClientes[];
  regras_alerta?: RegraAlertaCliente[];
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
  const url = `/api/empresas/${encodeURIComponent(empresa)}/clientes-tags${queryLoja(loja)}`;
  return comCache(`tags_${empresa}_${loja || ''}`, async () => {
    const res = await chamar(url, { headers: authHeaders() });
    return tratarResposta(res);
  });
}

export async function salvarCatalogoTags(
  empresa: string,
  catalogo: TagCatalogoItem[],
  loja?: string | null,
  catalogoBase?: TagCatalogoItem[],
): Promise<TagsClientesResposta> {
  const res = await chamar(
    `/api/empresas/${encodeURIComponent(empresa)}/clientes-tags/catalogo${queryLoja(loja)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ catalogo, catalogo_base: catalogoBase ?? null }),
    },
  );
  return tratarResposta(res);
}

export async function salvarGruposManuais(
  empresa: string,
  grupos: GrupoManualClientes[],
  loja?: string | null,
): Promise<TagsClientesResposta> {
  const res = await chamar(
    `/api/empresas/${encodeURIComponent(empresa)}/clientes-grupos${queryLoja(loja)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ grupos }),
    },
  );
  return tratarResposta(res);
}

export async function obterAlertasClientes(
  empresa: string,
  loja?: string | null,
): Promise<AlertasClientesResposta> {
  const res = await chamar(
    `/api/empresas/${encodeURIComponent(empresa)}/clientes-alertas${queryLoja(loja)}`,
    { headers: authHeaders() },
  );
  return tratarResposta(res);
}

export async function salvarRegrasAlertasClientes(
  empresa: string,
  regras: RegraAlertaCliente[],
  loja?: string | null,
): Promise<TagsClientesResposta> {
  const res = await chamar(
    `/api/empresas/${encodeURIComponent(empresa)}/clientes-alertas/regras${queryLoja(loja)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ regras }),
    },
  );
  return tratarResposta(res);
}

export type ItemClienteBusca = {
  cliente: string;
  receita: number;
};

export type DirecaoAlertaCliente = 'queda' | 'alta' | 'ambos';
export type GranularidadeAlertaCliente = 'diaria' | 'semanal' | 'mensal';

export type RegraAlertaCliente = {
  id: string;
  tag_id: string;
  ativa: boolean;
  metrica: 'receita';
  granularidade: GranularidadeAlertaCliente;
  direcao: DirecaoAlertaCliente;
  limite_percentual: number;
  limite_valor: number;
  meses_historico: number;
  min_dias_uteis: number;
};

export type AlertaRitmoCliente = {
  id: string;
  regra_id: string;
  tag_id: string;
  cliente: string;
  granularidade: GranularidadeAlertaCliente;
  sentido: 'queda' | 'alta';
  realizado: number;
  esperado: number;
  diferenca: number;
  variacao_percentual: number;
  media_diaria_atual: number;
  media_diaria_esperada: number;
  dia_realizado: number;
  dia_esperado: number;
  semana_realizado: number;
  semana_esperado: number;
  mes_realizado: number;
  mes_esperado: number;
};

export type AlertasClientesResposta = {
  disponivel: boolean;
  motivo: string | null;
  data_referencia: string | null;
  dia_referencia: string | null;
  semana_inicio: string | null;
  semana_fim: string | null;
  dias_uteis_decorridos: number;
  alertas: AlertaRitmoCliente[];
  regras: RegraAlertaCliente[];
  loja: string | null;
  resumo: {
    ativos: number;
    quedas: number;
    altas: number;
    clientes_avaliados: number;
  };
};

export type ClientesBuscaResposta = {
  itens: ItemClienteBusca[];
  total: number;
  limitado: boolean;
};

export type PainelClienteParametros = {
  empresa: string;
  cliente: string;
  loja?: string | null;
  posicao?: number;
  total?: number;
};

/** Gera no backend o PDF 16:9 do cliente monitorado e devolve o arquivo pronto. */
export async function gerarPainelCliente(
  parametros: PainelClienteParametros,
): Promise<Blob> {
  const res = await chamar('/api/relatorios/cliente/painel', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(parametros),
  });
  if (!res.ok) {
    await tratarResposta<never>(res);
  }
  return res.blob();
}

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
  const res = await chamar(`/api/clientes/buscar?${params}`, { headers: authHeaders() });
  const dados = await tratarResposta<{ itens: ItemClienteBusca[] }>(res);
  return Array.isArray(dados.itens) ? dados.itens : [];
}

/** Catálogo amplo usado pela tela dedicada de acompanhamento de clientes. */
export async function obterBaseClientes(
  empresa: string,
  loja?: string | null,
): Promise<ClientesBuscaResposta> {
  const params = new URLSearchParams({ empresa, limite: '5000' });
  if (loja) params.set('loja', loja);
  return comCache(`base_clientes_${empresa}_${loja || ''}`, async () => {
    const res = await chamar(`/api/clientes/buscar?${params}`, { headers: authHeaders() });
    const dados = await tratarResposta<ClientesBuscaResposta>(res);
    return {
      itens: Array.isArray(dados.itens) ? dados.itens : [],
      total: Number(dados.total) || 0,
      limitado: Boolean(dados.limitado),
    };
  });
}

export async function salvarTagsUmCliente(
  empresa: string,
  cliente: string,
  tags: TagCliente[],
  loja?: string | null,
): Promise<TagsClientesResposta> {
  const res = await chamar(
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
  const res = await chamar(`/api/explorar/schema${q}`, { headers: authHeaders(), signal });
  return tratarResposta(res);
}

export async function explorarAgregar(
  parametros: ParametrosExplorar,
  signal?: AbortSignal,
): Promise<ExplorarAgregado> {
  const res = await chamar('/api/explorar/agregar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(parametros),
    signal,
  });
  return tratarResposta(res);
}

export async function ensureBaseEmpresa(nome: string): Promise<void> {
  const res = await chamar(`/api/empresas/${encodeURIComponent(nome)}/ensure-base`, {
    method: 'POST',
    headers: authHeaders(),
  });
  await tratarResposta(res);
}

// ---------------------------------------------------------------------------
// Dashboard (rota / pública — endpoints sem autenticação no backend)
// ---------------------------------------------------------------------------

export async function listarEmpresasDashboard(): Promise<string[]> {
  const res = await chamar('/api/dashboard/empresas');
  return tratarResposta(res);
}

/**
 * Lojas da empresa, para o seletor de escopo da sidebar. Vem do resumo leve, não
 * da base — o seletor aparece até no Dashboard público. Empresa sem summary
 * gerado responde lista vazia.
 */
export async function listarLojasEmpresa(empresa: string): Promise<string[]> {
  const res = await chamar(`/api/dashboard/empresas/${encodeURIComponent(empresa)}/lojas`);
  const dados: { lojas?: string[] } = await tratarResposta(res);
  return dados.lojas ?? [];
}

export interface VersaoApp {
  versao: string;
  app: string;
}

/** Versão do backend em execução. Exibida em Configurações para o suporte. */
export async function obterVersao(): Promise<VersaoApp> {
  const res = await chamar('/api/versao');
  return tratarResposta(res);
}

export interface StatusAtualizacao {
  versao_atual: string;
  versao_disponivel: string | null;
  /** Só true quando o pacote está no canal e íntegro; o botão depende disto. */
  atualizavel: boolean;
  /** Sempre preenchido, inclusive quando não há o que atualizar. */
  motivo: string;
  notas: string;
  data: string;
}

export async function obterCaminhoAtualizacoes(): Promise<string> {
  const res = await chamar('/api/config/caminho-atualizacoes', { headers: authHeaders() });
  const dados = await tratarResposta<{ caminho: string | null }>(res);
  return dados.caminho ?? '';
}

/** Caminho vazio limpa o canal e desliga a verificação de atualização. */
export async function definirCaminhoAtualizacoes(caminho: string): Promise<string> {
  const res = await chamar('/api/config/caminho-atualizacoes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ caminho }),
  });
  const dados = await tratarResposta<{ caminho: string }>(res);
  return dados.caminho;
}

/**
 * Status do canal. O backend responde de um cache de 15 min alimentado no boot;
 * `forcar` ignora o cache, para quando o usuário pede a verificação na mão.
 */
export async function obterRegeneracao(): Promise<boolean> {
  const res = await chamar('/api/config/regeneracao', { headers: authHeaders() });
  const dados = await tratarResposta<{ permitida: boolean }>(res);
  return dados.permitida;
}

export async function definirRegeneracao(permitida: boolean): Promise<boolean> {
  const res = await chamar('/api/config/regeneracao', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ permitida }),
  });
  const dados = await tratarResposta<{ permitida: boolean }>(res);
  return dados.permitida;
}

/** Público — Dashboard e demais telas aplicam os cortes do Relatórios sem login. */
export async function obterAplicarCortesRelatorios(auth = false): Promise<boolean> {
  const res = await chamar(
    auth ? '/api/config/aplicar-cortes-relatorios' : '/api/dashboard/aplicar-cortes-relatorios',
    { headers: auth ? authHeaders() : {} },
  );
  const dados = await tratarResposta<{ ativo: boolean }>(res);
  return dados.ativo;
}

export async function definirAplicarCortesRelatorios(ativo: boolean, auth = false): Promise<boolean> {
  const res = await chamar(
    auth ? '/api/config/aplicar-cortes-relatorios' : '/api/dashboard/aplicar-cortes-relatorios',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(auth ? authHeaders() : {}) },
      body: JSON.stringify({ ativo }),
    },
  );
  const dados = await tratarResposta<{ ativo: boolean }>(res);
  return dados.ativo;
}

export interface EstadoPasta {
  suportado: boolean;
  caminho: string | null;
  arquivos: number;
  fixados: number;
  /** Arquivos que ainda são placeholder: a primeira leitura paga o download. */
  na_nuvem: number;
  bytes: number;
}

export interface DadosNoDisco {
  fonte: EstadoPasta;
  trabalho: EstadoPasta;
}

export async function obterDadosNoDisco(): Promise<DadosNoDisco> {
  const res = await chamar('/api/config/dados-no-disco', { headers: authHeaders() });
  return tratarResposta(res);
}

export async function definirDadosNoDisco(fixar: boolean): Promise<DadosNoDisco> {
  const res = await chamar('/api/config/dados-no-disco', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ fixar }),
  });
  return tratarResposta(res);
}

export interface InicioAutomatico {
  /** false na versão rodando do fonte: não há executável para agendar. */
  disponivel: boolean;
  logon: boolean;
  /** "HH:MM" ou null quando não há agendamento. */
  horario: string | null;
  motivo: string;
}

export async function obterInicioAutomatico(): Promise<InicioAutomatico> {
  const res = await chamar('/api/config/inicio-automatico', { headers: authHeaders() });
  return tratarResposta(res);
}

export async function definirInicioAutomatico(
  logon: boolean,
  horario: string | null,
): Promise<InicioAutomatico> {
  const res = await chamar('/api/config/inicio-automatico', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ logon, horario }),
  });
  return tratarResposta(res);
}

export async function obterStatusAtualizacao(forcar = false): Promise<StatusAtualizacao> {
  const url = forcar ? '/api/atualizacoes/status?forcar=true' : '/api/atualizacoes/status';
  const res = await chamar(url, { headers: authHeaders() });
  return tratarResposta(res);
}

/**
 * Dispara a troca da instalação. O backend responde e então se encerra, por isso
 * quem chama deve tratar a perda de conexão a seguir como esperada, não como
 * falha — o app volta sozinho em alguns instantes.
 */
export async function aplicarAtualizacao(): Promise<{ versao: string; mensagem: string }> {
  const res = await chamar('/api/atualizacoes/aplicar', {
    method: 'POST',
    headers: authHeaders(),
  });
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
  const res = await chamar(url, {
    method: 'POST',
    headers: auth ? authHeaders() : undefined,
  });
  return tratarResposta(res);
}

export async function obterSummaryEmpresa(
  empresa: string,
  signal?: AbortSignal,
  grupos?: string,
): Promise<DashboardData> {
  try {
    const qs = grupos ? `?grupos_clientes=${encodeURIComponent(grupos)}` : '';
    const res = await chamar(`/api/dashboard/summary/${encodeURIComponent(empresa)}${qs}`, { signal });
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

export interface PontoMargemPrice {
  periodo: string;
  rotulo: string;
  receita: number;
  cmv: number;
  lucro: number;
  margem: number | null;
  qtd: number;
  dias_venda: number;
  lucro_dia: number | null;
  qtd_dia: number | null;
}

export interface RespostaMargemPrice {
  disponivel: boolean;
  serie_mensal: PontoMargemPrice[];
}

/** Margem mensal ponderada da empresa inteira (todas as lojas, ver
 * `backend/margem_price.py`) — fonte mais precisa que a aproximação por
 * descrição calculada no frontend. `disponivel=false` quando a empresa ainda
 * não tem CNPJ mapeado ou parquet gerado; a tela cai de volta na aproximação. */
export async function obterMargemPrice(
  empresa: string,
  signal?: AbortSignal,
): Promise<RespostaMargemPrice> {
  const res = await chamar(`/api/dashboard/margem-price/${encodeURIComponent(empresa)}`, { signal });
  return tratarResposta(res);
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
  const res = await chamar('/api/analisar', {
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
  const res = await chamar(`/api/exportar/${formato}`, {
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
// Estoque × velocidade de venda
// ---------------------------------------------------------------------------

export type StatusCoberturaEstoque =
  | 'normal'
  | 'rupture'
  | 'out_of_stock'
  | 'negative'
  | 'stalled'
  | 'excess'
  | 'no_sales';

export type ItemCoberturaEstoque = {
  sku: string;
  codigo_interno: string;
  nome: string;
  fabricante: string;
  estoque: number;
  venda_media: number;
  cobertura: number | null;
  valor_estoque: number;
  variacao_pct: number | null;
  status: StatusCoberturaEstoque;
};

export type CoberturaEstoqueResposta = {
  disponivel: boolean;
  mensagem: string | null;
  empresa: string;
  loja: string | null;
  lojas: string[];
  periodo_inicio: string | null;
  periodo_fim: string | null;
  meses: number;
  itens: ItemCoberturaEstoque[];
  itens_exibidos: number;
  limitado: boolean;
  resumo: {
    produtos: number;
    valor_estoque: number;
    ruptura: number;
    excesso: number;
    sem_giro: number;
  };
};

export async function obterCoberturaEstoque(
  empresa: string,
  parametros: { loja?: string | null; meses?: number; limite?: number; usarMesesFechados?: boolean } = {},
  signal?: AbortSignal,
): Promise<CoberturaEstoqueResposta> {
  const query = new URLSearchParams();
  if (parametros.loja) query.set('loja', parametros.loja);
  if (parametros.meses) query.set('meses', String(parametros.meses));
  if (parametros.limite) query.set('limite', String(parametros.limite));
  if (parametros.usarMesesFechados === false) query.set('usar_mes_fechado', 'false');
  const qs = query.toString() ? `?${query}` : '';
  const url = `/api/estoque/cobertura/${encodeURIComponent(empresa)}${qs}`;
  // Signal fica de fora do fetch cacheado: FastAPI síncrono não aborta, e o
  // Strict Mode / troca de aba só cancelava o cliente — o worker seguia ocupado
  // e o retry do mapa nunca terminava no primeiro open.
  if (signal?.aborted) {
    throw new DOMException('Aborted', 'AbortError');
  }
  return comCache(`cobertura_${empresa}_${qs}`, async () => {
    const res = await chamar(url, { headers: authHeaders() });
    return tratarResposta(res);
  });
}

/** Produto nas listas da visão geral: o mesmo item, sem os campos que só o mapa usa. */
export type ItemResumoEstoque = {
  sku: string;
  codigo_interno: string;
  nome: string;
  fabricante: string;
  estoque: number;
  venda_media: number;
  cobertura: number | null;
  valor_estoque: number;
  /** Meses desde a última saída no histórico inteiro; null = nunca vendeu. */
  meses_sem_venda: number | null;
  status: StatusCoberturaEstoque;
};

export type ResumoEstoqueResposta = {
  disponivel: boolean;
  mensagem: string | null;
  empresa: string;
  loja: string | null;
  lojas: string[];
  periodo_inicio: string | null;
  periodo_fim: string | null;
  meses: number;
  resumo: {
    produtos: number;
    valor_estoque: number;
    ruptura: number;
    excesso: number;
    sem_giro: number;
    valor_parado: number;
    /** Meses de estoque em dinheiro: capital ÷ saída mensal a custo. */
    cobertura_media: number | null;
  };
  por_situacao: { status: StatusCoberturaEstoque; produtos: number; valor_estoque: number }[];
  ruptura_iminente: ItemResumoEstoque[];
  capital_parado_fabricante: { fabricante: string; valor_estoque: number; produtos: number }[];
  dinheiro_dormindo: ItemResumoEstoque[];
};

export async function obterResumoEstoque(
  empresa: string,
  parametros: { loja?: string | null; meses?: number; usarMesesFechados?: boolean; grupos?: string } = {},
  signal?: AbortSignal,
): Promise<ResumoEstoqueResposta> {
  const query = new URLSearchParams();
  if (parametros.loja) query.set('loja', parametros.loja);
  if (parametros.meses) query.set('meses', String(parametros.meses));
  if (parametros.usarMesesFechados === false) query.set('usar_mes_fechado', 'false');
  if (parametros.grupos) query.set('grupos_clientes', parametros.grupos);
  const qs = query.toString() ? `?${query}` : '';
  const url = `/api/estoque/resumo/${encodeURIComponent(empresa)}${qs}`;
  if (signal?.aborted) {
    throw new DOMException('Aborted', 'AbortError');
  }
  return comCache(`resumo_estoque_${empresa}_${qs}`, async () => {
    const res = await chamar(url, { headers: authHeaders() });
    return tratarResposta(res);
  });
}

// ---------------------------------------------------------------------------
// Despesas (Controladoria)
// ---------------------------------------------------------------------------

export type PontoDespesaMensal = {
  periodo: string;
  rotulo: string;
  valor: number;
};

export type ItemDespesaCategoria = {
  categoria: string;
  valor: number;
  pct: number;
  grupo_abc: string | null;
  tendencia_pct: number | null;
};

export type ItemDespesaLoja = {
  loja: string;
  valor: number;
};

export type PontoDespesaMensalCategoria = {
  periodo: string;
  rotulo: string;
  valores: Record<string, number>;
};

export type SerieMensalCategorias = {
  categorias: string[];
  pontos: PontoDespesaMensalCategoria[];
};

export type GrupoAbcDespesa = {
  grupo: string;
  quantidade: number;
  valor: number;
  pct: number;
};

export type CurvaAbcCategorias = {
  cortes: number[];
  grupos: GrupoAbcDespesa[];
};

export type ResumoDespesasResposta = {
  empresa: string;
  loja: string | null;
  lojas: string[];
  periodo_inicio: string | null;
  periodo_fim: string | null;
  meses: number;
  resumo: {
    total: number;
    media_mensal: number;
    mes_atual: number;
    mes_anterior: number;
    variacao_pct: number | null;
    mes_mesmo_periodo_ano_anterior: number | null;
    variacao_anual_pct: number | null;
  };
  serie_mensal: PontoDespesaMensal[];
  serie_mensal_categorias: SerieMensalCategorias;
  por_categoria: ItemDespesaCategoria[];
  por_loja: ItemDespesaLoja[];
  curva_abc_categorias: CurvaAbcCategorias;
};

export async function obterResumoDespesas(
  empresa: string,
  parametros: { loja?: string | null; meses?: number; usarMesesFechados?: boolean } = {},
  signal?: AbortSignal,
): Promise<ResumoDespesasResposta> {
  const query = new URLSearchParams();
  if (parametros.loja) query.set('loja', parametros.loja);
  if (parametros.meses) query.set('meses', String(parametros.meses));
  if (parametros.usarMesesFechados === false) query.set('usar_mes_fechado', 'false');
  const qs = query.toString() ? `?${query}` : '';
  const url = `/api/despesas/${encodeURIComponent(empresa)}${qs}`;
  if (signal?.aborted) {
    throw new DOMException('Aborted', 'AbortError');
  }
  return comCache(`resumo_despesas_${empresa}_${qs}`, async () => {
    const res = await chamar(url, { headers: authHeaders() });
    return tratarResposta(res);
  });
}

export type ItemDetalheDespesa = {
  loja: string;
  categoria: string;
  ano: number;
  mes: number;
  valor: number;
};

export type DetalheDespesasResposta = {
  empresa: string;
  loja: string | null;
  itens: ItemDetalheDespesa[];
  total_itens: number;
  limitado: boolean;
};

export async function obterDetalheDespesas(
  empresa: string,
  parametros: { loja?: string | null; periodo?: string | null; categoria?: string | null; limite?: number } = {},
  signal?: AbortSignal,
): Promise<DetalheDespesasResposta> {
  const query = new URLSearchParams();
  if (parametros.loja) query.set('loja', parametros.loja);
  if (parametros.periodo) query.set('periodo', parametros.periodo);
  if (parametros.categoria) query.set('categoria', parametros.categoria);
  if (parametros.limite) query.set('limite', String(parametros.limite));
  const qs = query.toString() ? `?${query}` : '';
  const res = await chamar(
    `/api/despesas/${encodeURIComponent(empresa)}/detalhe${qs}`,
    { headers: authHeaders(), signal },
  );
  return tratarResposta(res);
}

// ---------------------------------------------------------------------------
// Pós precificação
// ---------------------------------------------------------------------------

export type PeriodoIso = { inicio: string | null; fim: string | null };

export type SituacaoPrecificacao = 'acima' | 'abaixo' | 'no_alvo' | 'sem_venda' | 'sem_alvo' | 'nao_precificado';

export type PontoSeriePrecificacao = {
  periodo: string;
  rotulo: string;
  receita: number;
  lucro: number;
  qtd: number;
  margem: number | null;
  dias_venda: number;
  lucro_dia: number | null;
  qtd_dia: number | null;
};

export type SituacoesPrecificacao = Record<SituacaoPrecificacao, number>;

export type ChaveJanelaFixa = 'semana' | 'quinzena' | 'mes';

export type JanelaFixaPrecificacao = {
  dias: number;
  /** false = a janela "depois" ainda não fechou (corte recente demais). */
  completa: boolean;
  receita_antes: number;
  receita_depois: number;
  lucro_antes: number;
  lucro_depois: number;
  qtd_antes: number;
  qtd_depois: number;
  margem_antes: number | null;
  margem_depois: number | null;
  dias_venda_antes: number;
  dias_venda_depois: number;
  lucro_dia_antes: number | null;
  lucro_dia_depois: number | null;
  qtd_dia_antes: number | null;
  qtd_dia_depois: number | null;
  variacao_receita_pct: number | null;
  variacao_lucro_pct: number | null;
  variacao_qtd_pct: number | null;
  margem_alvo: number | null;
  gap_alvo_pp: number | null;
};

export type JanelasFixasPrecificacao = Record<ChaveJanelaFixa, JanelaFixaPrecificacao>;

export type ItemPosPrecificacao = {
  nome: string;
  /** Falso = família/fabricante fora da rodada (só no recorte "todos"). */
  precificado: boolean;
  skus_dump: number;
  receita_dump: number;
  margem_anterior_dump: number | null;
  margem_alvo: number | null;
  receita_antes: number;
  receita_depois: number;
  lucro_antes: number;
  lucro_depois: number;
  qtd_antes: number;
  qtd_depois: number;
  margem_antes: number | null;
  margem_depois: number | null;
  dias_venda_antes: number;
  dias_venda_depois: number;
  lucro_dia_antes: number | null;
  lucro_dia_depois: number | null;
  qtd_dia_antes: number | null;
  qtd_dia_depois: number | null;
  variacao_receita_pct: number | null;
  variacao_lucro_pct: number | null;
  variacao_qtd_pct: number | null;
  gap_alvo_pp: number | null;
  situacao: SituacaoPrecificacao;
  serie_mensal: PontoSeriePrecificacao[];
  serie_diaria: PontoSeriePrecificacao[];
  janelas: JanelasFixasPrecificacao;
};

export type ResumoPosPrecificacao = {
  receita_dump: number;
  margem_anterior_dump: number | null;
  margem_alvo: number | null;
  receita_antes: number;
  receita_depois: number;
  lucro_antes: number;
  lucro_depois: number;
  qtd_antes: number;
  qtd_depois: number;
  margem_antes: number | null;
  margem_depois: number | null;
  dias_venda_antes: number;
  dias_venda_depois: number;
  lucro_dia_antes: number | null;
  lucro_dia_depois: number | null;
  qtd_dia_antes: number | null;
  qtd_dia_depois: number | null;
  variacao_receita_pct: number | null;
  variacao_lucro_pct: number | null;
  variacao_qtd_pct: number | null;
  gap_alvo_pp: number | null;
  situacoes: SituacoesPrecificacao;
  janelas: JanelasFixasPrecificacao;
};

/** Uma rodada disponível no dump: um dia de `data_exportacao`.
 *  `linhas` e `pares` vêm junto porque rodada varia de 3 a ~15 mil linhas na
 *  mesma empresa — sem o tamanho à vista, rodada pequena parece tela quebrada
 *  em vez de escolha. */
export type RodadaPrecificacao = {
  dia: string;
  linhas: number;
  pares: number;
};

export type PosPrecificacaoResposta = {
  empresa: string;
  loja: string | null;
  /** Todas as rodadas do arquivo, da mais recente para a mais antiga. */
  rodadas: RodadaPrecificacao[];
  /** Rodada que este resultado calculou. */
  rodada: string | null;
  data_precificacao: string | null;
  periodo_corte: string | null;
  periodo_antes: PeriodoIso;
  periodo_depois: PeriodoIso;
  dias: number;
  linhas_dump: number;
  familias: number;
  fabricantes_qtd: number;
  pares: number;
  skus_com_preco_sugerido: number;
  tem_movimento_depois: boolean;
  resumo: ResumoPosPrecificacao;
  serie_mensal: PontoSeriePrecificacao[];
  serie_diaria: PontoSeriePrecificacao[];
  produtos: ItemPosPrecificacao[];
  fabricantes: ItemPosPrecificacao[];
};

// ---------------------------------------------------------------------------
// Precificação — aba Pós-precificação (histórico por SKU, sem prender a rodada)
// ---------------------------------------------------------------------------

export type SituacaoHistorico = 'acima' | 'no_alvo' | 'abaixo' | 'sem_venda' | 'sem_alvo';
export type NivelHistorico = 'familia' | 'fabricante' | 'par' | 'sku' | 'rodada';

export type MetricasHistorico = {
  alvo: number | null;
  margem_no_dia: number | null;
  margem_antes: number | null;
  margem_depois: number | null;
  gap_pp: number | null;
  receita_antes: number;
  receita_depois: number;
  lucro_dia_antes: number | null;
  lucro_dia_depois: number | null;
  qtd_dia_antes: number | null;
  qtd_dia_depois: number | null;
  efeito_lucro_pct: number | null;
  efeito_qtd_pct: number | null;
  situacao: SituacaoHistorico;
};

export type LinhaHistorico = MetricasHistorico & {
  nome: string;
  skus: number;
  precificacoes: number;
  ultima: string | null;
  faixas: string[];
  descricao?: string;
  fabricante?: string;
  fx?: string;
};

export type RodadaLinhaTempo = {
  dia: string;
  skus: number;
  pares: number;
  mensuravel: boolean;
  no_periodo: boolean;
  selecionada: boolean;
};

export type MarcadorPrecificacao = { dia: string; periodo: string; skus: number };

export type KpisHistorico = Partial<MetricasHistorico> & {
  skus: number;
  pares: number;
  rodadas: number;
  receita_coberta_pct: number | null;
  pct_acima: number | null;
  situacoes: Partial<Record<SituacaoHistorico, number>>;
};

export type HistoricoPrecificacaoResposta = {
  empresa: string;
  periodo_dias: number;
  janela_dias: number;
  inicio_periodo: string | null;
  inicio_movimento: string | null;
  fim_movimento: string | null;
  faixas_disponiveis: string[];
  linha_tempo: RodadaLinhaTempo[];
  kpis: KpisHistorico;
  serie_mensal: PontoSeriePrecificacao[];
  marcadores: MarcadorPrecificacao[];
  nivel: NivelHistorico;
  linhas: LinhaHistorico[];
  total_linhas: number;
};

export type ItemHistoricoPrecificacao = {
  nivel: NivelHistorico;
  nome: string;
  skus_total: number;
  fabricantes: number;
  faixas: string[];
  historico: {
    dia: string;
    alvo: number | null;
    margem_no_dia: number | null;
    skus: number;
    mensuravel: boolean;
    no_filtro: boolean;
  }[];
  serie_mensal: PontoSeriePrecificacao[];
  marcadores: MarcadorPrecificacao[];
  skus: (MetricasHistorico & { codigo: string; descricao: string; fabricante: string; fx: string })[];
};

export type FiltrosHistorico = {
  periodo: number;
  rodadas: string[];
  faixas: string[];
};

function queryFiltros(filtros: FiltrosHistorico, extra: Record<string, string>): string {
  const q = new URLSearchParams({ periodo: String(filtros.periodo), ...extra });
  if (filtros.rodadas.length) q.set('rodadas', filtros.rodadas.join(','));
  if (filtros.faixas.length) q.set('faixas', filtros.faixas.join(','));
  return q.toString();
}

/** Sem cache em localStorage de propósito: o dump muda quando a coleta do
 *  Postgres roda, e a chave não teria como saber — o backend já cacheia o
 *  cálculo pesado, e cada filtro custa ~1 s. */
export async function obterHistoricoPrecificacao(
  empresa: string,
  filtros: FiltrosHistorico & { nivel: NivelHistorico; todos: boolean; busca: string },
  signal?: AbortSignal,
): Promise<HistoricoPrecificacaoResposta> {
  const extra: Record<string, string> = { nivel: filtros.nivel };
  if (filtros.todos) extra.todos = 'true';
  if (filtros.busca.trim()) extra.busca = filtros.busca.trim();
  const res = await chamar(
    `/api/precificacao/${encodeURIComponent(empresa)}/historico?${queryFiltros(filtros, extra)}`,
    { headers: authHeaders(), signal },
  );
  return tratarResposta(res);
}

export async function obterItemHistoricoPrecificacao(
  empresa: string,
  filtros: FiltrosHistorico & { nivel: Exclude<NivelHistorico, 'rodada'>; nome: string },
  signal?: AbortSignal,
): Promise<ItemHistoricoPrecificacao> {
  const res = await chamar(
    `/api/precificacao/${encodeURIComponent(empresa)}/historico/item?${queryFiltros(filtros, { nivel: filtros.nivel, nome: filtros.nome })}`,
    { headers: authHeaders(), signal },
  );
  return tratarResposta(res);
}

// ---------------------------------------------------------------------------
// Precificação: SKUs a precificar (backend/a_precificar.py)
// ---------------------------------------------------------------------------

export type ProvaPrecificar = 'margem' | 'custo' | 'volume' | 'alvo';

export type ItemAPrecificar = {
  codigo: string;
  descricao: string;
  fabricante: string;
  curva: 'A' | 'B' | 'C';
  provas: ProvaPrecificar[];
  part_receita: number | null;
  part_fabricante: number | null;
  receita_base: number | null;
  margem_base: number | null;
  margem_recente: number | null;
  alvo: number | null;
  dia_alvo: string | null;
  /** Alvo vigente, ou a margem da base quando o SKU nunca foi precificado. */
  referencia: number | null;
  gap: number | null;
  var_custo: number | null;
  var_preco: number | null;
  var_qtd: number | null;
  qtd_dia_recente: number | null;
  preco_atual: number | null;
  custo_atual: number | null;
  preco_sugerido: number | null;
  reajuste: number | null;
  perdido_dia: number | null;
};

/** Descrição × fabricante — o grão em que o PRICE precifica. Soma os SKUs
 *  sinalizados do par; `provas` conta quantos SKUs têm cada uma. */
export type ParAPrecificar = {
  descricao: string;
  fabricante: string;
  curva: 'A' | 'B' | 'C';
  skus: number;
  skus_total: number;
  provas: Partial<Record<ProvaPrecificar, number>>;
  part_receita: number | null;
  part_fabricante: number | null;
  receita_base: number | null;
  margem_base: number | null;
  margem_recente: number | null;
  alvo: number | null;
  dia_alvo: string | null;
  referencia: number | null;
  gap: number | null;
  var_custo: number | null;
  var_preco: number | null;
  var_qtd: number | null;
  reajuste: number | null;
  perdido_dia: number | null;
  /** Falso nos pares que só o GPS aponta (sem prova do A precificar). Ausente em resposta antiga. */
  sinalizado?: boolean;
  /** `null` fora das 36 descrições da tabela 2D. */
  gps?: GpsPar | null;
};

export type FabricanteAPrecificar = {
  nome: string;
  perdido_dia: number | null;
  pares: number;
  skus: number;
  part_receita: number | null;
};

export type APrecificarResposta = {
  empresa: string;
  janela: {
    inicio_base: string;
    inicio_recente: string;
    fim: string;
    dias_base: number;
    dias_recente: number;
  } | null;
  resumo: {
    /** Produtos (descrições) sinalizados. Ausente em resposta antiga. */
    produtos?: number;
    pares: number;
    skus: number;
    curva_a: number;
    fabricantes: number;
    receita_em_jogo: number | null;
    part_receita: number | null;
    perdido_dia: number | null;
    custo_sem_repasse: number;
    com_alvo: number;
  };
  fabricantes: FabricanteAPrecificar[];
  /** A lista da tela, por produto (descrição): sinalizados primeiro, na ordem do
   *  A precificar; depois os que só o GPS aponta. Ausente em resposta antiga. */
  produtos?: ProdutoAPrecificar[];
  /** Só os sinalizados. */
  total_produtos?: number;
  /** Descrição × fabricante sinalizados (os mesmos que vêm dentro de cada produto). */
  pares: ParAPrecificar[];
  total_pares: number;
  /** Ausente em resposta gravada antes do GPS entrar na tela. */
  gps?: ResumoGps;
};

/** Um produto (descrição) da lista, somando os fabricantes; `fabricantes` abre embaixo da linha. */
export type ProdutoAPrecificar = Omit<ParAPrecificar, 'fabricante' | 'part_fabricante'> & {
  fabricantes: ParAPrecificar[];
};

export type RecomendacaoGps = 'reajustar' | 'etapas' | 'oportunidade' | 'divergencia' | 'reduzir' | 'segurar' | 'manter';

/** GPS de um par — calculado pela descrição, igual para todos os fabricantes dela.
 *  Unidades em pontos percentuais. Regras em `backend/gps_dispersao.py`. */
export type GpsPar = {
  classe: 'abaixo' | 'dentro' | 'acima';
  participacao: number | null;
  /** Margem da descrição − margem geral da empresa. */
  dispersao: number | null;
  /** Perfil em que o preço atual da descrição cai; `null` fora de todas as faixas. */
  perfil_item: string | null;
  /** Faixa do perfil da empresa; `null` no lado aberto do "Até X". */
  faixa: [number | null, number | null];
  regra: string;
  /** Limite MENOR/MAIOR; `null` em "Acima da Média", que vai até a borda da faixa. */
  limite_alvo: number | null;
  distancia: number | null;
  teto: number | null;
  /** Distância cortada pelo teto. */
  aplicado: number | null;
  recomendacao: RecomendacaoGps;
  /** O que mexer nesta rodada: metade em "Subir em etapas", zero em Segurar/Divergência/Manter. */
  ajuste_agora: number | null;
  margem_alvo: number | null;
};

export type ResumoGps =
  | {
      disponivel: true;
      perfil: {
        meses: string[];
        margem: number | null;
        despesas: number | null;
        taxa_retorno: number | null;
        perfil: string;
        rotulo: string;
      };
      margem_geral: number | null;
      descricoes: number;
      cobertura_receita: number | null;
      recomendacoes: {
        id: RecomendacaoGps;
        rotulo: string;
        direcao: 'subir' | 'descer' | 'manter';
        produtos: number;
        perdido_dia: number | null;
      }[];
      /** Produtos sinalizados fora das 36 descrições do GPS. */
      produtos_fora: number;
    }
  | { disponivel: false; motivo: string };

export type SemanaMargem = { semana: string; margem: number | null; receita: number | null; qtd: number | null };

export type DetalheParAPrecificar = {
  descricao: string;
  /** `null` no painel do produto inteiro. */
  fabricante: string | null;
  semanas: SemanaMargem[];
  skus: ItemAPrecificar[];
  total_skus: number;
};

export async function obterAPrecificar(empresa: string, signal?: AbortSignal): Promise<APrecificarResposta> {
  const res = await chamar(`/api/precificacao/${encodeURIComponent(empresa)}/a-precificar`, {
    headers: authHeaders(),
    signal,
  });
  return tratarResposta(res);
}

export async function obterParAPrecificar(
  empresa: string,
  par: { descricao: string; fabricante?: string | null },
  signal?: AbortSignal,
): Promise<DetalheParAPrecificar> {
  // Sem fabricante, o produto inteiro (todos os fabricantes da descrição).
  const query = new URLSearchParams({ descricao: par.descricao });
  if (par.fabricante != null) query.set('fabricante', par.fabricante);
  const res = await chamar(
    `/api/precificacao/${encodeURIComponent(empresa)}/a-precificar/par?${query}`,
    { headers: authHeaders(), signal },
  );
  return tratarResposta(res);
}

// ---------------------------------------------------------------------------
// Monitoramento de empresas
// ---------------------------------------------------------------------------

export type MetricaMonitor =
  | 'receita'
  | 'qtd'
  | 'clientes'
  | 'receita_dia'
  | 'lucro'
  | 'lucro_dia'
  /** % de receita em produtos sem descrição harmonizada (ver PRODUTO). */
  | 'nao_harmonizado';

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
  dias_venda_janela?: number | null;
  meses_serie?: number;
  /** Lojas da empresa (mesma fonte do seletor da sidebar), para o combobox do card. */
  lojas?: string[];
  /** Lucro/lucro por dia não são filtráveis por loja (CMV só existe agregado
   *  por empresa) — o card chega assim quando uma loja está selecionada. */
  indisponivel_por_loja?: boolean;
  /** Só na métrica `nao_harmonizado`: base do percentual, em produtos e em receita. */
  produtos_total?: number;
  produtos_nao_harmonizados?: number;
  receita_total?: number;
  receita_nao_harmonizada?: number;
};

export type MonitorResposta = {
  metrica: MetricaMonitor;
  meses: number;
  empresas: EmpresaMonitor[];
  favoritas: string[];
};

export async function obterMonitorEmpresas(
  parametros: {
    metrica?: MetricaMonitor;
    meses?: number;
    forcar?: boolean;
    /** Restringe a uma única empresa — usado para recalcular só um card ao trocar de loja. */
    empresa?: string;
    /** Filtra a série daquela loja; vazio/omitido = todas as lojas somadas. */
    loja?: string;
  } = {},
  signal?: AbortSignal,
): Promise<MonitorResposta> {
  const query = new URLSearchParams();
  if (parametros.metrica) query.set('metrica', parametros.metrica);
  if (parametros.meses) query.set('meses', String(parametros.meses));
  if (parametros.forcar) query.set('forcar', 'true');
  if (parametros.empresa) query.set('empresa', parametros.empresa);
  if (parametros.loja) query.set('loja', parametros.loja);
  const qs = query.toString();

  // Se forçado (atualizar tudo), não usa cache (na verdade comCache(..., forcar) resolveria, mas como não temos forcar no hook das páginas, ignoramos o cache manual aqui)
  if (parametros.forcar) {
    const res = await chamar(`/api/monitor/empresas?${qs}`, { headers: authHeaders(), signal });
    return tratarResposta(res);
  }

  return comCache(`monitor_${qs}`, async () => {
    const res = await chamar(`/api/monitor/empresas?${qs}`, { headers: authHeaders(), signal });
    return tratarResposta(res);
  });
}

export async function salvarFavoritas(empresas: string[]): Promise<{ empresas: string[] }> {
  const res = await chamar('/api/monitor/favoritas', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ empresas }),
  });
  return tratarResposta(res);
}

// ---------------------------------------------------------------------------
// Vendedores — último mês vs média dos 6 anteriores
// ---------------------------------------------------------------------------

export type ItemRankingVendedor = {
  vendedor: string;
  receita_atual: number;
  receita_media: number;
  variacao: number | null;
  qtd_atual: number;
  clientes_atual: number;
  alerta: boolean;
};

export type ItemFichaVendedor = {
  nome?: string;
  cliente?: string;
  produto?: string;
  fabricante?: string;
  receita_atual: number;
  receita_media: number;
  variacao: number | null;
  qtd_atual: number;
  clientes_atual: number;
  alerta: boolean;
};

export type RankingVendedoresResposta = {
  disponivel: boolean;
  mensagem: string | null;
  empresa?: string;
  loja?: string | null;
  periodo_atual: string | null;
  rotulo_periodo: string | null;
  meses_media: number;
  periodo_media_inicio: string | null;
  periodo_media_fim: string | null;
  itens: ItemRankingVendedor[];
  resumo: {
    vendedores: number;
    receita_atual: number;
    maior_alta: { vendedor: string; variacao: number; receita_atual: number } | null;
    maior_queda: { vendedor: string; variacao: number; receita_atual: number } | null;
  };
};

export type PontoSerieVendedor = {
  periodo: string;
  rotulo: string;
  valor: number;
};

export type FichaVendedorResposta = {
  disponivel: boolean;
  vendedor: string;
  periodo_atual: string;
  rotulo_periodo: string;
  meses_media: number;
  periodo_media_inicio: string | null;
  periodo_media_fim: string | null;
  receita_atual: number;
  receita_media: number;
  variacao: number | null;
  qtd_atual: number;
  clientes_atual: number;
  clientes: ItemFichaVendedor[];
  produtos: ItemFichaVendedor[];
  fabricantes: ItemFichaVendedor[];
  serie_mensal: PontoSerieVendedor[];
  alertas: {
    clientes: ItemFichaVendedor[];
    produtos: ItemFichaVendedor[];
    clientes_total?: number;
    produtos_total?: number;
  };
};

export async function obterRankingVendedores(
  empresa: string,
  loja?: string | null,
  _signal?: AbortSignal,
  modoPeriodo: ModoPeriodo = 'fechados',
  grupos?: string,
): Promise<RankingVendedoresResposta> {
  const query = new URLSearchParams();
  if (loja) query.set('loja', loja);
  if (modoPeriodo !== 'fechados') query.set('modo_periodo', modoPeriodo);
  if (grupos) query.set('grupos_clientes', grupos);
  const qs = query.toString() ? `?${query}` : '';
  const url = `/api/vendedores/${encodeURIComponent(empresa)}${qs}`;
  
  return comCache(`ranking_vendedores_${empresa}_${qs}`, async () => {
    const res = await chamar(url, { headers: authHeaders() });
    return tratarResposta(res);
  });
}

export async function obterFichaVendedor(
  empresa: string,
  vendedor: string,
  loja?: string | null,
  signal?: AbortSignal,
  modoPeriodo: ModoPeriodo = 'fechados',
  grupos?: string,
): Promise<FichaVendedorResposta> {
  const query = new URLSearchParams({ vendedor });
  if (loja) query.set('loja', loja);
  if (modoPeriodo !== 'fechados') query.set('modo_periodo', modoPeriodo);
  if (grupos) query.set('grupos_clientes', grupos);
  const res = await chamar(
    `/api/vendedores/${encodeURIComponent(empresa)}/ficha?${query}`,
    { headers: authHeaders(), signal },
  );
  return tratarResposta(res);
}

export type FaixaCurvaClientes = {
  nome: string;
  clientes: number;
  receita: number;
  participacao: number;
};

export type MovimentoCarteiraMes = {
  periodo: string;
  rotulo: string;
  ativos: number;
  novos: number;
  recuperados: number;
  perdidos: number;
  saldo: number;
  receita: number;
};

export type EventoCarteira = {
  cliente: string;
  receita: number;
  /** Só em `perdidos`: mês da última compra. */
  ultimo_mes: string | null;
};

export type TopClientePainel = {
  cliente: string;
  receita_atual: number;
  receita_media: number;
  variacao: number | null;
  qtd_atual: number;
  alerta: boolean;
};

export type TagResumoPainel = {
  id: string;
  rotulo: string;
  cor: string | null;
  clientes: number;
  receita: number;
  participacao: number;
};

export type FaixaScorePainel = {
  faixa: string;
  clientes: number;
};

export type SaldoPeriodoScorePainel = {
  periodo_anterior: string;
  periodo_atual: string;
  /** "set/25→out/25" — usado no tooltip do gráfico, não no eixo (lotado com 11+ pontos). */
  rotulo: string;
  /** "out/25" — o que o eixo X do gráfico mostra. */
  rotulo_curto: string;
  subiu: number;
  desceu: number;
  saldo: number;
};

export type RankingScorePainel = {
  cliente: string;
  score: number;
  subiu: number;
  desceu: number;
  permanencia: number;
};

export type ScoreMigracaoPainel = {
  disponivel: boolean;
  janela_meses: number;
  clientes_score_diferente_zero: number;
  clientes_pior_cauda: number;
  saldo_ultimo_periodo: SaldoPeriodoScorePainel | null;
  distribuicao: FaixaScorePainel[];
  saldo_por_periodo: SaldoPeriodoScorePainel[];
  pior_cauda: RankingScorePainel[];
  melhores: RankingScorePainel[];
};

export type FaixaPotencialPainel = {
  nome: string;
  /** Média do potencial por cliente do grupo — não a soma (grupos têm
   *  tamanhos muito diferentes; somar faria "Demais" dominar só por ter
   *  mais gente, não por potencial individual maior). */
  potencial_medio: number;
  clientes: number;
};

export type RankingPotencialPainel = {
  cliente: string;
  potencial: number;
  /** Média mensal atual do cliente na mesma janela — o "atual" pra comparar
   *  com o potencial (pico dos 3 melhores meses). */
  atual: number;
  /** % do potencial acima (ou abaixo) do atual; null se atual for zero. */
  variacao: number | null;
  grupo: string;
};

export type PotencialCompraPainel = {
  disponivel: boolean;
  janela_meses: number;
  potencial_total: number;
  potencial_medio: number;
  /** Soma da média mensal atual de todos os clientes — o "hoje" pra
   *  comparar com potencial_total (pico). */
  atual_total: number;
  variacao_total: number | null;
  por_grupo: FaixaPotencialPainel[];
  ranking: RankingPotencialPainel[];
};

export type PainelClientesResposta = {
  disponivel: boolean;
  mensagem: string | null;
  empresa?: string;
  loja?: string | null;
  periodo_atual: string | null;
  rotulo_periodo: string | null;
  meses_media: number;
  periodo_media_inicio: string | null;
  periodo_media_fim: string | null;
  janela_inatividade_meses: number;
  janela_abc_meses: number;
  balcao_excluidos: number;
  resumo: {
    clientes_ativos: number;
    clientes_media: number;
    variacao_clientes: number | null;
    receita_atual: number;
    receita_media: number;
    variacao_receita: number | null;
    ticket_medio: number;
    ticket_medio_media: number;
    variacao_ticket: number | null;
    novos: number;
    recuperados: number;
    perdidos: number;
    saldo: number;
  };
  concentracao: {
    clientes: number;
    receita: number;
    clientes_80: number;
    participacao_clientes_80: number;
    faixas: FaixaCurvaClientes[];
  };
  movimento: MovimentoCarteiraMes[];
  eventos: {
    novos: EventoCarteira[];
    recuperados: EventoCarteira[];
    perdidos: EventoCarteira[];
  };
  top_clientes: TopClientePainel[];
  tags: TagResumoPainel[];
  score_migracao: ScoreMigracaoPainel;
  potencial_compra: PotencialCompraPainel;
};

/** Visão geral da carteira (aba 1 da tela de Clientes), calculada no backend. */
export async function obterPainelClientes(
  empresa: string,
  loja?: string | null,
  _signal?: AbortSignal,
  modoPeriodo: ModoPeriodo = 'fechados',
  grupos?: string,
): Promise<PainelClientesResposta> {
  const query = new URLSearchParams();
  const loja_ = queryLoja(loja);
  if (modoPeriodo !== 'fechados') query.set('modo_periodo', modoPeriodo);
  if (grupos) query.set('grupos_clientes', grupos);
  const extra = query.toString();
  const url = loja_
    ? `/api/clientes/${encodeURIComponent(empresa)}/painel${loja_}${extra ? `&${extra}` : ''}`
    : `/api/clientes/${encodeURIComponent(empresa)}/painel${extra ? `?${extra}` : ''}`;

  return comCache(`painel_clientes_${empresa}_${loja || ''}_${modoPeriodo}_${grupos || ''}`, async () => {
    const res = await chamar(url, { headers: authHeaders() });
    return tratarResposta(res);
  });
}

export type ProdutoPotencialCliente = {
  descricao: string;
  receita: number;
  qtd: number;
  participacao: number;
};

export type PotencialProdutosClienteResposta = {
  disponivel: boolean;
  cliente: string;
  /** Rótulos dos meses de maior receita usados no cálculo, ex.: ["jan/26", "mar/26", "jun/26"]. */
  meses: string[];
  receita_total: number;
  potencial: number;
  produtos: ProdutoPotencialCliente[];
  empresa?: string;
  loja?: string | null;
};

/** Top produtos do cliente nos meses de maior receita — detalhe por trás de
 *  uma linha do ranking "Maiores potenciais de compra". */
export async function obterPotencialProdutosCliente(
  empresa: string,
  cliente: string,
  loja?: string | null,
  modoPeriodo: ModoPeriodo = 'fechados',
  grupos?: string,
): Promise<PotencialProdutosClienteResposta> {
  const query = new URLSearchParams();
  query.set('cliente', cliente);
  const loja_ = queryLoja(loja);
  if (modoPeriodo !== 'fechados') query.set('modo_periodo', modoPeriodo);
  if (grupos) query.set('grupos_clientes', grupos);
  const url = `/api/clientes/${encodeURIComponent(empresa)}/potencial-produtos${loja_ ? `${loja_}&` : '?'}${query.toString()}`;

  return comCache(`potencial_produtos_${empresa}_${loja || ''}_${modoPeriodo}_${grupos || ''}_${cliente}`, async () => {
    const res = await chamar(url, { headers: authHeaders() });
    return tratarResposta(res);
  });
}

export type EventoCausaMigracao = {
  periodo_anterior: string;
  periodo_atual: string;
  direcao: 'Subiu' | 'Desceu';
  faixa_anterior: string;
  faixa_atual: string;
  /** Vazio quando nenhuma heurística bateu com folga — não força uma causa
   *  genérica só pra preencher a célula (ver engine._causa_provavel_migracao). */
  causa: string;
};

export type CausaMigracaoClienteResposta = {
  disponivel: boolean;
  cliente: string;
  eventos: EventoCausaMigracao[];
  empresa?: string;
  loja?: string | null;
};

/** Eventos de migração de faixa ABC de um cliente (subiu/desceu), com a causa
 *  provável de cada um — o "porquê" por trás do score em "Pior cauda"/
 *  "Melhores scores". */
export async function obterCausaMigracaoCliente(
  empresa: string,
  cliente: string,
  loja?: string | null,
  modoPeriodo: ModoPeriodo = 'fechados',
  grupos?: string,
): Promise<CausaMigracaoClienteResposta> {
  const query = new URLSearchParams();
  query.set('cliente', cliente);
  const loja_ = queryLoja(loja);
  if (modoPeriodo !== 'fechados') query.set('modo_periodo', modoPeriodo);
  if (grupos) query.set('grupos_clientes', grupos);
  const url = `/api/clientes/${encodeURIComponent(empresa)}/causa-migracao${loja_ ? `${loja_}&` : '?'}${query.toString()}`;

  return comCache(`causa_migracao_${empresa}_${loja || ''}_${modoPeriodo}_${grupos || ''}_${cliente}`, async () => {
    const res = await chamar(url, { headers: authHeaders() });
    return tratarResposta(res);
  });
}

export type TensaoDiagnostico = {
  receita_periodo: number | null;
  receita_anterior: number | null;
  /** Variação vs. o mês anterior. */
  variacao_pct: number | null;
  delta_receita: number | null;
  receita_ano_anterior: number | null;
  /** Variação vs. o mesmo mês do ano passado — o corte que neutraliza sazonalidade. */
  variacao_ano_pct: number | null;
  produtos_em_queda: number;
  /** Quanto da queda total vem dos `topo_concentracao` produtos que mais caíram. */
  concentracao_queda_pct: number | null;
  topo_concentracao: number;
  rotulo_anterior: string | null;
  rotulo_ano_anterior: string | null;
};

export type PassoCascata = {
  tipo: 'inicio' | 'ganho' | 'perda' | 'fim';
  rotulo: string;
  delta: number | null;
  /** Geometria da barra flutuante: trecho invisível sob o colorido. */
  base: number | null;
  altura: number | null;
  acumulado: number | null;
};

export type CascataDiagnostico = {
  passos: PassoCascata[];
  /** % da receita do período coberta pela cascata (o comparativo descarta
   *  produto sem descrição harmonizada). */
  cobertura_pct: number | null;
};

export type LinhaTornado = {
  descricao: string;
  receita_anterior: number | null;
  receita_atual: number | null;
  delta_receita: number;
  variacao_pct: number | null;
};

export type FluxoFaixa = {
  de: string;
  para: string;
  clientes: number;
  receita: number | null;
  /** Sinal e tamanho do movimento (+1 subiu uma faixa, −2 desceu duas). Vem do
   *  backend porque a ordem das faixas não é alfabética: "Demais" é a última. */
  passo: number;
};

export type ResumoFluxoFaixas = {
  subiram: number;
  desceram: number;
  mantiveram: number;
  /** Comprou só no trimestre atual / só no anterior — não vira fluxo. */
  entraram: number;
  sairam: number;
  receita_subiram: number | null;
  receita_desceram: number | null;
};

export type FluxoFaixasDiagnostico = {
  disponivel: boolean;
  mensagem: string | null;
  /** Rótulo do trimestre móvel, ex. "jun/26–ago/26". */
  rotulo_atual: string | null;
  rotulo_anterior: string | null;
  /** Faixas na ordem da curva (Grupo 1 … Demais). */
  faixas: string[];
  fluxos: FluxoFaixa[];
  resumo: ResumoFluxoFaixas | null;
};

export type CelulaStreak = {
  periodo: string;
  receita: number | null;
  /** Variação contra o período anterior. `null` na primeira coluna, que não tem
   *  período anterior dentro da janela. */
  variacao_pct: number | null;
};

export type CriterioStreak = 'perda' | 'receita' | 'ganho';

export type ProdutoStreak = {
  descricao: string;
  /** O número que ordena a lista e vira o KPI da pílula: R$ perdido, R$
   *  ganho, ou receita atual — depende de qual lista (`perda`/`receita`/`ganho`). */
  valor: number | null;
  receita_atual: number | null;
  /** Altas ou quedas seguidas terminando no período mais recente. `null` na
   *  lista `receita`, que não olha tendência. */
  periodos_consecutivos: number | null;
  /** % da receita do período mais recente. `null` fora da lista `receita`. */
  participacao_pct: number | null;
  /** Uma célula por período de `StreakDiagnostico.periodos`, na mesma ordem. */
  celulas: CelulaStreak[];
};

export type StreakDiagnostico = {
  periodos: string[];
  /** Produtos em queda consecutiva agora, ordenados por R$ perdido. */
  perda: ProdutoStreak[];
  /** Produtos em alta consecutiva agora, ordenados por R$ ganho. */
  ganho: ProdutoStreak[];
  /** Maior receita no período mais recente, sem olhar tendência. */
  receita: ProdutoStreak[];
};

export type ClienteRisco = {
  cliente: string;
  receita_anterior: number | null;
  receita_atual: number | null;
  /** Sempre positivo — é o R$ que caiu, não o saldo. */
  perda_rs: number | null;
  /** Negativo = caiu (convenção do projeto; a tela não inverte sinal). */
  variacao_pct: number | null;
  parou_de_comprar: boolean;
  /** Faixa ABC do cliente no trimestre atual, ou "Sem faixa" sem receita na janela. */
  faixa: string;
};

export type ComposicaoRiscoFaixa = {
  faixa: string;
  perda_rs: number | null;
  clientes: number;
};

export type RiscoDiagnostico = {
  disponivel: boolean;
  mensagem: string | null;
  /** Top N por perda em R$ — não é lista de "todo mundo que caiu". */
  clientes: ClienteRisco[];
  /** Perda agregada por faixa ABC, maior perda primeiro. */
  composicao: ComposicaoRiscoFaixa[];
};

export type ClienteQuedaQuantidade = {
  cliente: string;
  qtd_anterior: number | null;
  qtd_atual: number | null;
  /** Negativo = caiu. */
  variacao_pct: number | null;
  /** Negativo = perdeu receita. */
  perda_receita: number | null;
  /** Produto que mais contribuiu para a queda de unidades deste cliente. */
  produto_critico: string;
};

export type QuedaQuantidadeDiagnostico = {
  disponivel: boolean;
  mensagem: string | null;
  clientes: ClienteQuedaQuantidade[];
};

/** Causa heurística da erosão, mesma régua do boletim "Correlação Produto x
 *  Cliente": Abandono de Categoria (3+ clientes no mesmo produto/período),
 *  Fim de Ciclo (produto já em alerta de queda consecutiva), Ruptura
 *  Estratégica (cliente parou de comprar, produto era ≥70% do que ele levava)
 *  ou Caso Específico (nenhum padrão acima). */
export type StatusCausaErosao = 'Abandono de Categoria' | 'Fim de Ciclo' | 'Ruptura Estratégica' | 'Caso Específico';

export type CelulaErosao = {
  produto: string;
  /** `null` = este cliente não teve queda neste produto (não é zero). */
  perda_rs: number | null;
  receita_anterior: number | null;
  /** Negativo = caiu (convenção do projeto; a tela não inverte sinal). */
  variacao_pct: number | null;
  /** `null` junto com `perda_rs: null` = célula vazia, sem causa a classificar. */
  status: StatusCausaErosao | null;
};

export type ClienteErosao = {
  cliente: string;
  perda_total: number | null;
  /** Uma célula por produto de `MatrizErosaoDiagnostico.produtos`, mesma ordem. */
  celulas: CelulaErosao[];
};

export type MatrizErosaoDiagnostico = {
  disponivel: boolean;
  mensagem: string | null;
  produtos: string[];
  clientes: ClienteErosao[];
};

export type ProdutoMargemGiro = {
  descricao: string;
  margem_pct: number | null;
  /** `null` = sem venda na janela (giro zero), não é o mesmo que cobertura 0. */
  cobertura_meses: number | null;
  valor_estoque: number | null;
  receita: number | null;
  status: StatusCoberturaEstoque;
};

export type FaixaMargemGiro = {
  status: StatusCoberturaEstoque;
  produtos: number;
  valor_estoque: number | null;
};

export type MargemGiroDiagnostico = {
  disponivel: boolean;
  mensagem: string | null;
  produtos: ProdutoMargemGiro[];
  bullet: FaixaMargemGiro[];
};

export type ProdutoRadarPercentual = {
  descricao: string;
  receita_anterior: number | null;
  receita_atual: number | null;
  variacao_pct: number | null;
};

export type RadarPercentualDiagnostico = {
  disponivel: boolean;
  mensagem: string | null;
  /** Produtos já cobertos pelo Tornado (ver `tornado`) não aparecem aqui de novo. */
  alta: ProdutoRadarPercentual[];
  queda: ProdutoRadarPercentual[];
};

export type ImpactoChurnDiagnostico = {
  /** Soma de toda queda individual cliente x produto — exposição, não perda confirmada. */
  receita_sob_risco: number | null;
  /** Maior retração percentual entre os eventos de erosão do período. */
  maior_retracao_pct: number | null;
  /** Variação global de receita entre os dois últimos períodos (mesmo número da Tensão). */
  variacao_global_pct: number | null;
};

export type DiagnosticoResposta = {
  disponivel: boolean;
  mensagem: string | null;
  periodo_atual: string | null;
  rotulo_periodo: string | null;
  tensao: TensaoDiagnostico | null;
  cascata: CascataDiagnostico;
  tornado: LinhaTornado[];
  radar_percentual: RadarPercentualDiagnostico;
  fluxo_faixas: FluxoFaixasDiagnostico;
  streak: StreakDiagnostico;
  risco: RiscoDiagnostico;
  queda_quantidade: QuedaQuantidadeDiagnostico;
  matriz_erosao: MatrizErosaoDiagnostico;
  impacto_churn: ImpactoChurnDiagnostico;
  margem_giro: MargemGiroDiagnostico;
  empresa?: string;
  loja?: string | null;
};

/** Diagnóstico da carteira: tensão do período, decomposição ano a ano e o que
 *  puxou o mês para cima e para baixo. */
export async function obterPainelDiagnostico(
  empresa: string,
  loja?: string | null,
  modoPeriodo: ModoPeriodo = 'fechados',
  grupos?: string,
): Promise<DiagnosticoResposta> {
  const query = new URLSearchParams();
  const loja_ = queryLoja(loja);
  if (modoPeriodo !== 'fechados') query.set('modo_periodo', modoPeriodo);
  if (grupos) query.set('grupos_clientes', grupos);
  const extra = query.toString();
  const url = loja_
    ? `/api/diagnostico/${encodeURIComponent(empresa)}${loja_}${extra ? `&${extra}` : ''}`
    : `/api/diagnostico/${encodeURIComponent(empresa)}${extra ? `?${extra}` : ''}`;

  return comCache(`diagnostico_${empresa}_${loja || ''}_${modoPeriodo}_${grupos || ''}`, async () => {
    const res = await chamar(url, { headers: authHeaders() });
    return tratarResposta(res);
  });
}
