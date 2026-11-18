# Clonar Estruturação de Produto WinThor 1601

Rotina desktop em Python/PySide6 para consultar e copiar formulações de produtos no WinThor, com origem e destino independentes, seleção de componentes e gravação transacional no Oracle. O executável da rotina WinThor 9806 é chamado `PCINF9806.exe`.

## Requisitos

### Para compilar a rotina

- Windows 64 bits e Python 64 bits. O ambiente validado foi Python 3.14.7 x64.
- Git e acesso à internet para clonar o projeto e instalar os pacotes Python.
- O Oracle Client x64 completo, compatível com o banco e com o Python usado na compilação. A versão usada nesta rotina foi a 23.26.3.
- Acesso ao Oracle e credenciais/permissões de homologação. A rotina consulta `PCPRODUT`, `PCFILIAL`, `PCETAPAPRODUCAO` e `PCCOMPOSICAO`, e remove e insere linhas em `PCCOMPOSICAO`; triggers e regras do WinThor podem exigir permissões adicionais.

O Oracle Client não é um pacote Python e não é baixado pelo `requirements.txt`. A pasta `oracle_client\` também é ignorada pelo Git: obtenha o cliente x64 autorizado pela empresa/Oracle e coloque os arquivos extraídos nessa pasta antes de compilar. O comando de compilação o incorpora ao EXE.

### Para executar no computador do WinThor

- Windows 64 bits e acesso de leitura/execução à pasta de rede onde ficará `PCINF9806.exe`.
- WinThor configurado para chamar o executável pela ação da rotina 529 e fornecer os cinco parâmetros descritos abaixo.
- Conectividade com o Oracle, alias/descrição de conexão Oracle resolvível e permissões de banco adequadas.

Não é necessário instalar Python, PyInstaller ou Oracle Client em cada estação: o Oracle Client x64 vai dentro do EXE. O WinThor pode usar seu cliente x86 próprio; ele não é o cliente usado por este EXE x64.

As versões testadas para desenvolvimento foram Python 3.14.7 x64, PySide6 6.12.0, python-oracledb 3.4.2 e PyInstaller 6.22.3. Esses dados registram o ambiente validado, não substituem a homologação no Oracle da empresa.

## Baixar e instalar dependências

Abra o PowerShell e execute:

```powershell
git clone https://github.com/rubemalecks/clonar-estruturacao-de-produto-winthor-1601.git
cd clonar-estruturacao-de-produto-winthor-1601
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Os comandos usam diretamente o Python do ambiente virtual; não é necessário ativá-lo nem mudar a política de execução do PowerShell.

| Pacote (`requirements.txt`) | Uso |
| --- | --- |
| `PySide6` | Interface gráfica |
| `oracledb` | Conexão Oracle e leitura de números como `Decimal` |
| `cryptography` | Dependência usada pelo driver Oracle, inclusive no modo Thin |
| `python-dotenv` | Carregamento opcional da configuração local `.env` |
| `pyinstaller` | Ferramenta de compilação; não é necessária na estação de execução |

O arquivo `requirements.txt` instala os pacotes Python. Ele não instala o Python, o Git nem o Oracle Client.

Para atualizar uma instalação existente, com suas alterações locais já salvas:

