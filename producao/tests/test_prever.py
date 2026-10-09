"""Uma previsão com o modelo congelado, sem usar o conjunto de teste."""

import json

from src.esquema import agora_utc
from src.features_treino import nomes_features
from src.prever import prever


def test_previsao_do_modelo_congelado(tmp_path):
    features = {nome: -1.0 for nome in nomes_features()}
    destino = tmp_path / "uma.jsonl"
    linha = prever(
        features,
        fluxo_id="1016806_3679",
        anchor_id=3679,
        classe_atual="OK",
        run_id="2026-10-05T14:00:00Z-01",
        ts_previsao="2026-10-05T14:00:00Z",
        caminho_log=destino,
        modelo_hash="sha256:teste",
    )
    assert linha["classe_prevista"] in {"OK", "RISCO", "FALHA"}
    assert set(linha["proba"]) == {"OK", "RISCO", "FALHA"}
    assert abs(sum(linha["proba"].values()) - 1) < 1e-6
    assert linha["rotulo_real"] is None
    assert linha["features"]["perda_pct"] == -1.0
    gravada = json.loads(destino.read_text(encoding="utf-8"))
    assert gravada["classe_prevista"] == linha["classe_prevista"]
    assert agora_utc().endswith("Z")
