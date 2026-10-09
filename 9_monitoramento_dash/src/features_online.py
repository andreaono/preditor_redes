"""Features e rótulo online com o mesmo código das etapas 5 e 7."""

import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import config

_MODULOS: dict[str, object] = {}


def _carregar(nome: str, pasta: Path, arquivo: str):
    """Importa o módulo da etapa com o config da própria pasta."""
    if nome in _MODULOS:
        return _MODULOS[nome]
    sys.path.insert(0, str(pasta))
    guardado = sys.modules.get("config")
    spec_config = importlib.util.spec_from_file_location("config", pasta / "config.py")
    if spec_config is None or spec_config.loader is None:
        raise FileNotFoundError(pasta / "config.py")
    modulo_config = importlib.util.module_from_spec(spec_config)
    sys.modules["config"] = modulo_config
    spec_config.loader.exec_module(modulo_config)
    spec = importlib.util.spec_from_file_location(nome, pasta / arquivo)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(pasta / arquivo)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nome] = modulo
    try:
        spec.loader.exec_module(modulo)
    finally:
        if guardado is None:
            sys.modules.pop("config", None)
        else:
            sys.modules["config"] = guardado
        sys.path.remove(str(pasta))
    _MODULOS[nome] = modulo
    return modulo


def etapa5():
    """Fórmulas de perda, jitter, RTT e TTL."""
    return _carregar("medicoes_etapa5_dash", config.PASTA_CODIGO_ETAPA5, "processar_dataset.py")


def etapa7():
    """Regra, janelas e sentinela. A pasta da etapa 7 não é alterada."""
    return _carregar("rotulagem_etapa7_dash", config.PASTA_CODIGO_ETAPA7, "rotular_e_gerar_final.py")


def _vazio_para_nan(valor) -> float:
    if valor is None or valor == "":
        return float("nan")
    numero = float(valor)
    if numero < 0:
        return float("nan")
    return numero


def metricas_de_resultado(item: dict, ttl_baseline) -> dict:
    """Extrai a rodada e calcula perda, jitter, latência e delta de TTL."""
    medicoes = etapa5()
    result = item.get("result")
    texto = result if isinstance(result, str) else json.dumps(result or [], ensure_ascii=False)
    rtts = medicoes.extrair_rtts(texto)
    sent = item.get("sent")
    rcvd = item.get("rcvd")
    perda_txt = medicoes.feature_perda_pct(sent if sent is not None else "", rcvd if rcvd is not None else "")
    perda_num = _vazio_para_nan(perda_txt)
    perda_total = math.isfinite(perda_num) and perda_num >= 100 - 0.01
    avg = item.get("avg")
    if avg is None:
        avg = ""
    rtt_avg = medicoes.feature_rtt_avg("" if avg == "" or (isinstance(avg, (int, float)) and avg < 0) else avg, rtts, perda_total)
    rtt_min = medicoes.feature_rtt_min(item.get("min") if item.get("min") is not None else "", rtts, perda_total)
    rtt_max = medicoes.feature_rtt_max(item.get("max") if item.get("max") is not None else "", rtts, perda_total)
    jitter = medicoes.feature_jitter_ms(rtts, perda_total)
    delta = medicoes.feature_delta_ttl(item.get("ttl") if item.get("ttl") is not None else "", ttl_baseline if ttl_baseline is not None else "")
    mudou = medicoes.feature_ttl_changed(delta)
    return {
        "timestamp": int(item["timestamp"]),
        "min": _vazio_para_nan(rtt_min),
        "max": _vazio_para_nan(rtt_max),
        "avg": _vazio_para_nan(rtt_avg),
        "sent": None if sent in (None, "") else int(sent),
        "rcvd": None if rcvd in (None, "") else int(rcvd),
        "ttl": _vazio_para_nan(item.get("ttl")),
        "result": texto,
        "perda_pct": _vazio_para_nan(perda_txt),
        "jitter_ms": _vazio_para_nan(jitter),
        "latencia_ms": _vazio_para_nan(rtt_avg),
        "delta_ttl": _vazio_para_nan(delta),
        "ttl_changed": None if mudou == "" else int(mudou),
        "ttl_baseline": _vazio_para_nan(ttl_baseline),
    }


def rotular_linha(metrica: dict, baseline: dict) -> tuple[str, str]:
    """Aplica a regra da etapa 7 numa medição. Perda de 100% não consulta a latência."""
    quadro = pd.DataFrame(
        [
            {
                "tem_baseline": True,
                "status_baseline": baseline.get("status_baseline") or config.STATUS_BASELINE_OK,
                "perda_num": metrica["perda_pct"],
                "latencia_num": metrica["latencia_ms"],
                "jitter_num": metrica["jitter_ms"],
                "p95_rtt_num": baseline["p95_rtt_num"],
                "p99_rtt_num": baseline["p99_rtt_num"],
                "p95_jitter_num": baseline["p95_jitter_num"],
            }
        ]
    )
    classes, motivos = etapa7().aplicar_regra(quadro)
    return str(classes[0]), str(motivos[0])


def quadro_de_historico(id_fluxo: str, linhas: list[dict], baseline: dict) -> pd.DataFrame:
    """Monta o quadro que calcular_features espera, na ordem do timestamp."""
    registros = []
    for linha in linhas:
        registros.append(
            {
                "id_fluxo": id_fluxo,
                "timestamp": int(linha["timestamp"]),
                "perda_num": linha["perda_pct"],
                "latencia_num": linha["latencia_ms"],
                "jitter_num": linha["jitter_ms"],
                "rtt_min_num": linha["min"],
                "rtt_max_num": linha["max"],
                "rtt_avg_num": linha["avg"],
                "delta_num": linha["delta_ttl"],
                "p95_rtt_num": baseline["p95_rtt_num"],
                "p99_rtt_num": baseline["p99_rtt_num"],
                "p95_jitter_num": baseline["p95_jitter_num"],
            }
        )
    if not registros:
        return pd.DataFrame()
    return pd.DataFrame(registros).sort_values("timestamp", kind="mergesort").reset_index(drop=True)


def features_do_historico(id_fluxo: str, linhas: list[dict], baseline: dict) -> pd.DataFrame:
    """Calcula as features oficiais. A sentinela entra só onde a etapa 7 manda."""
    bruto = quadro_de_historico(id_fluxo, linhas, baseline)
    if bruto.empty:
        return bruto
    rotulagem = etapa7()
    calculado = rotulagem.aplicar_sentinela(rotulagem.calcular_features(bruto))
    calculado["perda_pct"] = calculado["perda_pct_feature"]
    return calculado


def vetor(quadro: pd.DataFrame, indice: int, nomes: list[str]) -> dict:
    """Uma linha de features, com NaN virando None para o JSON."""
    linha = quadro.iloc[indice]
    saida = {}
    for nome in nomes:
        valor = linha[nome]
        if valor is None or (isinstance(valor, float) and not math.isfinite(valor)):
            saida[nome] = None
        else:
            saida[nome] = float(valor)
    return saida


def nomes_features() -> list[str]:
    """Lista oficial gravada pela etapa 7."""
    documento = json.loads(config.PACOTE_MODELO.features.read_text(encoding="utf-8"))
    return list(documento["features"])


def lacuna_entre(anterior: int | None, atual: int) -> int:
    """1 se o intervalo até a medição anterior passa de GAP_MAX_S."""
    if anterior is None:
        return 0
    return 1 if atual - anterior > config.GAP_MAX_S else 0
