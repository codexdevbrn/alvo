# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é

Projeto Prisma = Dashboard de vendas ("Alvo") + Analisador de Monitoria, unificados num único projeto web.

- **Dashboard** (`/`, público) — visualização de lucro bruto/quantidade por período, loja, cliente, fabricante e produto. Sempre por empresa: usuário escolhe uma empresa no seletor (`SidebarEmpresaSelect`), e o frontend busca `GET /api/dashboard/summary/{empresa}` no backend, que lê os dois CSV da empresa na pasta fonte (sem gerar nada em disco) e devolve o summary (`backend/dashboard_summary.py`), com cache em memória por mtime. Sem empresa salva, o seletor resolve uma automaticamente (empresa mock de demonstração, ou a primeira da lista) — não existe mais um modo "sem empresa". O valor monetário principal (hero, breakdowns por loja/cliente/fabricante/produto, gráfico) é **lucro bruto** (receita líquida − CMV), não receita crua — cada linha de `rows` já vem com CMV (`dashboard/src/types/dashboard.ts::margemLinha`), e o card "Margem" do `MetricsGrid` é lucro bruto − despesas (P&L: receita → CMV → lucro bruto → despesas → margem).
- **Analisador de Monitoria** (`/analisador`, atrás de login) — configuração de exclusões/cortes de clientes e produtos sobre a base padrão (`base_de_dados.xlsx`) ou, com empresa selecionada, sobre a base dessa empresa lida direto da fonte; relatórios do catálogo, export Excel/PDF. Precisa do backend em `backend/` (FastAPI), que reaproveita o motor de análise (`engine/analise_funil.py`) do app desktop original (`erickxc/analisador-monitoria-2d`).

Os dois módulos compartilham **dois caminhos** (chaves SQLite em `config_app`):

| Chave | Papel | Conteúdo |
|---|---|---|
| `caminho_fonte_dados` | **Somente leitura absoluta** | `/{cliente}/{cliente}_MOVIMENTO_ATUAL.parquet` + `/{cliente}_PRODUTO.parquet` (+ `_CONTROLADORIA.parquet` opcional), direto na pasta do cliente |
| `caminho_trabalho` | Escrita | `/{cliente}/config.json`, `summary_dashboard.json`, `resumo_monitor.json`, backups; sem `Base.csv`/`harm.xlsx` intermediário |

**Caminhos padrão** (`backend/caminhos_padrao.py`): quando nada foi configurado, os três caminhos são resolvidos dentro do OneDrive corporativo — `Dados Alvos` (fonte), `analisador` (trabalho) e `Prisma\Atualizações` (canal), todos sob `<OneDrive>\01 - Marco + Monitores\Ecossistema-Monitoria`. A raiz local do OneDrive é descoberta em tempo de execução (`%OneDriveCommercial%`, com varredura do perfil como reserva), porque ela contém o nome do usuário do Windows e não pode ser fixada no código. Assim uma máquina nova funciona sem ninguém digitar caminho. O que o usuário salvar em Configurações tem precedência, e só pastas que existem são sugeridas.

Consequência a ter em mente: a pasta de trabalho padrão é **compartilhada**. Isso é intencional — é nela que o lote noturno grava os summaries, e apontar uma máquina para pasta local vazia faria cada empresa ser gerada na hora (a Altese leva ~219 s contra ~1 s lendo o summary pronto). Em troca, uma instância rodando do fonte sem configuração também escreve lá; para experimentar sem risco, configure uma pasta de trabalho local.

Regra inviolável: o app **nunca** cria, altera, apaga ou renomeia nada sob a pasta fonte. Toda escrita (config, summaries) vai só para a pasta de trabalho. Fonte e trabalho não podem ser a mesma pasta nem uma dentro da outra — o backend recusa antes de qualquer `makedirs`/`to_csv`. O CLI `normalizar_base.py` exige `--trabalho` e também recusa gravar sob a fonte. Endpoints: `GET/POST /api/dashboard/caminho-fonte-dados` e `.../caminho-trabalho` (dash, público); `GET/POST /api/config/caminho-fonte-dados` e `.../caminho-trabalho` (Analisador, autenticado). Aliases legados (`caminho-dados`, `caminho-empresas`) ainda redirecionam para fonte/trabalho.

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
**Deploy (executável)** — único modo de distribuição hoje (o deploy via XAMPP/Apache foi descontinuado): ver "Empacotamento e atualização" abaixo. Nesse modo o próprio FastAPI serve o `dashboard/dist` e escuta só em `127.0.0.1`, sem depender de servidor web externo.

