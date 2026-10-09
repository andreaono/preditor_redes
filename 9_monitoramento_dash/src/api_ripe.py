"""HTTP do RIPE Atlas com cache, pausa e retry. A chave não entra na URL nem no cache."""

import hashlib
import json
import time
from pathlib import Path

import requests

import config


class ErroApi(RuntimeError):
    """Falha de rede ou resposta que não deve derrubar o processo chamador."""


def _chave() -> str | None:
    import os

    valor = os.environ.get(config.VAR_AMBIENTE_CHAVE)
    if valor is None or not str(valor).strip():
        return None
    return str(valor).strip()


def _caminho_cache(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return config.CACHE_DIR / f"{digest}.json"


def _ler_cache(url: str) -> dict | list | None:
    caminho = _caminho_cache(url)
    if not caminho.is_file():
        return None
    idade_h = (time.time() - caminho.stat().st_mtime) / 3600
    if idade_h > config.CACHE_TTL_HORAS:
        return None
    return json.loads(caminho.read_text(encoding="utf-8"))["corpo"]


def _gravar_cache(url: str, corpo) -> None:
    config.garantir_pastas()
    _caminho_cache(url).write_text(
        json.dumps({"url": url, "corpo": corpo}, ensure_ascii=False),
        encoding="utf-8",
    )


def _cabecalhos(com_chave: bool) -> dict:
    cab = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
    if com_chave:
        chave = _chave()
        if not chave:
            raise ErroApi(f"Variável {config.VAR_AMBIENTE_CHAVE} ausente. O modo novo não inicia.")
        cab["Authorization"] = f"Key {chave}"
    return cab


def pedir(url: str, metodo: str = "GET", corpo: dict | None = None, com_chave: bool = False, sem_cache: bool = False):
    """Faz a chamada. GET sem chave usa cache. 429 e 5xx tentam de novo."""
    if metodo == "GET" and not com_chave and not sem_cache:
        guardado = _ler_cache(url)
        if guardado is not None:
            return guardado
    espera = config.BACKOFF_S
    ultimo = "sem tentativa"
    for tentativa in range(1, config.MAX_TENTATIVAS + 1):
        try:
            resposta = requests.request(
                metodo,
                url,
                headers=_cabecalhos(com_chave),
                json=corpo,
                timeout=(config.TIMEOUT_CONEXAO_S, config.TIMEOUT_S),
            )
        except requests.RequestException as erro:
            ultimo = type(erro).__name__
            if "Timeout" in ultimo and tentativa >= 2:
                break
            time.sleep(espera)
            espera *= 2
            continue
        if resposta.status_code == 429 or resposta.status_code >= 500:
            ultimo = f"HTTP {resposta.status_code}"
            pausa = resposta.headers.get("Retry-After")
            time.sleep(float(pausa) if pausa and pausa.isdigit() else espera)
            espera *= 2
            continue
        if resposta.status_code >= 400:
            texto = resposta.text[:400]
            if config.INTERVALO_MINIMO_S is None and "interval" in texto.lower():
                raise ErroApi(
                    f"A API recusou o intervalo {config.INTERVALO_COLETA_S} s. "
                    f"A documentação consultada não publica um mínimo. Resposta: {texto}"
                )
            raise ErroApi(f"HTTP {resposta.status_code} em {metodo} {url.split('?')[0]}: {texto}")
        if not resposta.content:
            dado = {}
        else:
            dado = resposta.json()
        if metodo == "GET" and not com_chave:
            _gravar_cache(url, dado)
        time.sleep(config.PAUSA_S)
        return dado
    raise ErroApi(f"Esgotou tentativas ({ultimo}) em {url.split('?')[0]}")


def get_json(url: str, sem_cache: bool = False, com_chave: bool = False):
    """GET com cache quando a chamada é pública."""
    return pedir(url, "GET", com_chave=com_chave, sem_cache=sem_cache)


def post_json(url: str, corpo: dict):
    """POST autenticado. Não grava o corpo se ele contiver a chave."""
    return pedir(url, "POST", corpo=corpo, com_chave=True, sem_cache=True)
