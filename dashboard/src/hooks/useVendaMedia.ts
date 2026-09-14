import { useCallback, useEffect, useState } from 'react';
import {
  EVENTO_VENDA_MEDIA,
  definirMesesVendaMedia,
  lerMesesVendaMedia,
  type MesesVendaMedia,
} from '../utils/vendaMedia';

/** Preferência "Venda média" do topo, compartilhada pelo Estoque e pelo prefetch. */
export function useVendaMedia(): [MesesVendaMedia, (valor: MesesVendaMedia) => void] {
  const [meses, setEstado] = useState(lerMesesVendaMedia);

  useEffect(() => {
    const sincronizar = () => setEstado(lerMesesVendaMedia());
    window.addEventListener(EVENTO_VENDA_MEDIA, sincronizar);
    window.addEventListener('storage', sincronizar);
    return () => {
      window.removeEventListener(EVENTO_VENDA_MEDIA, sincronizar);
      window.removeEventListener('storage', sincronizar);
    };
  }, []);

  const definir = useCallback((valor: MesesVendaMedia) => {
    definirMesesVendaMedia(valor);
    setEstado(valor);
  }, []);

  return [meses, definir];
}
