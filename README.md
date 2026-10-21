# RB1601-X — Copiar Formulação WinThor

Recriação visual da rotina conforme imagem de referência: origem e destino lado a lado, caixas de seleção, marcação amarela de duplicidades, tratamento global e resumo.

## Executar

1. `python -m pip install -r requirements.txt`
2. Copie `.env.example` para `.env` e informe suas credenciais (não compartilhe o arquivo).
3. `python main.py`

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

## Conexão

Conexão automática com `.env`, em Thin ou Thick. Quando executado via WinThor, aceita cinco argumentos nesta ordem:

`RB\\RB1601.exe ${USUARIOWT} ${SENHABD} ${ALIASBD} ${USUARIOBD} ${CODROTINA}`

A senha passada por argumento pode ficar visível a ferramentas de inspeção de processos. O modo Thin depende de DSN resolvível pelo driver.

## Gerar EXE

`python -m PyInstaller --noconfirm --onefile --windowed --add-data "assets;assets" --name RB1601-X main.py`

A logo em `assets/Logo tecnológico RBTech Soluções.png` aparece como marca-d’água suave nas tabelas de origem e destino, adaptando-se ao tamanho da janela. O parâmetro `--add-data` inclui a imagem no executável.

Mantenha `.env` fora do EXE, ao lado do executável quando usar execução independente.

## Segurança e homologação

**Protótipo não homologado**. Antes de permitir gravação no banco de produção, testar em homologação as triggers `TRG_CHAVE_PCCOMPOSICAO` e `TRG_MAPACOMPOSICAO`, constraints e campos de auditoria. A opção de substituir/somar modifica apenas `QT`, não todos os atributos técnicos do vínculo existente. O aplicativo não desabilita triggers e não altera `PCPRODUT`.
