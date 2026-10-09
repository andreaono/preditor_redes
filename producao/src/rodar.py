"""Roda a inferência em lote. Um fluxo com erro não derruba os outros.

No início confere o lock dos critérios. Duas execuções não andam ao mesmo tempo.
A mesma janela, repetida, não duplica a linha run_id + fluxo_id + ts_previsao.
"""

import argparse
import ctypes
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.ajustes import RAIZ, carregar
from src.carregar_modelo import carregar_modelo
from src.coleta import buscar
from src.congelar_criterios import verificar
from src.contrato import ErroColeta, classificar_item, na_janela
from src.features import baseline_da_etapa6, baseline_novo, vetor_e_classe
from src.inferir import inferir
from src.log.coleta import registrar as registrar_coleta_http
from src.log.operacional import erro as log_erro
from src.log.operacional import fim as log_fim
from src.log.operacional import inicio as log_inicio
from src.log.operacional import quantidades as log_quantidades
from src.log.operacional import retry as log_retry
from src.log.predicoes import gravar as gravar_predicao
from src.prever import hash_arquivo

CAMPOS_NUMERICOS = (
    "perda_num",
    "latencia_num",
    "jitter_num",
    "rtt_min_num",
    "rtt_max_num",
    "rtt_avg_num",
    "ttl",
)


def _caminho(valor) -> Path:
    caminho = Path(valor)
    if caminho.is_absolute():
        return caminho
    return (RAIZ / caminho).resolve()


def ler_pipeline(caminho) -> dict:
    documento = yaml.safe_load(Path(caminho).read_text(encoding="utf-8"))
    for chave in (
        "pares",
        "criterios",
        "lock",
        "pasta_logs",
        "pasta_quarentena",
        "pasta_estado",
        "pasta_erros",
        "pasta_coleta",
        "arquivo_baseline",
        "arquivo_artefato",
        "arquivo_lock_execucao",
    ):
        documento[chave] = _caminho(documento[chave])
    return documento


