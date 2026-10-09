"""Log de coleta. Falha de API não é timeout de medição."""

import json
from pathlib import Path

from src.log.privacidade import mascarar


def registrar(
    pasta: Path,
    run_id: str,
    medicao_id: int | None,
    *,
    status_http: int | None,
    linhas_esperadas: int | None,
    linhas_recebidas: int | None,
    probes_offline: list | None = None,
    tempo_resposta_ms: int | None = None,
    creditos: int | None = None,
    falha_coleta: bool = False,
    timeout_medicao: int = 0,
    sem_resultado: int = 0,
    **extras,
) -> dict:
    """Grava uma linha por execução e medição.

    `falha_coleta` é HTTP, timeout da API ou fixture ausente.
    `timeout_medicao` conta ping com x=* . São eventos diferentes.
    Créditos ficam vazios: resultado de medição pública não cria medição.
    """
    evento = {
        "run_id": run_id,
        "medicao_id": medicao_id,
        "status_http": status_http,
        "linhas_esperadas": linhas_esperadas,
        "linhas_recebidas": linhas_recebidas,
        "probes_offline_hash": [],
        "tempo_resposta_ms": tempo_resposta_ms,
        "creditos": creditos,
        "falha_coleta": falha_coleta,
        "timeout_medicao": timeout_medicao,
        "sem_resultado": sem_resultado,
    }
    for probe in probes_offline or []:
        mascarado = mascarar({"probe_id": probe})
        evento["probes_offline_hash"].append(mascarado.get("probe_id_hash"))
    evento.update(mascarar(extras))
    destino = Path(pasta) / f"{run_id}.jsonl"
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(evento, ensure_ascii=False) + "\n")
    return evento
