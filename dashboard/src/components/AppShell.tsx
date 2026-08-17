import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import {
  LayoutGrid,
  LogOut,
  Settings,
  BarChart3,
  Gauge,
  Store,
  Wallet,
  PanelLeftClose,
  PanelLeftOpen,
  UsersRound,
  PackageSearch,
} from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { getToken, clearToken, obterStatusAtualizacao, type StatusAtualizacao } from '../api/client';
import { BannerAtualizacao } from './BannerAtualizacao';
import { SidebarEmpresaSelect } from './SidebarEmpresaSelect';
import { SidebarLojaSelect } from './SidebarLojaSelect';

const URL_CARTEIRA = 'http://monitor-2d/';
const LS_SIDEBAR = 'prisma_sidebar_collapsed';
const ANIM_MS = 340;
const ANIM_EASE = 'cubic-bezier(0.33, 1, 0.68, 1)';
/** Abaixo disso a sidebar vira topo estático (media query) e não empurra o main. */
const BREAKPOINT_PUSH = 1024;

function larguraSidebarPx(prop: string, fallback: number): number {
  const v = getComputedStyle(document.documentElement).getPropertyValue(prop).trim();
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : fallback;
}

interface NavItemProps {
  icon: ReactNode;
  label: string;
  collapsed: boolean;
  ativo?: boolean;
  destaque?: boolean;
  onClick?: () => void;
  href?: string;
  /** Ponto de aviso no ícone (ex.: atualização disponível). */
  aviso?: string;
}

/**
 * Item da sidebar. Ao recolher, texto e ícone recentram via CSS puro
 * (`max-width`/`padding-left`), na mesma transição/curva do width da
 * sidebar. Nada de framer aqui: animar `width` via JS exige medir layout a
 * cada frame (sem composição GPU) — é isso que deixava a animação travada.
 */
function NavItem({ icon, label, collapsed, ativo, destaque, onClick, href, aviso }: NavItemProps) {
  const className = `app-sidebar-nav-item${ativo ? ' is-ativo' : ''}${destaque ? ' app-sidebar-nav-item-destaque' : ''}`;
  const conteudo = (
    <>
      <span className="app-sidebar-nav-icon">
        {icon}
        {/* Ponto no ícone, e não ao lado do texto: a sidebar recolhida esconde o
            texto, e o aviso tem de continuar visível. */}
        {aviso && <span className="app-sidebar-nav-aviso" aria-hidden="true" />}
      </span>
      <span className="app-sidebar-nav-text" aria-hidden={collapsed}>
        {label}
      </span>
    </>
  );

  if (href) {
    return (
      <a className={className} href={href} target="_blank" rel="noopener noreferrer" title={aviso || label}>
        {conteudo}
      </a>
    );
  }
  return (
    <button type="button" className={className} onClick={onClick} title={aviso || label}>
      {conteudo}
    </button>
  );
}

function lerCollapsed(): boolean {
  try {
    return localStorage.getItem(LS_SIDEBAR) === '1';
  } catch {
    return false;
  }
}

interface AppShellProps {
  children: ReactNode;
  /** Rodapé da sidebar — hoje só o Dashboard tem essa info (data do BI). */
  ultimoMovimento?: string;
}

