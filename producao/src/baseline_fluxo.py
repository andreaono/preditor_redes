"""Baseline por fluxo, reusando a regra da etapa 7.

A persistência prevê que a próxima classe é a classe atual.
A regra de rótulo não é reescrita aqui: quem classifica é aplicar_regra.
"""

from src.reuso import modulo_rotulagem


def persistencia(classe_atual: str) -> str:
    """A próxima classe, segundo a persistência, é a classe desta medição."""
    if classe_atual not in ("OK", "RISCO", "FALHA"):
        raise ValueError(f"classe_atual fora do conjunto: {classe_atual}")
    return classe_atual


def regra(quadro):
    """Aplica a precedência FALHA > RISCO > OK definida na etapa 7."""
    return modulo_rotulagem().aplicar_regra(quadro)
