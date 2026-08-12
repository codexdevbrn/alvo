import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown, Search } from 'lucide-react';

interface AnalisadorComboboxProps {
  value?: string;
  options: string[];
  onChange?: (value: string) => void;
  /** Ativa seleção múltipla sem alterar consumidores legados de valor único. */
  multiple?: boolean;
  values?: string[];
  onMultipleChange?: (values: string[]) => void;
  /**
   * Rótulo da opção com value "" (ex.: Digitar manualmente / Todas as lojas).
   * Omitir ou `false` esconde a opção vazia (listas obrigatórias, ex.: granularidade).
   */
  emptyLabel?: string | false;
  /** Placeholder do campo de busca. `false` desativa a busca. */
  searchPlaceholder?: string | false;
  /** Mantém o valor atual na lista mesmo se não estiver em `options`. */
  includeOrphanValue?: boolean;
  /** Direção do painel. Padrão: abaixo (página); use `acima` no rodapé de modais. */
  direcao?: 'abaixo' | 'acima';
  /**
   * Renderiza o painel em portal (fixed) — evita corte por overflow da sidebar.
   */
  portal?: boolean;
  disabled?: boolean;
  'aria-label'?: string;
}

function medirPainel(
  trigger: HTMLElement,
  direcao: 'abaixo' | 'acima',
): { top: number; left: number; width: number } {
  const r = trigger.getBoundingClientRect();
  const largura = Math.max(r.width, 260);
  const left = Math.min(Math.max(8, r.left), window.innerWidth - largura - 8);
  if (direcao === 'acima') {
    return { top: Math.max(8, r.top - 6), left, width: largura };
  }
  return {
    top: Math.min(r.bottom + 6, window.innerHeight - 120),
    left,
    width: largura,
  };
}

function mesmosValores(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((item, indice) => item === b[indice]);
}

/**
 * Combobox custom (não usa &lt;select&gt; nativo).
 * Visual alinhado a FilterBar: painel glass escuro, accent no hover/selecionado.
 */
