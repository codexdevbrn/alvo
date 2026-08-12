"""
Versão do Prisma, embutida no executável.

Fonte única da verdade: `build.ps1` lê `VERSAO` daqui para nomear o pacote e
escrever o `version.json` publicado no canal de atualização, e o app compara
esse número com o do canal para saber se existe versão mais nova.

Bumpar aqui é o primeiro passo de todo release.

Não confundir com `engine.recursos.VERSAO_ATUAL`: aquela versiona o app desktop
"Monitor", de onde o motor de análise veio. São produtos diferentes, com
histórico de releases diferente — compartilhar o número confundiria o suporte.
"""

VERSAO = "1.0.7"
NOME_APP = "Prisma"


def versao_como_tupla(versao: str) -> tuple[int, ...]:
    """`"1.2.10"` → `(1, 2, 10)`, para comparar versões numericamente.

    Comparar as strings direto erraria: `"1.2.10" < "1.2.9"` é verdadeiro em
    ordem lexicográfica. Partes não numéricas (ex.: o `rc1` de `1.1.0rc1`) são
    ignoradas, o que basta para o esquema simples usado aqui — se um dia houver
    pré-release de verdade, isto precisa virar semver completo.
    """
    partes = []
    for parte in versao.strip().split("."):
        digitos = ""
        for caractere in parte:
            if not caractere.isdigit():
                break
            digitos += caractere
        partes.append(int(digitos) if digitos else 0)
    return tuple(partes)


def versao_mais_nova(candidata: str, referencia: str = VERSAO) -> bool:
    """True se `candidata` é posterior a `referencia`.

    Normaliza o tamanho das tuplas com zeros para que `1.1` e `1.1.0` sejam
    tratadas como a mesma versão em vez de a mais curta parecer menor.
    """
    a = versao_como_tupla(candidata)
    b = versao_como_tupla(referencia)
    tamanho = max(len(a), len(b))
    a += (0,) * (tamanho - len(a))
    b += (0,) * (tamanho - len(b))
    return a > b
