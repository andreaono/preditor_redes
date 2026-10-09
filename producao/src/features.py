"""Monta o vetor chamando o cálculo da etapa 7. Não reimplementa janela nem sentinela."""

import math

import pandas as pd

from src.features_treino import nomes_features
from src.reuso import modulo_baseline, modulo_rotulagem


def baseline_da_etapa6(caminho, probe_id: int, anchor_id: int):
    """Lê o baseline já gravado. Não recalcula o período A."""
    arquivo = caminho
    if not arquivo.is_file():
        return None
    quadro = pd.read_csv(arquivo, dtype=str)
    mascara = (quadro["probe_id"] == str(probe_id)) & (quadro["anchor_id"] == str(anchor_id))
    achados = quadro.loc[mascara]
    if achados.empty:
        return None
    linha = achados.iloc[0]
    status = str(linha["status_baseline"])
    if status != modulo_rotulagem().config.STATUS_BASELINE_OK:
        return None
    return {
        "p95_rtt_num": float(linha["p95_rtt_A"]),
        "p99_rtt_num": float(linha["p99_rtt_A"]),
        "p95_jitter_num": float(linha["p95_jitter_A"]),
        "ttl_baseline": float(linha["ttl_baseline"]),
        "tem_baseline": True,
        "status_baseline": status,
        "origem": "etapa6",
    }


def baseline_novo(medicoes: list[dict]):
    """Percentis da etapa 6 quando o par ainda não está no CSV e já há amostras."""
    modulo = modulo_baseline()
    minimo = modulo.config.MIN_AMOSTRAS_BASELINE
    rtts = [item["rtt_avg_num"] for item in medicoes if math.isfinite(item["rtt_avg_num"])]
    jitters = [item["jitter_num"] for item in medicoes if math.isfinite(item["jitter_num"])]
    ttls = [item["ttl"] for item in medicoes if math.isfinite(item["ttl"])]
    if len(rtts) < minimo:
        return None
    status = modulo_rotulagem().config.STATUS_BASELINE_OK
    p95_jitter = modulo.percentil_linear(jitters, 95) if jitters else float("nan")
    ttl = modulo.mediana(ttls) if ttls else float("nan")
    return {
        "p95_rtt_num": modulo.percentil_linear(rtts, 95),
        "p99_rtt_num": modulo.percentil_linear(rtts, 99),
        "p95_jitter_num": float("nan") if p95_jitter is None else p95_jitter,
        "ttl_baseline": float("nan") if ttl is None else ttl,
        "tem_baseline": True,
        "status_baseline": status,
        "origem": "medicoes_do_fluxo",
    }


def _delta(medicao: dict, baseline: dict) -> float:
    ttl = medicao["ttl"]
    base = baseline["ttl_baseline"]
    if not math.isfinite(ttl) or not math.isfinite(base):
        return float("nan")
    return ttl - base


def vetor_e_classe(fluxo_id: str, medicoes: list[dict], baseline: dict) -> tuple[dict, str]:
    """Calcula as features de todo o histórico e devolve a última linha."""
    rotulagem = modulo_rotulagem()
    linhas = []
    for medicao in medicoes:
        linhas.append(
            {
                "id_fluxo": fluxo_id,
                "timestamp": medicao["timestamp"],
                "perda_num": medicao["perda_num"],
                "latencia_num": medicao["latencia_num"],
                "jitter_num": medicao["jitter_num"],
                "rtt_min_num": medicao["rtt_min_num"],
                "rtt_max_num": medicao["rtt_max_num"],
                "rtt_avg_num": medicao["rtt_avg_num"],
                "delta_num": _delta(medicao, baseline),
                "p95_rtt_num": baseline["p95_rtt_num"],
                "p99_rtt_num": baseline["p99_rtt_num"],
                "p95_jitter_num": baseline["p95_jitter_num"],
                "tem_baseline": True,
                "status_baseline": baseline["status_baseline"],
            }
        )
    quadro = pd.DataFrame(linhas)
    quadro = rotulagem.calcular_features(quadro)
    quadro = rotulagem.aplicar_sentinela(quadro)
    quadro["perda_pct"] = quadro["perda_pct_feature"]
    classes, _motivos = rotulagem.aplicar_regra(quadro)
    ultima = quadro.iloc[-1]
    features = {nome: float(ultima[nome]) for nome in nomes_features()}
    return features, str(classes[-1])