Vite tem proxy de `/api` → `http://127.0.0.1:8003` (`dashboard/vite.config.ts`), então em dev o frontend chama `/api` relativo.

**Regenerar summary/resumo de uma empresa**: `python normalizar_base.py "<pasta_fonte>/<empresa>" --trabalho "<pasta_trabalho>/<empresa>"` — lê os dois parquet da fonte (`{empresa}_MOVIMENTO_ATUAL` + `{empresa}_PRODUTO`) e grava `summary_dashboard.json`/`resumo_monitor.json` na pasta de trabalho; a descrição harmonizada já vem pronta em `DESCRICAO_HARMONIZADA` no `_PRODUTO`, sem passo manual.

**Testes do backend**: `cd backend && python -m pytest -q`. Não há testes automatizados no frontend.

## Empacotamento e atualização

O Prisma também é distribuído como executável Windows, para máquinas onde instalar Python e Node não se justifica. Nesse modo o backend serve o `dashboard/dist` embutido, escolhe uma porta livre a partir da 8003 e abre o navegador.

### Publicar uma release

```powershell
# 1. bumpar a versão — fonte única, é dela que saem o nome do zip e o version.json
#    backend/versao.py:  VERSAO = "1.0.1"
# 2. gerar tudo
.\build.ps1
# 3. publicar no canal (mostra o plano; -Executar aplica)
.\publicar.ps1
.\publicar.ps1 -Executar
```

`publicar.ps1` existe porque a cópia manual não removia nada: o canal chegou a
guardar 25 zips de ~81 MB mais os instaladores de ~89 MB, uma release inteira por
versão. O canal só precisa do `version.json` e do zip que ele nomeia — quem está
em 1.0.9 atualiza direto para a mais nova, sem salto intermediário. `-Manter`
(padrão 1) deixa as anteriores como escada de volta. Duas coisas encodadas ali:
o zip é copiado **antes** do `version.json`, senão existe uma janela em que toda
máquina da rede vê versão nova apontando para zip ausente; e o instalador vive na
pasta **acima** do canal, que é onde o `_subpasta_com_manifesto` de
`atualizacoes.py` espera encontrá-lo.

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

Os dois endpoints usam `_exigir_origem_local`, como `/aplicar`: alteram o logon da máquina e disparam download de gigabytes — ação de máquina local, não de rede.

### Como a atualização funciona

O canal é uma pasta compartilhada (na prática o OneDrive da empresa) configurada em Configurações → Atualizações, gravada em `config_app.caminho_atualizacoes`. O app lê o `version.json`, compara com `versao.VERSAO` e oferece o update; ao aplicar, confere o sha256, entrega a troca ao `atualizador.exe` e se encerra. O atualizador espera o processo morrer, extrai ao lado, **preserva `dados_locais/`, `logs/` e `base_de_dados.xlsx`**, troca as pastas, religa e só apaga o backup depois de confirmar que a versão nova respondeu. Log em `<pai da instalação>\Prisma-atualizacao.log`.

Três coisas a não mexer sem entender:

- **`_exigir_origem_local`** recusa `/api/atualizacoes/aplicar` de fora da máquina, inclusive loopback com cabeçalho de proxy — defesa contra qualquer reverse proxy futuro que reexponha a API na rede, já que o login pode estar desativado (`auth.LOGIN_DESATIVADO`).
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

### Linguagem visual: chapado, borda e um acento

