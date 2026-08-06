import { useEffect, useRef } from 'react';
import { svg, stagger, createTimeline } from 'animejs';
import {
  LOADING_PRISMA_ASPECT,
  LOADING_PRISMA_GROUP_TRANSFORM,
  LOADING_PRISMA_LETTERS,
  LOADING_PRISMA_VIEWBOX,
} from '../assets/loadingPrismaPath';

interface LoadingScreenProps {
  /** Chamado assim que o primeiro ciclo completo do traçado terminar. A tela
   * deve permanecer visível até este callback disparar, mesmo que os dados
   * já tenham carregado — evita um flash de meio-segundo do desenho. */
  onFirstLoopDone?: () => void;
  /**
   * `tela-cheia` (padrão) ocupa a viewport inteira — usado só na primeira
   * entrada no site. `conteudo` ocupa apenas a área útil dentro do AppShell,
   * deixando a sidebar visível e navegável na troca de página.
   */
  variante?: 'tela-cheia' | 'conteudo';
}

/** Espera N requestAnimationFrames consecutivos. */
function waitFrames(n: number): Promise<void> {
  return new Promise<void>((resolve) => {
    let remaining = n;
    const tick = () => {
      remaining--;
      if (remaining <= 0) resolve();
      else requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

export function LoadingScreen({ onFirstLoopDone, variante = 'tela-cheia' }: LoadingScreenProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const orbRef = useRef<HTMLDivElement>(null);
  // Ref pro callback mais recente: o efeito abaixo roda só uma vez ([]) —
  // se `onFirstLoopDone` entrasse nas deps, uma prop inline (nova identidade
  // a cada render do pai) reiniciaria a animação do zero a cada re-render.
  const onFirstLoopDoneRef = useRef(onFirstLoopDone);
  onFirstLoopDoneRef.current = onFirstLoopDone;

  useEffect(() => {
    const root = svgRef.current;
    if (!root) return;

    let cancelled = false;
    let animation: { pause: () => void } | null = null;
    let avisado = false;
    const avisarUmaVez = () => {
      if (avisado) return;
      avisado = true;
      clearTimeout(travaDeSeguranca);
      onFirstLoopDoneRef.current?.();
    };

    // Rede de segurança: toda a animação depende de requestAnimationFrame, que
    // não roda em aba de fundo / janela não compositada. Sem isto o callback
    // nunca dispara e a página fica presa na tela de carregamento. O ciclo
    // completo leva ~3,2s; 8s é folga suficiente pra não cortar o desenho.
    const travaDeSeguranca = setTimeout(avisarUmaVez, 8000);

    // Mede o comprimento de cada traço (getTotalLength) já no mount e
    // pré-configura stroke-dasharray/dashoffset pra "traço totalmente oculto".
    // Isso evita que o createDrawable do anime.js force um reflow síncrono
    // surpresa no primeiro frame animado — principal causa do engasgo inicial.
    const paths = Array.from(root.querySelectorAll<SVGPathElement>('.loading-screen-prisma-line'));
    const lengths: number[] = [];
    paths.forEach((p, i) => {
      try {
        const len = p.getTotalLength();
        lengths[i] = len;
        // Esconde o traço: dasharray = comprimento total, dashoffset = comprimento total
        p.style.strokeDasharray = `${len}`;
        p.style.strokeDashoffset = `${len}`;
      } catch {
        lengths[i] = 0;
        /* path ainda não renderizado — createDrawable mede de novo depois */
      }
    });

    const start = async () => {
      // 2 rAFs: o 1º garante que o SVG está no layout; o 2º garante que o
      // browser já pintou e promoveu as camadas will-change pra GPU.
      // Antes usávamos apenas 1 rAF e os primeiros ~300ms engasgavam.
      await waitFrames(2);
      if (cancelled) return;
      if (!paths.length) {
        avisarUmaVez();
        return;
      }

      const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

      // Limpa o dash inline antes de entregar pro anime.js — createDrawable
      // vai recalcular, mas o trabalho pesado (getTotalLength) já foi feito
      // e está cacheado pelo browser.
      paths.forEach((p) => {
        p.style.strokeDasharray = '';
        p.style.strokeDashoffset = '';
      });

      const drawables = svg.createDrawable(paths, 0, 0);

      if (reduced) {
        drawables.forEach((d) => d.setAttribute('draw', '0 1'));
        avisarUmaVez();
        return;
      }

      const timeline = createTimeline({ loop: true, onLoop: avisarUmaVez });
      timeline
        .add(drawables, {
          draw: '0 1',
          ease: 'inOutQuad',
          duration: 1400,
          delay: stagger(85, { from: 'first' }),
        })
        .add(drawables, {
          draw: '1 1',
          ease: 'inOutQuad',
          duration: 900,
          delay: stagger(85, { from: 'last' }),
        });

      // Anima a luz de fundo exatamente no mesmo relógio do Javascript (0ms até 3150ms)
      if (orbRef.current) {
        timeline
          .add(
            orbRef.current,
            {
              scale: [0.85, 1.15],
              opacity: [0.45, 1],
              ease: 'easeInOutSine',
              duration: 1825,
            },
            0 // Fase 1: inicia em 0ms
          )
          .add(
            orbRef.current,
            {
              scale: [1.15, 0.85],
              opacity: [1, 0.45],
              ease: 'easeInOutSine',
              duration: 1325,
            },
            1825 // Fase 2: inicia em 1825ms
          );
      }

      animation = timeline;
    };

    start().catch(() => {
      paths.forEach((el) => el.setAttribute('stroke-opacity', '1'));
      avisarUmaVez();
    });

    return () => {
      cancelled = true;
      clearTimeout(travaDeSeguranca);
      animation?.pause();
    };
  }, []);

  return (
    <div
      className={`loading-screen loading-screen--${variante}`}
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div ref={orbRef} className="loading-screen-orb" aria-hidden="true" />
      <div className="loading-screen-prisma-wrap">
        <svg
          ref={svgRef}
          className="loading-screen-prisma"
          viewBox={LOADING_PRISMA_VIEWBOX}
          preserveAspectRatio="xMidYMid meet"
          style={{ aspectRatio: LOADING_PRISMA_ASPECT }}
          aria-hidden="true"
        >
          <g transform={LOADING_PRISMA_GROUP_TRANSFORM}>
            {LOADING_PRISMA_LETTERS.map((d, i) => (
              <path
                key={i}
                className="loading-screen-prisma-line"
                d={d}
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="butt"
              />
            ))}
          </g>
        </svg>
      </div>
      <p className="loading-screen-text">Carregando dados...</p>
    </div>
  );
}
