"""Medidas de drift. Funções puras: a mesma entrada devolve a mesma saída."""

import math

import numpy as np
from scipy.spatial.distance import jensenshannon
from scipy.stats import chisquare, ks_2samp

EPSILON = 1e-6


def _finitos(valores) -> np.ndarray:
    vetor = np.asarray(valores, dtype=float)
    if vetor.ndim == 0:
        vetor = np.asarray([valores], dtype=float)
    return vetor[np.isfinite(vetor)]


def bordas_quantis(referencia, bins: int = 10) -> np.ndarray:
    """Bordas pelos quantis da referência. Quantis repetidos viram uma borda só."""
    referencia = _finitos(referencia)
    if referencia.size == 0:
        return np.array([])
    quantis = np.linspace(0, 1, bins + 1)
    return np.unique(np.quantile(referencia, quantis))


def _proporcoes(valores, bordas: np.ndarray) -> np.ndarray:
    if bordas.size < 2:
        return np.array([1.0])
    indices = np.digitize(valores, bordas[1:-1], right=False)
    contagem = np.bincount(indices, minlength=bordas.size - 1).astype(float)
    contagem = np.maximum(contagem, EPSILON)
    return contagem / contagem.sum()


def proporcoes_nos_bins(valores, bordas) -> list[float]:
    """Proporção da referência em cada faixa, já com piso contra zero."""
    limites = np.asarray(bordas, dtype=float)
    observados = _finitos(valores)
    if limites.size < 2 or observados.size == 0:
        return []
    return [float(item) for item in _proporcoes(observados, limites)]


def psi_com_referencia(proporcao_ref, atual, bordas) -> float:
    """PSI quando a referência já está resumida em bordas e proporções."""
    observado = _finitos(atual)
    limites = np.asarray(list(bordas), dtype=float)
    esperado = np.asarray(list(proporcao_ref), dtype=float)
    if observado.size == 0:
        return float("nan")
    if limites.size < 2:
        if limites.size == 1 and np.all(observado == limites[0]):
            return 0.0
        return 1.0
    if esperado.size == 0:
        return float("nan")
    visto = _proporcoes(observado, limites)
    if visto.size != esperado.size:
        return float("nan")
    esperado = np.maximum(esperado, EPSILON)
    esperado = esperado / esperado.sum()
    return float(np.sum((visto - esperado) * np.log(visto / esperado)))


def psi(ref, atual, bins: int = 10, bordas=None) -> float:
    """PSI com as bordas da referência e piso nas proporções zeradas."""
    referencia = _finitos(ref)
    observado = _finitos(atual)
    if referencia.size == 0 or observado.size == 0:
        return float("nan")
    limites = np.asarray(bordas, dtype=float) if bordas is not None else bordas_quantis(referencia, bins)
    if limites.size < 2:
        valor = float(limites[0]) if limites.size == 1 else float("nan")
        if not math.isfinite(valor):
            return float("nan")
        return 0.0 if np.all(observado == valor) else 1.0
    esperado = _proporcoes(referencia, limites)
    visto = _proporcoes(observado, limites)
    return float(np.sum((visto - esperado) * np.log(visto / esperado)))


def ks(ref, atual) -> dict:
    """Estatística de Kolmogorov-Smirnov e o p-valor."""
    referencia = _finitos(ref)
    observado = _finitos(atual)
    if referencia.size == 0 or observado.size == 0:
        return {"estatistica": None, "p_valor": None}
    estatistica, p_valor = ks_2samp(referencia, observado)
    return {"estatistica": float(estatistica), "p_valor": float(p_valor)}


def qui_quadrado(ref_contagens: dict, atual_contagens: dict) -> dict:
    """Aderência das contagens atuais à proporção de referência."""
    chaves = list(ref_contagens)
    referencia = np.array([float(ref_contagens.get(chave, 0)) for chave in chaves], dtype=float)
    atual = np.array([float(atual_contagens.get(chave, 0)) for chave in chaves], dtype=float)
    if referencia.sum() <= 0 or atual.sum() <= 0:
        return {"estatistica": None, "p_valor": None}
    esperado = referencia / referencia.sum() * atual.sum()
    esperado = np.maximum(esperado, EPSILON)
    estatistica, p_valor = chisquare(atual, esperado)
    return {"estatistica": float(estatistica), "p_valor": float(p_valor)}


def divergencia_js(ref_proporcao: dict, atual_proporcao: dict) -> float:
    """Divergência de Jensen-Shannon, entre 0 e 1, base 2."""
    chaves = list(ref_proporcao)
    referencia = np.array([float(ref_proporcao.get(chave, 0)) for chave in chaves], dtype=float)
    atual = np.array([float(atual_proporcao.get(chave, 0)) for chave in chaves], dtype=float)
    if referencia.sum() <= 0 or atual.sum() <= 0:
        return float("nan")
    referencia = referencia / referencia.sum()
    atual = atual / atual.sum()
    distancia = jensenshannon(referencia, atual, base=2)
    if not math.isfinite(distancia):
        return float("nan")
    return float(distancia**2)


def taxa_nulos(valores) -> float:
    """Fração de ausentes. A sentinela -1 é valor, não nulo."""
    vetor = np.asarray(valores, dtype=float)
    if vetor.ndim == 0:
        vetor = np.asarray([valores], dtype=float)
    if vetor.size == 0:
        return float("nan")
    return float(np.mean(~np.isfinite(vetor)))


def status_psi(valor: float, estavel: float = 0.1, alerta: float = 0.25) -> str:
    """PSI abaixo de 0,1 é estável; até 0,25 é atenção; acima é alerta."""
    if valor is None or not math.isfinite(valor):
        return "amostra_insuficiente"
    if valor < estavel:
        return "estavel"
    if valor <= alerta:
        return "atencao"
    return "alerta"
