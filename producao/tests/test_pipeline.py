"""Pipeline offline: válido, inválido, aquecimento, timeout, API fora e repetição."""

import json
import os
from pathlib import Path

import yaml

from src.congelar_criterios import congelar
from src.contrato import ErroColeta, classificar_item
from src.rodar import executar, processo_vivo

BASE = 1791136846
FIM = BASE + 11 * 240 + 1
YAML_COMPLETO = Path(__file__).resolve().parents[1].joinpath("fixtures", "criterios_demonstracao.yaml").read_text(encoding="utf-8")


def ping(timestamp, probe=1016806, msm=66198951, avg=59.0):
    return {
        "timestamp": timestamp,
        "prb_id": probe,
        "msm_id": msm,
        "sent": 3,
        "rcvd": 3,
        "min": avg - 0.4,
        "max": avg + 0.3,
        "avg": avg,
        "ttl": 56,
        "result": [{"rtt": avg - 0.4}, {"rtt": avg}, {"rtt": avg + 0.3}],
    }


def serie_valida():
    return [ping(BASE + i * 240) for i in range(12)]


def preparar(tmp_path: Path, medicoes: dict) -> Path:
    yaml_criterios = tmp_path / "criterios.yaml"
    lock = tmp_path / "criterios.lock"
    yaml_criterios.write_text(YAML_COMPLETO, encoding="utf-8")
    assert congelar(yaml_criterios, lock) == 0
    pasta = tmp_path / "medicoes"
    pasta.mkdir()
    for medicao_id, itens in medicoes.items():
        (pasta / f"{medicao_id}.json").write_text(json.dumps(itens), encoding="utf-8")
    pares = tmp_path / "pares.json"
    pares.write_text(
        json.dumps(
            {
                "pares": [
                    {"fluxo_id": "1016806_3679", "probe_id": 1016806, "anchor_id": 3679, "measurement_id": 66198951},
                    {"fluxo_id": "999001_3679", "probe_id": 999001, "anchor_id": 3679, "measurement_id": 90000001},
                ]
            }
        ),
        encoding="utf-8",
    )
    raiz = Path(__file__).resolve().parents[1]
    config = {
        "janela_minutos": 60,
        "intervalo_medicao_s": 240,
        "minimo_medicoes_historico": 12,
        "historico_maximo": 48,
        "pares": str(pares),
        "criterios": str(yaml_criterios),
        "lock": str(lock),
        "url_resultados": "https://atlas.ripe.net/api/v2/measurements/{id}/results/",
        "timeout_s": 5,
        "max_tentativas": 2,
        "backoff_s": 0.01,
        "pausa_s": 0,
        "user_agent": "teste",
        "pasta_logs": str(tmp_path / "logs"),
        "pasta_quarentena": str(tmp_path / "quarentena"),
        "pasta_estado": str(tmp_path / "estado"),
        "pasta_erros": str(tmp_path / "erros"),
        "pasta_coleta": str(tmp_path / "coleta"),
        "arquivo_baseline": str(raiz.parent / "pipeline" / "06_baseline" / "data" / "baseline_rotulacao_por_fluxo.csv"),
        "arquivo_artefato": str(raiz / "modelo" / "modelo_rf_v1.0.0.joblib"),
        "arquivo_lock_execucao": str(tmp_path / "execucao.lock"),
    }
    destino = tmp_path / "pipeline.yaml"
    destino.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return destino


def test_timeout_nao_e_latencia_negativa():
    item = ping(BASE)
    item["avg"] = -1
    item["min"] = -1
    item["max"] = -1
    item["rcvd"] = 0
    item["result"] = [{"x": "*"}, {"x": "*"}, {"x": "*"}]
    classificado = classificar_item(item, 1016806)
    assert classificado["situacao"] == "timeout"
    assert classificado["perda_num"] == 100
    assert classificado["latencia_num"] != classificado["latencia_num"]
    ruim = ping(BASE + 1)
    ruim["avg"] = -5
    ruim["min"] = -5
    ruim["max"] = -5
    ruim["result"] = [{"rtt": -5}, {"rtt": -5}, {"rtt": -5}]
    assert classificar_item(ruim, 1016806)["situacao"] == "invalida"
    assert classificar_item({"prb_id": 1016806, "offline": True}, 1016806)["situacao"] == "probe_offline"


