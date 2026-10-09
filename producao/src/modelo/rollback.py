"""Restaura o ponteiro anterior. A troca fica no histórico."""

import json
from datetime import datetime, timezone
from pathlib import Path


def _agora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rollback(pasta: Path, quem: str, motivo: str) -> int:
    """Volta o ATIVO para a versão de antes da última promoção."""
    historico = pasta / "historico.jsonl"
    ponteiro = pasta / "ATIVO"
    if not historico.is_file() or not ponteiro.is_file():
        print("Não há promoção anterior para desfazer.")
        return 1
    eventos = [json.loads(linha) for linha in historico.read_text(encoding="utf-8").splitlines() if linha.strip()]
    promocoes = [item for item in eventos if item.get("evento") == "promocao" and item.get("anterior")]
    if not promocoes:
        print("Não há versão anterior registrada.")
        return 1
    anterior = promocoes[-1]["anterior"]
    ponteiro.write_text(json.dumps(anterior, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evento = {
        "evento": "rollback",
        "quando": _agora(),
        "quem": quem,
        "motivo": motivo,
        "restaurado": anterior,
    }
    with historico.open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(evento, ensure_ascii=False) + "\n")
    print(f"Restaurado {anterior.get('modelo_versao')}.")
    return 0