```powershell
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Configurar a conexão Oracle

Crie a configuração local a partir do modelo, somente se o `.env` ainda não existir:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

Em execução direta, `ORA_MODE=auto` tenta carregar o Oracle Client Thick compatível com a arquitetura do EXE; se não puder, tenta Thin. Ao iniciar pelo WinThor, o EXE x64 usa o Oracle Client x64 empacotado; usuário, senha e alias são recebidos do WinThor, sem gravar credenciais no `.env`. Para alias TNS, a rotina procura o `tnsnames.ora` em `TNS_ADMIN`, `ORACLE_HOME`, configurações Oracle do Windows e caminhos do Oracle Client.

### Modo Thin

Não utiliza Instant Client. Para forçar esse modo, configure `ORA_MODE=thin` e os dados fornecidos pelo administrador:

```dotenv
ORA_MODE=thin
ORACLE_USER=usuario_oracle
ORACLE_PASSWORD=senha_oracle
ORACLE_HOST=servidor
ORACLE_PORT=1521
ORACLE_SERVICE=servico
```

Outra opção é informar `ORACLE_DSN=servidor:1521/servico` no lugar de host, porta e serviço. Se `ORACLE_DSN` estiver preenchido, ele tem prioridade. A compatibilidade do modo Thin depende da versão e configuração do Oracle.

### Modo Thick

Para forçar esse modo, disponibilize o Instant Client completo, incluindo as DLLs e suas dependências, e configure:

```dotenv
ORA_MODE=thick
ORACLE_USER=usuario_oracle
ORACLE_PASSWORD=senha_oracle
ORACLE_DSN=servidor:1521/servico
ORACLE_CLIENT_LIB_DIR=C:\oracle\instantclient_19
```

No modo automático, o programa procura o cliente nos locais descritos acima. No modo Thick forçado, `ORACLE_CLIENT_LIB_DIR` deve apontar para o Instant Client completo, ou a pasta `oracle_client` deve existir ao lado do programa. A pasta precisa conter um Oracle Client de 64 bits compatível com a autenticação do banco. Para usar um alias TNS, informe o alias em `ORACLE_DSN` e a pasta que contém a configuração Oracle em `ORACLE_CONFIG_DIR` ou `TNS_ADMIN`.

O `.env.example` contém apenas exemplos. Nunca coloque credenciais reais nele: esse arquivo é público. O `.env`, as wallets, os arquivos locais de conexão e o Instant Client são ignorados pelo Git.

## Executar pelo código-fonte

Na pasta do projeto:

```powershell
.\.venv\Scripts\python.exe main.py
```

O programa carrega o `.env` ao lado de `main.py` e tenta conectar automaticamente. Primeiro valide o funcionamento em um banco de homologação.

## Pesquisar

Escolha **Código** e digite CODPROD + Enter (somente números), ou escolha **Descrição**, digite o início do nome + Enter e selecione na lista abaixo do próprio campo, com clique ou setas e Enter. Use `%nome` para buscar em qualquer parte da descrição. Após selecionar, o campo mostra código + nome em ambos os modos; no modo Código, digitar outro número inicia uma nova pesquisa.

As filiais são selecionadas em listas carregadas do cadastro `PCFILIAL`, sem digitação livre. Os métodos da origem são carregados ao selecionar o produto ou mudar a filial, mesmo antes de consultar o destino. Se não houver formulação na filial escolhida, a lista de métodos ficará vazia.

A pesquisa ocorre automaticamente após uma breve pausa na digitação; Enter permite antecipá-la. Origem e destino têm consultas independentes: selecionar produto, filial ou método atualiza somente o lado alterado. A comparação é automática, sem botão de consulta. Alterar o destino preserva as marcações da origem. O botão Confirmar só é habilitado quando as duas consultas estiverem válidas.

## Funcionamento

- Origem: a consulta lista os métodos disponíveis do produto na filial de origem e seleciona o primeiro por padrão. Escolha outro no campo **Método** para atualizar a comparação; apenas os componentes do método selecionado são copiados.
- Destino: apenas o método e a filial escolhidos no filtro de destino. É possível copiar o mesmo produto entre filiais diferentes.
- Os métodos do destino são carregados ao selecionar produto ou filial. Sem estrutura cadastrada, o método inicial é `1`; o campo permite informar outro método para receber a cópia.
- Mesmo produto e mesma filial: a cópia é permitida somente para um método novo, diferente do método de origem. O método original é preservado.
- Amarelo: item com vínculo equivalente no destino.
- Marque na coluna de seleção da origem somente os componentes que deseja copiar. Componentes desmarcados não entram no plano da cópia.
- Ao confirmar, a estrutura final do produto/método destino na filial escolhida fica igual aos componentes marcados na origem. Vínculos com chave correspondente são atualizados; componentes excedentes do destino são removidos; componentes sem correspondência são inseridos.
- A tabela do destino é apenas para conferência; não há marcação nem exclusão manual de componentes no destino.
- O produto destino não pode estar entre os componentes selecionados da origem. A rotina avisa e exige desmarcar o componente antes de copiar.
- Os números do Oracle são lidos como `Decimal`, sem conversão para `float`, para preservar a precisão das quantidades.
- Caso dois métodos da origem tenham componentes conflitantes no método destino, desmarque um deles antes de confirmar.
- Ao confirmar uma cópia, escolha **Somente filial** ou **Todas as filiais** (cadastro `PCFILIAL`, exceto 99). A confirmação informa, por filial, quantos componentes existentes serão atualizados, quantos excedentes serão removidos e quantos novos serão inseridos. A filial de origem pode receber o mesmo produto somente em um método novo; o método original é preservado.
- Todas as filiais escolhidas são gravadas na mesma transação, com rollback integral em caso de falha.
- A operação utiliza transação com rollback em caso de falha; as triggers permanecem ativas.
- Antes de gravar, a origem e cada destino são bloqueados e comparados com os dados pesquisados. A origem é conferida novamente antes do commit. Se houver mudanças, a operação é desfeita e a pesquisa é atualizada para revisão e nova confirmação.
- Após o sucesso, as marcações da origem são limpas e a operação é finalizada. Para iniciar outra cópia, marque novamente os componentes; o botão não permite repetir a operação anterior acidentalmente.
- Se o rollback falhar, o aviso preserva o erro original e a falha ao desfazer. Se a resposta do commit falhar, o resultado é tratado como não confirmado. Em ambos os casos, novas gravações ficam bloqueadas: confira o banco e reinicie a rotina antes de repetir.

## Instalar e executar pelo WinThor

### 1. Colocar o executável na pasta de rotinas

Depois de compilar, copie `dist\PCINF9806.exe` para a pasta de rotinas WinThor usada pelas estações. O caminho precisa ser acessível por todos os usuários que executarão a rotina.

No ambiente em que esta rotina foi configurada, o arquivo foi colocado em:

```text
P:\MOD-098\PCINF9806.exe
```

Use a pasta correspondente à instalação do WinThor da empresa. O nome da pasta do módulo começa com `98` e o código cadastrado para esta rotina é `9806`; o nome do executável deve permanecer `PCINF9806.exe`. Não copie `oracle_client`, Python ou `.env` para junto do EXE: o cliente está embutido no executável e as credenciais são recebidas do WinThor.

### 2. Configurar a ação da rotina 529

Na configuração da ação/botão externo da rotina 529, aponte para o caminho completo do EXE e passe os parâmetros nesta ordem. Exemplo para o caminho de rede acima:

```text
P:\MOD-098\PCINF9806.exe ${USUARIOWT} ${SENHABD} ${ALIASBD} ${USUARIOBD} 9806
```

Se a instalação usar outra letra ou pasta, substitua somente o caminho do executável. Use as variáveis equivalentes disponíveis na configuração do WinThor para usuário WinThor, senha do banco, alias e usuário do banco; preserve a ordem exigida pelo programa. O último argumento é o código `9806`, não o número da rotina 529.

Se a tela da rotina separar o caminho do executável dos argumentos, informe `P:\MOD-098\PCINF9806.exe` no campo do programa e coloque somente os cinco argumentos na configuração de parâmetros. Se a unidade `P:` não estiver mapeada no contexto que inicia o WinThor, use o caminho UNC da mesma pasta de rede.

O EXE espera exatamente cinco argumentos após o caminho:

| Argumento | Finalidade |
| --- | --- |
| `USUARIOWT` | Identificação do usuário WinThor, exibida no status da conexão |
| `SENHABD` | Senha do usuário Oracle |
| `ALIASBD` | Alias TNS ou endereço/descritor de conexão Oracle resolvível |
| `USUARIOBD` | Usuário Oracle |
| `CODROTINA` | Código da rotina WinThor; nesta instalação, `9806` |

No modo WinThor, o EXE usa Thick com o Oracle Client x64 empacotado e prioriza usuário, senha e alias recebidos na chamada; não é preciso manter credenciais no `.env`. O quinto argumento identifica o código da rotina, mas não implementa uma validação de autorização WinThor: o acesso efetivo continua sujeito às permissões Oracle e às regras do banco.

O alias enviado pelo WinThor precisa ser resolvível no computador. Se usar um alias TNS, disponibilize o `tnsnames.ora`/configuração Oracle conforme a instalação (por exemplo, no `TNS_ADMIN`, no Oracle Home ou no diretório `oracle_client\network\admin` incluído na compilação). A rotina procura as configurações locais Oracle e a configuração empacotada.

**Proteção da senha:** o WinThor passa a senha como argumento do processo; dependendo das permissões e ferramentas do Windows, ela pode ficar visível na linha de comando do processo. Não compartilhe capturas ou logs com os argumentos reais. Evite salvar a senha em uma configuração manual da ação; use a variável de senha fornecida pelo WinThor.

## Compilar o executável Windows

### Preparar o Oracle Client

1. Obtenha o pacote completo do Oracle Client/Instant Client **x64** autorizado para a empresa e compatível com o banco. Foi testado o Oracle Client 23.26.3 x64. Não use o cliente x86/10.2 que acompanha algumas instalações do WinThor.
2. Extraia o conteúdo do cliente para `oracle_client\` na raiz do repositório, ao lado de `main.py`. Copie o conteúdo da pasta extraída, não crie um nível extra como `oracle_client\instantclient_23\oci.dll`.
3. Confirme que `oracle_client\oci.dll` existe diretamente nessa pasta e mantenha junto as DLLs e demais arquivos fornecidos pelo cliente.
4. Se a conexão usar alias TNS e as estações não tiverem configuração Oracle própria, coloque a configuração necessária (por exemplo, `tnsnames.ora`) em `oracle_client\network\admin\` antes da compilação. Não inclua senha, wallet privada ou outros segredos no executável.

Essa pasta não é versionada pelo Git. Recrie-a localmente antes de cada compilação em uma cópia limpa do repositório. A opção `--add-binary "oracle_client;oracle_client"` abaixo empacota o cliente no EXE; não se distribui essa pasta separadamente.

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --onefile --windowed --hidden-import=getpass --collect-all cryptography --icon "assets\rb_app_icon.ico" --add-binary "oracle_client;oracle_client" --add-data "assets;assets" --name PCINF9806 main.py
```

