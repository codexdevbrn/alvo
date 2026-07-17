# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é

Projeto Prisma = Dashboard de vendas ("Alvo") + Analisador de Monitoria, unificados num único projeto web.

- **Dashboard** (`/`, público) — visualização de receita/quantidade por período, loja, cliente, fabricante e produto. Duas fontes de dados possíveis:
  - **Modo estático** (empresa `''`, padrão): lê `dashboard/public/data/summary.json`, gerado offline por `process_data.py` a partir de `base_de_dados.xlsx` (export do Power BI).
  - **Modo por empresa**: usuário escolhe uma empresa no seletor (`EmpresaSelector`), e o frontend busca `GET /api/dashboard/summary/{empresa}` no backend, que garante/gera `Base.csv` na pasta de trabalho a partir do BI da pasta fonte e devolve o summary (`backend/dashboard_summary.py`), com cache em memória por mtime.
- **Analisador de Monitoria** (`/analisador`, atrás de login) — configuração de exclusões/cortes de clientes e produtos sobre a base padrão (`base_de_dados.xlsx`) ou, com empresa selecionada, sobre o `Base.csv` dessa empresa na pasta de trabalho; relatórios do catálogo, export Excel/PDF. Precisa do backend em `backend/` (FastAPI), que reaproveita o motor de análise (`engine/analise_funil.py`) do app desktop original (`erickxc/analisador-monitoria-2d`).

Os dois módulos compartilham **dois caminhos** (chaves SQLite em `config_app`):

| Chave | Papel | Conteúdo |
|---|---|---|
| `caminho_fonte_dados` | **Somente leitura absoluta** | `/{cliente}/BI/{cliente}_MOVIMENTO_ATUAL.*` (ou `_MOVIMENTO`) + `{cliente}_PRODUTO.*` |
| `caminho_trabalho` | Escrita | `/{cliente}/Base.csv`, `config.json`, `harm.xlsx`, backups |

Regra inviolável: o app **nunca** cria, altera, apaga ou renomeia nada sob a pasta fonte. Toda escrita (normalização, harmonização, config) vai só para a pasta de trabalho. Fonte e trabalho não podem ser a mesma pasta nem uma dentro da outra — o backend recusa antes de qualquer `makedirs`/`to_csv`. O CLI `normalizar_base.py` exige `--trabalho` e também recusa gravar sob a fonte; `harmonizar_descricoes.py` recusa pastas que contenham `BI/`. Endpoints: `GET/POST /api/dashboard/caminho-fonte-dados` e `.../caminho-trabalho` (dash, público); `GET/POST /api/config/caminho-fonte-dados` e `.../caminho-trabalho` (Analisador, autenticado). Aliases legados (`caminho-dados`, `caminho-empresas`) ainda redirecionam para fonte/trabalho.

## Comandos

**Backend** (porta 8000):
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```
Login inicial: `admin` / `admin123` (SQLite criado automaticamente em `backend/dados_locais/app.db` no primeiro boot; trocar senha ou criar usuário via `db.criar_usuario`).

**Frontend** (porta 5173):
```bash
cd dashboard
npm install
npm run dev        # vite --host
npm run build       # tsc -b && vite build
npm run lint         # eslint .
npm run preview
```
Vite tem proxy de `/api` → `http://localhost:8000` (`dashboard/vite.config.ts`), então em dev o frontend chama `/api` relativo.

**Atualizar dados do dashboard (modo estático)**: `python process_data.py` na raiz (lê `base_de_dados.xlsx`, grava `dashboard/public/data/summary.json`).

**Harmonizar descrições de produto de uma empresa**: `python harmonizar_descricoes.py "<pasta_trabalho>/<empresa>"` (lê `harm.xlsx` da pasta de trabalho, reescreve a coluna `descricao` do `Base.csv`; `--dry-run` só mostra o relatório sem gravar; backup `Base.antes-harm.csv` na primeira execução). A normalização BI→Base: `python normalizar_base.py "<pasta_fonte>/<empresa>" --trabalho "<pasta_trabalho>/<empresa>"`.

Não há suíte de testes automatizada configurada em nenhum dos dois lados.

## Arquitetura

