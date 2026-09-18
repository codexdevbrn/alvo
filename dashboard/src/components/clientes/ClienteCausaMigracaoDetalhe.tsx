import { useEffect, useState } from 'react';
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Loader2 } from 'lucide-react';
import {
  obterCausaMigracaoCliente,
  type CausaMigracaoClienteResposta,
} from '../../api/client';
import type { ModoPeriodo } from '../../utils/mesesFechados';

interface Props {
  empresa: string;
  cliente: string;
  loja?: string | null;
  modoPeriodo: ModoPeriodo;
  grupos?: string;
}

const SEM_CAUSA = 'Sem causa aparente — nenhuma heurística bateu com folga nesta transição.';

/** Card que abre logo abaixo da linha clicada em "Pior cauda"/"Melhores
 *  scores" — cada migração de faixa ABC do cliente na janela do score, com a
 *  causa provável (produto abandonado/novo, frequência ou ticket médio).
 *  Mesmo padrão inline de ClientePotencialDetalhe, não um modal. */
export function ClienteCausaMigracaoDetalhe({ empresa, cliente, loja = null, modoPeriodo, grupos }: Props) {
  const [dados, setDados] = useState<CausaMigracaoClienteResposta | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    let vivo = true;
    setCarregando(true);
    setErro(null);
    setDados(null);
    void obterCausaMigracaoCliente(empresa, cliente, loja, modoPeriodo, grupos)
      .then((resposta) => {
        if (vivo) setDados(resposta);
      })
      .catch((falha) => {
        if (!vivo) return;
        setErro(falha instanceof Error ? falha.message : 'Falha ao carregar a migração do cliente.');
      })
      .finally(() => {
        if (vivo) setCarregando(false);
      });
    return () => {
      vivo = false;
    };
  }, [empresa, cliente, loja, modoPeriodo, grupos]);

  return (
    <li className="clientes-potencial-detalhe">
      <div className="clientes-potencial-detalhe-topo">
        <h3 title={cliente}>{cliente}</h3>
      </div>

      {carregando && (
        <p className="analisador-hint"><Loader2 size={14} className="dashboard-filter-spinner" /> Carregando migrações…</p>
      )}

      {!carregando && erro && (
        <div className="glass-card glass-card-flat analisador-erro" role="alert">
          <AlertTriangle size={17} /> {erro}
        </div>
      )}

      {!carregando && !erro && dados && !dados.disponivel && (
        <p className="analisador-hint">Histórico insuficiente para calcular a migração deste cliente.</p>
      )}

      {!carregando && !erro && dados?.disponivel && (
        dados.eventos.length === 0 ? (
          <p className="analisador-hint">Nenhuma migração de faixa na janela.</p>
        ) : (
          <ul className="clientes-causa-eventos">
            {dados.eventos.map((evento, indice) => {
              const subiu = evento.direcao === 'Subiu';
              return (
                <li key={`${evento.periodo_anterior}-${evento.periodo_atual}-${indice}`}>
                  <p className="clientes-causa-evento-topo">
                    {subiu
                      ? <ArrowUpRight size={13} className="is-alta" aria-hidden="true" />
                      : <ArrowDownRight size={13} className="is-queda" aria-hidden="true" />}
                    <span>{evento.periodo_anterior} → {evento.periodo_atual}</span>
                    <span className="clientes-causa-evento-faixas">
                      {evento.faixa_anterior} → {evento.faixa_atual}
                    </span>
                  </p>
                  <p className="clientes-causa-evento-texto">{evento.causa || SEM_CAUSA}</p>
                </li>
              );
            })}
          </ul>
        )
      )}
    </li>
  );
}
