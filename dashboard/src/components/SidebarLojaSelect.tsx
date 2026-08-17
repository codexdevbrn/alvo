import { useEffect, useState } from 'react';
import { listarLojasEmpresa } from '../api/client';
import { EVENTO_EMPRESA } from '../utils/empresaSelecionada';
import { EVENTO_LOJA, lerLoja, selecionarLojaGlobal } from '../utils/lojaSelecionada';
import { AnalisadorCombobox } from './analisador/AnalisadorCombobox';

const ROTULO_TODAS = 'Todas as lojas';

/**
 * Seletor de loja da sidebar, logo abaixo do de empresa.
 *
 * Só aparece quando a empresa tem mais de uma loja: com uma loja só, o combobox
 * seria uma escolha sem alternativa ocupando espaço fixo na barra.
 *
 * A loja escolhida vale para todas as telas (`useEscopoAtual`). Se a loja
 * gravada sumiu da base — renomearam a loja na fonte —, o escopo volta para
 * "todas" em vez de continuar filtrando por um nome morto, que faria o backend
 * responder 400 em toda tela.
 */
export function SidebarLojaSelect() {
  const [empresa, setEmpresa] = useState(() => {
    try {
      return localStorage.getItem('alvo_empresa') || '';
    } catch {
      return '';
    }
  });
  // A lista guarda de qual empresa ela é: assim trocar de empresa não deixa as
  // lojas da anterior aparecendo por um render, e o efeito não precisa zerar
  // estado de forma síncrona (o que dispara render em cascata).
  const [cacheLojas, setCacheLojas] = useState<{ empresa: string; lojas: string[] }>(
    { empresa: '', lojas: [] },
  );
  const lojas = cacheLojas.empresa === empresa ? cacheLojas.lojas : [];
  const [loja, setLoja] = useState('');

  useEffect(() => {
    const sincronizar = () => {
      let nome = '';
      try {
        nome = localStorage.getItem('alvo_empresa') || '';
      } catch {
        nome = '';
      }
      setEmpresa(nome);
      setLoja(lerLoja(nome));
    };
    sincronizar();
    window.addEventListener(EVENTO_EMPRESA, sincronizar);
    window.addEventListener(EVENTO_LOJA, sincronizar);
    window.addEventListener('storage', sincronizar);
    return () => {
      window.removeEventListener(EVENTO_EMPRESA, sincronizar);
      window.removeEventListener(EVENTO_LOJA, sincronizar);
      window.removeEventListener('storage', sincronizar);
    };
  }, []);

  useEffect(() => {
    if (!empresa) return;
    let cancelado = false;
    listarLojasEmpresa(empresa)
      .then((nomes) => {
        if (cancelado) return;
        setCacheLojas({ empresa, lojas: nomes });
        const atual = lerLoja(empresa);
        if (atual && !nomes.includes(atual)) selecionarLojaGlobal(empresa, '');
      })
      .catch(() => {
        if (!cancelado) setCacheLojas({ empresa, lojas: [] });
      });
    return () => {
      cancelado = true;
    };
  }, [empresa]);

  if (!empresa || lojas.length < 2) return null;

  return (
    <div className="app-sidebar-empresa">
      <span className="app-sidebar-nav-label">Loja</span>
      <AnalisadorCombobox
        value={loja}
        options={lojas}
        onChange={(nome) => {
          setLoja(nome);
          selecionarLojaGlobal(empresa, nome);
        }}
        emptyLabel={ROTULO_TODAS}
        searchPlaceholder={lojas.length > 8 ? 'Buscar…' : false}
        aria-label="Selecionar loja"
        direcao="abaixo"
        portal
      />
    </div>
  );
}
