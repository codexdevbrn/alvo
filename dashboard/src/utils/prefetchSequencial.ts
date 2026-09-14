import { EVENTO_EMPRESA } from './empresaSelecionada';
import { limparCacheGeral } from './cacheRequisicoes';
import { invalidarSummary, gravarSummaryCache } from './cacheSummary';
import {
  obterPainelClientes,
  obterRankingVendedores,
  obterResumoEstoque,
  obterResumoDespesas,
  obterMonitorEmpresas,
  obterSummaryEmpresa,
  obterBaseClientes,
  obterTagsClientes
} from '../api/client';

export const EVENTO_PREFETCH = 'prisma-prefetch-progress';

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

async function rodarFila(empresa: string) {
  const versaoExecucao = ++versaoFila; // Cancela qualquer fila anterior
  
  // Limpa cache da empresa anterior
  limparCacheGeral();
  invalidarSummary();
  
  if (!empresa) {
    despacharProgresso({ rodando: false, atual: 0, total: 0, nome: '', etapas: [] });
    return;
  }
  
  // Pausa leve para não travar a UI durante o render inicial do Dashboard
  await new Promise((resolve) => setTimeout(resolve, 800));
  if (versaoFila !== versaoExecucao) return;
  
  empresaAtual = empresa;

  // Lista de endpoints a precarregar sequencialmente
  const tarefas = [
    { nome: 'Dashboard', fn: async () => {
        const d = await obterSummaryEmpresa(empresaAtual);
        gravarSummaryCache(empresaAtual, d);
    }},
    { nome: 'Visão Geral', fn: () => obterPainelClientes(empresaAtual) },
    { nome: 'Clientes', fn: async () => { await obterBaseClientes(empresaAtual); await obterTagsClientes(empresaAtual); } },
    { nome: 'Vendedores', fn: () => obterRankingVendedores(empresaAtual) },
    { nome: 'Estoque', fn: () => obterResumoEstoque(empresaAtual, { meses: 6, usarMesesFechados: true }) },
    { nome: 'Despesas', fn: () => obterResumoDespesas(empresaAtual, { meses: 6, usarMesesFechados: true }) },
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
      // Respiro para deixar a main thread processar renders
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

  // Iniciar prefetch também no primeiro boot se houver empresa já salva
  const empresaSalva = localStorage.getItem('alvo_empresa');
  if (empresaSalva) {
    void rodarFila(empresaSalva);
  }
}