O EXE x64 carrega o Oracle Client x64 empacotado diretamente e usa as credenciais fornecidas pelo WinThor. O Oracle Client e suas DLLs serão incorporados ao executável; verifique e respeite os termos de redistribuição da Oracle antes de distribuir o arquivo.

| Opção | Efeito |
| --- | --- |
| `--clean` | Limpa caches usados na compilação |
| `--noconfirm` | Permite substituir a saída anterior com o mesmo nome |
| `--onefile` | Gera um único executável |
| `--windowed` | Executa sem janela de console |
| `--hidden-import=getpass` | Inclui módulo carregado dinamicamente pelo driver Oracle |
| `--collect-all cryptography` | Inclui módulos, bibliotecas nativas e dados do pacote criptográfico usado pelo driver Oracle no modo Thin |
| `--icon "assets\rb_app_icon.ico"` | Define o ícone RB do executável e do aplicativo |
| `--add-binary "oracle_client;oracle_client"` | Incorpora o Oracle Client x64 ao executável |
| `--add-data "assets;assets"` | Inclui logos e outros recursos da interface no pacote |
| `--name PCINF9806` | Define o nome do executável da rotina WinThor |

O resultado fica em `dist\PCINF9806.exe`. O Oracle Client x64 é embutido e extraído para uso durante a execução. A pasta `build` e os arquivos `.spec` são artefatos locais de compilação, ignorados pelo Git. O comando não inclui o `.env` nem as credenciais.

