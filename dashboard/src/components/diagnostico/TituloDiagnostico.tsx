interface Props {
  texto: string;
  destaque?: string;
  variante?: 'queda' | 'alta' | 'neutro';
}

/** Título curto + o número que importa em pílula separada — substitui a
 *  frase-conclusão longa que cada card tinha no <h2>. O detalhe (produto,
 *  contagem, comparação) vai para o <p> de descrição abaixo, não aqui. */
export function TituloDiagnostico({ texto, destaque, variante = 'neutro' }: Props) {
  return (
    <h2 className="diagnostico-titulo">
      {texto}
      {destaque && <span className={`diagnostico-titulo-pilula is-${variante}`}>{destaque}</span>}
    </h2>
  );
}