def test_rodar_offline_valido_invalido_e_aquecimento(tmp_path: Path):
    invalida = ping(BASE + 3)
    invalida["avg"] = -5
    invalida["min"] = -5
    invalida["max"] = -5
    invalida["result"] = [{"rtt": -5}, {"rtt": -5}, {"rtt": -5}]
    curto = [ping(BASE, probe=999001, msm=90000001), ping(BASE + 240, probe=999001, msm=90000001)]
    config = preparar(tmp_path, {"66198951": serie_valida() + [invalida], "90000001": curto})
    assert executar(config, offline=tmp_path / "medicoes", ate=FIM) == 0
    logs = list((tmp_path / "logs").glob("*.jsonl"))
    assert len(logs) == 1
    linhas = [json.loads(texto) for texto in logs[0].read_text(encoding="utf-8").splitlines() if texto.strip()]
    assert len(linhas) == 1
    linha = linhas[0]
    assert linha["fluxo_id"] == "1016806_3679"
    assert linha["classe_prevista"] in ("OK", "RISCO", "FALHA")
    assert linha["rotulo_real"] is None
    assert abs(sum(linha["proba"].values()) - 1) < 1e-9
    assert set(linha["proba"]) == {"OK", "RISCO", "FALHA"}
    estado_curto = json.loads((tmp_path / "estado" / "999001_3679.json").read_text(encoding="utf-8"))
    assert estado_curto["estado"] == "aquecimento"
    assert not (tmp_path / "logs").joinpath("999001_3679.jsonl").exists()
    quarentena = (tmp_path / "quarentena").joinpath(logs[0].name).read_text(encoding="utf-8")
    assert "latencia_negativa" in quarentena
    historico = json.loads((tmp_path / "estado" / "1016806_3679.json").read_text(encoding="utf-8"))
    assert all(item["timestamp"] != invalida["timestamp"] for item in historico["medicoes"])
    assert executar(config, offline=tmp_path / "medicoes", ate=FIM) == 0
    de_novo = [texto for texto in logs[0].read_text(encoding="utf-8").splitlines() if texto.strip()]
    assert len(de_novo) == 1


def test_api_fora_nao_corrompe_estado(tmp_path: Path):
    config = preparar(tmp_path, {})
    estado = tmp_path / "estado" / "1016806_3679.json"
    estado.parent.mkdir()
    estado.write_text('{"fluxo_id":"1016806_3679","medicoes":[],"baseline":null}\n', encoding="utf-8")
    antes = estado.read_bytes()

    def transporte(*_args):
        raise ErroColeta("api_indisponivel", "sem rede")

    assert executar(config, transporte=transporte, ate=FIM) == 1
    assert estado.read_bytes() == antes
    erros = list((tmp_path / "erros").glob("*.jsonl"))
    assert erros and "sem rede" in erros[0].read_text(encoding="utf-8")


def test_lock_de_execucao_impede_sobreposicao(tmp_path: Path):
    config = preparar(tmp_path, {"66198951": serie_valida(), "90000001": []})
    lock = tmp_path / "execucao.lock"
    lock.write_text(str(os.getpid()), encoding="utf-8")
    assert processo_vivo(os.getpid())
    try:
        executar(config, offline=tmp_path / "medicoes", ate=FIM)
        raise AssertionError("a segunda execução deveria recusar o lock")
    except RuntimeError as erro:
        assert "andamento" in str(erro)


def test_criterios_reais_sem_lock_interrompem():
    raiz = Path(__file__).resolve().parents[1]
    assert executar(raiz / "config" / "pipeline.yaml", ate=FIM) == 1