A logo utilizada nas tabelas é `assets/Logo tecnológico RBTech Soluções.png`. O símbolo em `assets/rb_app_icon.png` e `assets/rb_app_icon.ico` é usado como ícone do aplicativo e do executável. Esses recursos são incorporados ao EXE; não é necessário distribuir `assets` separadamente.

Para diagnosticar um problema de inicialização, gere uma versão com console:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --onefile --console --hidden-import=getpass --collect-all cryptography --icon "assets\rb_app_icon.ico" --add-binary "oracle_client;oracle_client" --add-data "assets;assets" --name PCINF9806-debug main.py
.\dist\PCINF9806-debug.exe
```

## Verificação após instalação

1. Confirme que o arquivo está acessível pelo caminho configurado na ação da rotina 529 e que se chama exatamente `PCINF9806.exe`.
2. Abra a rotina pelo WinThor, não apenas por duplo clique; assim, os cinco parâmetros e as credenciais são fornecidos pelo sistema.
3. Confirme o estado de conexão na barra inferior, pesquise produtos e filiais e confira a comparação antes de gravar.
4. Faça a primeira cópia em homologação. A estrutura final do método destino na filial ficará igual à seleção da origem: chaves correspondentes são atualizadas, excedentes removidos e novos componentes inseridos.
5. Depois de validar consultas, permissões e triggers em homologação, libere o caminho de rede e a ação conforme o processo de TI da empresa.

Na estação de execução, não é necessário criar uma pasta `RB1601`, copiar `.env`, instalar Python nem instalar Oracle Client. As configurações de TNS/Oracle e o acesso de rede ao banco ainda precisam estar disponíveis, a menos que a configuração TNS necessária tenha sido empacotada junto ao cliente.

## Testes locais

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_main
.\.venv\Scripts\python.exe -m py_compile main.py test_main.py
```