### Frontend (`dashboard/src`)
- `App.tsx` — três rotas: `/` (Dashboard, pública), `/login`, `/analisador` (protegida via `RotaProtegida`, que checa `getToken()` de `api/client.ts`).
- `api/client.ts` — cliente HTTP central para o backend; hoje aponta para `/api` relativo (em produção precisa apontar para a URL do backend hospedado, já que o backend não roda em função serverless da Vercel).
- `pages/` — `DashboardPage`, `LoginPage`, `AnalisadorPage` — um componente de página por rota.
- `components/` — componentes do Dashboard na raiz (`MetricsGrid`, `HistoryChart`, `BreakdownSection`, `FilterBar`, `PeriodSelector`, `EmpresaSelector`, `RevenueDetailModal`, etc.); componentes específicos do Analisador ficam em `components/analisador/` (`ConfigModal`, `ExportarModal`, `ResultTable`, `PreviaClientesTable`, `PreviaProdutosTable`, `NumberStepper`).
- `EmpresaSelector` / `ConfigModal` — dois campos de caminho (fonte RO + trabalho RW), compartilhados conceitualmente entre Dashboard e Analisador.
- `data/summary.json` vs `public/data/summary.json` — o dashboard estático lê o JSON gerado por `process_data.py`; `public/data/` é servido estaticamente pelo Vite/build, `src/data/` é uma cópia usada em import direto no código — ao regenerar dados, checar se as duas precisam ser atualizadas. Não se aplica ao modo por empresa, que busca do backend em runtime.
- `types/dashboard.ts` — tipos compartilhados do shape de `summary.json` (mesmo formato tanto no estático quanto no gerado em runtime por empresa).
- Filtros do Dashboard usam debounce (`useDebouncedValue`, ~300ms) + `useTransition` para recalcular sem travar a UI ao clicar rápido em filtros.

### Backend (`backend/`)
- `main.py` — app FastAPI, define todas as rotas: login, catálogo, base (Excel padrão ou `Base.csv` por empresa), prévias, caminhos fonte/trabalho, config.json por empresa, dashboard por empresa, análise, export. CORS liberado só para `http://localhost:5173`.
- `auth.py` — geração/validação de token (`criar_token`, `exigir_login` como dependency do FastAPI). As rotas `/api/dashboard/*` **não** exigem login — o dashboard é público (app de uso interno).
- `db.py` — camada SQLite: usuários (login do Analisador) e `config_app` (chave/valor genérico: `caminho_fonte_dados`, `caminho_trabalho`, com fallback das chaves legadas). Banco em `backend/dados_locais/app.db`.
- `_ensure_base_csv` / `_assert_escrita_fora_da_fonte` — ao selecionar empresa, só usa o `Base.csv` já existente no trabalho (não regenera se o BI for mais novo); regeneração só com `forcar=True` / botão Regenerar base / lote noturno. A data do último movimento no topo do dashboard continua lida do BI (`_data_ultimo_movimento_bi`). Aborta se o destino estiver sob a fonte ou se fonte == trabalho.
- `dashboard_summary.py` — gera o summary do Dashboard (mesmo shape de `summary.json`) a partir de um DataFrame já limpo pelo motor (`carregar_csv`), vetorizado com pandas (evita `iterrows`, lento nas ~650 mil linhas típicas de uma base).
- `engine/` — motor de análise reaproveitado do app desktop original:
  - `analise_funil.py` — lógica central de análise do funil de vendas (classificação ABC de clientes/produtos, erosão, churn, migração, tendências) a partir da base carregada (`carregar_csv`/`carregar_excel_base`).
  - `exportadores_pdf_word.py` — geração de relatórios PDF/Word (reportlab, python-docx).
  - `recursos.py` — helpers de caminho (assets embutidos, pasta de dados locais) herdados do app desktop original — partes como `_MEIPASS` do PyInstaller e permissão de dados locais não se aplicam ao contexto web.
- `exportar_excel.py` — export Excel via openpyxl; define `CATALOGO_RELATORIOS`, `COLUNAS_MOEDA_POR_ANALISE`, `NOMES_ANALISE` (usados também por `main.py` e por `exportadores_pdf_word.py`).
- Base padrão do Analisador (`base_de_dados.xlsx`) e `Base.csv` por empresa são cacheadas em memória por mtime (`_cache_base` / `_cache_base_empresa` / `_cache_summary_dashboard`).

### Pastas fonte e trabalho
- **Fonte** (RO): subpastas por cliente com `BI/` contendo exports de movimento e produto. Listagem de empresas = subpastas da fonte que têm `BI/`.
- **Trabalho** (RW): subpastas por cliente com `Base.csv` (schema canônico de `engine.analise_funil.carregar_csv`), `config.json` (Analisador) e opcionalmente `harm.xlsx`. O app pode criar a pasta do cliente aqui na primeira seleção.

## Deploy

- **Frontend**: estático, deploya direto na Vercel (`npm run build` gera `dashboard/dist`).
- **Backend**: usa pandas + reportlab, pesado para função serverless da Vercel — rodar em Render/Railway ou máquina própria, e ajustar `dashboard/src/api/client.ts` para apontar para a URL hospedada em produção.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
