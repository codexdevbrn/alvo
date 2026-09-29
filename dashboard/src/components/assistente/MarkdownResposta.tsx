import { Fragment, memo, type ReactNode } from 'react';

/**
 * Markdown das respostas da IA e das análises diárias, como elementos React.
 *
 * Só o subconjunto que o backend deixa passar (títulos, parágrafos, listas,
 * tabelas, negrito, itálico, código em linha) — o validador recusa bloco de
 * código e conteúdo ativo. Nada vira HTML cru: texto do modelo nunca chega a
 * `innerHTML`, então não há o que sanitizar. A citação de fonte ([CRM],
 * [PRISMA+ANÁLISE]…) vira selo, que é como a tela deixa claro de onde veio o fato.
 */

const FONTES = 'CRM|PRISMA|ANÁLISE|DADOS';
const RE_FONTE = new RegExp(`\\[((?:${FONTES})(?:\\+(?:${FONTES}))*)\\]`, 'g');
const RE_INLINE = new RegExp(
  `(\\*\\*[^*]+\\*\\*|\\*[^*\\s][^*]*\\*|\`[^\`]+\`|${RE_FONTE.source})`,
  'g',
);

/**
 * Marca onde o texto em escrita termina. Vai no fim do texto cru e vira o cursor
 * dentro do bloco em que cair — colado na última letra, seja parágrafo, item de
 * lista ou célula de tabela. Um `::after` no último bloco não servia: quando a
 * resposta terminava numa lista, o cursor ia parar fora do texto.
 */
const CURSOR = '\uE000';

function comCursor(texto: string, chave: string): ReactNode[] {
  if (!texto.includes(CURSOR)) return [texto];
  return texto.split(CURSOR).flatMap((trecho, n) => (
    n === 0 ? [trecho] : [<span key={`${chave}-cursor-${n}`} className="md-cursor" aria-hidden="true" />, trecho]
  ));
}

function renderizarInline(texto: string, chave: string): ReactNode[] {
  const partes: ReactNode[] = [];
  let ultimo = 0;
  let indice = 0;
  for (const achado of texto.matchAll(RE_INLINE)) {
    const inicio = achado.index ?? 0;
    if (inicio > ultimo) partes.push(...comCursor(texto.slice(ultimo, inicio), `${chave}-t${indice}`));
    const trecho = achado[0];
    const k = `${chave}-${indice++}`;
    if (trecho.startsWith('**')) {
      partes.push(<strong key={k}>{renderizarInline(trecho.slice(2, -2), k)}</strong>);
    } else if (trecho.startsWith('`')) {
      partes.push(<code key={k}>{trecho.slice(1, -1)}</code>);
    } else if (trecho.startsWith('[')) {
      const fontes = trecho.slice(1, -1).split('+');
      partes.push(
        <span key={k} className="md-fonte" title={`Fonte: ${fontes.join(' + ')}`}>
          {fontes.join(' + ')}
        </span>,
      );
    } else {
      partes.push(<em key={k}>{renderizarInline(trecho.slice(1, -1), k)}</em>);
    }
    ultimo = inicio + trecho.length;
  }
  if (ultimo < texto.length) partes.push(...comCursor(texto.slice(ultimo), `${chave}-fim`));
  return partes;
}

type Alinhamento = 'left' | 'right' | 'center' | undefined;

function celulas(linha: string): string[] {
  return linha.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
}

function alinhamentos(separador: string): Alinhamento[] {
  return celulas(separador).map((c) => {
    if (c.startsWith(':') && c.endsWith(':')) return 'center';
    if (c.endsWith(':')) return 'right';
    if (c.startsWith(':')) return 'left';
    return undefined;
  });
}

const RE_SEPARADOR_TABELA = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const RE_ITEM = /^\s*([-*]|\d+[.)])\s+(.*)$/;

