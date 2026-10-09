"""Escolhe um fluxo válido com checagem ao vivo. A ordem é id_fluxo crescente."""

import json
from datetime import datetime, timezone

import pandas as pd

import api_ripe
import config


def agora() -> str:
    """Instante UTC sem microssegundos."""
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ids_excluidos() -> set[str]:
    if not config.ARQUIVO_EXCLUSOES_ETAPA5.is_file():
        return set()
    quadro = pd.read_csv(config.ARQUIVO_EXCLUSOES_ETAPA5, dtype=str, usecols=["id_fluxo"])
    return set(quadro["id_fluxo"].astype(str))


def _baselines() -> dict[str, dict]:
    quadro = pd.read_csv(config.ARQUIVO_BASELINE_ETAPA6, dtype=str)
    saida = {}
    for _, linha in quadro.iterrows():
        saida[str(linha["id_fluxo"])] = linha.to_dict()
    return saida


def candidatos_locais() -> tuple[list[dict], list[dict]]:
    """Separa quem passa nos critérios de arquivo e quem já reprova."""
    metadados = json.loads(config.ARQUIVO_METADADOS_ETAPA5.read_text(encoding="utf-8"))
    baselines = _baselines()
    exclusoes = _ids_excluidos()
    aprovados = []
    reprovados = []
    for id_fluxo in sorted(metadados["fluxos"]):
        fluxo = metadados["fluxos"][id_fluxo]
        motivos = []
        if fluxo.get("classe") != config.CLASSE_AMBOS:
            motivos.append(f"classe {fluxo.get('classe')}")
        base = baselines.get(id_fluxo)
        if base is None or str(base.get("status_baseline")) != config.STATUS_BASELINE_OK:
            motivos.append("baseline ausente ou não VALIDO")
        if id_fluxo in exclusoes:
            motivos.append("exclusoes_processamento.csv")
        item = {"id_fluxo": id_fluxo, "fluxo": fluxo, "baseline": base}
        if motivos:
            reprovados.append({"id_fluxo": id_fluxo, "motivos": motivos})
        else:
            aprovados.append(item)
    return aprovados, reprovados


def _item(nome: str, ok: bool, detalhe: str) -> dict:
    return {"nome": nome, "ok": ok, "detalhe": detalhe, "checado_em": agora()}


