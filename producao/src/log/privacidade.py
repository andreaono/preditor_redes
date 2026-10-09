"""Hash de probe e de IP. O sal vem do ambiente e não entra no repositório."""

import hashlib
import os

VARIAVEL_SAL = "PREDITOR_SAL_LOG"
CHAVES_PROBE = {"probe_id", "prb_id", "ip", "src_addr", "probe_ip", "from"}


def sal_configurado() -> str | None:
    """Lê o sal. Vazio e ausente são a mesma coisa."""
    valor = os.environ.get(VARIAVEL_SAL, "").strip()
    return valor or None


def hash_probe(valor, sal: str | None = None) -> str:
    """SHA-256 estável do identificador da probe. O anchor não passa por aqui."""
    usado = sal if sal is not None else sal_configurado()
    if not usado:
        raise RuntimeError("PREDITOR_SAL_LOG ausente. O identificador da probe não foi gravado.")
    texto = f"{usado}:{valor}".encode("utf-8")
    return hashlib.sha256(texto).hexdigest()


def mascarar(extras: dict, sal: str | None = None) -> dict:
    """Troca IP e id de probe pelo hash. O restante fica como veio."""
    saida: dict = {}
    for chave, valor in extras.items():
        if chave in CHAVES_PROBE or chave.endswith("_probe"):
            try:
                saida[f"{chave}_hash"] = hash_probe(valor, sal)
            except RuntimeError:
                saida[f"{chave}_hash"] = None
                saida["privacidade"] = "identificador omitido; sal ausente"
            continue
        saida[chave] = valor
    return saida
