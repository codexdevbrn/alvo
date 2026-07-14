import type { ReactElement } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import DashboardPage from './pages/DashboardPage';
import LoginPage from './pages/LoginPage';
import AnalisadorPage from './pages/AnalisadorPage';
import { getToken } from './api/client';

function RotaProtegida({ children }: { children: ReactElement }) {
  return getToken() ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/analisador"
          element={
            <RotaProtegida>
              <AnalisadorPage />
            </RotaProtegida>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}
