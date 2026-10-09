"""Log operacional em JSON Lines, um arquivo por dia UTC."""

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

from src.log.privacidade import mascarar


def _agora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def caminho_do_dia(pasta: Path, instante: datetime | None = None) -> Path:
    """Rotação diária: logs/operacional/AAAA-MM-DD.jsonl."""
    momento = instante or datetime.now(timezone.utc)
    return Path(pasta) / f"{momento.strftime('%Y-%m-%d')}.jsonl"


def registrar(
    pasta: Path,
    nivel: str,
    run_id: str,
    etapa: str,
    mensagem: str,
    duracao_ms: int | None = None,
    instante: datetime | None = None,
    **extras,
) -> dict:
    """Acrescenta um evento. Campos de probe são hasheados antes de gravar."""
    evento = {
        "ts": _agora() if instante is None else instante.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "nivel": nivel,
        "run_id": run_id,
        "etapa": etapa,
        "mensagem": mensagem,
        "duracao_ms": duracao_ms,
    }
    evento.update(mascarar(extras))
    destino = caminho_do_dia(pasta, instante)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(evento, ensure_ascii=False) + "\n")
    return evento


def resumir_excecao(erro: BaseException) -> str:
    """Últimas linhas do stack, sem despejar o traceback inteiro."""
    linhas = traceback.format_exception(type(erro), erro, erro.__traceback__)
    return "".join(linhas[-4:])[:500]


def inicio(pasta: Path, run_id: str) -> dict:
    return registrar(pasta, "info", run_id, "inicio", "execucao iniciada")


def fim(pasta: Path, run_id: str, duracao_ms: int, falhas: int) -> dict:
    return registrar(pasta, "info", run_id, "fim", "execucao encerrada", duracao_ms=duracao_ms, falhas=falhas)


def quantidades(pasta: Path, run_id: str, coletadas: int, descartadas: int, previstas: int) -> dict:
    return registrar(
        pasta,
        "info",
        run_id,
        "quantidades",
        "contagem da execucao",
        coletadas=coletadas,
        descartadas=descartadas,
        previstas=previstas,
    )


def erro(pasta: Path, run_id: str, etapa: str, excecao: BaseException) -> dict:
    return registrar(pasta, "erro", run_id, etapa, resumir_excecao(excecao), tipo=type(excecao).__name__)


def retry(pasta: Path, run_id: str, tentativa: int, motivo: str, **extras) -> dict:
    return registrar(pasta, "aviso", run_id, "retry", motivo, tentativa=tentativa, **extras)
