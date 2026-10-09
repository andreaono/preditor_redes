"""Caminhos e parâmetros lidos de config/producao.yaml."""

from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[1]
ARQUIVO_YAML = RAIZ / "config" / "producao.yaml"
CAMPOS_LOG = (
    "run_id",
    "ts_previsao",
    "fluxo_id",
    "anchor_id",
    "modelo_versao",
    "modelo_hash",
    "features",
    "proba",
    "classe_prevista",
    "classe_atual",
    "latencia_inferencia_ms",
    "rotulo_real",
    "ts_rotulo",
)


def carregar() -> dict:
    """Lê o YAML e resolve os caminhos a partir de producao/."""
    documento = yaml.safe_load(ARQUIVO_YAML.read_text(encoding="utf-8"))
    documento["arquivo_modelo"] = (RAIZ / documento["arquivo_modelo"]).resolve()
    documento["arquivo_metadados_modelo"] = (RAIZ / documento["arquivo_metadados_modelo"]).resolve()
    documento["pasta_logs"] = (RAIZ / documento["pasta_logs"]).resolve()
    documento["classes"] = tuple(documento["classes"])
    return documento
