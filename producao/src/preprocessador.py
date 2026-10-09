"""O treino não ajustou scaler. A sentinela -1 já vem do cálculo das features.

Esta classe só coloca as colunas na ordem em que o modelo foi treinado.
"""

import numpy as np

from src.esquema import validar_features


class PreprocessadorIdentidade:
    """Devolve a matriz 1×n na ordem gravada no artefato."""

    def __init__(self, colunas: list[str]):
        self.colunas = list(colunas)

    def transformar(self, features: dict) -> tuple[np.ndarray, dict[str, float]]:
        ordenadas = validar_features(features)
        vetor = np.asarray([[ordenadas[nome] for nome in self.colunas]], dtype=float)
        return vetor, ordenadas
