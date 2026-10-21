# Clonar Estruturação de Produto WinThor 1601

Rotina desktop em Python/PySide6 para consultar e copiar formulações de produtos no WinThor, com origem e destino independentes, seleção de componentes, tratamento de duplicidades e gravação transacional no Oracle. O executável é chamado `RB1601-X.exe`.

## Pré-requisitos

- Windows para executar os comandos deste guia e gerar o EXE Windows.
- Python com suporte às versões de dependências de `requirements.txt` e o comando `py` disponível. Se o launcher não estiver instalado, use `python` no lugar de `py`.
- Git para clonar e atualizar o projeto.
- Acesso de rede ao Oracle e credenciais fornecidas pelo administrador do banco.
- Permissões de consulta em `PCPRODUT`, `PCFILIAL`, `PCETAPAPRODUCAO` e `PCCOMPOSICAO`, e de inclusão, atualização e exclusão em `PCCOMPOSICAO`. As triggers podem exigir permissões adicionais.
- No modo Thick, Oracle Instant Client compatível com o banco e com a arquitetura do Python. O código procura a pasta `oracle_client` por padrão.

As verificações locais foram executadas com Python 3.14.8 de 64 bits, PySide6 6.12.0, python-oracledb 3.4.2 e PyInstaller 6.22.3. Isso não substitui a homologação no Oracle da empresa.

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

| Dependência | Uso |
| --- | --- |
| PySide6 | Interface gráfica |
| oracledb >= 3.4 | Conexão Oracle e leitura de números como `Decimal` |
| python-dotenv | Carregamento da configuração local `.env` |
| PyInstaller | Geração do executável |

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

### Modo Thin

Não utiliza Instant Client. Preencha o `.env` com os dados fornecidos pelo administrador:

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

Disponibilize o Instant Client completo, incluindo as DLLs e suas dependências. Exemplo de configuração:

```dotenv
ORA_MODE=thick
ORACLE_USER=usuario_oracle
ORACLE_PASSWORD=senha_oracle
ORACLE_DSN=servidor:1521/servico
ORACLE_CLIENT_LIB_DIR=C:\oracle\instantclient_19
```

Se `ORACLE_CLIENT_LIB_DIR` não for informado, o programa procura `oracle_client` ao lado de `main.py` ou do EXE. Para usar um alias TNS, informe o alias em `ORACLE_DSN` e a pasta que contém a configuração Oracle em `ORACLE_CONFIG_DIR` ou `TNS_ADMIN`.

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

A pesquisa ocorre automaticamente após uma breve pausa na digitação; Enter permite antecipá-la. Origem e destino têm consultas independentes: selecionar produto, filial ou método atualiza somente o lado alterado. A comparação é automática, sem botão de consulta. Alterar o destino preserva as marcações da origem; alterar a origem preserva as exclusões marcadas no destino. O botão Confirmar só é habilitado quando as duas consultas estiverem válidas.

## Funcionamento

- Origem: a consulta lista os métodos disponíveis do produto na filial de origem e seleciona o primeiro por padrão. Escolha outro no campo **Método** para atualizar a comparação; apenas os componentes do método selecionado são copiados.
- Destino: apenas o método e a filial escolhidos no filtro de destino. É possível copiar o mesmo produto entre filiais diferentes.
- Os métodos do destino são carregados ao selecionar produto ou filial. Sem estrutura cadastrada, o método inicial é `1`; o campo permite informar outro método para receber a cópia.
- Mesmo produto e mesma filial: a cópia é permitida somente para um método novo, diferente do método de origem. O método original é preservado.
- Amarelo: item com vínculo equivalente no destino.
- Duplicidades: **Ignorar existentes** mantém a quantidade; **Substituir quantidade** atualiza `QT`; **Somar quantidades** acrescenta a quantidade de origem à quantidade do destino.
- Somar e substituir exigem unidades iguais e identificadas (unidade da estrutura ou, na ausência, unidade do produto). Unidades diferentes bloqueiam a cópia, sem conversão automática.
- O produto destino não pode estar entre os componentes selecionados da origem. A rotina avisa e exige desmarcar o componente antes de copiar.
- Os números do Oracle são lidos como `Decimal`, sem conversão para `float`. A soma preserva as casas decimais e bloqueia resultados com mais de 38 algarismos significativos.
- Checkboxes do destino: removem **apenas vínculos** da `PCCOMPOSICAO`.
- Caso dois métodos da origem tenham componentes conflitantes no método destino, desmarque um deles antes de confirmar.
- Ao confirmar uma cópia, escolha **Somente filial** ou **Todas as filiais** (cadastro `PCFILIAL`, exceto 99). A confirmação mostra as contagens por filial, com o tratamento de duplicidade aplicado separadamente em cada uma. A filial de origem pode receber o mesmo produto somente em um método novo; o método original é preservado.
- Exclusões marcadas afetam somente a filial filtrada no destino. Todas as filiais são gravadas na mesma transação, com rollback integral em caso de falha.
- A operação utiliza transação com rollback em caso de falha; as triggers permanecem ativas.
- Antes de gravar, a origem e cada destino são bloqueados e comparados com os dados pesquisados. A origem é conferida novamente antes do commit. Se houver mudanças, a operação é desfeita e a pesquisa é atualizada para revisão e nova confirmação.
- Após o sucesso, as marcações são limpas e a operação é finalizada. Para iniciar outra cópia, selecione os componentes novamente; o botão não permite repetir a soma anterior acidentalmente.
- Se o rollback falhar, o aviso preserva o erro original e a falha ao desfazer. Se a resposta do commit falhar, o resultado é tratado como não confirmado. Em ambos os casos, novas gravações ficam bloqueadas: confira o banco e reinicie a rotina antes de repetir.