A hierarquia é dada por **preenchimento sólido + borda**. Não há vidro:
`backdrop-filter` está fora do projeto, e `box-shadow` só aparece em camada
**flutuante** (dropdown, popover, tooltip, modal), via `--shadow-flutuante` —
onde a sombra é o único sinal de que o elemento não pertence ao fluxo. Card
tem hover com `translateY(-2px)`, mas **sem sombra**: é deslocamento, não
elevação. Card que não pode saltar (`.glass-card-flat`, a lista de empresas, o
painel do chat) zera com `transform: none`.

Os tokens em `dashboard/src/index.css` (`:root`) são a fonte única:

| Token | Uso |
|---|---|
| `--bg-main` / `--sidebar` / `--bg-card` | canvas, barra lateral, card |
| `--surface-1` … `--surface-4` | degraus de preenchimento (input, hover, chip, trilho) |
| `--border` / `--border-strong` | hairline e separador forte |
| `--accent` + `--accent-contrast` | pill/tab/botão **ativo**: ouro chapado, texto escuro |
| `--raio-card` / `--raio-controle` / `--raio-pill` | 12px / 8px / redondo |

Três coisas encodadas aqui:

- **Nada de `rgba(255,255,255,α)` como preenchimento.** Fill translúcido depende
  do pai, então o mesmo componente mudava de tom entre a barra lateral (`#08080a`)
  e o card (`#131316`) — e o degrau ficava indefinido em cima de gráfico. Os
  `--surface-*` tornam o degrau explícito. Cinza translúcido de _texto_ também
  saiu: use `--text-primary/secondary/muted`.
- **Branco puro não existe na paleta.** O canvas é preto quente, e `#fff` sobre
  ele destoa do `--text-primary` (`#f4f4f2`) usado ao lado. Sobre preenchimento
  ouro o texto é `--accent-contrast`, não branco.
- **Só dois raios.** Antes eram 26 valores distintos, o que fazia cada tela
  parecer de um app diferente. Raio menor que 6px (barra de progresso, thumb) e
  `50%` (avatar, botão redondo) seguem literais de propósito.
- **Acento semântico é filete, não borda.** O `--stat-accent` do StatCard vira
  um `::before` de 3px na lateral esquerda, recuado no topo e na base
  (`.stat-card-container::before`). Pseudo-elemento porque `border-left` herda o
  `border-radius` do card e curva nas duas pontas — vira uma lasca arredondada;
  recuado porque assim o filete nunca alcança canto. Tingir a borda inteira com
  `color-mix` também foi testado e pesou demais em três cards lado a lado. Chip
  do ícone e linha de tendência usam os mesmos `--success`/`--danger` do filete,
  senão o card mostra dois verdes.

### Escopo global: empresa + loja

A barra lateral é a única dona do escopo. `SidebarEmpresaSelect` grava `alvo_empresa`; `SidebarLojaSelect` grava `prisma_loja_<empresa>` (`utils/lojaSelecionada.ts`) e só aparece quando a empresa tem mais de uma loja. `hooks/useEscopoAtual` entrega `{empresa, lojas, loja}` já sincronizado — `lojas` é a lista crua e `loja` é o escopo codificado que as APIs esperam. As telas não leem mais o localStorage por conta própria, que era como cada uma acabava com uma regra diferente para zerar a loja.

Três consequências a ter em mente:

- **Qualquer combinação de lojas** (lista vazia = todas). O escopo viaja no contrato de sempre — nome puro para uma loja, `@lojas:[...]` para várias (`codificarEscopoLojas`) — e é ele que nomeia o escopo em que `config.json` e `clientes_tags.json` são lidos e gravados. Ordenar antes de codificar não é cosmético: a mesma seleção precisa gerar sempre a mesma chave, senão a config salva não é reencontrada. O combobox multi só confirma ao fechar o painel, comportamento que já era o do Analisador.
- **Nenhuma tela tem seletor de loja próprio.** Saíram o filtro "Loja" da `FilterBar`, o do Analisador, o do Estoque e o de Clientes. No Dashboard a loja não é filtro: os nomes viram índices em `maps.s` e entram no mesmo cálculo de antes — o summary já traz a loja em cada linha, então não há ida ao servidor.
- **A lista de lojas sai de `GET /api/dashboard/empresas/{empresa}/lojas`**, que lê o `resumo_monitor.json` (poucos KB), não a base. O seletor aparece no Dashboard público: tirar a lista da base carregaria o XLSX inteiro para preencher um combobox, anulando o ganho do summary pré-gerado. Empresa sem summary responde lista vazia e o seletor some, em vez de a tela quebrar.
- `types/dashboard.ts` — tipos compartilhados do shape do summary (o mesmo que `dashboard_summary.py` gera em runtime por empresa).
- Filtros do Dashboard usam debounce (`useDebouncedValue`, ~300ms) + `useTransition` para recalcular sem travar a UI ao clicar rápido em filtros.

