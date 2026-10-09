"""Valida a medição antes de ela chegar ao modelo.

Timeout, ausência de resultado e probe offline são situações diferentes.
Linha inválida vai para a quarentena e não entra no histórico.
As contas de perda, RTT e jitter são as funções da etapa 5.
"""

import json
import math

from src.reuso import modulo_medicoes


class ErroColeta(Exception):
    """Falha de rede ou de fixture. Não é uma medição inválida."""

    def __init__(self, tipo: str, mensagem: str):
        super().__init__(mensagem)
        self.tipo = tipo


def _float_ou_nan(valor) -> float:
    if valor is None or valor == "" or isinstance(valor, bool):
        return float("nan")
    try:
        return float(valor)
    except (TypeError, ValueError):
        return float("nan")


def _dentro(perda: float) -> bool:
    return math.isfinite(perda) and 0 <= perda <= 100


def classificar_item(item: dict, probe_id: int) -> dict:
    """Converte um resultado da API em medição válida, timeout ou inválida."""
    if not isinstance(item, dict):
        return {"situacao": "invalida", "motivo": "item_nao_e_objeto", "item": item}
    if item.get("offline") is True:
        return {"situacao": "probe_offline", "probe_id": item.get("prb_id"), "item": item}
    if item.get("prb_id") != probe_id:
        return {"situacao": "invalida", "motivo": "probe_diferente", "item": item}
    timestamp = item.get("timestamp")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        return {"situacao": "invalida", "motivo": "timestamp_invalido", "item": item}
    medicoes = modulo_medicoes()
    resultado = item.get("result")
    texto = json.dumps(resultado) if isinstance(resultado, list) else ""
    timeout = bool(medicoes.tem_timeout(texto) or item.get("avg") == -1)
    rtts = medicoes.extrair_rtts(texto)
    rcvd = item.get("rcvd")
    perda_total = timeout or rcvd == 0
    perda = _float_ou_nan(medicoes.feature_perda_pct(item.get("sent"), rcvd))
    if not _dentro(perda):
        return {"situacao": "invalida", "motivo": "perda_fora_de_0_a_100", "item": item}
    bruto_avg = "" if timeout else item.get("avg", "")
    bruto_min = "" if timeout else item.get("min", "")
    bruto_max = "" if timeout else item.get("max", "")
    latencia = _float_ou_nan(medicoes.feature_latencia_ms(medicoes.feature_rtt_avg(bruto_avg, rtts, perda_total)))
    if not timeout and math.isfinite(latencia) and latencia < 0:
        return {"situacao": "invalida", "motivo": "latencia_negativa", "item": item}
    if not timeout and not math.isfinite(latencia) and not perda_total:
        return {"situacao": "invalida", "motivo": "latencia_ausente", "item": item}
    ttl = _float_ou_nan(medicoes.feature_ttl(item.get("ttl")))
    return {
        "situacao": "timeout" if timeout else "ok",
        "timestamp": timestamp,
        "perda_num": perda,
        "latencia_num": latencia,
        "jitter_num": _float_ou_nan(medicoes.feature_jitter_ms(rtts, perda_total)),
        "rtt_min_num": _float_ou_nan(medicoes.feature_rtt_min(bruto_min, rtts, perda_total)),
        "rtt_max_num": _float_ou_nan(medicoes.feature_rtt_max(bruto_max, rtts, perda_total)),
        "rtt_avg_num": latencia,
        "ttl": ttl,
    }


def na_janela(item: dict, inicio: int, fim: int) -> bool:
    """Janela meio aberta [inicio, fim), em Unix UTC.

    Item sem timestamp ainda passa, para a validação mandá-lo à quarentena.
    Fora da janela, a medição é de outro período e não é erro.
    """
    if not isinstance(item, dict):
        return False
    if item.get("offline") is True:
        return True
    timestamp = item.get("timestamp")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        return True
    return inicio <= timestamp < fim
