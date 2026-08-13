"""Comparação de versões usada para decidir se o canal tem release mais nova."""

from versao import VERSAO, versao_como_tupla, versao_mais_nova


def test_converte_para_tupla_de_inteiros():
    assert versao_como_tupla("1.2.10") == (1, 2, 10)


def test_ignora_sufixo_nao_numerico():
    assert versao_como_tupla("1.1.0rc1") == (1, 1, 0)


def test_parte_sem_digito_vira_zero():
    assert versao_como_tupla("1.x.3") == (1, 0, 3)


def test_reconhece_versao_posterior():
    assert versao_mais_nova("1.0.1", "1.0.0")
    assert versao_mais_nova("1.1.0", "1.0.9")
    assert versao_mais_nova("2.0.0", "1.99.99")


def test_recusa_versao_igual_ou_anterior():
    assert not versao_mais_nova("1.0.0", "1.0.0")
    assert not versao_mais_nova("0.9.9", "1.0.0")


def test_compara_numericamente_e_nao_como_texto():
    """`"1.2.10" < "1.2.9"` em ordem lexicográfica — o caso que a comparação
    ingênua por string erraria, deixando o usuário preso na 1.2.9."""
    assert versao_mais_nova("1.2.10", "1.2.9")
    assert not versao_mais_nova("1.2.9", "1.2.10")


def test_tamanhos_diferentes_sao_normalizados():
    """`1.1` e `1.1.0` são a mesma versão; a mais curta não pode parecer menor."""
    assert not versao_mais_nova("1.1", "1.1.0")
    assert not versao_mais_nova("1.1.0", "1.1")
    assert versao_mais_nova("1.2", "1.1.9")


def test_versao_declarada_tem_formato_comparavel():
    """Guarda contra bump manual malformado: um `VERSAO` que não parseia faria
    todo release parecer igual ao anterior e o update nunca seria oferecido."""
    partes = versao_como_tupla(VERSAO)
    assert len(partes) == 3
    assert VERSAO == ".".join(str(p) for p in partes)
