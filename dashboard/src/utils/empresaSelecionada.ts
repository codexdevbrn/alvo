/** Evento único para sincronizar empresa entre sidebar e páginas sem contexto global. */
export const EVENTO_EMPRESA = 'prisma-empresa-change';

const LS_EMPRESA = 'alvo_empresa';

/** Atualiza fonte persistida e avisa componentes já montados na mesma aba. */
export function selecionarEmpresaGlobal(nome: string) {
  try {
    if (nome) localStorage.setItem(LS_EMPRESA, nome);
    else localStorage.removeItem(LS_EMPRESA);
  } catch {
    /* Modo privado pode bloquear localStorage; evento ainda mantém aba sincronizada. */
  }
  window.dispatchEvent(new CustomEvent(EVENTO_EMPRESA, { detail: nome }));
}
