/**
 * Controle da splash de tela cheia (o traçado "Prisma" sobre fundo preto).
 *
 * Ela só deve aparecer na PRIMEIRA entrada no site. Trocar de página depois
 * disso mostra a mesma animação, mas restrita à área de conteúdo, com a
 * sidebar no lugar — ver `LoadingScreen` (prop `variante`).
 *
 * O estado vive num módulo, não em React state nem em localStorage:
 * sobrevive à troca de rota (que desmonta a página) e zera num F5 —
 * recarregar a página é entrar no site de novo.
 *
 * Fica em arquivo próprio porque um módulo que exporta componente não pode
 * exportar outras coisas sem quebrar o fast refresh do Vite.
 */

let exibida = false;

export function jaExibiuSplashTelaCheia(): boolean {
  return exibida;
}

export function marcarSplashTelaCheiaExibida(): void {
  exibida = true;
}
