"""Critérios vazios não congelam. Uma cópia completa congela e o hash trava."""

import json
from pathlib import Path

from src.congelar_criterios import ARQUIVO_LOCK, ARQUIVO_YAML, congelar, hash_arquivo, verificar

YAML_COMPLETO = """
modelo_versao: rf_v1.0.0
fatias: [geral, transicoes, por_continente, probe_vs_anchor, com_e_sem_anchor_dominante]
metricas:
  primarias: [macro_f1, recall_falha, ganho_sobre_persistencia]
  secundarias: [f1_por_classe, precisao, pr_auc, antecedencia]
limiares:
  macro_f1_transicoes_min: 0.25
  recall_falha_min: 0.50
  ganho_sobre_persistencia_min: 0.03
  antecedencia_media_min_minutos: 4
periodo_minimo_coleta_dias: 14
minimo_eventos_falha: 100
minimo_fluxos: 30
bootstrap:
  nivel: fluxo
  iteracoes: 1000
  seed: 42
  ic: 0.95
"""


def test_yaml_real_incompleto_e_recusado():
    assert not ARQUIVO_LOCK.exists()
    assert congelar(ARQUIVO_YAML, ARQUIVO_LOCK) == 1
    assert not ARQUIVO_LOCK.exists()


def test_congelamento_valido_e_hash_estavel(tmp_path: Path):
    yaml = tmp_path / "criterios.yaml"
    lock = tmp_path / "criterios.lock"
    yaml.write_text(YAML_COMPLETO, encoding="utf-8")
    primeiro = hash_arquivo(yaml)
    segundo = hash_arquivo(yaml)
    assert primeiro == segundo
    assert congelar(yaml, lock) == 0
    guardado = json.loads(lock.read_text(encoding="utf-8"))
    assert guardado["sha256"] == primeiro
    assert guardado["congelado_em"].endswith("Z")
    assert congelar(yaml, lock) == 0
    de_novo = json.loads(lock.read_text(encoding="utf-8"))
    assert de_novo == guardado
    assert verificar(yaml, lock) == 0


def test_mudanca_depois_do_freeze_falha(tmp_path: Path):
    yaml = tmp_path / "criterios.yaml"
    lock = tmp_path / "criterios.lock"
    yaml.write_text(YAML_COMPLETO, encoding="utf-8")
    assert congelar(yaml, lock) == 0
    hash_original = json.loads(lock.read_text(encoding="utf-8"))["sha256"]
    yaml.write_text(YAML_COMPLETO + "\n# alterado\n", encoding="utf-8")
    assert verificar(yaml, lock) == 1
    assert congelar(yaml, lock) == 1
    assert json.loads(lock.read_text(encoding="utf-8"))["sha256"] == hash_original


def test_lock_ausente_falha(tmp_path: Path):
    yaml = tmp_path / "criterios.yaml"
    yaml.write_text(YAML_COMPLETO, encoding="utf-8")
    assert verificar(yaml, tmp_path / "nao_existe.lock") == 1