def checar_fluxo(item: dict, sem_cache: bool = False) -> dict:
    """Consulta probe, anchor e, no modo mesh, a medição. Erro de rede não sobe."""
    fluxo = item["fluxo"]
    criterios = []
    criterios.append(_item("classe A+B e baseline VALIDO", True, "arquivo local"))
    criterios.append(_item("fora de exclusoes_processamento.csv", True, "arquivo local"))
    try:
        probe = api_ripe.get_json(config.URL_PROBES.format(id=fluxo["probe_id"]), sem_cache=sem_cache)
        status = ((probe.get("status") or {}).get("name")) if isinstance(probe, dict) else None
        conectada = status == "Connected"
        criterios.append(_item("probe Connected", conectada, f"status.name={status}"))
        tags = " ".join(str(tag.get("slug", "")) for tag in (probe.get("tags") or []) if isinstance(tag, dict))
        aceita = conectada and "system-disabled" not in tags
        if config.MODO_COLETA == "novo":
            criterios.append(_item("probe aceita medição do usuário", aceita, "Connected e sem tag system-disabled; recusa na criação tenta o próximo"))
        else:
            criterios.append(_item("probe aceita medição do usuário", True, "não se aplica fora do modo novo"))
    except api_ripe.ErroApi as erro:
        criterios.append(_item("probe Connected", False, str(erro)))
        criterios.append(_item("probe aceita medição do usuário", False, str(erro)))
        probe = {}
    try:
        anchor = api_ripe.get_json(config.URL_ANCHORS.format(id=fluxo["anchor_id"]), sem_cache=sem_cache)
        desligada = bool(anchor.get("is_disabled")) if isinstance(anchor, dict) else True
        criterios.append(_item("anchor is_disabled false", not desligada, f"is_disabled={anchor.get('is_disabled') if isinstance(anchor, dict) else None}"))
        ip_api = None
        if isinstance(anchor, dict):
            ip_api = anchor.get("ip_v4") or (anchor.get("address_v4") or None)
            if isinstance(ip_api, dict):
                ip_api = ip_api.get("address") or ip_api.get("ipv4")
        ip_meta = (fluxo.get("destino") or {}).get("ip")
        coerente = bool(ip_api) and str(ip_api) == str(ip_meta)
        criterios.append(_item("ip_v4 presente e igual ao metadados", coerente, f"api={ip_api} metadados={ip_meta}"))
    except api_ripe.ErroApi as erro:
        criterios.append(_item("anchor is_disabled false", False, str(erro)))
        criterios.append(_item("ip_v4 presente e igual ao metadados", False, str(erro)))
        anchor = {}
        ip_api = None
    if config.MODO_COLETA == "mesh":
        try:
            med = api_ripe.get_json(config.URL_MEASUREMENT.format(id=fluxo["msm_id"]), sem_cache=sem_cache)
            status = ((med.get("status") or {}).get("name")) if isinstance(med, dict) else None
            ok = (
                isinstance(med, dict)
                and status == config.STATUS_ONGOING_NOME
                and med.get("type") == config.TIPO_MEDICAO
                and med.get("af") == config.ADDRESS_FAMILY
                and med.get("is_public") is True
            )
            criterios.append(_item("medição mesh Ongoing ping af=4 pública", ok, f"status={status} type={med.get('type') if isinstance(med, dict) else None} af={med.get('af') if isinstance(med, dict) else None}"))
        except api_ripe.ErroApi as erro:
            criterios.append(_item("medição mesh Ongoing ping af=4 pública", False, str(erro)))
    else:
        criterios.append(_item("medição mesh Ongoing ping af=4 pública", True, "não se aplica no modo novo ou replay"))
    valido = all(criterio["ok"] for criterio in criterios)
    return {
        "id_fluxo": item["id_fluxo"],
        "valido": valido,
        "criterios": criterios,
        "fluxo": fluxo,
        "baseline": item["baseline"],
        "ip_v4": ip_api,
        "probe": {"id": fluxo["probe_id"], "ip": (fluxo.get("origem") or {}).get("ip"), "pais": (fluxo.get("origem") or {}).get("pais"), "cidade": (fluxo.get("origem") or {}).get("cidade")},
        "anchor": {"id": fluxo["anchor_id"], "ip": (fluxo.get("destino") or {}).get("ip"), "pais": (fluxo.get("destino") or {}).get("pais"), "cidade": (fluxo.get("destino") or {}).get("cidade"), "hostname": (fluxo.get("destino") or {}).get("hostname")},
    }


