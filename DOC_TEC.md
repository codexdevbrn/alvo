# Documentação técnica — 2D Prisma

Estado atual das telas e funcionalidades, na versão `1.5.0`. Este documento **não
é incremental**: ele descreve o que existe hoje. Histórico de mudanças fica em
`CHANGELOG.md`; as decisões de arquitetura e o "por que" de cada regra ficam em
`CLAUDE.md`.

## Composição

| Parte | Onde | O que é |
|---|---|---|
| Frontend | `dashboard/` | React + Vite + TypeScript, roteado por `react-router-dom` |
| Backend | `backend/` | FastAPI; serve a API e, no modo executável, o próprio `dist` |
| Motor de análise | `backend/engine/` | reaproveitado do app desktop "Monitor" |
| Empacotamento | `build.ps1`, `publicar.ps1`, `instalador/` | executável Windows, canal de atualização |

Três formas de rodar: dev (Vite 5173 + uvicorn), XAMPP na LAN (`http://monitor-2d/`,
Apache faz `ProxyPass /api` para a 8003) e executável Windows com ícone na bandeja.

## Telas

Todas as rotas ficam em `dashboard/src/App.tsx`. O escopo (empresa + loja) é
global, escolhido na barra lateral, e vale em todas as telas.

| Rota | Página | O que faz |
|---|---|---|
| `/` | `DashboardPage` | receita e quantidade por período, loja, cliente, fabricante e produto; histórico, breakdowns e modal de detalhe de receita. Lê `summary.json` estático ou `GET /api/dashboard/summary/{empresa}` |
| `/login` | `LoginPage` | autenticação do Analisador (SQLite local) |
| `/config` | `ConfiguracoesPage` | caminhos fonte/trabalho/atualizações, início automático, "manter dados nesta máquina", regeneração e atualização de versão |
| `/monitor` | `MonitorPage` | visão de todas as empresas a partir dos `resumo_monitor.json`; métrica, janela de meses, busca, ordenação e favoritas |
| `/analisador` | `AnalisadorPage` | configuração de exclusões e cortes de clientes e produtos, prévias, catálogo de relatórios e export Excel/PDF/Word |
| `/clientes` | `ClientesPage` | busca de clientes, tags por cliente e catálogo de tags |
| `/estoque` | `EstoquePage` | cobertura de estoque por item, classificada em saudável, risco de ruptura, sem estoque, estoque negativo, perdendo força, excesso e sem giro |
| `/assistente` | `AssistenteIAPage` | chat sobre a empresa selecionada, restrito aos MDs de CRM e análise diária |
| `/mercadologico` | `MercadologicoPage` | Pregão Mercadológico embutido numa aba; a URL é constante de produto, não configuração |

## Dados

Dois caminhos, gravados em `config_app` (SQLite):

- **Fonte** (somente leitura absoluta): `/{cliente}/BI/` com os exports de
  movimento e produto. O app nunca cria, altera, apaga ou renomeia nada aqui.
- **Trabalho** (escrita): `/{cliente}/` com `Base.csv`, `config.json`,
  `summary_dashboard.json`, `resumo_monitor.json` e, opcionalmente, `harm.xlsx`
  e `clientes_harm.json`.

Sem configuração, os dois são resolvidos dentro do OneDrive corporativo
(`backend/caminhos_padrao.py`). Fonte e trabalho não podem ser a mesma pasta nem
uma dentro da outra — o backend recusa antes de qualquer escrita.

O lote noturno (`normalizar_todas_empresas`) normaliza BI → `Base.csv` e regera
summary e resumo do monitor. Sem ele, a primeira pessoa a abrir o Monitoramento
paga a reconstrução (~18 s de CPU mais o download dos summaries).

## Assistente IA e análises da carteira

Fluxo em duas partes, ligadas pelos arquivos MD da pasta `Carteira/`:

1. **Lote diário** (`gerar_analises_ia.py` + `backend/dossie_ia.py`), de segunda a
   sexta às 02:00. Lê `Carteira/database_dev.xlsx`, os `<clientId>-crm.md` e os
   summaries renovados na própria execução; grava apenas
   `Carteira/dossie/<clientId>-analise.md`. `--dry-run` valida entradas e
   mapeamentos sem chamar a nuvem e sem gravar. Empresa sem correspondência exata
   é ignorada; falha em um cliente não interrompe os demais e substitui a análise
   anterior por um MD com `status: erro`. Logs em `logs_agendador/`, sem a chave.
2. **Chat** (`/assistente`, `backend/chat_ia.py`, rotas `GET /api/ia/contexto` e
   `POST /api/ia/chat`). Responde só a partir do CRM e da análise diária da
   empresa selecionada. Bloqueia empresa sem correspondência exata, MD ausente ou
   análise com `status: erro`. Limita perguntas e requisições por máquina. O
   histórico vive na página e some ao trocar de empresa ou reiniciar a conversa.

O contexto entregue ao modelo é factual e pré-calculado (`montar_contexto_prisma`):
períodos, rankings, cards de 12 meses e sinalizadores de qualidade, incluindo mês
parcial e períodos com quantidade negativa. O LLM não faz conta.

Modelo padrão `gpt-oss:120b`, via `https://ollama.com/api/chat`. A API key é
gravada por `configurar_ollama.ps1` como blob DPAPI em
`%LOCALAPPDATA%\Prisma\secrets\ollama_api_key.dpapi`, fora do repositório e
legível só pelo mesmo usuário do Windows — por isso a tarefa agendada roda como o
usuário atual, que precisa estar conectado.

## Segurança operacional

- O Analisador exige login; o Dashboard é público por decisão de produto.
- No modo XAMPP a API é alcançável por qualquer máquina da rede. Rota destrutiva
  precisa de proteção própria: `_exigir_origem_local` cobre
  `/api/atualizacoes/aplicar`, `dados-no-disco` e `inicio-automatico`.
- Nenhum segredo no repositório. A chave do Ollama só existe como blob DPAPI na
  máquina que roda o lote.

## Interface

Preenchimento sólido e borda, sem vidro. `backdrop-filter` não é usado;
`box-shadow` só em camada flutuante (dropdown, popover, tooltip, modal). Card tem
hover de deslocamento, não de elevação. Tokens em `dashboard/src/index.css`
(`:root`) são a fonte única: `--bg-main`/`--sidebar`/`--bg-card`, degraus
`--surface-1..4`, `--border`/`--border-strong`, `--accent` + `--accent-contrast` e
dois raios (`--raio-card` 12px, `--raio-controle` 8px, mais `--raio-pill`).

## Release

`build.ps1` roda, nesta ordem: `npm run build` → `pytest` → PyInstaller do app →
PyInstaller do atualizador → zip + `version.json` com sha256 → instalador Inno
Setup. Teste reprovando aborta a release. `publicar.ps1` copia o zip antes do
`version.json` (senão existe janela com manifesto novo apontando para zip
ausente), põe o instalador na pasta acima do canal e apaga releases obsoletas,
mantendo uma anterior como escada de volta.

Dois atritos conhecidos do ambiente, que não são defeito do produto:

- Os `.ps1` são UTF-8 sem BOM; o Windows PowerShell 5.1 os lê como ANSI e falha no
  parser. Use `pwsh` 7.
- `publicar.ps1` resolve o canal pelo stdout de um `python -c`. Com o console fora
  de UTF-8, o "ç/õ" de `Atualizações` chega corrompido e o script acusa
  "canal nao encontrado" mesmo com a pasta existindo.
