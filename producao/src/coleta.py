"""Busca resultados de ping na API do RIPE Atlas ou num diretório offline.

O endpoint é o de resultados públicos já usado na etapa 4:
https://atlas.ripe.net/api/v2/measurements/{id}/results/
Consulta de resultado não cria medição. A pausa, o timeout e as tentativas
vêm do YAML, com os mesmos números que a etapa 4 já usava. Em 429 vale
Retry-After, se a resposta trouxer esse campo.
"""

import json
import time
from pathlib import Path

import requests

from src.contrato import ErroColeta


def _esperar(resposta, tentativa: int, backoff_s: float) -> float:
    indicado = resposta.headers.get("Retry-After") if resposta is not None else None
    if indicado:
        try:
            return float(indicado)
        except ValueError:
            pass
    return backoff_s * (2**tentativa)


def buscar_http(medicao_id: int, probe_id: int, inicio: int, fim: int, cfg: dict, ao_retry=None) -> list:
    """Baixa os resultados do probe na janela, seguindo next se a API paginar."""
    url = str(cfg["url_resultados"]).replace("{id}", str(medicao_id))
    params = {
        "probe_ids": str(probe_id),
        "start": str(inicio),
        "stop": str(fim),
        "format": "json",
    }
    headers = {"User-Agent": cfg["user_agent"]}
    timeout = float(cfg["timeout_s"])
    tentativas = int(cfg["max_tentativas"])
    backoff = float(cfg["backoff_s"])
    sessao = requests.Session()
    pagina = url
    primeira = True
    acumulado: list = []
    for tentativa in range(tentativas):
        try:
            resposta = sessao.get(
                pagina,
                params=params if primeira else None,
                headers=headers,
                timeout=timeout,
            )
        except requests.Timeout as erro:
            if tentativa + 1 == tentativas:
                raise ErroColeta("timeout_http", f"A API não respondeu a tempo na medição {medicao_id}.") from erro
            if ao_retry:
                ao_retry(tentativa + 1, "timeout_http")
            time.sleep(backoff * (2**tentativa))
            continue
        except requests.RequestException as erro:
            if tentativa + 1 == tentativas:
                raise ErroColeta("api_indisponivel", f"A API falhou na medição {medicao_id}: {erro}") from erro
            if ao_retry:
                ao_retry(tentativa + 1, "api_indisponivel")
            time.sleep(backoff * (2**tentativa))
            continue
        if resposta.status_code == 429 or resposta.status_code >= 500:
            if tentativa + 1 == tentativas:
                raise ErroColeta("api_indisponivel", f"HTTP {resposta.status_code} na medição {medicao_id}.")
            if ao_retry:
                ao_retry(tentativa + 1, f"http_{resposta.status_code}")
            time.sleep(_esperar(resposta, tentativa, backoff))
            continue
        if resposta.status_code >= 400:
            raise ErroColeta("api_indisponivel", f"HTTP {resposta.status_code} na medição {medicao_id}.")
        corpo = resposta.json()
        if isinstance(corpo, list):
            acumulado.extend(corpo)
            return acumulado
        if isinstance(corpo, dict):
            acumulado.extend(corpo.get("results") or [])
            seguinte = corpo.get("next")
            if not seguinte:
                return acumulado
            pagina = seguinte
            primeira = False
            continue
        raise ErroColeta("api_indisponivel", f"Resposta inesperada na medição {medicao_id}.")
    return acumulado


def buscar_offline(pasta: Path, medicao_id: int) -> list:
    """Lê o JSON local no lugar da API."""
    arquivo = Path(pasta) / f"{medicao_id}.json"
    if not arquivo.is_file():
        raise ErroColeta("sem_fixture", f"Não há fixture para a medição {medicao_id}.")
    corpo = json.loads(arquivo.read_text(encoding="utf-8"))
    if not isinstance(corpo, list):
        raise ErroColeta("sem_fixture", f"A fixture {arquivo.name} não é uma lista.")
    return corpo


def buscar(medicao_id: int, probe_id: int, inicio: int, fim: int, cfg: dict, offline: Path | None, transporte=None, ao_retry=None) -> list:
    """Escolhe API, fixture ou um transporte injetado no teste."""
    if transporte is not None:
        return transporte(medicao_id, probe_id, inicio, fim)
    if offline is not None:
        return buscar_offline(offline, medicao_id)
    return buscar_http(medicao_id, probe_id, inicio, fim, cfg, ao_retry=ao_retry)
