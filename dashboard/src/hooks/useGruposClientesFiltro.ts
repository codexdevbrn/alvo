import { useEffect, useState } from 'react';
import { EVENTO_GRUPOS_CLIENTES, lerGruposClientesFiltro } from '../utils/gruposClientesFiltro';

/** Grupos de clientes selecionados no filtro do topo — vazio = todos (sem filtro). */
export function useGruposClientesFiltro(): string[] {
  const [grupos, setGrupos] = useState<string[]>(lerGruposClientesFiltro);
  useEffect(() => {
    const sincronizar = () => setGrupos(lerGruposClientesFiltro());
    window.addEventListener(EVENTO_GRUPOS_CLIENTES, sincronizar);
    window.addEventListener('storage', sincronizar);
    return () => {
      window.removeEventListener(EVENTO_GRUPOS_CLIENTES, sincronizar);
      window.removeEventListener('storage', sincronizar);
    };
  }, []);
  return grupos;
}