def escolher(fluxo_id: str | None = None, sem_cache: bool = False) -> dict:
    """FLUXO_MONITORADO ou --fluxo, senão o primeiro válido do Brasil, senão o primeiro válido."""
    config.garantir_pastas()
    locais, reprovados = candidatos_locais()
    pedido = fluxo_id or config.FLUXO_MONITORADO
    if pedido is not None and pedido not in {item["id_fluxo"] for item in locais}:
        raise SystemExit(f"Fluxo {pedido} não passa nos critérios de arquivo. Veja a tabela de reprovação.")
    fila = locais if pedido is None else [item for item in locais if item["id_fluxo"] == pedido]
    if pedido is None:
        brasil = [item for item in fila if ((item["fluxo"].get("destino") or {}).get("pais") or "").upper() == config.PAIS_DESTAQUE]
        resto = [item for item in fila if item not in brasil]
        fila = brasil + resto
    checados = []
    falhas_rede = 0
    for item in fila:
        if falhas_rede >= 2:
            checados.append({
                "id_fluxo": item["id_fluxo"],
                "valido": False,
                "criterios": [_item("consulta ao vivo", False, "API sem conexão depois de falhas seguidas; o fluxo não entra como válido")],
                "fluxo": item["fluxo"],
                "baseline": item["baseline"],
                "probe": {},
                "anchor": {"pais": (item["fluxo"].get("destino") or {}).get("pais")},
            })
            continue
        try:
            resultado = checar_fluxo(item, sem_cache=sem_cache)
            checados.append(resultado)
            if any("Esgotou tentativas" in c["detalhe"] or "timed out" in c["detalhe"].lower() or "Max retries" in c["detalhe"] for c in resultado["criterios"] if not c["ok"]):
                falhas_rede += 1
            else:
                falhas_rede = 0
        except Exception as erro:
            falhas_rede += 1
            checados.append({"id_fluxo": item["id_fluxo"], "valido": False, "criterios": [_item("checagem", False, str(erro))], "fluxo": item["fluxo"], "baseline": item["baseline"], "probe": {}, "anchor": {}})
        print(f"checado {item['id_fluxo']} valido={checados[-1]['valido']}", flush=True)
    validos = [item for item in checados if item["valido"]]
    if pedido is not None:
        escolhido = next((item for item in validos if item["id_fluxo"] == pedido), None)
    else:
        brasil = [item for item in validos if (item["anchor"].get("pais") or "").upper() == config.PAIS_DESTAQUE]
        escolhido = (brasil or validos or [None])[0]
    if escolhido is None:
        linhas = ["Nenhum fluxo válido.", "id_fluxo\tmotivos"]
        for item in reprovados:
            linhas.append(f"{item['id_fluxo']}\t{'; '.join(item['motivos'])}")
        for item in checados:
            if not item["valido"]:
                motivos = [c["nome"] + ": " + c["detalhe"] for c in item["criterios"] if not c["ok"]]
                linhas.append(f"{item['id_fluxo']}\t{'; '.join(motivos)}")
        raise SystemExit("\n".join(linhas))
    base = escolhido["baseline"]
    documento = {
        "id_fluxo": escolhido["id_fluxo"],
        "origem": escolhido["probe"],
        "destino": escolhido["anchor"],
        "msm_id": escolhido["fluxo"].get("msm_id") if config.MODO_COLETA == "mesh" else None,
        "modo": config.MODO_COLETA,
        "criterios": escolhido["criterios"],
        "baseline": {
            "mediana_rtt": float(base["mediana_rtt_A"]),
            "p95_rtt": float(base["p95_rtt_A"]),
            "p99_rtt": float(base["p99_rtt_A"]),
            "p95_jitter": float(base["p95_jitter_A"]),
            "ttl_baseline": float(base["ttl_baseline"]),
            "status_baseline": base["status_baseline"],
        },
        "ttl_baseline": float(base["ttl_baseline"]),
        "outros_validos": [item["id_fluxo"] for item in validos if item["id_fluxo"] != escolhido["id_fluxo"]],
        "checado_em": agora(),
    }
    config.ARQUIVO_PAR.write_text(json.dumps(documento, ensure_ascii=False, indent=2), encoding="utf-8")
    if not config.ARQUIVO_CONTROLE.is_file():
        config.ARQUIVO_CONTROLE.write_text(json.dumps({"pausado": False, "atualizado_em": agora()}, indent=2), encoding="utf-8")
    return documento


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Seleciona o par monitorado.")
    parser.add_argument("--fluxo", default=None)
    parser.add_argument("--sem-cache", action="store_true")
    args = parser.parse_args(argv)
    documento = escolher(args.fluxo, sem_cache=args.sem_cache)
    print(documento["id_fluxo"], documento["modo"], "msm_id=", documento["msm_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
