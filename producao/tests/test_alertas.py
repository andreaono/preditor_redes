"""Alertas, promoção e rollback."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.alertas.avaliar import avaliar, carregar_regras, gerar
from src.modelo.promover import ler_criterios, promover
from src.modelo.rollback import rollback

AGORA = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def _relatorio_psi() -> dict:
    return {
        "arquivo": "relatorios/drift_2026-10-06.json",
        "importancia_permutacao": {"perda_pct": 0.4, "ttl_reset": 0.0},
        "janelas": [
            {
                "nome": "24h",
                "data_drift": {
                    "status": "alerta",
                    "features": {"perda_pct": {"psi": 0.4, "status": "alerta"}, "ttl_reset": {"psi": 0.4, "status": "alerta"}},
                },
                "predicao": {"status": "estavel", "js": 0.01},
                "fatias": [{"tipo": "anchor", "chave": 1, "n": 2, "status": "amostra_insuficiente"}],
            }
        ],
    }


def test_cooldown_nao_repete(tmp_path: Path):
    regras = carregar_regras()
    primeiro = avaliar(_relatorio_psi(), tmp_path, agora=AGORA, regras=regras)
    assert len(primeiro) == 1
    assert primeiro[0]["regra"] == "psi_feature_importante"
    assert primeiro[0]["gravidade"] == "media"
    segundo = avaliar(_relatorio_psi(), tmp_path, agora=AGORA + timedelta(hours=1), regras=regras)
    assert segundo == []
    terceiro = avaliar(_relatorio_psi(), tmp_path, agora=AGORA + timedelta(hours=25), regras=regras)
    assert len(terceiro) == 1


def test_macro_f1_so_com_janelas_seguidas():
    regras = carregar_regras()
    abaixo = {"macro_f1": 0.4, "status": "alerta"}
    acima = {"macro_f1": 0.8, "status": "estavel"}
    assert gerar(None, regras, [abaixo, abaixo], AGORA) == []
    alertas = gerar(None, regras, [abaixo, abaixo, abaixo], AGORA)
    assert [item["regra"] for item in alertas] == ["macro_f1"]
    assert alertas[0]["gravidade"] == "alta"
    assert gerar(None, regras, [abaixo, acima, abaixo], AGORA) == []


def test_fatia_insuficiente_nao_alerta():
    regras = carregar_regras()
    relatorio = {
        "importancia_permutacao": {"perda_pct": 1.0},
        "janelas": [
            {
                "nome": "24h",
                "data_drift": {"status": "amostra_insuficiente", "n": 2},
                "fatias": [{"status": "amostra_insuficiente", "n": 2}],
            }
        ],
    }
    assert gerar(relatorio, regras, agora=AGORA) == []


def test_promocao_recusada_e_rollback(tmp_path: Path):
    from src.ajustes import RAIZ

    vazios = ler_criterios(RAIZ / "config" / "criterios.yaml")
    metricas = {
        "conjunto_teste": "novo",
        "macro_f1_transicoes": 0.4,
        "recall_falha": 0.8,
        "ganho_sobre_persistencia": 0.05,
        "antecedencia_media_minutos": 8,
    }
    assert promover(tmp_path, "rf_v2", "sha256:novo", metricas, vazios, "teste", "nao deve promover") == 1
    assert not (tmp_path / "ATIVO").exists()
    completos = ler_criterios(RAIZ / "fixtures" / "criterios_demonstracao.yaml")
    (tmp_path / "ATIVO").write_text(
        '{"modelo_versao":"rf_v1.0.0","modelo_hash":"sha256:velho","quem":"etapa 8","motivo":"champion"}\n',
        encoding="utf-8",
    )
    fracas = dict(metricas, macro_f1_transicoes=0.01)
    assert promover(tmp_path, "rf_v2", "sha256:novo", fracas, completos, "teste", "abaixo do piso") == 1
    assert "rf_v1.0.0" in (tmp_path / "ATIVO").read_text(encoding="utf-8")
    assert promover(tmp_path, "rf_v2", "sha256:novo", metricas, completos, "teste", "venceu o champion") == 0
    assert "rf_v2" in (tmp_path / "ATIVO").read_text(encoding="utf-8")
    assert (tmp_path / "modelo_rf_v1.0.0.joblib").exists() is False
    assert rollback(tmp_path, "teste", "resultado pior no campo") == 0
    assert "rf_v1.0.0" in (tmp_path / "ATIVO").read_text(encoding="utf-8")
    historico = (tmp_path / "historico.jsonl").read_text(encoding="utf-8")
    assert "rollback" in historico
    assert "promocao" in historico
