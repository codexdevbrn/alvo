import { BrowserRouter, Route, Routes } from 'react-router-dom';
import DashboardPage from './pages/DashboardPage';
import LoginPage from './pages/LoginPage';
import AnalisadorPage from './pages/AnalisadorPage';
import ConfiguracoesPage from './pages/ConfiguracoesPage';
import MonitorPage from './pages/MonitorPage';

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
      </Routes>
    </BrowserRouter>
  );
}
