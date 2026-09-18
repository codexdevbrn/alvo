import { Suspense, lazy } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { ErrorBoundary } from './components/ErrorBoundary';
import { AppShell } from './components/AppShell';
import DashboardPage from './pages/DashboardPage';

// Só o Dashboard fica no chunk inicial: é a rota que o app abre ("/") e a
// única dona da splash de primeira entrada — em lazy, o shell vazio piscaria
// antes dela. As outras treze telas viram chunk sob demanda; juntas elas
// respondiam pela maior parte do bundle que o navegador baixava e parseava
// antes do primeiro paint, mesmo para quem só abria o Dashboard.
const LoginPage = lazy(() => import('./pages/LoginPage'));
const ConfiguracoesPage = lazy(() => import('./pages/ConfiguracoesPage'));
const MonitorPage = lazy(() => import('./pages/MonitorPage'));
const AnalisadorPage = lazy(() => import('./pages/AnalisadorPage'));
const CortesPage = lazy(() => import('./pages/CortesPage'));
const ClientesPage = lazy(() => import('./pages/ClientesPage'));
const VendedoresPage = lazy(() => import('./pages/VendedoresPage'));
const EstoquePage = lazy(() => import('./pages/EstoquePage'));
const DiagnosticoPage = lazy(() => import('./pages/DiagnosticoPage'));
const DespesasPage = lazy(() => import('./pages/DespesasPage'));
const PosPrecificacaoPage = lazy(() => import('./pages/PosPrecificacaoPage'));
const AssistenteIAPage = lazy(() => import('./pages/AssistenteIAPage'));
const MercadologicoPage = lazy(() => import('./pages/MercadologicoPage'));

// Mesma regra de "troca de tela" que o Dashboard já aplica: shell vivo,
// conteúdo vazio, sem o traçado do Prisma — o chunk vem do disco local e a
// animação só produziria piscada. Com o React Router 7 a navegação roda em
// transition, então isto aparece só quando a rota é aberta direto (F5, link).
const shellCarregando = (
  <AppShell>
    <div className="dashboard-container" />
  </AppShell>
);

// Login desativado: o Analisador é aberto, como o Dashboard. A tela de login
// segue existindo em /login (o backend continua emitindo token para quem quiser
// se identificar), mas nenhuma rota é bloqueada.
export default function App() {
  return (
    <BrowserRouter>
      <ErrorBoundary>
        <Suspense fallback={shellCarregando}>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            {/* Login não vive dentro do shell; herdar o fallback com sidebar
                mostraria uma tela que esta rota nunca desenha. */}
            <Route
              path="/login"
              element={
                <Suspense fallback={null}>
                  <LoginPage />
                </Suspense>
              }
            />
            <Route path="/config" element={<ConfiguracoesPage />} />
            <Route path="/monitor" element={<MonitorPage />} />
            <Route path="/analisador" element={<AnalisadorPage />} />
            <Route path="/cortes" element={<CortesPage />} />
            <Route path="/clientes" element={<ClientesPage />} />
            <Route path="/vendedores" element={<VendedoresPage />} />
            <Route path="/estoque" element={<EstoquePage />} />
            <Route path="/diagnostico" element={<DiagnosticoPage />} />
            <Route path="/despesas" element={<DespesasPage />} />
            <Route path="/pos-precificacao" element={<PosPrecificacaoPage />} />
            <Route path="/assistente" element={<AssistenteIAPage />} />
            <Route path="/mercadologico" element={<MercadologicoPage />} />
          </Routes>
        </Suspense>
      </ErrorBoundary>
    </BrowserRouter>
  );
}