Os testes usam interface em modo offscreen e conexão simulada, sem ler ou gravar no Oracle. Cobrem validações de cópia, unidades, precisão, alterações concorrentes simuladas, rollback e finalização da operação. Não validam as triggers nem as permissões do banco real.

## Problemas comuns

| Situação | O que verificar |
| --- | --- |
| `py` ou `python` não encontrado durante a compilação | Instalação do Python x64 e disponibilidade do launcher/PATH; isso não é requisito nas estações que apenas executam o EXE |
| Erro de módulo não encontrado | Instalar `requirements.txt` usando o mesmo Python de `.venv` que executa ou compila |
| Ação não inicia o programa | Caminho para `PCINF9806.exe`, acesso à pasta de rede, código `9806` e cinco parâmetros na ordem documentada |
| Erro de parâmetros WinThor | Confirmar que a ação envia `USUARIOWT`, `SENHABD`, `ALIASBD`, `USUARIOBD` e `9806` |
| Oracle Client não encontrado ao compilar | Verificar se `oracle_client\oci.dll` existe diretamente na pasta, se o cliente é x64 e se as DLLs de suporte foram copiadas |
| Sem conexão Oracle | Credenciais recebidas do WinThor, alias/descritor, acesso à rede, TNS e permissões do banco |
| Alias não resolvido | Validar o alias TNS e disponibilizar o `tnsnames.ora` em `TNS_ADMIN`, Oracle Home ou `oracle_client\network\admin` antes de compilar |
| `ORA-20010` em `TRG_CHAVE_PCCOMPOSICAO` | A trigger usa transação autônoma e pode enxergar a chave antiga apesar de um `DELETE` pendente na mesma transação. A rotina atualiza vínculos de mesma chave, insere apenas novos e remove excedentes. Se persistir, conferir trigger/índices e atualizar o EXE na pasta de rede |
| EXE não abre ou fecha ao iniciar | Gerar a versão `-debug`, executar pelo terminal com parâmetros de teste não produtivos e consultar a mensagem |
| Logo não aparece no EXE | Confirmar as imagens em `assets` e recompilar com `--add-data "assets;assets"` |
| Lista de métodos da origem vazia | Produto e filial selecionados precisam ter formulação cadastrada |
| Aviso de dados alterados | Revisar a pesquisa atualizada e confirmar novamente; o plano antigo não é reaplicado |
| Resultado da gravação não confirmado | Conferir o banco antes de repetir e reiniciar a rotina |

## Segurança e homologação

**Protótipo não homologado**. Antes de permitir gravação no banco de produção, testar em homologação a atualização das chaves existentes, a remoção de componentes excedentes e a inserção dos novos com as triggers `TRG_CHAVE_PCCOMPOSICAO` e `TRG_MAPACOMPOSICAO`, constraints e campos de auditoria. As alterações ocorrem na mesma transação; o aplicativo não desabilita triggers e não altera `PCPRODUT`.
