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

**Caminhos padrão** (`backend/caminhos_padrao.py`): quando nada foi configurado, os três caminhos são resolvidos dentro do OneDrive corporativo — `Dados Alvos` (fonte), `analisador` (trabalho) e `Prisma\Atualizações` (canal), todos sob `<OneDrive>\01 - Marco + Monitores\Ecossistema-Monitoria`. A raiz local do OneDrive é descoberta em tempo de execução (`%OneDriveCommercial%`, com varredura do perfil como reserva), porque ela contém o nome do usuário do Windows e não pode ser fixada no código. Assim uma máquina nova funciona sem ninguém digitar caminho. O que o usuário salvar em Configurações tem precedência, e só pastas que existem são sugeridas.

Consequência a ter em mente: a pasta de trabalho padrão é **compartilhada**. Isso é intencional — é nela que o lote noturno grava os summaries, e apontar uma máquina para pasta local vazia faria cada empresa ser gerada na hora (a Altese leva ~219 s contra ~1 s lendo o summary pronto). Em troca, uma instância rodando do fonte sem configuração também escreve lá; para experimentar sem risco, configure uma pasta de trabalho local.

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
**Deploy (XAMPP)** — instalação servida na LAN (`http://monitor-2d/`):
Ao alterar o frontend, além de rodar `npm run build`, é necessário copiar os arquivos de `dashboard/dist` para o diretório do Apache: `c:\xampp\monitoria\htdocs`. (Ex: `Copy-Item -Path ".\dist\*" -Destination "c:\xampp\monitoria\htdocs" -Recurse -Force`)

O Apache (`c:\xampp\monitoria\apache\conf\httpd.conf`) escuta na 80 em todas as interfaces e faz `ProxyPass /api http://127.0.0.1:8003/api`; o backend roda como serviço via `nssm` (`c:\xampp\monitoria\prisma-svc`). Consequência a ter em mente: **a API é alcançável por qualquer máquina da rede**, e `auth.LOGIN_DESATIVADO = True` não barra ninguém. Rota destrutiva nova precisa de proteção própria — ver o gate de origem local em `_exigir_origem_local`.

**Deploy (executável)** — distribuição para máquinas que não têm Python nem XAMPP: ver "Empacotamento e atualização" abaixo. Nesse modo o próprio FastAPI serve o `dashboard/dist`, então o Apache não é necessário.

Vite tem proxy de `/api` → `http://127.0.0.1:8003` (`dashboard/vite.config.ts`), então em dev o frontend chama `/api` relativo.

**Atualizar dados do dashboard (modo estático)**: `python process_data.py` na raiz (lê `base_de_dados.xlsx`, grava `dashboard/public/data/summary.json`).

**Harmonizar descrições de produto de uma empresa**: `python harmonizar_descricoes.py "<pasta_trabalho>/<empresa>"` (lê `harm.xlsx` da pasta de trabalho, reescreve a coluna `descricao` do `Base.csv`; `--dry-run` só mostra o relatório sem gravar; backup `Base.antes-harm.csv` na primeira execução). A normalização BI→Base: `python normalizar_base.py "<pasta_fonte>/<empresa>" --trabalho "<pasta_trabalho>/<empresa>"`.

**Testes do backend**: `cd backend && python -m pytest -q`. Não há testes automatizados no frontend.

## Empacotamento e atualização

O Prisma também é distribuído como executável Windows, para máquinas onde instalar Python, Node e XAMPP não se justifica. Nesse modo o backend serve o `dashboard/dist` embutido, escolhe uma porta livre a partir da 8003 e abre o navegador.

### Publicar uma release

```powershell
# 1. bumpar a versão — fonte única, é dela que saem o nome do zip e o version.json
#    backend/versao.py:  VERSAO = "1.0.1"
# 2. gerar tudo
.\build.ps1
# 3. copiar dist_release\Prisma-1.0.1.zip e version.json para a pasta de
#    atualizações no OneDrive (preencher "notas" no version.json antes)
```

`build.ps1` roda nesta ordem, e a ordem importa: `npm run build` → `pytest` → PyInstaller do app → PyInstaller do atualizador → zip + `version.json` (com sha256) → instalador Inno Setup. O frontend vem primeiro porque o `dist` entra embutido; empacotar com um `dist` velho passa despercebido, já que o app abre normal, só com a interface da versão anterior. Os testes reprovando abortam a release.

Saída em `dist_release/`:

| Arquivo | Para quê |
|---|---|
| `Prisma-<v>.zip` | o que vai para o canal de atualização |
| `version.json` | manifesto que o app lê para detectar release nova |
| `Prisma-<v>-instalador.exe` | primeira instalação numa máquina |

