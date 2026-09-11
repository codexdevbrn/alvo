import { EVENTO_EMPRESA } from './empresaSelecionada';
import { limparCacheGeral } from './cacheRequisicoes';
import { invalidarSummary } from './cacheSummary';
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
};

function despacharProgresso(estado: EstadoPrefetch) {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent<EstadoPrefetch>(EVENTO_PREFETCH, { detail: estado }));
  }
}

let filaCancelada = false;
let empresaAtual = '';

async function rodarFila(empresa: string) {
  filaCancelada = true; // Cancela qualquer fila em andamento
  
  // Limpa cache da empresa anterior
  limparCacheGeral();
  invalidarSummary();
  
  if (!empresa) {
    despacharProgresso({ rodando: false, atual: 0, total: 0, nome: '' });
    return;
  }
  
  // Pausa leve para não travar a UI durante o render inicial do Dashboard
  await new Promise((resolve) => setTimeout(resolve, 800));
  
  filaCancelada = false;
  empresaAtual = empresa;

  // Lista de endpoints a precarregar sequencialmente
  const tarefas = [
    { nome: 'Dashboard', fn: () => obterSummaryEmpresa(empresaAtual) },
    { nome: 'Visão Geral', fn: () => obterPainelClientes(empresaAtual) },
    { nome: 'Clientes', fn: async () => { await obterBaseClientes(empresaAtual); await obterTagsClientes(empresaAtual); } },
    { nome: 'Vendedores', fn: () => obterRankingVendedores(empresaAtual) },
    { nome: 'Estoque', fn: () => obterResumoEstoque(empresaAtual) },
    { nome: 'Despesas', fn: () => obterResumoDespesas(empresaAtual) },
    { nome: 'Monitoramento', fn: () => obterMonitorEmpresas() }
  ];

  for (let i = 0; i < tarefas.length; i++) {
    if (filaCancelada) break;
    const tarefa = tarefas[i];
    
    despacharProgresso({ rodando: true, atual: i, total: tarefas.length, nome: tarefa.nome });
    
    try {
      await tarefa.fn();
      // Respiro para deixar a main thread processar renders
      await new Promise((resolve) => setTimeout(resolve, 200));
    } catch (e) {
      console.warn('Prisma Prefetch: falha ao precarregar tela silenciosamente', e);
    }
  }
  
  if (!filaCancelada) {
    despacharProgresso({ rodando: false, atual: tarefas.length, total: tarefas.length, nome: 'Concluído' });
  }
}

export function inicializarPrefetchSequencial(): void {
  if (typeof window === 'undefined') return;
  
  window.addEventListener(EVENTO_EMPRESA, ((evento: CustomEvent<string>) => {
    void rodarFila(evento.detail);
  }) as EventListener);
}
