"""Confere um período do log de predições e imprime PASSOU, FALHOU ou ATENCAO."""

import argparse
import json
from pathlib import Path

from src.ajustes import CAMPOS_LOG, RAIZ, carregar
from src.features_treino import nomes_features
from src.log.predicoes import TOLERANCIA_PROBA


def _linhas(pasta: Path, inicio: str | None, fim: str | None) -> list[dict]:
    achados: list[dict] = []
    for arquivo in sorted(Path(pasta).glob("*.jsonl")):
        for texto in arquivo.read_text(encoding="utf-8").splitlines():
            if not texto.strip():
                continue
            item = json.loads(texto)
            data = str(item.get("ts_previsao", ""))[:10]
            if inicio and data < inicio:
                continue
            if fim and data > fim:
                continue
            achados.append(item)
    return achados


def avaliar(linhas: list[dict], minimo_rotulo: float = 0.5) -> tuple[str, list[str]]:
    """Devolve o veredito e os motivos. ATENCAO não é falha de contrato."""
    motivos: list[str] = []
    falhou = False
    classes = set(carregar()["classes"])
    vistas: set[tuple] = set()
    nomes = nomes_features()
    nulos = {nome: 0 for nome in nomes}
    with_rotulo = 0
    for item in linhas:
        if tuple(item.keys()) != CAMPOS_LOG:
            falhou = True
            motivos.append("campos obrigatorios fora do contrato")
            continue
        chave = (item["run_id"], item["fluxo_id"], item["ts_previsao"])
        if chave in vistas:
            falhou = True
            motivos.append("duplicata")
        vistas.add(chave)
        if item["classe_prevista"] not in classes or item["classe_atual"] not in classes:
            falhou = True
            motivos.append("classe invalida")
        proba = item.get("proba") or {}
        if set(proba) != classes or abs(sum(float(valor) for valor in proba.values()) - 1) > TOLERANCIA_PROBA:
            falhou = True
            motivos.append("proba nao soma 1")
        if item["rotulo_real"] is not None:
            with_rotulo += 1
            if item["rotulo_real"] not in classes:
                falhou = True
                motivos.append("rotulo_real invalido")
        for nome in nomes:
            valor = (item.get("features") or {}).get(nome)
            if valor is None:
                nulos[nome] += 1
    if not linhas:
        return "ATENCAO", ["periodo sem previsoes"]
    fracao = with_rotulo / len(linhas)
    if fracao < minimo_rotulo:
        motivos.append(f"rotulo_real preenchido em {fracao:.0%}")
    nulos_altos = [nome for nome, quantidade in nulos.items() if quantidade]
    if nulos_altos:
        motivos.append("nulos em " + ", ".join(nulos_altos))
    if falhou:
        return "FALHOU", motivos
    if motivos:
        return "ATENCAO", motivos
    return "PASSOU", []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Valida o log de predições de um período.")
    parser.add_argument("--pasta", default=str(RAIZ / "logs" / "predicoes"))
    parser.add_argument("--inicio", default=None)
    parser.add_argument("--fim", default=None)
    args = parser.parse_args(argv)
    veredito, motivos = avaliar(_linhas(Path(args.pasta), args.inicio, args.fim))
    print(veredito)
    for motivo in motivos:
        print(motivo)
    return 1 if veredito == "FALHOU" else 0


if __name__ == "__main__":
    raise SystemExit(main())