### Modo segundo plano

O executável abre uma janela de console, mostra o boot, e **fecha a janela** quando o servidor responde (`servidor._fechar_console`, via `FreeConsole`). A partir daí o app vive na bandeja do Windows (`bandeja.py`: Abrir Prisma / Verificar atualização / Sair). Se o boot falhar, a janela **permanece** com o motivo — é de propósito, e é o motivo de não empacotar como aplicação de janela (`console=False`), que esconderia o erro e mexeria no bootloader do PyInstaller.

Três consequências que já custaram um ciclo de teste cada, e que quem mexer aqui precisa saber:

- **Todo `subprocess` precisa dos três descritores explícitos.** Depois do `FreeConsole` os handles padrão ficam inválidos e herdá-los falha com `WinError 50`. Atinge `inicio_automatico._schtasks` e o `Popen` que lança o atualizador.
- **`print` e o log de stream não podem ser o único canal.** `registro.py` manda tudo para `logs/prisma.log` (rotativo) e substitui stdout/stderr por um adaptador; o uvicorn sobe com `log_config=None` para herdar essa raiz.
- **A janela só fecha depois de o ícone existir.** Sem janela e sem ícone, o usuário não teria como abrir a interface nem encerrar o app. Bandeja indisponível ⇒ a janela fica.

### Inicialização automática e dados locais

`inicio_automatico.py`: "Abrir junto com o Windows" (valor em `HKCU\...\Run`) e "Abrir todo dia às HH:MM" (tarefa no Agendador, como o usuário, sem admin). O horário é lido do **XML** da tarefa, não da saída em lista do `schtasks`, que é traduzida.

`dados_no_disco.py`: marca fonte e trabalho com `FILE_ATTRIBUTE_PINNED` — o mesmo "Sempre manter neste dispositivo" do OneDrive. Serve para máquina nova, onde os arquivos podem ser placeholder e a primeira leitura paga download; **não** acelera o que já está local.

Os dois endpoints usam `_exigir_origem_local`, como `/aplicar`: alteram o logon da máquina e disparam download de gigabytes, e o Apache expõe a API para a rede.

### Como a atualização funciona

O canal é uma pasta compartilhada (na prática o OneDrive da empresa) configurada em Configurações → Atualizações, gravada em `config_app.caminho_atualizacoes`. O app lê o `version.json`, compara com `versao.VERSAO` e oferece o update; ao aplicar, confere o sha256, entrega a troca ao `atualizador.exe` e se encerra. O atualizador espera o processo morrer, extrai ao lado, **preserva `dados_locais/`, `logs/`, `data/` e `base_de_dados.xlsx`**, troca as pastas, religa e só apaga o backup depois de confirmar que a versão nova respondeu. Log em `<pai da instalação>\Prisma-atualizacao.log`.

Três coisas a não mexer sem entender:

- **`_exigir_origem_local`** recusa `/api/atualizacoes/aplicar` de fora da máquina, inclusive loopback com cabeçalho de proxy. Sem isso, o `ProxyPass` do Apache deixaria qualquer PC da rede substituir a instalação.
- **`CREATE_NEW_CONSOLE`**, não `DETACHED_PROCESS`, ao lançar o app e o atualizador: sem console, o bootloader do PyInstaller morre antes de subir o servidor.
- **O atualizador roda de uma cópia no `%TEMP%`**, nunca de dentro da pasta que substitui: o Windows mantém handle no binário em execução e na cwd, e o rename falha com `WinError 32`.

### Arquivos envolvidos

| Arquivo | Papel |
|---|---|
| `backend/versao.py` | `VERSAO` (fonte única) e comparação numérica de versões |
| `backend/servidor.py` | entrypoint do exe: porta livre, instância única, console, navegador |
| `backend/registro.py` | log em arquivo; sobrevive a não ter stdout |
| `backend/bandeja.py` | ícone na área de notificação |
| `backend/inicio_automatico.py` | início com o Windows / em horário |
| `backend/dados_no_disco.py` | "sempre manter nesta máquina" (OneDrive) |
| `backend/atualizacoes.py` | leitura do canal, validação de sync e sha256 |
| `atualizador/atualizador.py` | troca das pastas, preservação de dados, rollback |
| `prisma.spec` / `atualizador.spec` | empacotamento (onedir / onefile) |
| `instalador/prisma.iss` | instalador, atalhos, desinstalador |
| `build.ps1` | orquestra tudo acima |

## Arquitetura

