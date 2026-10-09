"""Testes do contrato de produção. Não leem o split de teste."""

import json

import pytest

from src.ajustes import CAMPOS_LOG, carregar
from src.esquema import linha_log, texto_jsonl, validar_features
from src.features_treino import grupos, nomes_features
from src.log_predicoes import anexar, completar_rotulo


def features_validas() -> dict[str, float]:
    return {nome: -1.0 for nome in nomes_features()}


def test_grupos_cobrem_a_lista_oficial():
    partes = grupos()
    juntas = partes["instantanea"] + partes["janela"] + partes["dinamica"]
    assert juntas == nomes_features()
    assert len(juntas) == len(set(juntas))


def test_features_do_modelo_coincidem_com_a_etapa7():
    ajustes = carregar()
    metadados = json.loads(ajustes["arquivo_metadados_modelo"].read_text(encoding="utf-8"))
    assert metadados["features"] == nomes_features()


def test_rotulo_nao_entra_nas_features():
    features = features_validas()
    features["alvo"] = "FALHA"
    with pytest.raises(ValueError, match="alvo"):
        validar_features(features)


def test_linha_nasce_sem_rotulo_real():
    linha = linha_log(
        run_id="2026-10-05T14:00:00Z-01",
        ts_previsao="2026-10-05T14:00:00Z",
        fluxo_id="1016806_3679",
        anchor_id=3679,
        modelo_versao="rf_v1.0.0",
        modelo_hash="sha256:teste",
        features=features_validas(),
        proba={"OK": 0.91, "RISCO": 0.07, "FALHA": 0.02},
        classe_prevista="OK",
        classe_atual="OK",
        latencia_inferencia_ms=4,
    )
    assert tuple(linha) == CAMPOS_LOG
    assert linha["rotulo_real"] is None
    assert linha["ts_rotulo"] is None
    recarregada = json.loads(texto_jsonl(linha))
    assert recarregada["anchor_id"] == 3679


def test_rotulo_posterior_nao_altera_features(tmp_path):
    caminho = tmp_path / "predicoes.jsonl"
    features = features_validas()
    linha = linha_log(
        run_id="r1",
        ts_previsao="2026-10-05T14:00:00Z",
        fluxo_id="1016806_3679",
        anchor_id=3679,
        modelo_versao="rf_v1.0.0",
        modelo_hash="sha256:teste",
        features=features,
        proba={"OK": 1.0, "RISCO": 0.0, "FALHA": 0.0},
        classe_prevista="OK",
        classe_atual="OK",
        latencia_inferencia_ms=1,
    )
    anexar(caminho, linha)
    atualizada = completar_rotulo(
        caminho,
        "r1",
        "1016806_3679",
        "2026-10-05T14:00:00Z",
        "RISCO",
        "2026-10-05T14:04:00Z",
    )
    assert atualizada["rotulo_real"] == "RISCO"
    assert atualizada["features"] == features
    assert atualizada["classe_prevista"] == "OK"
