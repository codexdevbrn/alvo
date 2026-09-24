/** Evento único para sincronizar empresa entre sidebar e páginas sem contexto global. */
export const EVENTO_EMPRESA = 'prisma-empresa-change';

const LS_EMPRESA = 'alvo_empresa';

/**
 * Empresa usada quando nada foi escolhido nesta máquina. É uma pasta de verdade
 * na fonte e no trabalho, como qualquer outra empresa — não o modo estático.
 */
export const EMPRESA_MOCK = 'Dados Mockados';

/**
 * Primeira empresa a usar quando `alvo_empresa` está vazio: a mockada, ou a
 * primeira da lista se ela não estiver publicada nesta instalação.
 *
 * Fonte única porque mais de uma tela precisa resolver a empresa inicial: o
 * SidebarEmpresaSelect (uso normal, dentro do AppShell) e o DashboardPage
 * (1ª visita ao site, quando o AppShell ainda nem montou — ver comentário no
 * efeito que chama esta função em DashboardPage.tsx).
 */
export function escolherEmpresaInicial(lista: string[]): string | undefined {
  if (!lista.length) return undefined;
  return lista.includes(EMPRESA_MOCK) ? EMPRESA_MOCK : lista[0];
}

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
