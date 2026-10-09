"""Hash do artefato, ordem das colunas e reprodução da amostra de treino."""

import json
from pathlib import Path

import joblib
import pytest

from src.carregar_modelo import _carregar_cacheado, carregar_modelo
from src.empacotar_modelo import CHAVES_MANIFESTO
from src.features_treino import nomes_features
from src.prever import hash_arquivo
from src.verificar_artefato import ARQUIVO_AMOSTRA, ARQUIVO_ARTEFATO, conferir

MANIFESTO = ARQUIVO_ARTEFATO.parent / "modelo_manifest.json"


def test_hash_correto_e_hash_adulterado(tmp_path: Path):
    arquivo = tmp_path / "modelo.joblib"
    joblib.dump({"colunas_features": ["a"]}, arquivo)
    manifesto = tmp_path / "modelo_manifest.json"
    manifesto.write_text(
        json.dumps({"sha256": hash_arquivo(arquivo), "colunas_features": ["a"], "versoes_bibliotecas": {}}),
        encoding="utf-8",
    )
    assert carregar_modelo(arquivo, manifesto)["colunas_features"] == ["a"]
    _carregar_cacheado.cache_clear()
    manifesto.write_text(
        json.dumps({"sha256": "sha256:0", "colunas_features": ["a"], "versoes_bibliotecas": {}}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="não confere"):
        carregar_modelo(arquivo, manifesto)


def test_manifesto_completo_ordem_e_amostra():
    documento = json.loads(MANIFESTO.read_text(encoding="utf-8"))
    faltando = [chave for chave in CHAVES_MANIFESTO if chave not in documento]
    assert not faltando
    artefato = carregar_modelo(ARQUIVO_ARTEFATO, MANIFESTO)
    assert artefato["colunas_features"] == nomes_features()
    assert documento["colunas_features"] == nomes_features()
    assert documento["amostra"]["split"] == "treino"
    assert documento["amostra"]["teste_nao_lido"] is True
    assert conferir(ARQUIVO_AMOSTRA, ARQUIVO_ARTEFATO) == 0
