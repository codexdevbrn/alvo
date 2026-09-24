import { EVENTO_EMPRESA } from './empresaSelecionada';
import { EVENTO_LOJA, codificarEscopoLojas, lerLojas } from './lojaSelecionada';
import { EVENTO_VENDA_MEDIA, lerMesesVendaMedia } from './vendaMedia';
import { limparCacheGeral } from './cacheRequisicoes';
import { invalidarSummary, gravarSummaryCache, lerSummaryCache } from './cacheSummary';
import {
  obterPainelClientes,
  obterPainelDiagnostico,
  obterRankingVendedores,
  obterResumoEstoque,
  obterResumoDespesas,
  obterAPrecificar,
  obterHistoricoPrecificacao,
  obterMonitorEmpresas,
  obterSummaryEmpresa,
  obterBaseClientes,
  obterTagsClientes,
  obterBase,
  obterCatalogo,
  tentarCarregarConfiguracaoEmpresa,
} from '../api/client';
import type { ModoPeriodo } from './mesesFechados';

export const EVENTO_PREFETCH = 'prisma-prefetch-progress';

/** Os três modos do toggle Período. Clientes e Vendedores usam os três;
 *  Estoque/Despesas só distinguem fechados vs o resto (completo ≡ mesmo período). */
const MODOS_PERIODO: readonly ModoPeriodo[] = ['fechados', 'completo', 'mesmo_periodo'];

/** Teto de telas pesadas ao mesmo tempo, depois da tela aberta.
 *  Chrome segura ~6 conexões HTTP/1.1 no host; 4 deixa folga pro clique do usuário.
 *  O backend serializa a 1ª leitura da base por empresa (`_trava_summary_empresa`);
 *  o resto é pandas em threadpool em cima do DataFrame já em RAM. */
const LIMITE_PARALELO = 4;

export type EstadoPrefetch = {
  rodando: boolean;
  atual: number;
  total: number;
  nome: string;
  etapas: string[];
  emAndamento: string[];
  feitas: string[];
};

let estadoAtual: EstadoPrefetch = {
  rodando: false,
  atual: 0,
  total: 0,
  nome: '',
  etapas: [],
  emAndamento: [],
  feitas: [],
};
let concluidoEm = 0;

function despacharProgresso(estado: EstadoPrefetch) {
  estadoAtual = estado;
  if (!estado.rodando && estado.nome === 'Concluído') {
    concluidoEm = Date.now();
  }
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent<EstadoPrefetch>(EVENTO_PREFETCH, { detail: estado }));
  }
}

export function obterEstadoPrefetch(): EstadoPrefetch {
  return estadoAtual;
}

export function obterTempoConclusaoPrefetch(): number {
  return concluidoEm;
}

export function estaPrefetchVisivel(): boolean {
  if (estadoAtual.rodando) return true;
  if (estadoAtual.nome === 'Concluído' && Date.now() - concluidoEm < 3000) return true;
  return false;
}

let versaoFila = 0;
let empresaAtual = '';

function lojaDaEmpresa(empresa: string): string | null {
  return codificarEscopoLojas(lerLojas(empresa));
}

type MotivoPrefetch = 'empresa' | 'loja' | 'venda-media';

type TarefaPrefetch = {
  nome: string;
  fn: () => Promise<void>;
};

/** Mais específico primeiro: `/` casa com tudo se vier no começo. */
const ROTA_TAREFA: [string, string][] = [
  ['/precificacao', 'Precificação'],
  ['/diagnostico', 'Diagnóstico'],
  ['/vendedores', 'Vendedores'],
  ['/estoque', 'Estoque'],
  ['/despesas', 'Despesas'],
  ['/monitor', 'Monitoramento'],
  ['/clientes', 'Clientes: Visão geral'],
  ['/cortes', 'Cortes'],
  ['/analisador', 'Relatórios'],
  ['/', 'Dashboard'],
];

function nomeTarefaDaRota(pathname: string, nomes: string[]): string | null {
  for (const [prefixo, nome] of ROTA_TAREFA) {
    if (!nomes.includes(nome)) continue;
    if (prefixo === '/') {
      if (pathname === '/') return nome;
      continue;
    }
    if (pathname.startsWith(prefixo)) return nome;
  }
  return null;
}

async function mapaComLimite<T>(
  itens: T[],
  limite: number,
  fn: (item: T) => Promise<void>,
  cancelado: () => boolean,
): Promise<void> {
  const fila = [...itens];
  const workers = Array.from({ length: Math.min(limite, Math.max(fila.length, 0)) }, async () => {
    while (fila.length > 0) {
      if (cancelado()) return;
      const item = fila.shift();
      if (item === undefined) return;
      await fn(item);
    }
  });
  await Promise.all(workers);
}