### Backend (`backend/`)
- `main.py` — app FastAPI, define todas as rotas: login, catálogo, base (Excel padrão ou os dois parquet por empresa, lidos direto da fonte), prévias, caminhos fonte/trabalho, config.json por empresa, dashboard por empresa, análise, export. CORS liberado só para `http://localhost:5173`.
- `auth.py` — geração/validação de token (`criar_token`, `exigir_login` como dependency do FastAPI). As rotas `/api/dashboard/*` **não** exigem login — o dashboard é público (app de uso interno).
- `db.py` — camada SQLite: usuários (login do Analisador) e `config_app` (chave/valor genérico: `caminho_fonte_dados`, `caminho_trabalho`, com fallback das chaves legadas). Banco em `backend/dados_locais/app.db`.
- `monitor_empresas.py` — resumo de poucos KB por empresa (`resumo_monitor.json`), derivado do summary e usado pela tela de Monitoramento e pelo seletor de lojas. O cache é invalidado pelo mtime do summary, e é o **lote noturno** (`normalizar_todas_empresas`) que o regera junto do summary. Sem isso a invalidação diária caía no primeiro usuário a abrir a tela: reconstruir os 46 resumos custa ~18 s de CPU com os arquivos já locais, mais o download de ~65 MB de summary numa máquina em que o OneDrive ainda não baixou — contra 0,4 s lendo os resumos prontos. Se a tela voltar a demorar, o suspeito é o lote não ter rodado.
- `_carregar_base_empresa_sem_trava` / `_assert_escrita_fora_da_fonte` — ao selecionar empresa, lê os dois parquet direto da fonte e cacheia em RAM por mtime; nada é persistido no trabalho (nem `Base.csv` nem intermediário). A data do último movimento no topo do dashboard vem de `DATA_MOVIMENTO` (`_data_ultimo_movimento_bi`), não mais de mtime de arquivo. Aborta se o destino estiver sob a fonte ou se fonte == trabalho.
- `cache_atacado.py` — cache em parquet do join MOVIMENTO_ATUAL+PRODUTO, na pasta de trabalho (`_cache_atacado.parquet`). Nasceu quando a fonte era CSV (IBAD: ~19 s de parse contra ~0,4 s do cache); com a fonte em parquet o join direto custa ~1 s, então o ganho encolheu e o cache é candidato a sair quando as telas passarem a consultar via `consulta_parquet`. Frescor é o mtime do mais recente entre os dois arquivos da fonte, carimbado no próprio parquet via `os.utime` (sem sidecar). Escrita é atômica (tmp + `os.replace`) e best-effort: falha ao gravar (disco cheio, OneDrive travando o arquivo) não impede o carregamento.
- `dashboard_summary.py` — gera o summary do Dashboard (mesmo shape de `summary.json`) a partir de um DataFrame já limpo pelo motor (`carregar_csv_base_empresa`), vetorizado com pandas (evita `iterrows`, lento nas ~650 mil linhas típicas de uma base).
- `engine/` — motor de análise reaproveitado do app desktop original:
  - `analise_funil.py` — lógica central de análise do funil de vendas (classificação ABC de clientes/produtos, erosão, churn, migração, tendências) a partir da base carregada (`carregar_csv`/`carregar_csv_base_empresa`). `carregar_csv_base_empresa` faz o join `{empresa}_MOVIMENTO_ATUAL.csv` × `{empresa}_PRODUTO.csv` pela chave de produto, monta `CMV`, `Vendedor`, `Data_Venda_Diaria` e a `descricao` a partir de `DESCRICAO_HARMONIZADA` (fallback para a bruta). `montar_estoque_e_vendas` deriva estoque/vendas de `QUANTIDADE_ESTOQUE` do PRODUTO, com custo unitário = CMV total ÷ QTD total do produto.
  - `exportadores_pdf_word.py` — geração de relatórios PDF/Word (reportlab, python-docx).
  - `recursos.py` — helpers de caminho (assets embutidos, pasta de dados locais) herdados do app desktop original — partes como `_MEIPASS` do PyInstaller e permissão de dados locais não se aplicam ao contexto web.
