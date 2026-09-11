/** Evento único: Configurações liga/desliga e a barra some o item na mesma aba. */
export const EVENTO_TELA_VENDEDORES = 'prisma-tela-vendedores';

export function avisarTelaVendedores(visivel: boolean) {
  window.dispatchEvent(new CustomEvent(EVENTO_TELA_VENDEDORES, { detail: visivel }));
}
