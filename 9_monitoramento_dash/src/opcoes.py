"""Cinco fluxos para a página Monitorar. A escolha não cria medição."""

import json
import os
from datetime import datetime, timezone

import pandas as pd

import api_ripe
import config
import selecionar_par


def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _faixa(mediana: float, curto: float, medio: float) -> str:
    """Terços da mediana de RTT: curta, média ou longa."""
    if mediana <= curto:
        return "curta"
    if mediana <= medio:
        return "média"
    return "longa"


def _toca_pais(item: dict) -> bool:
    origem = (item["fluxo"].get("origem") or {}).get("pais") or ""
    destino = (item["fluxo"].get("destino") or {}).get("pais") or ""
    return origem.upper() == config.PAIS_DESTAQUE or destino.upper() == config.PAIS_DESTAQUE


def candidatos() -> tuple[list[dict], float, float]:
    """Monta a lista local e devolve os cortes de curta e média."""
    aprovados, _reprovados = selecionar_par.candidatos_locais()
    medianas = [float(item["baseline"]["mediana_rtt_A"]) for item in aprovados]
    serie = pd.Series(medianas)
    curto = float(serie.quantile(1 / 3))
    medio = float(serie.quantile(2 / 3))
    for item in aprovados:
        mediana = float(item["baseline"]["mediana_rtt_A"])
        item["mediana_rtt_ms"] = mediana
        item["faixa"] = _faixa(mediana, curto, medio)
    return aprovados, curto, medio


def cinco_opcoes() -> tuple[list[dict], float, float]:
    """Duas curtas, duas médias e uma longa. Prefere fluxo que toca o Brasil."""
    aprovados, curto, medio = candidatos()
    grupos = {"curta": [], "média": [], "longa": []}
    for item in aprovados:
        grupos[item["faixa"]].append(item)
    grupos["curta"].sort(key=lambda item: (0 if _toca_pais(item) else 1, item["mediana_rtt_ms"], item["id_fluxo"]))
    centro = float(pd.Series([item["mediana_rtt_ms"] for item in grupos["média"]]).median()) if grupos["média"] else 0.0
    grupos["média"].sort(key=lambda item: (0 if _toca_pais(item) else 1, abs(item["mediana_rtt_ms"] - centro), item["id_fluxo"]))
    grupos["longa"].sort(key=lambda item: (0 if _toca_pais(item) else 1, -item["mediana_rtt_ms"], item["id_fluxo"]))
    escolhidos = grupos["curta"][:2] + grupos["média"][:2] + grupos["longa"][:1]
    return escolhidos[: config.N_OPCOES_MONITORAR], curto, medio


def _ip_anchor(anchor: dict):
    ip = anchor.get("ip_v4")
    if isinstance(ip, dict):
        return ip.get("address") or ip.get("ipv4")
    return ip


def _pais_anchor(anchor: dict):
    pais = anchor.get("country") or anchor.get("country_code")
    if isinstance(pais, dict):
        return pais.get("code") or pais.get("name")
    return pais


def _ler_url(url: str, com_chave: bool) -> tuple[dict, str | None]:
    try:
        corpo = api_ripe.get_json(url, com_chave=com_chave) or {}
        return corpo if isinstance(corpo, dict) else {}, None
    except api_ripe.ErroApi as erro:
        return {}, str(erro)


