"""Log operacional, contrato, rótulo atômico, sal e retenção."""

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.esquema import linha_log
from src.features_treino import nomes_features
from src.log.coleta import registrar as registrar_coleta
from src.log.limpar import executar as limpar
from src.log.operacional import erro, quantidades, registrar
from src.log.predicoes import exportar_jsonl, gravar, registrar_rotulo
from src.log.privacidade import hash_probe, mascarar
from src.log.validar_logs import avaliar


def _linha(run_id: str = "r1") -> dict:
    return linha_log(
        run_id=run_id,
        ts_previsao="2026-10-05T14:00:00Z",
        fluxo_id="1016806_3679",
        anchor_id=3679,
        modelo_versao="rf_v1.0.0",
        modelo_hash="sha256:teste",
        features={nome: -1.0 for nome in nomes_features()},
        proba={"OK": 0.91, "RISCO": 0.07, "FALHA": 0.02},
        classe_prevista="OK",
        classe_atual="OK",
        latencia_inferencia_ms=4,
    )


def test_esquema_recusa_e_exporta_jsonl(tmp_path: Path):
    jsonl = tmp_path / "predicoes.jsonl"
    parquet = tmp_path / "parquet"
    quarentena = tmp_path / "quarentena"
    assert gravar(_linha(), jsonl, parquet, quarentena)
    ruim = _linha("r2")
    ruim["classe_prevista"] = "TALVEZ"
    assert not gravar(ruim, jsonl, parquet, quarentena)
    assert "Classe fora" in (quarentena / "contrato.jsonl").read_text(encoding="utf-8")
    exportado = tmp_path / "exportado.jsonl"
    assert exportar_jsonl(parquet, exportado) == 1
    recarregado = json.loads(exportado.read_text(encoding="utf-8"))
    assert recarregado["features"]["perda_pct"] == -1.0
    assert recarregado["modelo_versao"] == "rf_v1.0.0"
    veredito, _motivos = avaliar([recarregado], minimo_rotulo=0.0)
    assert veredito == "PASSOU"


def test_rotulo_atomico_nao_duplica(tmp_path: Path):
    jsonl = tmp_path / "predicoes.jsonl"
    parquet = tmp_path / "parquet"
    gravar(_linha("r1"), jsonl, parquet, tmp_path / "q")
    outra = _linha("r2")
    gravar(outra, jsonl, parquet, tmp_path / "q")
    atualizada = registrar_rotulo(
        {"run_id": "r1", "fluxo_id": "1016806_3679", "ts_previsao": "2026-10-05T14:00:00Z"},
        "FALHA",
        "2026-10-05T14:04:00Z",
        jsonl,
        parquet,
    )
    assert atualizada["rotulo_real"] == "FALHA"
    assert atualizada["features"] == outra["features"]
    linhas = [json.loads(texto) for texto in jsonl.read_text(encoding="utf-8").splitlines()]
    assert len(linhas) == 2
    assert sum(item["rotulo_real"] == "FALHA" for item in linhas) == 1


def test_hash_de_ip_estavel_e_anchor_inteiro():
    assert hash_probe("187.109.226.175", "sal-teste") == hash_probe("187.109.226.175", "sal-teste")
    assert hash_probe("187.109.226.175", "sal-teste") != hash_probe("187.109.226.175", "outro-sal")
    mascarado = mascarar({"anchor_id": 3679, "ip": "187.109.226.175"}, sal="sal-teste")
    assert mascarado["anchor_id"] == 3679
    assert "ip" not in mascarado
    assert mascarado["ip_hash"] == hash_probe("187.109.226.175", "sal-teste")


def test_retencao_dry_run_preserva_agregado(tmp_path: Path):
    bruto = tmp_path / "logs" / "operacional" / "velho.jsonl"
    bruto.parent.mkdir(parents=True)
    bruto.write_text("{}\n", encoding="utf-8")
    antigo = datetime.now(timezone.utc) - timedelta(days=120)
    os.utime(bruto, (antigo.timestamp(), antigo.timestamp()))
    agregado = tmp_path / "relatorios" / "drift_antigo.json"
    agregado.parent.mkdir()
    agregado.write_text("{}\n", encoding="utf-8")
    os.utime(agregado, (antigo.timestamp(), antigo.timestamp()))
    alvos = limpar(tmp_path, agora=datetime.now(timezone.utc), dry_run=True, retencao={"bruto_dias": 90})
    assert bruto in alvos
    assert agregado not in alvos
    assert bruto.is_file()


def test_duas_escritas_concorrentes(tmp_path: Path):
    jsonl = tmp_path / "predicoes.jsonl"
    parquet = tmp_path / "parquet"
    erros: list[BaseException] = []

    def gravar_uma(indice: int) -> None:
        try:
            assert gravar(_linha(f"r{indice}"), jsonl, parquet, tmp_path / "q")
        except BaseException as erro_local:
            erros.append(erro_local)

    fios = [threading.Thread(target=gravar_uma, args=(indice,)) for indice in (1, 2)]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join()
    assert not erros
    linhas = [texto for texto in jsonl.read_text(encoding="utf-8").splitlines() if texto.strip()]
    assert len(linhas) == 2


def test_operacional_e_coleta_separam_timeout(tmp_path: Path):
    evento = registrar(tmp_path / "op", "info", "run", "retry", "nova tentativa", tentativa=2, probe_id=1016806)
    assert "probe_id" not in evento
    coleta = registrar_coleta(
        tmp_path / "coleta",
        "run",
        66198951,
        status_http=200,
        linhas_esperadas=1,
        linhas_recebidas=1,
        probes_offline=[1016806],
        tempo_resposta_ms=30,
        creditos=None,
        falha_coleta=False,
        timeout_medicao=2,
    )
    assert coleta["falha_coleta"] is False
    assert coleta["timeout_medicao"] == 2
    assert coleta["creditos"] is None
    assert coleta["probes_offline_hash"][0] is None or isinstance(coleta["probes_offline_hash"][0], str)
    falha = erro(tmp_path / "op", "run", "coleta", TimeoutError("api"))
    assert falha["nivel"] == "erro"
    quantidades(tmp_path / "op", "run", 3, 1, 1)
