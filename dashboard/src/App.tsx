import { BrowserRouter, Route, Routes } from 'react-router-dom';
import DashboardPage from './pages/DashboardPage';
import LoginPage from './pages/LoginPage';
import AnalisadorPage from './pages/AnalisadorPage';
import ConfiguracoesPage from './pages/ConfiguracoesPage';
import MonitorPage from './pages/MonitorPage';
import MercadologicoPage from './pages/MercadologicoPage';
import ClientesPage from './pages/ClientesPage';
import VendedoresPage from './pages/VendedoresPage';
import EstoquePage from './pages/EstoquePage';
import DespesasPage from './pages/DespesasPage';
import AssistenteIAPage from './pages/AssistenteIAPage';

// Login desativado: o Analisador é aberto, como o Dashboard. A tela de login
// segue existindo em /login (o backend continua emitindo token para quem quiser
// se identificar), mas nenhuma rota é bloqueada.
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/config" element={<ConfiguracoesPage />} />
        <Route path="/monitor" element={<MonitorPage />} />
        <Route path="/analisador" element={<AnalisadorPage />} />
        <Route path="/clientes" element={<ClientesPage />} />
        <Route path="/vendedores" element={<VendedoresPage />} />
        <Route path="/estoque" element={<EstoquePage />} />
        <Route path="/despesas" element={<DespesasPage />} />
        <Route path="/assistente" element={<AssistenteIAPage />} />
        <Route path="/mercadologico" element={<MercadologicoPage />} />
      </Routes>
    </BrowserRouter>
  );
}
