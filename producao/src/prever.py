"""Carrega o modelo congelado e registra a previsão do próximo estado.

O arquivo do modelo é só lido. O rótulo real não entra nas features.
"""

import hashlib
import json
import os
import time
from functools import lru_cache

import joblib
import numpy as np

from src.ajustes import carregar
from src.esquema import agora_utc, linha_log, validar_features
from src.features_treino import nomes_features
from src.log_predicoes import anexar

PREFIXO_HASH = "sha256:"


def hash_arquivo(caminho) -> str:
    """SHA-256 do arquivo, sem modificá-lo."""
    digest = hashlib.sha256()
    with open(caminho, "rb") as arquivo:
        while True:
            bloco = arquivo.read(1024 * 1024)
            if not bloco:
                break
            digest.update(bloco)
    return PREFIXO_HASH + digest.hexdigest()


@lru_cache(maxsize=1)
def carregar_modelo():
    """Abre o joblib do treino e recusa se a lista de features mudou."""
    ajustes = carregar()
    pacote = joblib.load(ajustes["arquivo_modelo"])
    esperadas = nomes_features()
    if list(pacote["features"]) != esperadas:
        raise RuntimeError("As features do modelo congelado divergem da etapa 7.")
    return pacote, ajustes


def prever(
    features: dict,
    *,
    fluxo_id: str,
    anchor_id: int,
    classe_atual: str,
    run_id: str | None = None,
    ts_previsao: str | None = None,
    caminho_log=None,
    modelo_hash: str | None = None,
) -> dict:
    """Prevê a classe seguinte e, se pedido, acrescenta uma linha no jsonl."""
    ajustes_previos = carregar()
    if classe_atual not in ajustes_previos["classes"]:
        raise ValueError(f"classe_atual fora do conjunto: {classe_atual}")
    ordenadas = validar_features(features)
    pacote, ajustes = carregar_modelo()
    vetor = np.asarray([[ordenadas[nome] for nome in nomes_features()]], dtype=float)
    inicio = time.perf_counter()
    classe = str(pacote["modelo"].predict(vetor)[0])
    probabilidades = pacote["modelo"].predict_proba(vetor)[0]
    latencia = int(round((time.perf_counter() - inicio) * 1000))
    proba = {str(nome): float(valor) for nome, valor in zip(pacote["modelo"].classes_, probabilidades)}
    proba = {nome: proba[nome] for nome in ajustes["classes"]}
    instante = ts_previsao or agora_utc()
    identificador = run_id or os.environ.get("RUN_ID") or f"{instante}-01"
    resumo = modelo_hash or hash_arquivo(ajustes["arquivo_modelo"])
    linha = linha_log(
        run_id=identificador,
        ts_previsao=instante,
        fluxo_id=fluxo_id,
        anchor_id=anchor_id,
        modelo_versao=ajustes["modelo_versao"],
        modelo_hash=resumo,
        features=ordenadas,
        proba=proba,
        classe_prevista=classe,
        classe_atual=classe_atual,
        latencia_inferencia_ms=latencia,
    )
    if caminho_log is not None:
        anexar(caminho_log, linha)
    return linha


def main() -> None:
    """Lê um JSON na entrada padrão e grava a previsão no log configurado."""
    pedido = json.loads(input())
    ajustes = carregar()
    destino = ajustes["pasta_logs"] / f"{pedido.get('run_id', 'execucao')}.jsonl"
    linha = prever(
        pedido["features"],
        fluxo_id=pedido["fluxo_id"],
        anchor_id=int(pedido["anchor_id"]),
        classe_atual=pedido["classe_atual"],
        run_id=pedido.get("run_id"),
        ts_previsao=pedido.get("ts_previsao"),
        caminho_log=destino,
    )
    print(json.dumps({"classe_prevista": linha["classe_prevista"], "arquivo": str(destino)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
