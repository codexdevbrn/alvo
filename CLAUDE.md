# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é

Projeto Prisma = Dashboard de vendas ("Alvo") + Analisador de Monitoria, unificados num único projeto web.

- **Dashboard** (`/`, público) — visualização de receita/quantidade por período, loja, cliente, fabricante e produto. Duas fontes de dados possíveis:
  - **Modo estático** (empresa `''`, padrão): lê `dashboard/public/data/summary.json`, gerado offline por `process_data.py` a partir de `base_de_dados.xlsx` (export do Power BI).
  - **Modo por empresa**: usuário escolhe uma empresa no seletor (`EmpresaSelector`), e o frontend busca `GET /api/dashboard/summary/{empresa}` no backend, que gera o mesmo shape de summary em runtime a partir do `Base.csv` da empresa (`backend/dashboard_summary.py`), com cache em memória por mtime do arquivo.
- **Analisador de Monitoria** (`/analisador`, atrás de login) — configuração de exclusões/cortes de clientes e produtos sobre a base padrão ou por empresa, relatórios do catálogo, export Excel/PDF. Precisa do backend em `backend/` (FastAPI), que reaproveita o motor de análise (`engine/analise_funil.py`) do app desktop original (`erickxc/analisador-monitoria-2d`).

Os dois módulos compartilham o conceito de "empresa": uma pasta em `base-clientes/<nome>/` com `Base.csv` (dados) e `config.json` (parâmetros salvos do Analisador para aquela empresa — cortes, exclusões, granularidade etc.). O caminho raiz dessas pastas é configurável em runtime (ícone de engrenagem no frontend → `POST /api/config/caminho-empresas` para o Analisador, `POST /api/dashboard/caminho-dados` para o Dashboard — chaves de config separadas em `config_app`, mesmo que hoje apontem para o mesmo lugar por padrão).

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

**Harmonizar descrições de produto de uma empresa**: `python harmonizar_descricoes.py "base-clientes/<empresa>"` (lê `harm.xlsx` da pasta da empresa, reescreve a coluna `descricao` do `Base.csv` cruzando por `Código Interno`; `--dry-run` só mostra o relatório sem gravar; faz backup automático em `Base.antes-harm.csv` na primeira execução).

Não há suíte de testes automatizada configurada em nenhum dos dois lados.

## Arquitetura

### Frontend (`dashboard/src`)
- `App.tsx` — três rotas: `/` (Dashboard, pública), `/login`, `/analisador` (protegida via `RotaProtegida`, que checa `getToken()` de `api/client.ts`).
- `api/client.ts` — cliente HTTP central para o backend; hoje aponta para `/api` relativo (em produção precisa apontar para a URL do backend hospedado, já que o backend não roda em função serverless da Vercel).
- `pages/` — `DashboardPage`, `LoginPage`, `AnalisadorPage` — um componente de página por rota.
- `components/` — componentes do Dashboard na raiz (`MetricsGrid`, `HistoryChart`, `BreakdownSection`, `FilterBar`, `PeriodSelector`, `EmpresaSelector`, `RevenueDetailModal`, etc.); componentes específicos do Analisador ficam em `components/analisador/` (`ConfigModal`, `ExportarModal`, `ResultTable`, `PreviaClientesTable`, `PreviaProdutosTable`, `NumberStepper`).
- `data/summary.json` vs `public/data/summary.json` — o dashboard estático lê o JSON gerado por `process_data.py`; `public/data/` é servido estaticamente pelo Vite/build, `src/data/` é uma cópia usada em import direto no código — ao regenerar dados, checar se as duas precisam ser atualizadas. Não se aplica ao modo por empresa, que busca do backend em runtime.
- `types/dashboard.ts` — tipos compartilhados do shape de `summary.json` (mesmo formato tanto no estático quanto no gerado em runtime por empresa).
- Filtros do Dashboard usam debounce (`useDebouncedValue`, ~300ms) + `useTransition` para recalcular sem travar a UI ao clicar rápido em filtros.

### Backend (`backend/`)
- `main.py` — app FastAPI, define todas as rotas: login, catálogo, base padrão, prévias de grupos/produtos, configuração de empresas do Analisador, dashboard por empresa, análise, export. CORS liberado só para `http://localhost:5173`.
- `auth.py` — geração/validação de token (`criar_token`, `exigir_login` como dependency do FastAPI). As rotas `/api/dashboard/*` **não** exigem login — o dashboard é público (app de uso interno).
- `db.py` — camada SQLite: usuários (login do Analisador) e `config_app` (chave/valor genérico, usado hoje para os dois caminhos de pastas de empresas). Banco em `backend/dados_locais/app.db`.
- `dashboard_summary.py` — gera o summary do Dashboard (mesmo shape de `summary.json`) a partir de um DataFrame já limpo pelo motor (`carregar_csv`), vetorizado com pandas (evita `iterrows`, lento nas ~650 mil linhas típicas de uma base). É o equivalente em runtime do `process_data.py` da raiz, mas para bases por empresa (`Base.csv`) em vez do Excel do Power BI.
- `engine/` — motor de análise reaproveitado do app desktop original:
  - `analise_funil.py` — lógica central de análise do funil de vendas (classificação ABC de clientes/produtos, erosão, churn, migração, tendências) a partir da base carregada (`carregar_csv`/`carregar_excel_base`).
  - `exportadores_pdf_word.py` — geração de relatórios PDF/Word (reportlab, python-docx).
  - `recursos.py` — helpers de caminho (assets embutidos, pasta de dados locais) herdados do app desktop original — partes como `_MEIPASS` do PyInstaller e permissão de dados locais não se aplicam ao contexto web.
- `exportar_excel.py` — export Excel via openpyxl; define `CATALOGO_RELATORIOS`, `COLUNAS_MOEDA_POR_ANALISE`, `NOMES_ANALISE` (usados também por `main.py` e por `exportadores_pdf_word.py`).
- A base padrão do Analisador (`base_de_dados.xlsx` na raiz) é cacheada em memória por mtime (`_cache_base` em `main.py`); o mesmo padrão se repete para o summary por empresa do dashboard (`_cache_summary_dashboard`) — recarregar do disco a cada requisição seria lento nesse volume de linhas.

### `base-clientes/`
Pasta padrão (configurável via engrenagem) com uma subpasta por empresa: `Base.csv` (schema canônico esperado por `engine.analise_funil.carregar_csv` — colunas incluindo `Código Interno`, `descricao`, `Cliente`, `Loja`, `NOME_FABRICANTE`, `Receita`, `QTD`, `Data_Venda`), `config.json` (parâmetros salvos do Analisador para essa empresa) e opcionalmente `harm.xlsx` (planilha de harmonização usada por `harmonizar_descricoes.py`).

## Deploy

- **Frontend**: estático, deploya direto na Vercel (`npm run build` gera `dashboard/dist`).
- **Backend**: usa pandas + reportlab, pesado para função serverless da Vercel — rodar em Render/Railway ou máquina própria, e ajustar `dashboard/src/api/client.ts` para apontar para a URL hospedada em produção.
