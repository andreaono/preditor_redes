"""Drift sintético: estável, deslocado, fatia pequena e nulos."""

import numpy as np
import pandas as pd

from src.drift.calcular import avaliar_grupo
from src.drift.metricas import (
    divergencia_js,
    ks,
    proporcoes_nos_bins,
    psi,
    qui_quadrado,
    status_psi,
    taxa_nulos,
    bordas_quantis,
)

REGRAS = {
    "psi_estavel": 0.1,
    "psi_alerta": 0.25,
    "js_alerta": 0.1,
    "minimo_amostra": 30,
    "macro_f1_min": 0.60,
    "recall_falha_min": 0.50,
}


def _referencia(valores: np.ndarray) -> dict:
    bordas = bordas_quantis(valores, 10)
    return {
        "features": {
            "perda_pct": {
                "quantis": bordas.tolist(),
                "proporcao_bins": proporcoes_nos_bins(valores, bordas),
                "amostra": valores.tolist(),
                "taxa_nulos": 0.0,
            }
        },
        "proporcao_classes_previstas": {"OK": 0.8, "RISCO": 0.15, "FALHA": 0.05},
    }


def _quadro(valores: np.ndarray, classe: str = "OK") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "perda_pct": valores,
            "classe_prevista": [classe] * len(valores),
            "rotulo_real": ["OK"] * len(valores),
        }
    )


def test_sem_drift_psi_perto_de_zero():
    gerador = np.random.default_rng(42)
    valores = gerador.normal(0, 1, 400)
    assert psi(valores, valores) < 0.01
    assert status_psi(psi(valores, valores)) == "estavel"
    grupo = avaliar_grupo(_referencia(valores), _quadro(valores), REGRAS)
    assert grupo["data_drift"]["status"] == "estavel"
    assert grupo["data_drift"]["features"]["perda_pct"]["status"] == "estavel"


def test_drift_de_media_e_de_variancia():
    gerador = np.random.default_rng(42)
    base = gerador.normal(0, 1, 400)
    deslocada = base + 4
    assert psi(base, deslocada) > 0.25
    assert status_psi(psi(base, deslocada)) == "alerta"
    assert avaliar_grupo(_referencia(base), _quadro(deslocada), REGRAS)["data_drift"]["status"] == "alerta"
    espalhada = gerador.normal(0, 6, 400)
    assert ks(base, espalhada)["estatistica"] > 0.2
    assert psi(base, espalhada) > 0.25


def test_mudanca_de_proporcao_de_classes():
    valor = divergencia_js({"OK": 0.8, "RISCO": 0.15, "FALHA": 0.05}, {"OK": 0.1, "RISCO": 0.1, "FALHA": 0.8})
    assert valor > 0.1
    qui = qui_quadrado({"OK": 80, "RISCO": 15, "FALHA": 5}, {"OK": 10, "RISCO": 10, "FALHA": 80})
    assert qui["p_valor"] < 0.01
    gerador = np.random.default_rng(42)
    base = gerador.normal(0, 1, 80)
    grupo = avaliar_grupo(_referencia(base), _quadro(base, classe="FALHA"), REGRAS)
    assert grupo["predicao"]["status"] == "alerta"


def test_fatia_pequena_nao_e_alerta():
    grupo = avaliar_grupo(_referencia(np.array([0.0, 1.0, 2.0])), _quadro(np.array([10.0, 10.0, 10.0])), REGRAS)
    assert grupo["data_drift"]["status"] == "amostra_insuficiente"
    assert "features" not in grupo["data_drift"]


def test_nulos_em_excesso():
    gerador = np.random.default_rng(42)
    base = gerador.normal(0, 1, 80)
    atual = base.copy()
    atual[:40] = np.nan
    assert taxa_nulos(atual) == 0.5
    grupo = avaliar_grupo(_referencia(base), _quadro(atual), REGRAS)
    assert grupo["qualidade_dados"]["status"] == "alerta"
