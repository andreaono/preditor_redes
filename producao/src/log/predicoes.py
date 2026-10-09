"""Grava o contrato de predição em JSONL e em Parquet particionado por data.

Linha inválida vai para a quarentena e não entra no arquivo de previsão.
O rótulo tardio atualiza a mesma chave, sem duplicar e sem apagar as outras.
"""

import json
import os
import time
from pathlib import Path

import pandas as pd

from src.ajustes import CAMPOS_LOG, carregar
from src.esquema import texto_jsonl

TOLERANCIA_PROBA = 1e-6


class RecusaContrato(ValueError):
    """A linha não segue o contrato."""


def _trava(pasta: Path):
    """Trava exclusiva por arquivo. Duas escritas esperam a vez."""
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / ".escrita.lock"
    for _ in range(200):
        try:
            descritor = os.open(caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descritor, str(os.getpid()).encode("ascii"))
            os.close(descritor)
            return caminho
        except FileExistsError:
            time.sleep(0.01)
    raise TimeoutError("Não consegui a trava do log de predições.")


def _solta(caminho: Path) -> None:
    if caminho.is_file():
        caminho.unlink()


def conferir_linha(linha: dict) -> dict:
    """Recusa chave fora de ordem, classe inválida ou probabilidade que não soma 1."""
    try:
        texto_jsonl(linha)
    except ValueError as erro:
        raise RecusaContrato(str(erro)) from erro
    classes = carregar()["classes"]
    if linha["classe_prevista"] not in classes or linha["classe_atual"] not in classes:
        raise RecusaContrato("Classe fora de OK, RISCO e FALHA.")
    if linha["rotulo_real"] is not None and linha["rotulo_real"] not in classes:
        raise RecusaContrato("rotulo_real fora do conjunto.")
    proba = linha["proba"]
    if set(proba) != set(classes):
        raise RecusaContrato("proba precisa ter OK, RISCO e FALHA.")
    if abs(sum(float(valor) for valor in proba.values()) - 1) > TOLERANCIA_PROBA:
        raise RecusaContrato("A soma de proba não é 1.")
    if not linha["modelo_versao"] or not str(linha["modelo_hash"]).startswith("sha256:"):
        raise RecusaContrato("modelo_versao e modelo_hash vêm do manifesto.")
    return linha


def _data_da_linha(linha: dict) -> str:
    return str(linha["ts_previsao"])[:10]


def _arquivo_parquet(pasta: Path, data: str) -> Path:
    return Path(pasta) / f"data={data}.parquet"


def _ler_particao(caminho: Path) -> list[dict]:
    if not caminho.is_file():
        return []
    quadro = pd.read_parquet(caminho)
    linhas = []
    for bruto in quadro.to_dict(orient="records"):
        item = dict(bruto)
        item["features"] = json.loads(item["features"])
        item["proba"] = json.loads(item["proba"])
        if item["rotulo_real"] is None or (isinstance(item["rotulo_real"], float) and pd.isna(item["rotulo_real"])):
            item["rotulo_real"] = None
        if item["ts_rotulo"] is None or (isinstance(item["ts_rotulo"], float) and pd.isna(item["ts_rotulo"])):
            item["ts_rotulo"] = None
        item["anchor_id"] = int(item["anchor_id"])
        item["latencia_inferencia_ms"] = int(item["latencia_inferencia_ms"])
        linhas.append({chave: item[chave] for chave in CAMPOS_LOG})
    return linhas


