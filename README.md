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

## Análises diárias da carteira com Ollama Cloud

O lote lê, sem alterar, `Carteira/database_dev.xlsx`, os arquivos
`Carteira/dossie/<clientId>-crm.md` e os summaries da pasta de trabalho do Prisma.
Para cada empresa com correspondência exata, grava somente
`Carteira/dossie/<clientId>-analise.md`. Empresas sem correspondência são ignoradas.

O modelo padrão é `gpt-oss:120b`. A API key nunca deve ser colocada no código,
na linha de comando ou no workbook. Configure uma vez no Windows; o script salva
um blob DPAPI fora do repositório, legível somente pelo mesmo usuário:

```powershell
.\configurar_ollama.ps1
```

Valide entradas e mapeamentos sem chamar a nuvem e sem gravar MD:

```powershell
python .\gerar_analises_ia.py --dry-run
```

Registre o lote de segunda a sexta, às 02:00. Ele normaliza todas as empresas
primeiro e analisa apenas summaries renovados durante a execução:

```powershell
.\agendar_normalizacao_todas.ps1
```

A tarefa usa o usuário Windows atual, pois o DPAPI é vinculado a ele. O usuário
deve estar conectado; se o computador estiver indisponível às 02:00, a opção
`StartWhenAvailable` tenta executar quando possível.

### Chat sobre a empresa

A rota `/assistente` permite conversar com o Ollama Cloud usando exclusivamente
os arquivos `<clientId>-crm.md` e `<clientId>-analise.md` da empresa selecionada
na barra lateral. Os documentos e a API key ficam no backend; o navegador recebe
somente metadados de disponibilidade e a resposta final. O histórico permanece
apenas na página e é apagado ao trocar de empresa ou iniciar nova conversa.

O chat segue o modo aberto das demais telas, limita perguntas e requisições por
máquina e bloqueia empresas sem correspondência exata, MD ausente ou análise
diária com `status: erro`.

Logs operacionais ficam em `logs_agendador/` e não contêm a chave. Falha de um
cliente não interrompe os demais. Conforme a política do processo, uma falha
substitui a análise anterior por um MD com `status: erro`. A execução real exige
que o gerador do CRM já tenha criado cada `<clientId>-crm.md`.

## Deploy

- **Executável Windows** (para máquinas sem Python/Node): `.\build.ps1` gera, em
  `dist_release/`, o instalador (`Prisma-<versao>-instalador.exe`) e o pacote
  (`Prisma-<versao>.zip` + `version.json`) que alimenta a atualização automática. Bumpar
  `backend/versao.py` antes — é a fonte única da versão. Nesse modo o próprio FastAPI serve o
  frontend, então o Apache não é necessário. Detalhes do fluxo de release e da atualização em
  `CLAUDE.md`, seção "Empacotamento e atualização".
- **Frontend**: estático, deploya direto na Vercel (`npm run build` gera `dashboard/dist`).
- **Backend**: usa pandas + reportlab, pesado para função serverless da Vercel — recomendado rodar em Render/Railway ou máquina própria, apontando o frontend para essa URL via variável de ambiente (ver `dashboard/src/api/client.ts`, hoje aponta para `/api` relativo — para produção, ajustar para a URL do backend hospedado).
