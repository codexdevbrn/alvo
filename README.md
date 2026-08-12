# Projeto Prisma

Dashboard de vendas ("Alvo") + Analisador de Monitoria, unificados em um projeto web só.

- **Dashboard** (`/`) — tela principal, dados vêm de `process_data.py` (lê `base_de_dados.xlsx`, gera `dashboard/public/data/summary.json`).
- **Analisador de Monitoria** (`/analisador`, atrás de login) — upload de CSV de vendas, configuração de exclusões/cortes, relatórios do catálogo na tela, export Excel/PDF. Backend em `backend/` (FastAPI) reaproveita o motor de análise do app desktop original.

## Rodando local

**Backend** (porta 8000):
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```
Login inicial: usuário `admin`, senha `admin123` (banco SQLite criado automaticamente em `backend/dados_locais/app.db` no primeiro boot — troque a senha ou crie outro usuário com `db.criar_usuario`).

**Frontend** (porta 5173):
```bash
cd dashboard
npm install
npm run dev
```
O Vite já tem proxy de `/api` para `http://localhost:8000` (`vite.config.ts`).

**Atualizar os dados do dashboard**: `python process_data.py` na raiz (lê `base_de_dados.xlsx`, grava `dashboard/public/data/summary.json`).

## Deploy

- **Executável Windows** (para máquinas sem Python/Node/XAMPP): `.\build.ps1` gera, em
  `dist_release/`, o instalador (`Prisma-<versao>-instalador.exe`) e o pacote
  (`Prisma-<versao>.zip` + `version.json`) que alimenta a atualização automática. Bumpar
  `backend/versao.py` antes — é a fonte única da versão. Nesse modo o próprio FastAPI serve o
  frontend, então o Apache não é necessário. Detalhes do fluxo de release e da atualização em
  `CLAUDE.md`, seção "Empacotamento e atualização".
- **Frontend**: estático, deploya direto na Vercel (`npm run build` gera `dashboard/dist`).
- **Backend**: usa pandas + reportlab, pesado para função serverless da Vercel — recomendado rodar em Render/Railway ou máquina própria, apontando o frontend para essa URL via variável de ambiente (ver `dashboard/src/api/client.ts`, hoje aponta para `/api` relativo — para produção, ajustar para a URL do backend hospedado).