export function AppShell({ children, ultimoMovimento }: AppShellProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const logado = Boolean(getToken());
  const emAnalisador = location.pathname.startsWith('/analisador');
  const emMonitor = location.pathname.startsWith('/monitor');
  const emClientes = location.pathname.startsWith('/clientes');
  const emEstoque = location.pathname.startsWith('/estoque');
  const emConfig = location.pathname.startsWith('/config');
  const emMercadologico = location.pathname.startsWith('/mercadologico');
  const emDashboard = location.pathname === '/';
  const initialCollapsed = lerCollapsed();
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.innerWidth <= BREAKPOINT_PUSH,
  );
  // No mobile a sidebar é uma barra de topo estática e sempre mostra os rótulos.
  const colapsado = collapsed && !isMobile;
  const mainRef = useRef<HTMLElement>(null);
  const [statusAtualizacao, setStatusAtualizacao] = useState<StatusAtualizacao | null>(null);

  // Aviso de versão nova em qualquer tela, e não só dentro de Configurações:
  // quem nunca abre aquela tela nunca saberia que existe atualização. O backend
  // responde de um cache alimentado no boot, então isto não custa acesso à pasta
  // de rede a cada navegação. Falha é silenciosa de propósito — canal ausente ou
  // fora do ar é estado normal, não erro para mostrar na sidebar.
  useEffect(() => {
    let cancelado = false;
    void obterStatusAtualizacao()
      .then((status) => {
        if (cancelado || !status.atualizavel) return;
        setStatusAtualizacao(status);
      })
      .catch(() => { /* sem aviso */ });
    return () => { cancelado = true; };
  }, [location.pathname]);
  const primeiraRenderizacao = useRef(true);

  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${BREAKPOINT_PUSH}px)`);
    const onChange = () => setIsMobile(mq.matches);
    onChange();
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(LS_SIDEBAR, collapsed ? '1' : '0');
    } catch {
      /* private mode */
    }
  }, [collapsed]);

  // FLIP: o main reflowa 1× para o layout final (margin já no valor novo) e
  // desliza via `transform` (composição GPU, sem reflow por frame). Evita que o
  // gráfico responsivo recalcule a cada frame — causa do baixo FPS.
  useLayoutEffect(() => {
    const el = mainRef.current;
    if (!el) return;
    if (primeiraRenderizacao.current) {
      primeiraRenderizacao.current = false;
      return;
    }
    if (window.innerWidth <= BREAKPOINT_PUSH) return; // no mobile a sidebar não empurra

    const delta =
      larguraSidebarPx('--sidebar-width', 232) -
      larguraSidebarPx('--sidebar-width-collapsed', 68);
    // Ao recolher, o layout final está `delta` à esquerda → começa deslocado +delta.
    // Ao expandir, o inverso.
    const from = colapsado ? delta : -delta;

    el.style.transition = 'none';
    el.style.transform = `translateX(${from}px)`;
    void el.offsetWidth; // força o browser a assumir o estado inicial
    el.style.transition = `transform ${ANIM_MS}ms ${ANIM_EASE}`;
    el.style.transform = 'translateX(0)';

    const limpar = () => {
      el.style.transition = '';
      el.style.transform = '';
    };
    const timer = window.setTimeout(limpar, ANIM_MS + 40);
    return () => window.clearTimeout(timer);
  }, [colapsado]);

  const sair = () => {
    clearToken();
    navigate('/login');
  };

  const toggle = () => setCollapsed((c) => !c);

  return (
    <div className={`app-shell${colapsado ? ' is-sidebar-collapsed' : ''}`}>
      <aside className={`app-sidebar${colapsado ? ' is-collapsed' : ''}`}>
        <div className="app-sidebar-brand">
          <img
            className="app-sidebar-logo"
            src="/logo_2d_icone.png"
            alt=""
            width={34}
            height={34}
          />
          <div className="app-sidebar-brand-text">
            <span className="app-sidebar-brand-nome">Prisma</span>
            <span className="app-sidebar-brand-sub">Sistema de análises</span>
          </div>
          <button
            type="button"
            className="app-sidebar-toggle"
            onClick={toggle}
            aria-label={colapsado ? 'Expandir menu' : 'Recolher menu'}
            title={colapsado ? 'Expandir menu' : 'Recolher menu'}
          >
            {colapsado ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
          </button>
        </div>

        <SidebarEmpresaSelect />
        <SidebarLojaSelect />

        <nav className="app-sidebar-nav">
          <span className="app-sidebar-nav-label">Menu</span>
          <NavItem
            icon={<LayoutGrid size={17} />}
            label="Dashboard"
            collapsed={colapsado}
            ativo={emDashboard}
            onClick={() => navigate('/')}
          />
          <NavItem
            icon={<BarChart3 size={17} />}
            label="Analisador de Monitoria"
            collapsed={colapsado}
            ativo={emAnalisador}
            onClick={() => navigate('/analisador')}
          />
          <NavItem
            icon={<Gauge size={17} />}
            label="Monitoramento"
            collapsed={colapsado}
            ativo={emMonitor}
            onClick={() => navigate('/monitor')}
          />
          <NavItem
            icon={<UsersRound size={17} />}
            label="Clientes"
            collapsed={colapsado}
            ativo={emClientes}
            onClick={() => navigate('/clientes')}
          />
          <NavItem
            icon={<PackageSearch size={17} />}
            label="Estoque"
            collapsed={colapsado}
            ativo={emEstoque}
            onClick={() => navigate('/estoque')}
          />
          <NavItem
            icon={<Store size={17} />}
            label="Dados mercadológicos"
            collapsed={colapsado}
            ativo={emMercadologico}
            onClick={() => navigate('/mercadologico')}
          />
        </nav>

        <div className="app-sidebar-spacer" />

        <nav className="app-sidebar-nav">
          <span className="app-sidebar-nav-label">Sistema</span>
          <NavItem
            icon={<Settings size={17} />}
            label="Configurações"
            collapsed={colapsado}
            ativo={emConfig}
            aviso={statusAtualizacao?.atualizavel ? `Versão ${statusAtualizacao.versao_disponivel} disponível` : undefined}
            onClick={() => navigate('/config')}
          />
          <NavItem
            icon={<Wallet size={17} />}
            label="Carteira"
            collapsed={colapsado}
            destaque
            href={URL_CARTEIRA}
          />
          {emAnalisador && logado && (
            <NavItem
              icon={<LogOut size={17} />}
              label="Sair"
              collapsed={colapsado}
              onClick={sair}
            />
          )}
          {/* "Sair" só aparece para quem tem token: com o login desativado
              ninguém precisa entrar, mas quem entrou pode sair. */}
        </nav>

        {ultimoMovimento && (
          <p className="app-sidebar-footer">
            Último movimento: <strong>{ultimoMovimento}</strong>
          </p>
        )}
      </aside>

      <main ref={mainRef} className="app-shell-main">
        {statusAtualizacao && <BannerAtualizacao status={statusAtualizacao} />}
        {children}
      </main>
    </div>
  );
}
