/** Evento único: Configurações liga/desliga os cortes do Relatórios nas outras telas. */
export const EVENTO_CORTES_RELATORIOS = 'prisma-cortes-relatorios';

export function avisarCortesRelatorios(ativo: boolean) {
  window.dispatchEvent(new CustomEvent(EVENTO_CORTES_RELATORIOS, { detail: ativo }));
}
