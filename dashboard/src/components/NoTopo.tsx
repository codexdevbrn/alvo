import { useContext, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { EncaixeTopoContext } from './encaixeTopo';

/** Encaixe no `app-shell-topo` para filtros que dependem do estado da própria
 *  tela (ex.: rodadas que só se conhecem depois da resposta). Os controles
 *  `Topo*` vivem no AppShell e leem estado global; estes continuam no
 *  componente da tela e só são desenhados lá em cima. */
export function NoTopo({ children }: { children: ReactNode }) {
  const encaixe = useContext(EncaixeTopoContext);
  return encaixe ? createPortal(children, encaixe) : null;
}