export function AnalisadorCombobox({
  value = '',
  options,
  onChange,
  multiple = false,
  values = [],
  onMultipleChange,
  emptyLabel = false,
  searchPlaceholder = 'Buscar…',
  includeOrphanValue = false,
  direcao = 'abaixo',
  portal = false,
  disabled = false,
  'aria-label': ariaLabel,
}: AnalisadorComboboxProps) {
  const [aberto, setAberto] = useState(false);
  const [busca, setBusca] = useState('');
  /** Seleção provisória: só sobe ao pai quando o painel fecha. */
  const [valoresRascunho, setValoresRascunho] = useState<string[]>(values);
  const [painelPos, setPainelPos] = useState<{ top: number; left: number; width: number } | null>(null);
  /** Outside-click só após o ciclo do clique que abriu — evita fechar no mesmo gesto. */
  const [foraPronto, setForaPronto] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const buscaRef = useRef<HTMLInputElement>(null);
  const painelRef = useRef<HTMLDivElement>(null);
  const listboxId = useId();
  const searchable = searchPlaceholder !== false;
  const emptyTexto = typeof emptyLabel === 'string' ? emptyLabel : '';
  const temEmpty = emptyTexto.length > 0;
  const valoresAtivos = multiple && aberto ? valoresRascunho : values;
  const valoresSelecionados = useMemo(() => new Set(valoresAtivos), [valoresAtivos]);

  const opcoesExtras = useMemo(() => {
    if (!includeOrphanValue) return [];
    if (multiple) return valoresAtivos.filter((item) => item && !options.includes(item));
    if (!value || options.includes(value)) return [];
    return [value];
  }, [includeOrphanValue, multiple, value, valoresAtivos, options]);

  const todasOpcoes = useMemo(
    () => [...opcoesExtras, ...options],
    [opcoesExtras, options],
  );

  const filtradas = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    if (!termo) return todasOpcoes;
    return todasOpcoes.filter((nome) => nome.toLowerCase().includes(termo));
  }, [todasOpcoes, busca]);

  const termoBusca = busca.trim().toLowerCase();
  const mostraEmpty =
    temEmpty && (!termoBusca || emptyTexto.toLowerCase().includes(termoBusca));

  const rotulo = multiple
    ? valoresAtivos.length === 0
      ? emptyTexto || 'Selecionar…'
      : valoresAtivos.length === 1
        ? valoresAtivos[0]
        : `${valoresAtivos.length} lojas selecionadas`
    : value || emptyTexto || 'Selecionar…';

  const fechar = useCallback(() => {
    if (multiple && !mesmosValores(valoresRascunho, values)) {
      onMultipleChange?.(valoresRascunho);
    }
    setAberto(false);
    setBusca('');
    setPainelPos(null);
    setForaPronto(false);
  }, [multiple, onMultipleChange, valoresRascunho, values]);

  const atualizarPosicao = () => {
    const el = triggerRef.current;
    if (!el) return;
    setPainelPos(medirPainel(el, direcao));
  };

  useLayoutEffect(() => {
    if (!aberto) {
      setPainelPos(null);
      return;
    }
    if (portal) {
      atualizarPosicao();
      window.addEventListener('resize', atualizarPosicao);
      window.addEventListener('scroll', atualizarPosicao, true);
      return () => {
        window.removeEventListener('resize', atualizarPosicao);
        window.removeEventListener('scroll', atualizarPosicao, true);
      };
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aberto, portal, direcao]);

  // Foco na busca sem rolar a página
  useLayoutEffect(() => {
    if (!aberto || !searchable) return;
    buscaRef.current?.focus({ preventScroll: true });
  }, [aberto, searchable, painelPos]);

  useEffect(() => {
    if (!aberto) {
      setForaPronto(false);
      return;
    }
    const t = window.setTimeout(() => setForaPronto(true), 0);
    return () => window.clearTimeout(t);
  }, [aberto]);

  useEffect(() => {
    if (!aberto) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') fechar();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [aberto, fechar]);

  // Fecha ao clicar fora (portal e inline); registrado só no próximo tick
  useEffect(() => {
    if (!aberto || !foraPronto) return;
    const onPointerDown = (e: PointerEvent) => {
      const alvo = e.target as Node | null;
      if (!alvo) return;
      if (triggerRef.current?.contains(alvo)) return;
      if (painelRef.current?.contains(alvo)) return;
      fechar();
    };
    document.addEventListener('pointerdown', onPointerDown, true);
    return () => document.removeEventListener('pointerdown', onPointerDown, true);
  }, [aberto, fechar, foraPronto]);

  const selecionar = (nome: string) => {
    const scrollY = window.scrollY;
    const main = document.querySelector('.app-shell-main') as HTMLElement | null;
    const mainScroll = main?.scrollTop ?? 0;
    if (multiple) {
      let proximos: string[];
      if (!nome) {
        proximos = [];
      } else if (valoresSelecionados.has(nome)) {
        proximos = valoresRascunho.filter((item) => item !== nome);
      } else {
        proximos = [...valoresRascunho, nome].sort((a, b) => a.localeCompare(b, 'pt-BR'));
      }
      // Marcar todas equivale ao escopo vazio "Todas as lojas".
      if (options.length > 0 && proximos.length === options.length) proximos = [];
      setValoresRascunho(proximos);
    } else {
      fechar();
      // Devolve foco ao trigger sem scroll jump
      triggerRef.current?.focus({ preventScroll: true });
      if (nome !== value) onChange?.(nome);
    }
    requestAnimationFrame(() => {
      window.scrollTo({
        top: scrollY,
        left: 0,
        behavior: 'instant' in document.documentElement.style ? 'instant' as ScrollBehavior : 'auto',
      });
      if (main) main.scrollTop = mainScroll;
    });
  };

  const alternar = () => {
    if (disabled) return;
    if (aberto) {
      fechar();
      return;
    }
    // Posição pronta antes do 1º paint do portal → evita flash “pra cima”
    if (portal && triggerRef.current) {
      setPainelPos(medirPainel(triggerRef.current, direcao));
    }
    if (multiple) setValoresRascunho(values);
    setBusca('');
    setAberto(true);
  };

  const painelStyle: CSSProperties | undefined = portal && painelPos
    ? {
        position: 'fixed',
        top: direcao === 'acima' ? 'auto' : painelPos.top,
        bottom: direcao === 'acima' ? window.innerHeight - painelPos.top : 'auto',
        left: painelPos.left,
        width: painelPos.width,
        right: 'auto',
        zIndex: 10050,
      }
    : undefined;

  // Portal só monta depois da posição — sem frame com CSS “abre pra cima”
  const mostrarPortal = portal && aberto && painelPos !== null;
  const mostrarInline = !portal && aberto;

  const painelConteudo = (
    <div
      ref={painelRef}
      id={listboxId}
      className={`empresa-dropdown-panel${direcao === 'abaixo' ? ' is-abaixo' : ''}${portal ? ' is-portal' : ''}`}
      role="listbox"
      aria-multiselectable={multiple || undefined}
      style={painelStyle}
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => {
        // Evita blur ao clicar opções; deixa o input de busca receber foco
        if ((e.target as HTMLElement).closest('input, textarea')) return;
        e.preventDefault();
      }}
    >
      {searchable && (
        <div className="empresa-dropdown-busca">
          <Search size={14} aria-hidden />
          <input
            ref={buscaRef}
            type="search"
            className="analisador-input"
            placeholder={searchPlaceholder || 'Buscar…'}
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
            aria-label={typeof searchPlaceholder === 'string' ? searchPlaceholder : 'Buscar'}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                e.stopPropagation();
                fechar();
              }
            }}
          />
        </div>
      )}
      <div className="empresa-dropdown-lista custom-scrollbar">
        {mostraEmpty && (
          <button
            type="button"
            role="option"
            aria-selected={multiple ? valoresAtivos.length === 0 : value === ''}
            className={`dropdown-menu-item empresa-dropdown-item is-padrao${(multiple ? valoresAtivos.length === 0 : value === '') ? ' is-selecionada is-selected' : ''}`}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => selecionar('')}
          >
            {multiple && (
              <span className="analisador-combobox-check-slot" aria-hidden>
                {valoresAtivos.length === 0 && <Check size={14} />}
              </span>
            )}
            {emptyTexto}
          </button>
        )}
        {filtradas.map((nome) => {
          const selecionada = multiple ? valoresSelecionados.has(nome) : value === nome;
          return (
            <button
              type="button"
              key={nome}
              role="option"
              aria-selected={selecionada}
              className={`dropdown-menu-item empresa-dropdown-item${selecionada ? ' is-selecionada is-selected' : ''}`}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => selecionar(nome)}
            >
              {multiple && (
                <span className="analisador-combobox-check-slot" aria-hidden>
                  {selecionada && <Check size={14} />}
                </span>
              )}
              {nome}
            </button>
          );
        })}
        {todasOpcoes.length === 0 && (
          <div className="empresa-dropdown-vazio">Nenhuma opção disponível.</div>
        )}
        {todasOpcoes.length > 0 && filtradas.length === 0 && !mostraEmpty && (
          <div className="empresa-dropdown-vazio">
            Nenhuma opção correspondente a “{busca.trim()}”.
          </div>
        )}
      </div>
    </div>
  );

  return (
    <div className={`empresa-select-wrap${aberto ? ' is-open' : ''}`}>
      <button
        ref={triggerRef}
        type="button"
        role="combobox"
        aria-expanded={aberto}
        aria-controls={listboxId}
        aria-haspopup="listbox"
        aria-label={ariaLabel}
        disabled={disabled}
        className="custom-select analisador-select custom-select-trigger"
        onClick={alternar}
      >
        <span className={`custom-select-trigger-label${(multiple ? valoresAtivos.length === 0 : !value) ? ' is-placeholder' : ''}`}>{rotulo}</span>
        <ChevronDown size={14} className="custom-select-trigger-chevron" aria-hidden />
      </button>

      {mostrarInline && painelConteudo}

      {mostrarPortal && createPortal(painelConteudo, document.body)}
    </div>
  );
}
