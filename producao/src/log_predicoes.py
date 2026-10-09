"""Acrescenta previsões e, depois, o rótulo da medição seguinte."""

import json
from pathlib import Path

from src.ajustes import CAMPOS_LOG
from src.esquema import texto_jsonl


def anexar(caminho: Path, linha: dict) -> None:
    """Grava uma previsão. Não reescreve linhas antigas."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("a", encoding="utf-8") as arquivo:
        arquivo.write(texto_jsonl(linha) + "\n")


def completar_rotulo(caminho: Path, run_id: str, fluxo_id: str, ts_previsao: str, rotulo_real: str, ts_rotulo: str) -> dict:
    """Preenche rotulo_real da previsão já gravada. Não mexe nas features."""
    if not caminho.is_file():
        raise FileNotFoundError(caminho)
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    atualizada = None
    saida: list[str] = []
    for texto in linhas:
        if not texto.strip():
            continue
        item = json.loads(texto)
        combina = (
            atualizada is None
            and item.get("run_id") == run_id
            and item.get("fluxo_id") == fluxo_id
            and item.get("ts_previsao") == ts_previsao
            and item.get("rotulo_real") is None
        )
        if combina:
            item["rotulo_real"] = rotulo_real
            item["ts_rotulo"] = ts_rotulo
            if tuple(item) != CAMPOS_LOG:
                raise ValueError("A linha deixaria de seguir o contrato.")
            atualizada = item
        saida.append(texto_jsonl(item))
    if atualizada is None:
        raise LookupError("Não há previsão sem rótulo com essa chave.")
    caminho.write_text("\n".join(saida) + "\n", encoding="utf-8")
    return atualizada
