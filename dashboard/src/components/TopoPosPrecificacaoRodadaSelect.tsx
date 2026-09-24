import { Loader2 } from 'lucide-react';
import type { RodadaPrecificacao } from '../api/client';
import { useEscopoAtual } from '../hooks/useEscopoAtual';
import { useRodadaPrecificacao } from '../hooks/useRodadaPrecificacao';
import { AnalisadorCombobox } from './analisador/AnalisadorCombobox';

function rotulo(rodada: RodadaPrecificacao): string {
  const [ano, mes, dia] = rodada.dia.split('-');
  const pares = rodada.pares.toLocaleString('pt-BR');
  return `${dia}/${mes}/${ano} · ${pares} ${rodada.pares === 1 ? 'par' : 'pares'}`;
}

/** Rodada de precificação no `app-shell-topo`, só na Pós precificação. Aparece
 *  mesmo com uma rodada só, para a data do dump ficar sempre visível. */
export function TopoPosPrecificacaoRodadaSelect() {
  const { empresa } = useEscopoAtual();
  const { escolhida, publicadas, escolher } = useRodadaPrecificacao(empresa);
  const rodadas = publicadas?.rodadas ?? [];
  if (rodadas.length === 0) return null;

  const ativa = rodadas.find((item) => item.dia === (escolhida ?? publicadas?.ativa)) ?? rodadas[0];

  return (
    <div className="app-sidebar-empresa">
      <span className="app-sidebar-nav-label">
        Rodada
        {publicadas?.ocupado && <Loader2 size={10} className="dashboard-filter-spinner" aria-label="Recalculando" />}
      </span>
      <AnalisadorCombobox
        value={rotulo(ativa)}
        options={rodadas.map(rotulo)}
        onChange={(texto) => {
          const item = rodadas.find((rodada) => rotulo(rodada) === texto);
          if (item) escolher(item.dia);
        }}
        emptyLabel={false}
        searchPlaceholder={false}
        disabled={publicadas?.ocupado}
        aria-label="Rodada de precificação"
        direcao="abaixo"
        portal
      />
    </div>
  );
}
