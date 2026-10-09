"""Reproduz a amostra de treino com o artefato empacotado.

A amostra não contém o split de teste. A igualdade pedida é a da classe prevista.
"""

import sys
from pathlib import Path

import pandas as pd

from src.ajustes import RAIZ
from src.carregar_modelo import carregar_modelo
from src.features_treino import nomes_features

ARQUIVO_AMOSTRA = RAIZ / "modelo" / "predicoes_amostra.csv"
ARQUIVO_ARTEFATO = RAIZ / "modelo" / "modelo_rf_v1.0.0.joblib"


def conferir(caminho_amostra: Path = ARQUIVO_AMOSTRA, caminho_artefato: Path = ARQUIVO_ARTEFATO) -> int:
    """Carrega o artefato e compara a classe de cada linha da amostra."""
    if not caminho_amostra.is_file():
        print(f"Amostra ausente: {caminho_amostra}")
        return 1
    artefato = carregar_modelo(caminho_artefato)
    features = nomes_features()
    tabela = pd.read_csv(caminho_amostra)
    if set(tabela["split"]) != {"treino"}:
        print("A amostra não está restrita ao split treino.")
        return 1
    if list(artefato["colunas_features"]) != features:
        print("A ordem das colunas do artefato mudou.")
        return 1
    vetor = tabela[features].astype(float).to_numpy()
    previstas = [str(item) for item in artefato["modelo"].predict(vetor)]
    gravadas = [str(item) for item in tabela["classe_prevista"]]
    if previstas != gravadas:
        print("As classes do artefato divergem da amostra gravada no empacotamento.")
        return 1
    print(f"Amostra conferida: {len(gravadas)} classes iguais às do joblib original.")
    return 0


def main() -> int:
    return conferir()


if __name__ == "__main__":
    raise SystemExit(main())