function renderizarBlocos(markdown: string): ReactNode[] {
  const linhas = markdown.replace(/\r\n/g, '\n').split('\n');
  const blocos: ReactNode[] = [];
  let i = 0;
  let paragrafo: string[] = [];

  const fecharParagrafo = () => {
    if (paragrafo.length === 0) return;
    const k = `p-${blocos.length}`;
    blocos.push(
      <p key={k}>
        {paragrafo.map((linha, n) => (
          <Fragment key={n}>
            {n > 0 && <br />}
            {renderizarInline(linha, `${k}-${n}`)}
          </Fragment>
        ))}
      </p>,
    );
    paragrafo = [];
  };

  while (i < linhas.length) {
    const linha = linhas[i];
    const k = `b-${blocos.length}`;

    if (!linha.trim()) {
      fecharParagrafo();
      i += 1;
      continue;
    }

    const titulo = /^(#{1,4})\s+(.*)$/.exec(linha);
    if (titulo) {
      fecharParagrafo();
      const nivel = Math.min(titulo[1].length + 1, 5);
      const conteudo = renderizarInline(titulo[2], k);
      blocos.push(
        nivel === 2 ? <h2 key={k}>{conteudo}</h2>
          : nivel === 3 ? <h3 key={k}>{conteudo}</h3>
            : nivel === 4 ? <h4 key={k}>{conteudo}</h4>
              : <h5 key={k}>{conteudo}</h5>,
      );
      i += 1;
      continue;
    }

    if (linha.trim().startsWith('|') && RE_SEPARADOR_TABELA.test(linhas[i + 1] ?? '')) {
      fecharParagrafo();
      const cabecalho = celulas(linha);
      const alinha = alinhamentos(linhas[i + 1]);
      i += 2;
      const corpo: string[][] = [];
      while (i < linhas.length && linhas[i].trim().startsWith('|')) {
        corpo.push(celulas(linhas[i]));
        i += 1;
      }
      blocos.push(
        <div key={k} className="md-tabela">
          <table>
            <thead>
              <tr>{cabecalho.map((c, n) => <th key={n} style={{ textAlign: alinha[n] }}>{renderizarInline(c, `${k}-h${n}`)}</th>)}</tr>
            </thead>
            <tbody>
              {corpo.map((linhaTabela, r) => (
                <tr key={r}>
                  {linhaTabela.map((c, n) => (
                    <td key={n} style={{ textAlign: alinha[n] }}>{renderizarInline(c, `${k}-${r}-${n}`)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    const item = RE_ITEM.exec(linha);
    if (item) {
      fecharParagrafo();
      const ordenada = /\d/.test(item[1]);
      const itens: string[] = [];
      while (i < linhas.length) {
        const atual = RE_ITEM.exec(linhas[i]);
        if (atual && /\d/.test(atual[1]) === ordenada) {
          itens.push(atual[2]);
        } else if (linhas[i].trim() && /^\s{2,}/.test(linhas[i]) && itens.length) {
          itens[itens.length - 1] += ` ${linhas[i].trim()}`;
        } else {
          break;
        }
        i += 1;
      }
      const lis = itens.map((texto, n) => <li key={n}>{renderizarInline(texto, `${k}-${n}`)}</li>);
      blocos.push(ordenada ? <ol key={k}>{lis}</ol> : <ul key={k}>{lis}</ul>);
      continue;
    }

    if (/^\s*(-{3,}|\*{3,})\s*$/.test(linha)) {
      fecharParagrafo();
      blocos.push(<hr key={k} />);
      i += 1;
      continue;
    }

    paragrafo.push(linha.trim());
    i += 1;
  }
  fecharParagrafo();
  return blocos;
}

export const MarkdownResposta = memo(function MarkdownResposta({
  texto,
  className,
  escrevendo = false,
}: {
  texto: string;
  className?: string;
  /** Mostra o cursor no fim do texto (resposta sendo escrita). */
  escrevendo?: boolean;
}) {
  return (
    <div className={`md-resposta${className ? ` ${className}` : ''}`}>
      {renderizarBlocos(escrevendo ? texto + CURSOR : texto)}
    </div>
  );
});
