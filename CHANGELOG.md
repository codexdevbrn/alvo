# Changelog

Formato: uma seção por versão publicada, mais recente no topo. Histórico é
incremental — entradas antigas nunca são apagadas. O estado atual das telas e
funcionalidades vive em `DOC_TEC.md`, não aqui.

## 1.5.0 — 2026-09-01

### Adicionado

- **Assistente IA (`/assistente`)** — conversa sobre a empresa selecionada na
  barra lateral, usando exclusivamente os arquivos `<clientId>-crm.md` e
  `<clientId>-analise.md` da carteira. Documentos e API key ficam no backend; o
  navegador recebe só metadados de disponibilidade e a resposta final. Histórico
  vive apenas na página e é apagado ao trocar de empresa ou reiniciar a conversa.
  Backend em `backend/chat_ia.py`, rotas `GET /api/ia/contexto` e
  `POST /api/ia/chat`, com limite de perguntas e requisições por máquina.
- **Análises diárias da carteira** (`gerar_analises_ia.py`, `backend/dossie_ia.py`)
  — lote que lê `Carteira/database_dev.xlsx`, os `<clientId>-crm.md` e os
  summaries do Prisma, e grava `<clientId>-analise.md` por empresa com
  correspondência exata. Empresa sem correspondência é ignorada; falha de um
  cliente não interrompe os demais e vira MD com `status: erro`.
  O contexto entregue ao modelo é factual e pré-calculado — o LLM não faz conta.
- **`configurar_ollama.ps1`** — grava a API key do Ollama Cloud como blob DPAPI
  em `%LOCALAPPDATA%\Prisma\secrets`, fora do repositório, legível só pelo mesmo
  usuário do Windows. A chave nunca entra em código, linha de comando ou workbook.
- **`executar_lote_noturno.ps1`** e revisão de `agendar_normalizacao_todas.ps1`
  — o lote normaliza todas as empresas e depois analisa apenas os summaries
  renovados na própria execução. Agendado de segunda a sexta às 02:00, como o
  usuário Windows atual (exigência do DPAPI), com `StartWhenAvailable`.

### Alterado

- **Linguagem visual unificada** (`dashboard/src/index.css` e componentes):
  preenchimento sólido + borda no lugar de vidro. `backdrop-filter` saiu do
  projeto e `box-shadow` ficou restrito a camada flutuante. Tokens `--surface-1..4`
  substituem `rgba(255,255,255,α)`, que mudava de tom conforme o pai; os 26 raios
  distintos viraram dois (`--raio-card`, `--raio-controle`). O acento do StatCard
  virou filete `::before` de 3px, recuado — `border-left` herdava o raio do card
  e curvava nas pontas.
- `backend/relatorio_cliente.py` — painel do cliente revisado.
- `publicar.ps1` e `normalizar_todas_empresas.bat` — ajustes operacionais do
  fluxo de release e do lote.

### Corrigido

- `montar_contexto_prisma` aceitava `hoje`, mas não repassava para `montar_card`,
  que chamava `date.today()` direto. O sinalizador `ultimo_periodo_parcial` era
  calculado contra o relógio real mesmo com data injetada, o que deixava o teste
  `test_contexto_usa_ultimo_mes_fechado` dependente do dia da execução — quebrou
  na virada de agosto para setembro. `hoje` agora desce até `_eh_mes_corrente`.
