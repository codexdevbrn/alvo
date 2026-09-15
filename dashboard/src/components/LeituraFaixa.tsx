import type { ReactNode } from 'react';

interface LeituraFaixaProps {
  children: ReactNode;
  /** Aviso = período aberto ou buraco de dado — não é o recorte “justo”. */
  tom?: 'normal' | 'aviso';
}

/** Frase de leitura no topo da tela: o que os números significam, em uma linha. */
export function LeituraFaixa({ children, tom = 'normal' }: LeituraFaixaProps) {
  if (children == null || children === '') return null;
  return (
    <p className={`leitura-faixa${tom === 'aviso' ? ' is-aviso' : ''}`} role="status">
      {children}
    </p>
  );
}
