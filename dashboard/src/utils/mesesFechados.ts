/**
 * Preferência global "período usado nos cálculos", compartilhada por
 * Dashboard, Clientes, Vendedores e Estoque.
 *
 * Mesmo desenho de `lojaSelecionada`/`empresaSelecionada`: localStorage como
 * fonte de verdade (chave `alvo_meses_fechados`, já usada pelo Dashboard) e um
 * CustomEvent para acordar quem já está montado na mesma aba — sem contexto
 * global, porque o controle vive na sidebar e as telas são irmãs, não filhas.
 *
 * Três modos:
 * - "fechados" (padrão): mês corrente em aberto fica fora dos cálculos.
 * - "completo": inclui o mês corrente inteiro, mesmo em aberto.
 * - "mesmo_periodo": mantém o mês corrente, mas corta os meses de
 *   comparação no mesmo dia do mês — evita que um mês com poucos dias de
 *   movimento (ex.: dia 2) apareça como queda brusca contra meses inteiros.
 *   Só existe em Clientes e Vendedores (telas que comparam "mês atual vs
 *   média histórica"); Dashboard e Estoque tratam como "completo".
 */
export const LS_MESES_FECHADOS = 'alvo_meses_fechados';
export const EVENTO_MESES_FECHADOS = 'prisma-meses-fechados-change';

export type ModoPeriodo = 'fechados' | 'completo' | 'mesmo_periodo';

const MODOS_VALIDOS: readonly ModoPeriodo[] = ['fechados', 'completo', 'mesmo_periodo'];

function normalizar(valor: string | null): ModoPeriodo {
  if (valor === 'true') return 'fechados'; // migração do formato antigo (booleano)
  if (valor === 'false') return 'completo';
  return (MODOS_VALIDOS as string[]).includes(valor ?? '') ? (valor as ModoPeriodo) : 'fechados';
}

export function lerModoPeriodo(): ModoPeriodo {
  try {
    return normalizar(localStorage.getItem(LS_MESES_FECHADOS));
  } catch {
    return 'fechados';
  }
}

export function definirModoPeriodo(valor: ModoPeriodo) {
  try {
    localStorage.setItem(LS_MESES_FECHADOS, valor);
  } catch {
    /* Modo privado pode bloquear localStorage; o evento ainda sincroniza a aba. */
  }
  window.dispatchEvent(new CustomEvent(EVENTO_MESES_FECHADOS, { detail: valor }));
}

/** Para telas sem o modo "mesmo período" (Dashboard, Estoque): só "fechados"
 *  exclui o mês corrente; qualquer outro modo inclui o mês corrente inteiro. */
export function modoParaBooleano(modo: ModoPeriodo): boolean {
  return modo === 'fechados';
}