### Frontend (`dashboard/src`)
- `App.tsx` — três rotas: `/` (Dashboard, pública), `/login`, `/analisador` (protegida via `RotaProtegida`, que checa `getToken()` de `api/client.ts`).
- `api/client.ts` — cliente HTTP central para o backend; hoje aponta para `/api` relativo (em produção precisa apontar para a URL do backend hospedado, já que o backend não roda em função serverless da Vercel).
- `pages/` — `DashboardPage`, `LoginPage`, `AnalisadorPage` — um componente de página por rota.
- `components/` — componentes do Dashboard na raiz (`MetricsGrid`, `HistoryChart`, `BreakdownSection`, `FilterBar`, `PeriodSelector`, `EmpresaSelector`, `RevenueDetailModal`, etc.); componentes específicos do Analisador ficam em `components/analisador/` (`ConfigModal`, `ExportarModal`, `ResultTable`, `PreviaClientesTable`, `PreviaProdutosTable`, `NumberStepper`).
- `EmpresaSelector` / `ConfigModal` — dois campos de caminho (fonte RO + trabalho RW), compartilhados conceitualmente entre Dashboard e Analisador.

### Escopo global: empresa + loja

A barra lateral é a única dona do escopo. `SidebarEmpresaSelect` grava `alvo_empresa`; `SidebarLojaSelect` grava `prisma_loja_<empresa>` (`utils/lojaSelecionada.ts`) e só aparece quando a empresa tem mais de uma loja. `hooks/useEscopoAtual` entrega `{empresa, loja}` já sincronizado — as telas não leem mais o localStorage por conta própria, que era como cada uma acabava com uma regra diferente para zerar a loja.

Três consequências a ter em mente:

- **Uma loja por vez** (`''` = todas). O backend continua entendendo o escopo multi-loja (`@lojas:[...]`), e `config.json`/`clientes_tags.json` já gravados assim seguem válidos no disco, mas nenhuma tela produz mais esse escopo.
- **Nenhuma tela tem seletor de loja próprio.** Saíram o filtro "Loja" da `FilterBar`, o do Analisador, o do Estoque e o de Clientes. No Dashboard a loja não é filtro: vira índice em `maps.s` e entra no mesmo cálculo de antes — o summary já traz a loja em cada linha, então não há ida ao servidor.
- **A lista de lojas sai de `GET /api/dashboard/empresas/{empresa}/lojas`**, que lê o `resumo_monitor.json` (poucos KB), não a base. O seletor aparece no Dashboard público: tirar a lista da base carregaria o XLSX inteiro para preencher um combobox, anulando o ganho do summary pré-gerado. Empresa sem summary responde lista vazia e o seletor some, em vez de a tela quebrar.
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
- **Trabalho** (RW): subpastas por cliente com `Base.csv` (schema canônico de `engine.analise_funil.carregar_csv`), `config.json` (Analisador) e opcionalmente `harm.xlsx` e `clientes_harm.json`. O app pode criar a pasta do cliente aqui na primeira seleção.

### Harmonização de nomes de cliente (`clientes_harm.json`)

Algumas fontes gravam o mesmo cliente uma vez por origem, distinguindo pelo sufixo no fim do nome — `JHONE TEIXEIRA COSTA (CM)` e `JHONE TEIXEIRA COSTA (SA)` são a mesma pessoa. O sufixo **não** é a loja: as variantes convivem dentro da mesma loja, então filtrar por loja não resolvia. `backend/harmonizar_clientes.py` reescreve a coluna `Cliente` em `_carregar_base_empresa_sem_trava`, antes do cache — logo vale para Dashboard, Analisador, Explorar e exports, ao contrário dos grupos manuais (`grupos_manuais`), que só existem no Analisador.

A regra é o arquivo opcional `clientes_harm.json` na pasta de trabalho da empresa (`unificar_por_sufixo`, `sufixos`, `mapa`). Sem o arquivo, nada muda; arquivo inválido vira aviso no log e a base segue crua. Três decisões que limitam o estrago:

- só unifica com o nome **idêntico** antes do sufixo e as variantes convivendo **na mesma loja** — nomes só parecidos ou separados por loja vão no `mapa` manual, porque somar receita de quem não é a mesma pessoa é pior que deixar duplicado;
- nome com sufixo único fica como está, o que mantém válidas as tags e exclusões já gravadas por nome (ex.: `CONSUMIDOR ITABORAI (SA)`);
- o mtime do `clientes_harm.json` entra na chave do cache da base e no frescor do `summary_dashboard.json` — sem isso, editar a regra não teria efeito até a fonte mudar.

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