async function rodarFila(empresa: string, motivo: MotivoPrefetch = 'empresa') {
  const versaoExecucao = ++versaoFila;
  const cancelado = () => versaoFila !== versaoExecucao;

  if (motivo === 'empresa' && empresa !== empresaAtual) {
    limparCacheGeral();
    invalidarSummary();
  }

  if (!empresa) {
    empresaAtual = '';
    despacharProgresso({
      rodando: false, atual: 0, total: 0, nome: '', etapas: [], emAndamento: [], feitas: [],
    });
    return;
  }

  if (motivo === 'empresa') {
    await new Promise((resolve) => setTimeout(resolve, 800));
    if (cancelado()) return;
  }

  empresaAtual = empresa;
  const loja = lojaDaEmpresa(empresa);
  const mesesEstoque = lerMesesVendaMedia();

  const tarefaEstoque: TarefaPrefetch = {
    nome: 'Estoque',
    fn: async () => {
      await Promise.all([
        obterResumoEstoque(empresaAtual, { loja, meses: mesesEstoque, usarMesesFechados: true }),
        obterResumoEstoque(empresaAtual, { loja, meses: mesesEstoque, usarMesesFechados: false }),
      ]);
    },
  };

  const tarefas: TarefaPrefetch[] = motivo === 'venda-media' ? [tarefaEstoque] : [
    { nome: 'Dashboard', fn: async () => {
        const emCache = lerSummaryCache(empresaAtual);
        if (emCache) return;
        const d = await obterSummaryEmpresa(empresaAtual);
        gravarSummaryCache(empresaAtual, d);
    }},
    { nome: 'Cortes', fn: async () => {
        await Promise.all([
          obterBase(empresaAtual, loja),
          tentarCarregarConfiguracaoEmpresa(empresaAtual, loja),
        ]);
    }},
    { nome: 'Relatórios', fn: async () => {
        await Promise.all([
          obterCatalogo(),
          obterBase(empresaAtual, loja),
          tentarCarregarConfiguracaoEmpresa(empresaAtual, loja),
        ]);
    }},
    { nome: 'Clientes: Visão geral', fn: async () => {
        await Promise.all(MODOS_PERIODO.map((modo) => obterPainelClientes(empresaAtual, loja, undefined, modo)));
    }},
    { nome: 'Diagnóstico', fn: async () => {
        await Promise.all(MODOS_PERIODO.map((modo) => obterPainelDiagnostico(empresaAtual, loja, modo)));
    }},
    { nome: 'Clientes: Base e tags', fn: async () => {
        await Promise.all([obterBaseClientes(empresaAtual), obterTagsClientes(empresaAtual)]);
    }},
    { nome: 'Vendedores', fn: async () => {
        await Promise.all(MODOS_PERIODO.map((modo) => obterRankingVendedores(empresaAtual, loja, undefined, modo)));
    }},
    tarefaEstoque,
    { nome: 'Despesas', fn: async () => {
        await Promise.all([
          obterResumoDespesas(empresaAtual, { loja, meses: 12, usarMesesFechados: true }),
          obterResumoDespesas(empresaAtual, { loja, meses: 12, usarMesesFechados: false }),
        ]);
    }},
    // As duas telas leem o movimento do PRICE, que soma as lojas: a loja não
    // entra no pedido. Aqui só se aquece o cache do servidor.
    { nome: 'Precificação', fn: async () => {
        await obterAPrecificar(empresaAtual);
    }},
    { nome: 'Pós-precificação', fn: async () => {
        await obterHistoricoPrecificacao(empresaAtual, {
          periodo: 180, rodadas: [], faixas: [], nivel: 'familia', todos: false, busca: '',
        });
    }},
    { nome: 'Monitoramento', fn: async () => {
        await obterMonitorEmpresas({ meses: 6, metrica: 'receita' });
    }},
  ];

  const nomesEtapas = tarefas.map((t) => t.nome);
  const emAndamento = new Set<string>();
  const feitas = new Set<string>();

  const emitir = () => {
    const voo = [...emAndamento];
    if (voo.length === 0 && feitas.size === tarefas.length) return;
    despacharProgresso({
      rodando: true,
      atual: feitas.size,
      total: tarefas.length,
      nome: voo.length === 1 ? voo[0] : (voo.length > 1 ? `${voo.length} telas` : ''),
      etapas: nomesEtapas,
      emAndamento: voo,
      feitas: [...feitas],
    });
  };

  const rodarTarefa = async (tarefa: TarefaPrefetch) => {
    if (cancelado()) return;
    emAndamento.add(tarefa.nome);
    emitir();
    try {
      await tarefa.fn();
    } catch (e) {
      console.warn('Prisma Prefetch: falha ao precarregar tela silenciosamente', e);
    }
    emAndamento.delete(tarefa.nome);
    feitas.add(tarefa.nome);
    emitir();
  };

  const pathname = typeof window !== 'undefined' ? window.location.pathname : '/';
  const prioridade = nomeTarefaDaRota(pathname, nomesEtapas);
  const resto = tarefas.filter((tarefa) => tarefa.nome !== prioridade);
  const primeira = tarefas.find((tarefa) => tarefa.nome === prioridade);

  if (primeira) {
    await rodarTarefa(primeira);
  }
  if (!cancelado()) {
    await mapaComLimite(resto, LIMITE_PARALELO, rodarTarefa, cancelado);
  }

  if (!cancelado()) {
    despacharProgresso({
      rodando: false,
      atual: tarefas.length,
      total: tarefas.length,
      nome: 'Concluído',
      etapas: nomesEtapas,
      emAndamento: [],
      feitas: nomesEtapas,
    });
  }
}

export function inicializarPrefetchSequencial(): void {
  if (typeof window === 'undefined') return;

  window.addEventListener(EVENTO_EMPRESA, ((evento: CustomEvent<string>) => {
    void rodarFila(evento.detail);
  }) as EventListener);

  window.addEventListener(EVENTO_LOJA, (() => {
    const empresa = localStorage.getItem('alvo_empresa') || '';
    if (empresa) void rodarFila(empresa, 'loja');
  }) as EventListener);

  window.addEventListener(EVENTO_VENDA_MEDIA, (() => {
    const empresa = localStorage.getItem('alvo_empresa') || '';
    if (empresa) void rodarFila(empresa, 'venda-media');
  }) as EventListener);

  const empresaSalva = localStorage.getItem('alvo_empresa');
  if (empresaSalva) {
    void rodarFila(empresaSalva);
  }
}
