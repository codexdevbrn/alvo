/**
 * Modo debug de performance — liga com `?debug=perf` na URL (persiste em
 * sessionStorage, sobrevive à navegação SPA e ao F5) ou rodando no console
 * `sessionStorage.prisma_debug_perf = '1'`. Desliga com `?debug=0`.
 *
 * `api/client.ts` (fetch + parse de toda chamada) e `utils/cacheRequisicoes.ts`
 * (hit/miss do cache local) já logam sozinhos — cobre as 15 telas sem precisar
 * marcar cada uma. Telas com processamento client-side pesado (agregação,
 * sort de milhares de linhas) chamam `perfIniciar(nomeDaTela)` e marcam os
 * passos extras à mão.
 *
 * Pra me mandar o resultado: no console, `__prismaPerf.exportar()` devolve o
 * texto pronto pra colar; `copy(__prismaPerf.exportar())` já copia.
 */

const CHAVE_ATIVO = 'prisma_debug_perf';

function lerFlagUrl(): boolean | null {
  if (typeof window === 'undefined') return null;
  const params = new URLSearchParams(window.location.search);
  if (!params.has('debug')) return null;
  const valor = params.get('debug');
  return valor === 'perf' || valor === '1';
}

(function aplicarFlagUrl() {
  const flag = lerFlagUrl();
  if (flag === null) return;
  try {
    if (flag) sessionStorage.setItem(CHAVE_ATIVO, '1');
    else sessionStorage.removeItem(CHAVE_ATIVO);
  } catch {
    // Modo anônimo / storage bloqueado — debug simplesmente não liga.
  }
})();

export function perfAtivo(): boolean {
  try {
    return sessionStorage.getItem(CHAVE_ATIVO) === '1';
  } catch {
    return false;
  }
}

type Registro = {
  hora: string;
  rota: string;
  escopo: string;
  etapa: string;
  ms: number;
  extra?: string;
};

const registros: Registro[] = [];

function agora(): number {
  return typeof performance !== 'undefined' ? performance.now() : Date.now();
}

function rotaAtual(): string {
  return typeof window !== 'undefined' ? window.location.pathname : '';
}

export function perfLog(escopo: string, etapa: string, ms: number, extra?: string): void {
  if (!perfAtivo()) return;
  const registro: Registro = {
    hora: new Date().toISOString().slice(11, 23),
    rota: rotaAtual(),
    escopo,
    etapa,
    ms: Math.round(ms * 10) / 10,
    extra,
  };
  registros.push(registro);
  const cauda = extra ? ` (${extra})` : '';
  console.log(
    `%c[perf] %c${registro.rota} %c${escopo} %c${etapa} %c${registro.ms}ms${cauda}`,
    'color:#888', 'color:#0af', 'color:#0a0', 'color:#999', 'color:#e90;font-weight:bold',
  );
}

/** Timer simples: `const t = perfTimer(); ...; perfLog(escopo, etapa, t());` */
export function perfTimer(): () => number {
  const inicio = agora();
  return () => agora() - inicio;
}

/** Checkpoints nomeados dentro de um mesmo fluxo — cada `marca` mede o tempo
 * desde a marca anterior (ou desde `perfIniciar`). */
export function perfIniciar(escopo: string) {
  let ultimo = agora();
  return {
    marca(etapa: string, extra?: string) {
      const agoraMs = agora();
      perfLog(escopo, etapa, agoraMs - ultimo, extra);
      ultimo = agoraMs;
    },
  };
}

/** Todo o log desta aba, formatado pra colar — usar `__prismaPerf.exportar()`. */
export function perfExportar(): string {
  if (registros.length === 0) return '(sem registros — confirme que o debug está ativo: __prismaPerf.ativo())';
  return registros
    .map((r) =>
      `${r.hora}  ${r.rota.padEnd(24)} ${r.escopo.padEnd(28)} ${r.etapa.padEnd(20)} ${r.ms}ms${r.extra ? ` (${r.extra})` : ''}`,
    )
    .join('\n');
}

export function perfLimpar(): void {
  registros.length = 0;
}

if (typeof window !== 'undefined') {
  (window as unknown as Record<string, unknown>).__prismaPerf = {
    ativo: perfAtivo,
    exportar: perfExportar,
    limpar: perfLimpar,
    registros,
  };
}