def _consultar(item: dict) -> dict:
    """Completa localidade, tipo, IPv4, ongoing e IPs com a API do RIPE."""
    fluxo = item["fluxo"]
    origem = fluxo.get("origem") or {}
    destino = fluxo.get("destino") or {}
    com_chave = bool(os.environ.get(config.VAR_AMBIENTE_CHAVE))
    probe, erro_probe = _ler_url(config.URL_PROBES.format(id=fluxo["probe_id"]), com_chave)
    anchor, erro_anchor = _ler_url(config.URL_ANCHORS.format(id=fluxo["anchor_id"]), com_chave)
    medicao, erro_medicao = _ler_url(config.URL_MEASUREMENT.format(id=fluxo["msm_id"]), com_chave)
    detalhe = "; ".join(parte for parte in (erro_probe, erro_anchor, erro_medicao) if parte)
    vivo = {"ok": not detalhe, "detalhe": detalhe or None}
    status_med = ((medicao.get("status") or {}).get("name")) if medicao else None
    af = medicao.get("af") if medicao else None
    tipo = medicao.get("type") if medicao else None
    return {
        "id_fluxo": item["id_fluxo"],
        "faixa": item["faixa"],
        "mediana_rtt_ms": item["mediana_rtt_ms"],
        "origem": {
            "id": fluxo.get("probe_id"),
            "ip": probe.get("address_v4"),
            "pais": probe.get("country_code") or origem.get("pais"),
            "cidade": origem.get("cidade"),
            "status": ((probe.get("status") or {}).get("name")) if probe else None,
        },
        "destino": {
            "id": fluxo.get("anchor_id"),
            "ip": _ip_anchor(anchor) if anchor else None,
            "pais": (_pais_anchor(anchor) if anchor else None) or destino.get("pais"),
            "cidade": (anchor.get("city") if anchor else None) or destino.get("cidade"),
            "hostname": (anchor.get("hostname") if anchor else None) or destino.get("hostname"),
        },
        "medicao": {
            "msm_id": fluxo.get("msm_id"),
            "tipo": tipo,
            "af": af,
            "ipv4": af == config.ADDRESS_FAMILY if af is not None else None,
            "ongoing": status_med == config.STATUS_ONGOING_NOME if status_med else None,
            "status": status_med,
        },
        "consulta_ao_vivo": vivo,
        "baseline": {
            "mediana_rtt": item["mediana_rtt_ms"],
            "p95_rtt": float(item["baseline"]["p95_rtt_A"]),
            "p99_rtt": float(item["baseline"]["p99_rtt_A"]),
            "p95_jitter": float(item["baseline"]["p95_jitter_A"]),
            "ttl_baseline": float(item["baseline"]["ttl_baseline"]),
            "status_baseline": item["baseline"]["status_baseline"],
        },
    }


def listar() -> dict:
    """As cinco opções com a consulta ao vivo. Não cria medição."""
    escolhidos, curto, medio = cinco_opcoes()
    return {
        "corte_curta_ms": curto,
        "corte_media_ms": medio,
        "chave_definida": bool(os.environ.get(config.VAR_AMBIENTE_CHAVE)),
        "opcoes": [_consultar(item) for item in escolhidos],
        "escolhido": _ler_escolha(),
    }


def _ler_escolha() -> str | None:
    if not config.ARQUIVO_ESCOLHA.is_file():
        return None
    return json.loads(config.ARQUIVO_ESCOLHA.read_text(encoding="utf-8")).get("id_fluxo")


def gravar_escolha(id_fluxo: str) -> dict:
    """Registra o fluxo. A medição paga continua só no coletor, com confirmação."""
    escolhidos, _curto, _medio = cinco_opcoes()
    item = next((opcao for opcao in escolhidos if opcao["id_fluxo"] == id_fluxo), None)
    if item is None:
        raise ValueError("Esse fluxo não está entre as cinco opções.")
    ficha = _consultar(item)
    documento = {
        "id_fluxo": id_fluxo,
        "escolhido_em": _agora(),
        "medicao_criada": False,
        "faixa": ficha["faixa"],
        "origem": ficha["origem"],
        "destino": ficha["destino"],
        "msm_id_publico": ficha["medicao"]["msm_id"],
        "baseline": ficha["baseline"],
    }
    config.garantir_pastas()
    config.ARQUIVO_ESCOLHA.write_text(json.dumps(documento, ensure_ascii=False, indent=2), encoding="utf-8")
    par = {
        "id_fluxo": id_fluxo,
        "origem": ficha["origem"],
        "destino": ficha["destino"],
        "msm_id": None,
        "modo": config.MODO_COLETA,
        "baseline": ficha["baseline"],
        "ttl_baseline": ficha["baseline"]["ttl_baseline"],
        "escolhido_em": documento["escolhido_em"],
        "medicao_criada": False,
    }
    config.ARQUIVO_PAR.write_text(json.dumps(par, ensure_ascii=False, indent=2), encoding="utf-8")
    return documento