def _gravar_particao(caminho: Path, linhas: list[dict]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    registros = []
    for linha in linhas:
        registros.append(
            {
                **{chave: linha[chave] for chave in CAMPOS_LOG if chave not in ("features", "proba")},
                "features": json.dumps(linha["features"], ensure_ascii=False),
                "proba": json.dumps(linha["proba"], ensure_ascii=False),
                "data": _data_da_linha(linha),
            }
        )
    quadro = pd.DataFrame(registros)
    temporario = caminho.with_suffix(".tmp.parquet")
    quadro.to_parquet(temporario, index=False)
    temporario.replace(caminho)


def _anexar_jsonl(destino: Path, linha: dict) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("a", encoding="utf-8") as arquivo:
        arquivo.write(texto_jsonl(linha) + "\n")


def _quarentena(pasta: Path, linha: dict, motivo: str) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / "contrato.jsonl"
    with destino.open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps({"motivo": motivo, "linha": linha}, ensure_ascii=False, default=str) + "\n")


def gravar(linha: dict, destino_jsonl: Path, pasta_parquet: Path, pasta_quarentena: Path) -> bool:
    """Valida e grava. Devolve False se a linha foi para a quarentena."""
    try:
        conferir_linha(linha)
    except RecusaContrato as erro:
        _quarentena(pasta_quarentena, linha, str(erro))
        return False
    trava = _trava(pasta_parquet)
    try:
        particao = _arquivo_parquet(pasta_parquet, _data_da_linha(linha))
        linhas = _ler_particao(particao)
        chave = (linha["run_id"], linha["fluxo_id"], linha["ts_previsao"])
        if any((item["run_id"], item["fluxo_id"], item["ts_previsao"]) == chave for item in linhas):
            return True
        linhas.append(linha)
        _gravar_particao(particao, linhas)
        _anexar_jsonl(destino_jsonl, linha)
    finally:
        _solta(trava)
    return True


def registrar_rotulo(
    chave: dict,
    rotulo_real: str,
    ts_rotulo: str,
    destino_jsonl: Path,
    pasta_parquet: Path,
) -> dict:
    """Preenche o rótulo da chave. Não cria outra linha e não altera as features."""
    classes = carregar()["classes"]
    if rotulo_real not in classes:
        raise RecusaContrato("rotulo_real fora do conjunto.")
    trava = _trava(pasta_parquet)
    try:
        data = str(chave["ts_previsao"])[:10]
        particao = _arquivo_parquet(pasta_parquet, data)
        linhas = _ler_particao(particao)
        atualizada = None
        for item in linhas:
            combina = (
                item["run_id"] == chave["run_id"]
                and item["fluxo_id"] == chave["fluxo_id"]
                and item["ts_previsao"] == chave["ts_previsao"]
            )
            if combina and atualizada is None and item["rotulo_real"] is None:
                item["rotulo_real"] = rotulo_real
                item["ts_rotulo"] = ts_rotulo
                atualizada = dict(item)
        if atualizada is None:
            raise LookupError("Não há previsão sem rótulo com essa chave.")
        _gravar_particao(particao, linhas)
        if destino_jsonl.is_file():
            from src.log_predicoes import completar_rotulo

            completar_rotulo(
                destino_jsonl,
                chave["run_id"],
                chave["fluxo_id"],
                chave["ts_previsao"],
                rotulo_real,
                ts_rotulo,
            )
        return atualizada
    finally:
        _solta(trava)


def exportar_jsonl(pasta_parquet: Path, destino: Path, inicio: str | None = None, fim: str | None = None) -> int:
    """Exporta o Parquet no contrato, para a interface de testes."""
    arquivos = sorted(Path(pasta_parquet).glob("data=*.parquet"))
    quantidade = 0
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8") as arquivo:
        for caminho in arquivos:
            for linha in _ler_particao(caminho):
                data = _data_da_linha(linha)
                if inicio and data < inicio:
                    continue
                if fim and data > fim:
                    continue
                arquivo.write(texto_jsonl(linha) + "\n")
                quantidade += 1
    return quantidade


def manifesto_versao() -> tuple[str, str]:
    """Versão e hash gravados no empacotamento."""
    from src.ajustes import RAIZ

    documento = json.loads((RAIZ / "modelo" / "modelo_manifest.json").read_text(encoding="utf-8"))
    return documento["modelo_versao"], documento["sha256"]
