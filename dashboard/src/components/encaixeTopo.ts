import { createContext } from 'react';

/** Elemento do `app-shell-topo` onde `NoTopo` desenha os filtros da tela. */
export const EncaixeTopoContext = createContext<HTMLElement | null>(null);
