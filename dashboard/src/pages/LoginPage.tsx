import { useState } from 'react';
import type { FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Lock, User } from 'lucide-react';
import { login } from '../api/client';

export default function LoginPage() {
  const navigate = useNavigate();
  const [usuario, setUsuario] = useState('');
  const [senha, setSenha] = useState('');
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(false);

  const handleSubmit = async (evento: FormEvent) => {
    evento.preventDefault();
    setErro(null);
    setCarregando(true);
    try {
      await login(usuario, senha);
      navigate('/analisador');
    } catch (erroLogin) {
      setErro(erroLogin instanceof Error ? erroLogin.message : 'Falha ao entrar.');
    } finally {
      setCarregando(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem' }}>
      <form onSubmit={handleSubmit} className="glass-card" style={{ width: '100%', maxWidth: 380, display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
        <div>
          <h1 style={{ fontSize: '1.75rem', fontWeight: 700, margin: 0 }}>Analisador de Monitoria</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: '0.25rem' }}>
            Entre para acessar as análises de vendas.
          </p>
        </div>

        <label style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
          Usuário
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border)', borderRadius: '0.75rem', padding: '0.6rem 0.8rem' }}>
            <User size={16} color="var(--text-secondary)" />
            <input
              value={usuario}
              onChange={(e) => setUsuario(e.target.value)}
              autoFocus
              required
              style={{ background: 'transparent', border: 'none', outline: 'none', color: 'var(--text-primary)', fontSize: '0.95rem', width: '100%' }}
            />
          </div>
        </label>

        <label style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
          Senha
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border)', borderRadius: '0.75rem', padding: '0.6rem 0.8rem' }}>
            <Lock size={16} color="var(--text-secondary)" />
            <input
              type="password"
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              required
              style={{ background: 'transparent', border: 'none', outline: 'none', color: 'var(--text-primary)', fontSize: '0.95rem', width: '100%' }}
            />
          </div>
        </label>

        {erro && <p style={{ color: '#f43f5e', fontSize: '0.85rem', margin: 0 }}>{erro}</p>}

        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <button
            type="button"
            onClick={() => navigate('/')}
            disabled={carregando}
            style={{
              flex: 1, background: 'rgba(255,255,255,0.05)', color: 'var(--text-primary)',
              border: '1px solid var(--border)', borderRadius: '0.75rem',
              padding: '0.75rem', fontSize: '0.95rem', fontWeight: 600, cursor: carregando ? 'not-allowed' : 'pointer',
              opacity: carregando ? 0.7 : 1,
            }}
          >
            Cancelar
          </button>
          <button
            type="submit"
            disabled={carregando}
            style={{
              flex: 1, background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: '0.75rem',
              padding: '0.75rem', fontSize: '0.95rem', fontWeight: 600, cursor: carregando ? 'wait' : 'pointer',
              opacity: carregando ? 0.7 : 1,
            }}
          >
            {carregando ? 'Entrando...' : 'Entrar'}
          </button>
        </div>
      </form>
    </div>
  );
}