- `exportar_excel.py` — export Excel via openpyxl; define `CATALOGO_RELATORIOS`, `COLUNAS_MOEDA_POR_ANALISE`, `NOMES_ANALISE` (usados também por `main.py` e por `exportadores_pdf_word.py`).
- Base padrão do Analisador (`base_de_dados.xlsx`) e a base por empresa (lida direto da fonte) são cacheadas em memória por mtime (`_cache_base` / `_cache_base_empresa` / `_cache_summary_dashboard`).

### Escopo de produtos no Analisador: regra, não lista de nomes

Três coisas tiram um produto dos relatórios, e elas são de naturezas diferentes:

| Origem | Onde vive | Efeito |
|---|---|---|
| Checkbox da linha na prévia | `produtos_excluidos` no `config.json` | exclusão manual, nome a nome |
| "Desconsiderar os demais" | flag `desconsiderar_demais_produtos` | derivada da curva, na hora do cálculo |
| "Desconsiderar não harmonizados" | flag `desconsiderar_nao_harmonizados` | derivada do nome, na hora do cálculo |

Até a versão anterior os dois checkboxes **materializavam nomes** dentro de `produtos_excluidos`. Isso congelava uma foto: mudar o corte depois não devolvia ninguém, e exclusão manual virava indistinguível de exclusão por regra. `_curva_produtos` centraliza a ordem, que não é arbitrária — manual e não harmonizado saem **antes** da curva (o balde `NÃO HARMONIZADO` costuma ser o maior item da base e deslocaria todo o Pareto); "demais" é **consequência** da curva, então só pode ser decidido depois dela. `previa_produtos` e `_carregar_df_filtrado` (relatório final) usam a mesma função — é o que garante que a prévia e o PDF concordem.

Ao carregar um `config.json` antigo, o frontend subtrai de `produtos_excluidos` os nomes que a resposta traz em `produtos_fora_por_regra`, deixando ali só o manual. Efeito colateral aceito: produto excluído à mão que também está abaixo do corte perde a marcação manual — enquanto a regra estiver ligada dá no mesmo.

**O teto de itens em produto é ação, não efeito colateral.** O problema da versão antiga não era existir um máximo — era ele rebaixar o corte dentro da prévia, deixando a tela mostrar 90% enquanto classificava com outro número, e item de R$ 298 mil caindo em "Demais". Hoje `/api/produtos/sugerir-corte` (botão "Sugerir corte automaticamente", espelhando o de clientes) devolve o percentual e a tela o grava no campo: o número lido é o número que classifica. A prévia nunca mexe no corte sozinha.

### Régua de corte (`faixa_por_curva`) — fonte única

A entidade cai na **primeira faixa cujo corte o acumulado inclusivo dela não
passa**. É o mesmo número que a prévia mostra na coluna "Acumulado": com corte em
80%, item que fecha em 80,23% fica em "Demais". Toda classificação do projeto
passa por aqui — prévia de clientes, prévia de produtos, relatório por período,
contadores e sugeridor de cortes —, e é isso que garante que a tela e o PDF
concordem.