## Executar pelo WinThor

Ao cadastrar a chamada externa na rotina 529, configure o caminho do executável conforme a instalação. O programa aceita exatamente cinco argumentos nesta ordem:

```text
RB\RB1601-X.exe ${USUARIOWT} ${SENHABD} ${ALIASBD} ${USUARIOBD} ${CODROTINA}
```

| Argumento | Finalidade |
| --- | --- |
| USUARIOWT | Identificação do usuário WinThor exibida na conexão |
| SENHABD | Senha do usuário do banco |
| ALIASBD | Alias ou endereço de conexão Oracle |
| USUARIOBD | Usuário do banco |
| CODROTINA | Código da rotina recebido na chamada |

Nesse modo, usuário, senha e alias recebidos têm prioridade sobre o `.env`. O `.env` continua definindo o modo Thin/Thick e os caminhos locais. O código da rotina é recebido, mas não há validação de permissão WinThor implementada com esse argumento; as permissões de banco continuam sendo necessárias.

O alias enviado pelo WinThor precisa ser resolvível pelo driver. A senha em argumentos pode ficar visível a ferramentas de inspeção de processos; não compartilhe capturas ou logs da linha de comando com valores reais.

## Compilar o executável Windows

Instale as dependências e execute na pasta que contém `main.py`:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --onefile --windowed --add-data "assets;assets" --name RB1601-X main.py
```

| Opção | Efeito |
| --- | --- |
| `--clean` | Limpa caches usados na compilação |
| `--noconfirm` | Permite substituir a saída anterior com o mesmo nome |
| `--onefile` | Gera um único executável |
| `--windowed` | Executa sem janela de console |
| `--add-data "assets;assets"` | Inclui as imagens da marca-d’água no pacote |
| `--name RB1601-X` | Define o nome do executável |

O resultado fica em `dist\RB1601-X.exe`. A pasta `build` e o arquivo `.spec` são artefatos locais de compilação, ignorados pelo Git. O comando acima não inclui o `.env` nem o Instant Client no EXE.

A logo utilizada é `assets/Logo tecnológico RBTech Soluções.png`. Ela é incorporada ao EXE e aparece como marca-d’água nas tabelas; não é necessário distribuir `assets` separadamente ao usar esse comando.

Para diagnosticar um problema de inicialização, gere uma versão com console:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --onefile --console --add-data "assets;assets" --name RB1601-X-debug main.py
.\dist\RB1601-X-debug.exe
```

### Distribuir e executar

Para execução independente, prepare a pasta de destino assim:

```text
RB1601/
  RB1601-X.exe
  .env                  # configuração privada do computador destino
  oracle_client/        # somente se usar Thick com o caminho padrão
```

1. Copie `dist\RB1601-X.exe` para a pasta de instalação.
2. Crie o `.env` dessa instalação com os dados locais. O programa procura esse arquivo ao lado do EXE, independentemente da pasta de onde foi iniciado.
3. Se usar Thick, disponibilize o Instant Client e configure seu caminho. Arquivos TNS e wallets devem ser provisionados separadamente quando necessários.
4. Confirme o acesso de rede ao Oracle e execute `RB1601-X.exe`.
5. Valide consultas, cópia, duplicidades, exclusões e transações em homologação antes de liberar para produção.

O computador destino não precisa de Python instalado para executar o pacote gerado pelo PyInstaller. O modo Thick continua dependendo do Oracle Client e de suas dependências locais.

## Testes locais

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_main
.\.venv\Scripts\python.exe -m py_compile main.py test_main.py
```

Os testes usam interface em modo offscreen e conexão simulada, sem ler ou gravar no Oracle. Cobrem validações de cópia, unidades, precisão, alterações concorrentes simuladas, rollback e finalização da operação. Não validam as triggers nem as permissões do banco real.

## Problemas comuns

| Situação | O que verificar |
| --- | --- |
| `py` ou `python` não encontrado | Instalação do Python e disponibilidade do launcher/PATH |
| Erro de módulo não encontrado | Instalar `requirements.txt` usando o mesmo Python de `.venv` que executa ou compila |
| Sem conexão Oracle | `.env`, usuário, senha, host/alias, serviço, rede e permissões do banco |
| Oracle Client não encontrado | `ORA_MODE`, caminho do Instant Client, DLLs e arquitetura compatível com Python/EXE |
| Alias não resolvido | `ORACLE_DSN`/ALIASBD e diretório TNS configurado |
| EXE não abre ou fecha ao iniciar | Executar a versão `-debug` pelo terminal para visualizar a falha |
| Logo não aparece no EXE | Confirmar a imagem em `assets` e recompilar com `--add-data "assets;assets"` |
| Lista de métodos da origem vazia | Produto e filial selecionados precisam ter formulação cadastrada |
| Aviso de dados alterados | Revisar a pesquisa atualizada e confirmar novamente; o plano antigo não é reaplicado |
| Resultado da gravação não confirmado | Conferir o banco antes de repetir e reiniciar a rotina |

## Segurança e homologação

**Protótipo não homologado**. Antes de permitir gravação no banco de produção, testar em homologação as triggers `TRG_CHAVE_PCCOMPOSICAO` e `TRG_MAPACOMPOSICAO`, constraints e campos de auditoria. A opção de substituir/somar modifica apenas `QT`, não todos os atributos técnicos do vínculo existente. O aplicativo não desabilita triggers e não altera `PCPRODUT`.