def processo_vivo(pid: int) -> bool:
    """Diz se o pid do lock ainda é um processo."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        acesso = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(acesso, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def adquirir_lock(caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if caminho.exists():
        try:
            pid = int(caminho.read_text(encoding="utf-8").strip())
        except ValueError:
            pid = -1
        if processo_vivo(pid):
            raise RuntimeError("Já existe uma execução em andamento.")
        caminho.unlink()
    descritor = os.open(caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(descritor, str(os.getpid()).encode("ascii"))
    os.close(descritor)


def liberar_lock(caminho: Path) -> None:
    if caminho.is_file() and caminho.read_text(encoding="utf-8").strip() == str(os.getpid()):
        caminho.unlink()


def _anexar_jsonl(caminho: Path, objeto: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(objeto, ensure_ascii=False) + "\n")


def _numero_estado(valor):
    if isinstance(valor, float) and not math.isfinite(valor):
        return None
    return valor


def _ler_estado(caminho: Path) -> dict:
    if not caminho.is_file():
        return {"medicoes": [], "baseline": None, "estado": "aquecimento"}
    bruto = json.loads(caminho.read_text(encoding="utf-8"))
    medicoes = []
    for item in bruto.get("medicoes") or []:
        convertido = dict(item)
        for nome in CAMPOS_NUMERICOS:
            valor = convertido.get(nome)
            convertido[nome] = float("nan") if valor is None else float(valor)
        medicoes.append(convertido)
    bruto["medicoes"] = medicoes
    baseline = bruto.get("baseline")
    if isinstance(baseline, dict):
        for nome in ("p95_rtt_num", "p99_rtt_num", "p95_jitter_num", "ttl_baseline"):
            valor = baseline.get(nome)
            baseline[nome] = float("nan") if valor is None else float(valor)
    return bruto


def _gravar_estado(caminho: Path, fluxo_id: str, medicoes: list, baseline, estado: str) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    serial = []
    for item in medicoes:
        copia = dict(item)
        for nome in CAMPOS_NUMERICOS:
            copia[nome] = _numero_estado(copia.get(nome))
        serial.append(copia)
    base = None
    if baseline is not None:
        base = {chave: _numero_estado(valor) if isinstance(valor, float) else valor for chave, valor in baseline.items()}
    payload = {
        "fluxo_id": fluxo_id,
        "estado": estado,
        "medicoes": serial,
        "baseline": base,
        "atualizado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporario.replace(caminho)


def _ja_gravada(caminho: Path, run_id: str, fluxo_id: str, ts_previsao: str) -> bool:
    if not caminho.is_file():
        return False
    for texto in caminho.read_text(encoding="utf-8").splitlines():
        if not texto.strip():
            continue
        item = json.loads(texto)
        if item.get("run_id") == run_id and item.get("fluxo_id") == fluxo_id and item.get("ts_previsao") == ts_previsao:
            return True
    return False


def _instante(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def processar_fluxo(par: dict, cfg: dict, inicio: int, fim: int, run_id: str, artefato, modelo_hash: str, offline, transporte, dry_run: bool, ao_retry=None) -> dict:
    """Coleta, valida, atualiza o estado e, se couber, prevê."""
    fluxo_id = par["fluxo_id"]
    probe_id = int(par["probe_id"])
    anchor_id = int(par["anchor_id"])
    medicao_id = int(par["measurement_id"])
    estado_path = cfg["pasta_estado"] / f"{fluxo_id}.json"
    brutos = buscar(medicao_id, probe_id, inicio, fim, cfg, offline, transporte, ao_retry=ao_retry)
    recebidos = sorted({item.get("prb_id") for item in brutos if isinstance(item, dict) and "prb_id" in item})
    relatorio = {
        "fluxo_id": fluxo_id,
        "probe_esperado": probe_id,
        "probes_recebidos": recebidos,
        "situacoes": {"ok": 0, "timeout": 0, "sem_resultado": 0, "probe_offline": 0, "invalida": 0},
    }
    if probe_id not in recebidos:
        relatorio["situacoes"]["sem_resultado"] = 1
    estado = _ler_estado(estado_path)
    medicoes = list(estado.get("medicoes") or [])
    ja_no_historico = {item["timestamp"] for item in medicoes}
    vistos_no_lote: set[int] = set()
    novas = 0
    for item in brutos:
        if not na_janela(item, inicio, fim):
            continue
        classificado = classificar_item(item, probe_id)
        situacao = classificado["situacao"]
        if situacao == "probe_offline":
            relatorio["situacoes"]["probe_offline"] += 1
            continue
        if situacao == "invalida":
            relatorio["situacoes"]["invalida"] += 1
            if not dry_run:
                _anexar_jsonl(
                    cfg["pasta_quarentena"] / f"{run_id}.jsonl",
                    {"fluxo_id": fluxo_id, "motivo": classificado["motivo"], "item": classificado["item"]},
                )
            continue
        relatorio["situacoes"][situacao] += 1
        marca = classificado["timestamp"]
        if marca in vistos_no_lote:
            relatorio["situacoes"]["invalida"] += 1
            relatorio["situacoes"][situacao] -= 1
            if not dry_run:
                _anexar_jsonl(
                    cfg["pasta_quarentena"] / f"{run_id}.jsonl",
                    {"fluxo_id": fluxo_id, "motivo": "timestamp_duplicado", "item": item},
                )
            continue
        vistos_no_lote.add(marca)
        if marca in ja_no_historico:
            continue
        medicoes.append({nome: classificado[nome] for nome in ("situacao", "timestamp", *CAMPOS_NUMERICOS)})
        novas += 1
    medicoes.sort(key=lambda item: item["timestamp"])
    teto = int(cfg["historico_maximo"])
    if len(medicoes) > teto:
        medicoes = medicoes[-teto:]
    minimo = int(cfg["minimo_medicoes_historico"])
    baseline = estado.get("baseline")
    if baseline is None:
        baseline = baseline_da_etapa6(cfg["arquivo_baseline"], probe_id, anchor_id)
    if baseline is None:
        baseline = baseline_novo(medicoes)
    if len(medicoes) < minimo or baseline is None:
        relatorio["estado"] = "aquecimento"
        relatorio["previsao"] = False
        if not dry_run:
            _gravar_estado(estado_path, fluxo_id, medicoes, baseline, "aquecimento")
        if not dry_run:
            _anexar_jsonl(cfg["pasta_coleta"] / f"{run_id}.jsonl", relatorio)
        return relatorio
    features, classe_atual = vetor_e_classe(fluxo_id, medicoes, baseline)
    if classe_atual not in carregar()["classes"] or not math.isfinite(features["perda_pct"]):
        relatorio["estado"] = "sem_classe"
        relatorio["previsao"] = False
        if not dry_run:
            _gravar_estado(estado_path, fluxo_id, medicoes, baseline, "sem_classe")
            _anexar_jsonl(cfg["pasta_coleta"] / f"{run_id}.jsonl", relatorio)
        return relatorio
    ts_previsao = _instante(medicoes[-1]["timestamp"])
    linha = inferir(
        artefato,
        features,
        fluxo_id=fluxo_id,
        anchor_id=anchor_id,
        classe_atual=classe_atual,
        run_id=run_id,
        ts_previsao=ts_previsao,
        modelo_versao=cfg["modelo_versao"],
        modelo_hash=modelo_hash,
        classes_saida=tuple(cfg["classes"]),
    )
    destino = cfg["pasta_logs"] / f"{run_id}.jsonl"
    relatorio["estado"] = "previsto"
    relatorio["previsao"] = not _ja_gravada(destino, run_id, fluxo_id, ts_previsao)
    relatorio["classe_prevista"] = linha["classe_prevista"]
    relatorio["novas"] = novas
    if not dry_run:
        _gravar_estado(estado_path, fluxo_id, medicoes, baseline, "previsto")
        if relatorio["previsao"]:
            gravar_predicao(
                linha,
                destino,
                cfg["pasta_logs"].parent / "predicoes_parquet",
                cfg["pasta_logs"].parent / "quarentena_contrato",
            )
        _anexar_jsonl(cfg["pasta_coleta"] / f"{run_id}.jsonl", relatorio)
    return relatorio


def executar(caminho_config, dry_run: bool = False, offline=None, transporte=None, ate: int | None = None) -> int:
    """Confere o lock, processa os pares e devolve 0 só se nenhum fluxo falhou."""
    cfg = ler_pipeline(caminho_config)
    ajustes = carregar()
    cfg["modelo_versao"] = ajustes["modelo_versao"]
    cfg["classes"] = ajustes["classes"]
    if verificar(cfg["criterios"], cfg["lock"]) != 0:
        print("Execução interrompida: critérios sem lock válido.")
        return 1
    fim = int(time.time()) if ate is None else int(ate)
    inicio = fim - int(cfg["janela_minutos"]) * 60
    run_id = f"{inicio}-{fim}"
    adquirir_lock(cfg["arquivo_lock_execucao"])
    falhas = 0
    previstas = 0
    descartadas = 0
    coletadas = 0
    comeco = time.perf_counter()
    pasta_op = cfg["pasta_logs"].parent / "operacional"
    if not dry_run:
        log_inicio(pasta_op, run_id)

    def ao_retry(tentativa: int, motivo: str) -> None:
        if not dry_run:
            log_retry(pasta_op, run_id, tentativa, motivo)

    try:
        artefato = carregar_modelo(cfg["arquivo_artefato"])
        modelo_hash = hash_arquivo(cfg["arquivo_artefato"])
        pares = json.loads(cfg["pares"].read_text(encoding="utf-8"))["pares"]
        for indice, par in enumerate(pares):
            if indice and not offline and transporte is None and not dry_run:
                time.sleep(float(cfg["pausa_s"]))
            try:
                relatorio = processar_fluxo(
                    par, cfg, inicio, fim, run_id, artefato, modelo_hash, offline, transporte, dry_run, ao_retry
                )
                coletadas += sum(relatorio["situacoes"].values())
                descartadas += relatorio["situacoes"].get("invalida", 0)
                previstas += int(bool(relatorio.get("previsao")))
                if not dry_run:
                    registrar_coleta_http(
                        cfg["pasta_logs"].parent / "coleta_http",
                        run_id,
                        int(par["measurement_id"]),
                        status_http=None if offline or transporte else 200,
                        linhas_esperadas=1,
                        linhas_recebidas=0 if relatorio["situacoes"].get("sem_resultado") else 1,
                        probes_offline=[par["probe_id"]] if relatorio["situacoes"].get("probe_offline") else [],
                        creditos=None,
                        falha_coleta=False,
                        timeout_medicao=relatorio["situacoes"].get("timeout", 0),
                        sem_resultado=relatorio["situacoes"].get("sem_resultado", 0),
                        probe_id=par["probe_id"],
                    )
                print(
                    f"{relatorio['fluxo_id']}: {relatorio['estado']} "
                    f"nova_linha={relatorio.get('previsao')} "
                    f"recebidos={relatorio['probes_recebidos']} {relatorio['situacoes']}"
                )
            except Exception as erro:
                falhas += 1
                print(f"{par.get('fluxo_id')}: erro {erro}")
                if not dry_run:
                    _anexar_jsonl(
                        cfg["pasta_erros"] / f"{run_id}.jsonl",
                        {"fluxo_id": par.get("fluxo_id"), "erro": str(erro)},
                    )
                    log_erro(pasta_op, run_id, "fluxo", erro)
                    from src.contrato import ErroColeta

                    falha_de_coleta = isinstance(erro, ErroColeta)
                    registrar_coleta_http(
                        cfg["pasta_logs"].parent / "coleta_http",
                        run_id,
                        int(par.get("measurement_id") or 0),
                        status_http=None,
                        linhas_esperadas=1,
                        linhas_recebidas=0,
                        creditos=None,
                        falha_coleta=falha_de_coleta,
                        timeout_medicao=0,
                        probe_id=par.get("probe_id"),
                    )
        if not dry_run:
            log_quantidades(pasta_op, run_id, coletadas, descartadas, previstas)
            log_fim(pasta_op, run_id, int((time.perf_counter() - comeco) * 1000), falhas)
        print(f"run_id={run_id} fluxos={len(pares)} falhas={falhas} dry_run={dry_run}")
    finally:
        liberar_lock(cfg["arquivo_lock_execucao"])
    return 1 if falhas else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inferência em lote dos pares monitorados.")
    parser.add_argument("--config", default="config/pipeline.yaml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--offline", default=None)
    parser.add_argument("--ate", type=int, default=None)
    args = parser.parse_args(argv)
    offline = Path(args.offline) if args.offline else None
    return executar(args.config, dry_run=args.dry_run, offline=offline, ate=args.ate)


if __name__ == "__main__":
    raise SystemExit(main())
