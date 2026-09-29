import { memo } from 'react';
import { CheckCircle2, ChevronDown, Loader2, XCircle } from 'lucide-react';
import type { PassoChatIA } from '../../api/client';

export interface PassoLocal extends PassoChatIA {
  texto: string;
}

function IconePasso({ estado }: { estado: PassoChatIA['estado'] }) {
  if (estado === 'andamento') return <Loader2 size={14} className="chat-ia-spin" aria-hidden="true" />;
  if (estado === 'erro') return <XCircle size={14} aria-hidden="true" />;
  return <CheckCircle2 size={14} aria-hidden="true" />;
}

/**
 * O que o agente está fazendo enquanto a resposta não vem.
 *
 * A linha "Lendo os documentos" é a fase antes da primeira consulta; cada
 * ferramenta chamada entra como um passo (girando → ok/erro); "Escrevendo a
 * resposta" aparece quando o texto começa a chegar. O relógio é para a espera
 * de 20–40 s com várias consultas não parecer travada.
 */
export const PassosAgenteAoVivo = memo(function PassosAgenteAoVivo({
  passos,
  escrevendo,
  refazendo,
  segundos,
}: {
  passos: PassoLocal[];
  escrevendo: boolean;
  refazendo: boolean;
  segundos: number;
}) {
  const leuDocumentos = passos.length > 0 || escrevendo;
  const consultando = passos.some((p) => p.estado === 'andamento');
  return (
    <div className="chat-ia-passos" aria-live="polite">
      <div className="chat-ia-passos-topo">
        <span>{refazendo ? 'Ajustando o formato da resposta' : escrevendo ? 'Escrevendo' : consultando ? 'Consultando a base' : 'Pensando'}</span>
        <span className="chat-ia-passos-relogio">{segundos} s</span>
      </div>
      <ol>
        <li className={`is-${leuDocumentos ? 'ok' : 'andamento'}`}>
          <IconePasso estado={leuDocumentos ? 'ok' : 'andamento'} /> Lendo os documentos da empresa
        </li>
        {passos.map((passo) => (
          <li key={passo.id} className={`is-${passo.estado}`}>
            <IconePasso estado={passo.estado} /> {passo.texto}
          </li>
        ))}
        {escrevendo && (
          <li className="is-andamento">
            <IconePasso estado="andamento" /> Escrevendo a resposta
          </li>
        )}
      </ol>
    </div>
  );
});

/** Resumo recolhível, embaixo da resposta: o que foi consultado e quanto levou. */
export const PassosAgenteResumo = memo(function PassosAgenteResumo({
  passos,
  segundos,
}: {
  passos: PassoLocal[];
  segundos?: number;
}) {
  if (passos.length === 0) return null;
  const erros = passos.filter((p) => p.estado === 'erro').length;
  return (
    <details className="chat-ia-passos-resumo">
      <summary>
        <ChevronDown size={13} aria-hidden="true" />
        {passos.length} {passos.length === 1 ? 'consulta' : 'consultas'} à base
        {erros > 0 && ` · ${erros} com erro`}
        {segundos != null && ` · ${segundos} s`}
      </summary>
      <ol>
        {passos.map((passo) => (
          <li key={passo.id} className={`is-${passo.estado}`}>
            <IconePasso estado={passo.estado} /> {passo.texto}
          </li>
        ))}
      </ol>
    </details>
  );
});