Até a 1.2.0 a régua era o acumulado **antes** da entidade (`acumulado -
individual`). Ela nasceu para resolver a primeira faixa vazia quando um cliente
sozinho passa do primeiro corte, mas classificava por um número que a tela não
mostrava — o item de 80,23% aparecia no Grupo 1 com corte em 80%, e lia como
defeito. Hoje o grupo vazio é resolvido de outro jeito: **nenhuma faixa fica
vazia** — a que já teve seu corte ultrapassado leva a próxima entidade da fila.

Consequência a ter em mente: com cortes manuais longe da curva, as faixas se
enchem uma a uma e "Demais" é que pode ficar vazio (três clientes de 70/20/10%
com cortes 30/50/60 saem um em cada grupo). Com os cortes que o sugeridor
calcula isso não acontece, porque eles saem da própria curva.

### Sugestão automática de cortes (`sugerir_cortes_grupos`)

`_ajustar_corte_para_max` escolhe, para a faixa que começa no corte anterior, o maior valor da grade de 0,5% que ainda deixa a faixa dentro do máximo. Duas coisas que a versão anterior errava e que os testes em `test_sugestao_cortes.py` travam:

- **só sabia diminuir.** O corte inicial (30/50/60) virava teto, então o máximo nunca preenchia — Gisalto saía com 15 clientes no Grupo 1 pedindo 20. De `cortes_iniciais` hoje só importa **quantos** cortes existem; cada percentual sai da curva.
- **deixava grupo vazio.** Na Altese um cliente sozinho passa dos 50%: o Grupo 1 ficava com ele, o Grupo 2 nascia vazio (`[1, 0, 17]`) e virava seção em branco no relatório. Agora `[18, 17, 14]`.

A contagem às vezes para abaixo do máximo (os 18 acima) porque o corte é ancorado na grade de 0,5% em vez de virar um número de quatro casas decimais — foi escolha explícita: o percentual continua sendo a régua legível do relatório. Sem busca passo a passo: as entradas da curva estão ordenadas, então é `searchsorted`.

### Pastas fonte e trabalho
- **Fonte** (RO): subpastas por cliente com `{cliente}_MOVIMENTO_ATUAL` + `{cliente}_PRODUTO` direto na pasta (sem subpasta `BI/`), em parquet. Listagem de empresas = subpastas da fonte que têm os dois arquivos (`resolver_arquivos_dados`).
- **Trabalho** (RW): subpastas por cliente com `config.json` (Analisador), `summary_dashboard.json`, `resumo_monitor.json` e opcionalmente `clientes_harm.json`. Sem `Base.csv`/`harm.xlsx` — a base em si nunca é persistida fora da fonte. O app pode criar a pasta do cliente aqui na primeira seleção.

### Fonte em parquet, e consultas SQL em cima dela

A fonte é **só parquet** desde set/2026, com o mesmo esquema nas 41 empresas: identificador `string`, `DATA_MOVIMENTO`/`DATA_VENC` `date32`, `DIA`/`MES`/`ANO` `int32`, valores `double`. CSV que sobre na pasta é ignorado. O movimento da Altese caiu de 325 MB para 10,6 MB, e carregar a base foi de 14,5 s para 1,5 s (IBAD, 1,46 milhão de linhas: ~19 s → 1,0 s). O gargalo passou a ser a limpeza em pandas depois da leitura (`validar_e_limpar`, 2,7 s na Altese).

`analise_funil._ler_tabela_empresa` é o leitor único, travado em `tests/test_fonte_parquet.py`:

- **Confere colunas pelo rodapé e lê só as pedidas.** O `_PRODUTO` da Altese tem 2,6 milhões de linhas e o join com o movimento usa 2 das 6 colunas.
- **Identificador sai texto mesmo que venha numérico.** O join movimento × produto é por texto: código gravado como float por causa de um nulo (`100.0`) não casaria com "100" — sem erro, só receita sumindo. Campo `""` vira ausente.
- **`date32` sai `datetime64[ns]`.** O pandas o entregaria como objeto `date`, e todo cálculo de período iria pelo caminho lento.

Os testes gravam as linhas descritas como texto ("1.234,56") no esquema real da fonte, via `tests/fonte_parquet_util.escrever_fonte`.

