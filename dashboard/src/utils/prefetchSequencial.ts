import { EVENTO_EMPRESA } from './empresaSelecionada';
import { EVENTO_LOJA, codificarEscopoLojas, lerLojas } from './lojaSelecionada';
import { EVENTO_VENDA_MEDIA, lerMesesVendaMedia } from './vendaMedia';
import { limparCacheGeral } from './cacheRequisicoes';
import { invalidarSummary, gravarSummaryCache, lerSummaryCache } from './cacheSummary';
import {
  obterPainelClientes,
  obterRankingVendedores,
  obterResumoEstoque,
  obterResumoDespesas,
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

export type EstadoPrefetch = {
  rodando: boolean;
  atual: number;
  total: number;
  nome: string;
  etapas: string[];
};

let estadoAtual: EstadoPrefetch = {
  rodando: false,
  atual: 0,
  total: 0,
  nome: '',
  etapas: []
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

async function rodarFila(empresa: string, motivo: MotivoPrefetch = 'empresa') {
  const versaoExecucao = ++versaoFila;

  if (motivo === 'empresa' && empresa !== empresaAtual) {
    limparCacheGeral();
    invalidarSummary();
  }

  if (!empresa) {
    empresaAtual = '';
    despacharProgresso({ rodando: false, atual: 0, total: 0, nome: '', etapas: [] });
    return;
  }

  if (motivo === 'empresa') {
    await new Promise((resolve) => setTimeout(resolve, 800));
    if (versaoFila !== versaoExecucao) return;
  }

  empresaAtual = empresa;
  const loja = lojaDaEmpresa(empresa);
  const mesesEstoque = lerMesesVendaMedia();

  const tarefaEstoque = {
    nome: 'Estoque',
    fn: async () => {
      await obterResumoEstoque(empresaAtual, { loja, meses: mesesEstoque, usarMesesFechados: true });
      await obterResumoEstoque(empresaAtual, { loja, meses: mesesEstoque, usarMesesFechados: false });
    },
  };

  // Cada etapa cobre todas as visualizações de período daquela tela, pra o
  // clique no toggle Período achar cache quente. Não espera o clique.
  const tarefas = motivo === 'venda-media' ? [tarefaEstoque] : [
    { nome: 'Dashboard', fn: async () => {
        const emCache = lerSummaryCache(empresaAtual);
        if (emCache) return;
        const d = await obterSummaryEmpresa(empresaAtual);
        gravarSummaryCache(empresaAtual, d);
    }},
    { nome: 'Cortes', fn: async () => {
        await obterBase(empresaAtual, loja);
        await tentarCarregarConfiguracaoEmpresa(empresaAtual, loja);
    }},
    { nome: 'Relatórios', fn: async () => {
        await obterCatalogo();
        await obterBase(empresaAtual, loja);
        await tentarCarregarConfiguracaoEmpresa(empresaAtual, loja);
    }},
    { nome: 'Clientes: Visão geral', fn: async () => {
        for (const modo of MODOS_PERIODO) {
          await obterPainelClientes(empresaAtual, loja, undefined, modo);
        }
    }},
    { nome: 'Clientes: Base e tags', fn: async () => { await obterBaseClientes(empresaAtual); await obterTagsClientes(empresaAtual); } },
    { nome: 'Vendedores', fn: async () => {
        for (const modo of MODOS_PERIODO) {
          await obterRankingVendedores(empresaAtual, loja, undefined, modo);
        }
    }},
    tarefaEstoque,
    { nome: 'Despesas', fn: async () => {
        await obterResumoDespesas(empresaAtual, { loja, meses: 12, usarMesesFechados: true });
        await obterResumoDespesas(empresaAtual, { loja, meses: 12, usarMesesFechados: false });
    }},
    { nome: 'Monitoramento', fn: () => obterMonitorEmpresas({ meses: 6, metrica: 'receita' }) }
  ];

  const nomesEtapas = tarefas.map((t) => t.nome);

  for (let i = 0; i < tarefas.length; i++) {
    if (versaoFila !== versaoExecucao) break;
    const tarefa = tarefas[i];

    despacharProgresso({ rodando: true, atual: i, total: tarefas.length, nome: tarefa.nome, etapas: nomesEtapas });

    try {
      await tarefa.fn();
      if (versaoFila !== versaoExecucao) break;
      await new Promise((resolve) => setTimeout(resolve, 200));
    } catch (e) {
      console.warn('Prisma Prefetch: falha ao precarregar tela silenciosamente', e);
    }
  }

  if (versaoFila === versaoExecucao) {
    despacharProgresso({ rodando: false, atual: tarefas.length, total: tarefas.length, nome: 'Concluído', etapas: nomesEtapas });
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
