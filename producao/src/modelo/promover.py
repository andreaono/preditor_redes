"""Promove um challenger. Sem critérios satisfeitos, o ponteiro não muda."""

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.congelar_criterios import pendencias


def _agora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ler_ponteiro(pasta: Path) -> dict | None:
    caminho = pasta / "ATIVO"
    if not caminho.is_file():
        return None
    return json.loads(caminho.read_text(encoding="utf-8"))


def _historico(pasta: Path, evento: dict) -> None:
    destino = pasta / "historico.jsonl"
    with destino.open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(evento, ensure_ascii=False) + "\n")


def satisfeitos(metricas: dict, criterios: dict) -> tuple[bool, str]:
    """O teste original está consumido. A promoção exige teste novo e piso atingido."""
    faltas = pendencias(criterios)
    if faltas:
        return False, "Critérios ainda vazios ou inválidos: " + ", ".join(faltas)
    if metricas.get("conjunto_teste") != "novo":
        return False, "A promoção exige um conjunto de teste novo. O teste da etapa 8 está consumido."
    comparacoes = (
        ("macro_f1_transicoes", criterios["limiares"]["macro_f1_transicoes_min"]),
        ("recall_falha", criterios["limiares"]["recall_falha_min"]),
        ("ganho_sobre_persistencia", criterios["limiares"]["ganho_sobre_persistencia_min"]),
        ("antecedencia_media_minutos", criterios["limiares"]["antecedencia_media_min_minutos"]),
    )
    for nome, piso in comparacoes:
        if nome not in metricas or float(metricas[nome]) < float(piso):
            return False, f"{nome} não atinge o piso {piso}."
    return True, "Critérios satisfeitos."


def promover(pasta: Path, versao: str, modelo_hash: str, metricas: dict, criterios: dict, quem: str, motivo: str) -> int:
    """Troca o ponteiro ATIVO. O joblib anterior permanece no disco."""
    ok, mensagem = satisfeitos(metricas, criterios)
    print(mensagem)
    if not ok:
        return 1
    pasta.mkdir(parents=True, exist_ok=True)
    anterior = _ler_ponteiro(pasta)
    novo = {
        "modelo_versao": versao,
        "modelo_hash": modelo_hash,
        "desde": _agora(),
        "quem": quem,
        "motivo": motivo,
    }
    (pasta / "ATIVO").write_text(json.dumps(novo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _historico(
        pasta,
        {"evento": "promocao", "quando": novo["desde"], "quem": quem, "motivo": motivo, "anterior": anterior, "novo": novo},
    )
    return 0


def ler_criterios(caminho: Path) -> dict:
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))