`_PRECIFICACAO.parquet` também é parquet, mas vive na **pasta de trabalho**: quem grava é o lote `precificacao_do_postgres.py`, e a reserva na fonte (CSV exportado à mão) saiu.

**Consultas SQL: `backend/consulta_parquet.py` (DuckDB).** Lê do disco só as colunas e os blocos que a pergunta precisa, sem carregar a base na RAM. Conexão em memória por chamada (DuckDB não aceita a mesma conexão em duas threads, e o FastAPI atende em paralelo), caminho sempre como parâmetro (`read_parquet(?)`), nunca interpolado. Primeiro uso: o "Último movimento" da barra lateral é `max(DATA_MOVIMENTO)`, tirado das estatísticas do rodapé (~20 ms, 0,2 ms em cache) — antes era a data de modificação do arquivo, que diz quando o OneDrive sincronizou. Para dar escala: receita, CMV, lucro, clientes e famílias por mês × loja do IBAD, com o join no catálogo, sai em 0,21 s, contra ~6,6 s só para carregar e limpar a mesma base em pandas.

### Corte D-1 e preparo da manhã

**A base vai sempre até ontem.** `af.data_corte_padrao()` (D-1; `PRISMA_DATA_CORTE=AAAA-MM-DD` força outra data) e `af.cortar_ate` tiram as linhas de `Data_Venda_Diaria` depois do corte. O dia corrente chega parcial, e "hoje até agora" contra dias cheios faz toda tela ler queda. O corte roda **depois** do `_cache_atacado.parquet` (chaveado pela fonte; gravar o corte nele congelaria a data), e a data entra na chave da base em RAM e no `summary_dashboard.corte`, que o frescor do summary confere — virou o dia, tudo que foi calculado com o corte velho deixa de valer mesmo sem a fonte mudar. O "Último movimento" também é limitado ao corte.

**Telas pesadas têm cache em disco** (`backend/cache_telas.py`, `{trabalho}/{empresa}/_cache_telas/`): Clientes, Diagnóstico, Vendedores e Estoque (resumo e mapa). A chave é a mesma tupla que a tela já usava na RAM (empresa, loja, modo, assinatura da base, dia, cortes, tags), mais corte D-1 e regra de nomes; ela vira hash no nome do arquivo e fica gravada dentro, conferida na leitura. Qualquer mudança que invalidaria a RAM muda a chave, e o arquivo antigo não é mais achado. Antes, cada máquina recalculava cada tela na primeira abertura do dia (Clientes ~8 s na IBAD).

**`preparar_telas.py`** chama esses endpoints para cada empresa, com os parâmetros do prefetch do frontend (escopo "todas as lojas", 3 modos de período, venda média 6, mapa de estoque com limite 1200), via `TestClient` — o arquivo preparado é o que a tela calcularia. 4 empresas em paralelo, maiores primeiro. Empresa que não mudou sai do disco em < 1 s.

**Lote da manhã** (`executar_lote_noturno.ps1`): summaries → base CNPJ → precificação → telas → análises IA. Duas tarefas do usuário: `Prisma-LoteManha` às 05:30 com `-AguardarFonteAte 09:30` — `aguardar_fonte.py` espera o movimento de cada empresa ser atualizado **hoje** (não "ter venda de ontem": numa segunda, loja fechada no domingo nunca teria o dia) e o lote segue assim que a fonte chega ou o prazo vence; e `Prisma-LoteNoturno` às 13:00 e 18:00, sem espera, para quem chega atrasado (em set/2026, 31 empresas chegavam entre 08:18 e 08:31 e 10 por volta das 17h). Empresa que não mudou sai do cache em < 1 s, então as passadas extras custam pouco. A tarefa `Prisma - abrir diariamente` (08:00) só sobe o backend (`Prisma.exe` sem argumento). A antiga `Prisma-NormalizarTodasEmpresas` (`Prisma.exe --pre-gerar` numa pasta de build que não existia mais, falhando desde 10/09) foi excluída em 24/09/2026.

