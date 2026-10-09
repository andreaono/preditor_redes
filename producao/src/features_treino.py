"""Reusa a definição de features da etapa 7. Não copia a lista."""

import importlib.util
from functools import lru_cache

from src.ajustes import RAIZ

ARQUIVO_CONFIG_ETAPA7 = RAIZ.parent / "pipeline" / "07_rotulagem" / "src" / "config.py"


@lru_cache(maxsize=1)
def modulo_etapa7():
    """Carrega o config da rotulagem sem colocá-lo no caminho de importação."""
    spec = importlib.util.spec_from_file_location("config_rotulagem_etapa7", ARQUIVO_CONFIG_ETAPA7)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(ARQUIVO_CONFIG_ETAPA7)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def nomes_features() -> list[str]:
    """Ordem oficial, a mesma usada no treino."""
    return list(modulo_etapa7().lista_features())


def grupos() -> dict[str, list[str]]:
    """Os três grupos do contexto: instantânea, janela e dinâmica."""
    modulo = modulo_etapa7()
    janela: list[str] = []
    for tamanho in modulo.JANELAS:
        janela.extend(modulo.nomes_janela(tamanho))
    return {
        "instantanea": list(modulo.FEATURES_INSTANTANEAS),
        "janela": janela,
        "dinamica": [modulo.FEATURE_DINAMICA],
    }


def colunas_proibidas() -> set[str]:
    """Metadados e rótulos que não podem entrar no vetor de features."""
    modulo = modulo_etapa7()
    return set(modulo.COLUNAS_PROIBIDAS) | {modulo.COLUNA_ALVO, "rotulo_real", "ts_rotulo"}
