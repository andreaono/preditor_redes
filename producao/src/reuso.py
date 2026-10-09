"""Carrega código das etapas 5, 6 e 7 sem copiar a fórmula.

Cada etapa tem um módulo chamado config. Ele entra em sys.modules só
durante o import e o módulo carregado guarda a referência certa.
"""

import importlib.util
import sys

from src.ajustes import RAIZ

_CACHE: dict[str, object] = {}


def carregar_com_config(nome: str, caminho_modulo, caminho_config):
    """Executa o módulo com o config da pasta dele."""
    if nome in _CACHE:
        return _CACHE[nome]
    pasta = str(caminho_config.parent)
    sys.path.insert(0, pasta)
    guardado = sys.modules.get("config")
    spec_config = importlib.util.spec_from_file_location("config", caminho_config)
    if spec_config is None or spec_config.loader is None:
        raise FileNotFoundError(caminho_config)
    modulo_config = importlib.util.module_from_spec(spec_config)
    sys.modules["config"] = modulo_config
    spec_config.loader.exec_module(modulo_config)
    spec = importlib.util.spec_from_file_location(nome, caminho_modulo)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(caminho_modulo)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nome] = modulo
    try:
        spec.loader.exec_module(modulo)
    finally:
        if guardado is None:
            sys.modules.pop("config", None)
        else:
            sys.modules["config"] = guardado
        sys.path.remove(pasta)
    _CACHE[nome] = modulo
    return modulo


def modulo_medicoes():
    """Fórmulas de perda, RTT, jitter e TTL da etapa 5."""
    pasta = RAIZ.parent / "pipeline" / "05_periodos" / "src"
    return carregar_com_config("medicoes_etapa5", pasta / "processar_dataset.py", pasta / "config.py")


def modulo_baseline():
    """Percentil e mediana da etapa 6, para um fluxo que ainda não tem baseline."""
    pasta = RAIZ.parent / "pipeline" / "06_baseline" / "src"
    return carregar_com_config("baseline_etapa6", pasta / "construir_baseline.py", pasta / "config.py")


def modulo_rotulagem():
    """Regra, janelas e sentinela da etapa 7."""
    pasta = RAIZ.parent / "pipeline" / "07_rotulagem" / "src"
    return carregar_com_config("rotulagem_etapa7", pasta / "rotular_e_gerar_final.py", pasta / "config.py")