### Precificação: duas abas, movimento do PRICE

Uma tela (`/precificacao`) com abas como o Estoque; a aba fica na URL (`?aba=pos`) e `/pos-precificacao` redireciona para ela. As duas leem o movimento por SKU do PRICE (`margem_price`), que soma as lojas da empresa — por isso nenhuma tem seletor de loja nem os controles de escopo do topo.

- **A precificar** (aba padrão, `backend/a_precificar.py`): o que precisa de preço novo. Janelas encostadas no fim do movimento (já limitado ao D-1): **recente** = últimos 30 dias, **base** = os 90 antes. Provas: margem caiu ≥ 2 pp, custo subiu 2 pp a mais que o preço, qtd/dia caiu ≥ 15%, margem > 1 pp abaixo do alvo vigente. Referência = alvo da última precificação do SKU no dump; sem dump ou sem precificação, a margem da base — logo a tela funciona também para empresa ainda não precificada, desde que tenha o parquet do PRICE. Lucro perdido/dia = qtd/dia × (custo ÷ (1 − ref) − preço), na mesma quantidade. Ordem = perdido × peso da curva (A 1 · B 0,6 · C 0,3) × nº de provas. SKU com menos de 3 unidades em alguma janela fica fora: variação de uma venda só é ruído. A lista e os fabricantes são por **descrição × fabricante** (o grão em que o PRICE precifica), somando os SKUs sinalizados de cada par; margem sai das somas, custo/preço/reajuste são médias dos SKUs ponderadas pela receita recente (preço unitário de SKUs diferentes somado não significa nada). O SKU só aparece no painel do item (`/a-precificar/par`), junto da margem semanal do par.
- **Pós-precificação** (`?aba=pos`, `historico_precificacao.py`): quando cada SKU foi precificado e como vendeu antes × depois, todas as rodadas. A visão por rodada (`/api/precificacao/{empresa}`, `precificacao.py`) não tem mais tela; o endpoint ficou.

### Base empresa / loja / CNPJ (`base_empresas.parquet`)

Precificação (Postgres do PRICE) e margem por transação (`DB/PRICE/margem_price`) são indexadas por **CNPJ**; o Prisma, por pasta de empresa e `ID_LOJA`. A ponte oficial é o `{empresa}_EMPRESA.dw_2d` do DW (`<OneDrive>/DB/DW/{empresa}/BI/`, CSV `;`, uma linha por loja com `ID_LOJA;CNPJ;NOME;CEP;TIPO_TRIBUTACAO`). `montar_base_empresas.py` mantém `{trabalho}/base_empresas.parquet` (`backend/base_empresas.py`) só com as empresas da fonte (Dados Alvos), e o lote noturno o roda antes do dump de precificação. É **incremental**: o mapa salvo fica; empresa que entra na Dados Alvos tem o `_EMPRESA.dw_2d` buscado e é adicionada (sem arquivo no DW, tenta de novo no dia seguinte); empresa que sai da Dados Alvos sai do mapa. `--refazer` relê o DW de todas, para quando uma empresa abre ou fecha loja.

- O nome da pasta no DW é o da fonte e o `ID_LOJA` é o do movimento — casa sem tradução.
- Loja que o DW traz sem CNPJ (a Cativo exporta só os nomes das lojas) é completada por `{trabalho}/base_empresas_complemento.json` (empresa → {loja: CNPJ}), aplicado a cada execução. O complemento só preenche vazio e acrescenta loja que o DW não lista; CNPJ que o DW já traz não é sobrescrito.
- O lote de precificação e a margem por transação (`margem_price.resolver_cnpjs`) usam a base primeiro; `precificacao_cnpj.json` virou **reserva** de nível empresa. O mapa manual trazia só a matriz de várias empresas: com a base, a margem de 15 empresas passou a somar todas as lojas e 8 ganharam margem (36 no total, set/2026).
- A inferência por código de produto (`sugerir_cnpj_precificacao.py`) conferiu com a base nas 28 empresas em que as duas existiam; ficou como ferramenta de conferência.

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
