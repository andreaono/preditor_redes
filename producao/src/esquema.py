"""Linha do log de predições. O rótulo real começa vazio."""

import json
import math
from datetime import datetime, timezone

from src.ajustes import CAMPOS_LOG
from src.features_treino import colunas_proibidas, nomes_features


def agora_utc() -> str:
    """Instante UTC no formato do contrato, sem fração de segundo."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validar_features(features: dict) -> dict[str, float]:
    """Confere o conjunto e devolve os valores na ordem do treino.

    Um rótulo, mesmo que venha no dicionário, não entra no vetor.
    """
    if not isinstance(features, dict):
        raise TypeError("features precisa ser um dicionário.")
    proibidas = sorted(set(features) & colunas_proibidas())
    if proibidas:
        raise ValueError("Estas colunas não podem entrar nas features: " + ", ".join(proibidas))
    esperadas = nomes_features()
    faltando = [nome for nome in esperadas if nome not in features]
    sobrando = sorted(set(features) - set(esperadas))
    if faltando or sobrando:
        raise ValueError(f"Features divergentes. Faltando: {faltando}. Sobrando: {sobrando}.")
    ordenadas: dict[str, float] = {}
    for nome in esperadas:
        valor = features[nome]
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            raise TypeError(f"{nome} precisa ser numérico.")
        numero = float(valor)
        if not math.isfinite(numero):
            raise ValueError(f"{nome} não é finito.")
        ordenadas[nome] = numero
    return ordenadas


def linha_log(
    *,
    run_id: str,
    ts_previsao: str,
    fluxo_id: str,
    anchor_id: int,
    modelo_versao: str,
    modelo_hash: str,
    features: dict[str, float],
    proba: dict[str, float],
    classe_prevista: str,
    classe_atual: str,
    latencia_inferencia_ms: int,
    rotulo_real: str | None = None,
    ts_rotulo: str | None = None,
) -> dict:
    """Monta o objeto do contrato, com as chaves na ordem combinada."""
    if not isinstance(anchor_id, int) or isinstance(anchor_id, bool):
        raise TypeError("anchor_id precisa ser inteiro.")
    if latencia_inferencia_ms < 0:
        raise ValueError("latencia_inferencia_ms não pode ser negativa.")
    return {
        "run_id": run_id,
        "ts_previsao": ts_previsao,
        "fluxo_id": fluxo_id,
        "anchor_id": anchor_id,
        "modelo_versao": modelo_versao,
        "modelo_hash": modelo_hash,
        "features": features,
        "proba": proba,
        "classe_prevista": classe_prevista,
        "classe_atual": classe_atual,
        "latencia_inferencia_ms": latencia_inferencia_ms,
        "rotulo_real": rotulo_real,
        "ts_rotulo": ts_rotulo,
    }


def texto_jsonl(linha: dict) -> str:
    """Uma linha JSON. As chaves extras não entram."""
    if tuple(linha) != CAMPOS_LOG:
        raise ValueError("A linha do log não está no contrato.")
    return json.dumps(linha, ensure_ascii=False, separators=(",", ":"))
