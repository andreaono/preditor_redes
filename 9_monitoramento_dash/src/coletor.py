"""Coleta em processo separado da API. Sem --confirmar-creditos não cria medição."""

import argparse
import json
import logging
import os
import signal
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

import joblib
import pandas as pd

import api_ripe
import banco
import config
import features_online


_PARAR = False


def agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _chave_presente() -> str | None:
    valor = os.environ.get(config.VAR_AMBIENTE_CHAVE)
    if valor is None or not str(valor).strip():
        return None
    return str(valor).strip()


def _sem_chave(texto: str) -> str:
    chave = _chave_presente()
    if chave and chave in texto:
        return texto.replace(chave, "[omitido]")
    return texto


class _JsonLinha(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "nivel": record.levelname.replace("WARNING", "AVISO").replace("ERROR", "ERRO").replace("INFO", "INFO"),
            "tipo": getattr(record, "tipo", "log"),
            "mensagem": _sem_chave(record.getMessage()),
            "dados": getattr(record, "dados", {}),
        }
        return json.dumps(payload, ensure_ascii=False)


def configurar_log() -> logging.Logger:
    """JSONL com rotação. O mesmo evento também vai para a tabela."""
    config.garantir_pastas()
    logger = logging.getLogger("coletor")
    logger.setLevel(getattr(logging, config.LOG_NIVEL))
    logger.handlers.clear()
    arquivo = RotatingFileHandler(config.ARQUIVO_LOG, maxBytes=config.LOG_MAX_MB * 1024 * 1024, backupCount=config.LOG_BACKUP, encoding="utf-8")
    arquivo.setFormatter(_JsonLinha())
    logger.addHandler(arquivo)
    return logger


def evento(logger: logging.Logger, conexao, nivel: str, tipo: str, mensagem: str, dados: dict | None = None) -> None:
    """Registra o evento no arquivo e no SQLite. A chave de API não entra."""
    mapa = {"INFO": logging.INFO, "AVISO": logging.WARNING, "ERRO": logging.ERROR}
    logger.log(mapa.get(nivel, logging.INFO), _sem_chave(mensagem), extra={"tipo": tipo, "dados": dados or {}})
    banco.inserir_evento(conexao, agora(), nivel, tipo, _sem_chave(mensagem), dados or {})


def carregar_modelo():
    """Carrega o joblib da etapa 8 sem gravar de volta."""
    modelo = joblib.load(config.PACOTE_MODELO.joblib)
    if isinstance(modelo, dict) and "modelo" in modelo:
        modelo = modelo["modelo"]
    if hasattr(modelo, "set_params"):
        modelo.set_params(n_jobs=1)
    return modelo


def hash_modelo() -> str:
    import hashlib

    digest = hashlib.sha256(config.PACOTE_MODELO.joblib.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def baseline_do_par(par: dict) -> dict:
    base = par["baseline"]
    return {
        "p95_rtt_num": float(base["p95_rtt"]),
        "p99_rtt_num": float(base["p99_rtt"]),
        "p95_jitter_num": float(base["p95_jitter"]),
        "ttl_baseline": float(base["ttl_baseline"]),
        "status_baseline": base.get("status_baseline") or config.STATUS_BASELINE_OK,
        "mediana_rtt": float(base["mediana_rtt"]),
    }


def estimar_creditos() -> dict:
    """Estima o custo diário com a fórmula da documentação. Não cria medição."""
    unitario = config.custo_por_resultado(oneoff=False)
    por_dia = config.resultados_por_dia(config.INTERVALO_COLETA_S)
    custo_dia = unitario * por_dia
    saldo = None
    if _chave_presente():
        try:
            corpo = api_ripe.get_json(config.URL_CREDITS, com_chave=True, sem_cache=True)
            saldo = corpo.get("current_balance") if isinstance(corpo, dict) else None
        except api_ripe.ErroApi as erro:
            saldo = f"indisponível: {erro}"
    return {
        "custo_por_resultado": unitario,
        "resultados_por_dia": por_dia,
        "custo_dia": custo_dia,
        "duracao_h": config.DURACAO_MEDICAO_H,
        "custo_janela": unitario * (config.DURACAO_MEDICAO_H * 3600 // config.INTERVALO_COLETA_S),
        "teto_dia": config.MAX_CREDITOS_DIA,
        "saldo": saldo,
        "fonte": config.URL_DOC_CREDITOS,
        "intervalo_minimo_documentado": config.INTERVALO_MINIMO_S,
    }


def _dentro_do_teto(estimativa: dict) -> None:
    if estimativa["custo_dia"] > config.MAX_CREDITOS_DIA:
        raise SystemExit(
            f"Custo diário estimado {estimativa['custo_dia']} passa de MAX_CREDITOS_DIA={config.MAX_CREDITOS_DIA}. Medição não criada."
        )
    saldo = estimativa["saldo"]
    if isinstance(saldo, int) and saldo < estimativa["custo_janela"]:
        raise SystemExit(f"Saldo {saldo} menor que o custo estimado da janela {estimativa['custo_janela']}. Medição não criada.")


def criar_medicao(par: dict, confirmar: bool) -> dict:
    """Modo novo. Sem a flag, imprime a estimativa e sai."""
    estimativa = estimar_creditos()
    print(json.dumps(estimativa, ensure_ascii=False, indent=2))
    if not confirmar:
        print("Dry-run: sem --confirmar-creditos a medição não é criada.")
        return {"criada": False, "estimativa": estimativa}
    if not _chave_presente():
        raise SystemExit(f"Sem {config.VAR_AMBIENTE_CHAVE} o modo novo não inicia.")
    _dentro_do_teto(estimativa)
    if par.get("msm_id"):
        try:
            atual = api_ripe.get_json(config.URL_MEASUREMENT.format(id=par["msm_id"]), com_chave=True, sem_cache=True)
            status = ((atual.get("status") or {}).get("name")) if isinstance(atual, dict) else None
            if status == config.STATUS_ONGOING_NOME:
                print(f"Reaproveitando medição {par['msm_id']} ({status}).")
                return {"criada": False, "reaproveitada": True, "msm_id": par["msm_id"], "estimativa": estimativa}
        except api_ripe.ErroApi:
            pass
    agora_unix = int(time.time())
    corpo = {
        "definitions": [
            {
                "target": par["destino"]["ip"],
                "description": f"monitoramento {par['id_fluxo']}",
                "type": config.TIPO_MEDICAO,
                "af": config.ADDRESS_FAMILY,
                "is_oneoff": False,
                "is_public": True,
                "interval": config.INTERVALO_COLETA_S,
                "packets": config.PACOTES,
            }
        ],
        "probes": [{"requested": 1, "type": "probes", "value": str(par["origem"]["id"])}],
        "is_oneoff": False,
        "start_time": agora_unix,
        "stop_time": agora_unix + config.DURACAO_MEDICAO_H * 3600,
    }
    try:
        resposta = api_ripe.post_json(config.URL_MEASUREMENTS, corpo)
    except api_ripe.ErroApi as erro:
        raise SystemExit(str(erro)) from erro
    msm = resposta["measurements"][0] if isinstance(resposta, dict) and resposta.get("measurements") else resposta
    par["msm_id"] = int(msm)
    par["stop_time"] = corpo["stop_time"]
    config.ARQUIVO_PAR.write_text(json.dumps(par, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"criada": True, "msm_id": par["msm_id"], "estimativa": estimativa, "stop_time": corpo["stop_time"]}


def parar_medicao(par: dict) -> None:
    """Encerra a medição criada por este coletor."""
    if not par.get("msm_id"):
        raise SystemExit("Não há msm_id para parar.")
    if not _chave_presente():
        raise SystemExit(f"Sem {config.VAR_AMBIENTE_CHAVE} não é possível parar a medição.")
    api_ripe.post_json(config.URL_MEASUREMENT.format(id=par["msm_id"]), {"stop_time": int(time.time())})
    print(f"Medição {par['msm_id']} parada.")


def _controle() -> dict:
    if not config.ARQUIVO_CONTROLE.is_file():
        return {"pausado": False}
    return json.loads(config.ARQUIVO_CONTROLE.read_text(encoding="utf-8"))


def _resultados_atlas(par: dict, inicio: int, fim: int) -> list[dict]:
    url = config.URL_RESULTS.format(msm_id=par["msm_id"]) + f"?probe_ids={par['origem']['id']}&start={inicio}&stop={fim}&format=json"
    corpo = api_ripe.get_json(url, sem_cache=True)
    if isinstance(corpo, dict) and "results" in corpo:
        return list(corpo["results"])
    if isinstance(corpo, list):
        return corpo
    return []


def _resultados_replay(par: dict, ja: set[int]) -> list[dict]:
    """Lê o Período B do fluxo e devolve o que ainda não foi gravado, limitado ao backfill."""
    usecols = ["id_fluxo", "periodo", "msm_id", "probe_id", "ttl", "result", "rcvd", "sent", "min", "max", "avg", "timestamp"]
    pedacos = []
    for pedaco in pd.read_csv(config.ARQUIVO_CSV_BRUTO_ETAPA5, usecols=usecols, chunksize=100000):
        mascara = (pedaco["id_fluxo"] == par["id_fluxo"]) & (pedaco["periodo"] == config.PERIODO_REPLAY)
        if mascara.any():
            pedacos.append(pedaco.loc[mascara])
    if not pedacos:
        return []
    quadro = pd.concat(pedacos, ignore_index=True).sort_values("timestamp")
    limite = int(quadro["timestamp"].max()) - config.BACKFILL_HORAS * 3600
    quadro = quadro[quadro["timestamp"] >= limite]
    linhas = []
    for _, row in quadro.iterrows():
        ts = int(row["timestamp"])
        if ts in ja:
            continue
        linhas.append(row.to_dict())
    return linhas


def processar_resultados(par: dict, brutos: list[dict], conexao, logger, modelo, nomes: list[str], origem_modo: str) -> int:
    """Deduplica, rotula, prevê t+1 e fecha a previsão anterior."""
    base = baseline_do_par(par)
    existentes = pd.read_sql_query(
        "SELECT timestamp FROM medicoes WHERE id_fluxo = ? ORDER BY timestamp",
        conexao,
        params=(par["id_fluxo"],),
    )
    timestamps = [int(item) for item in existentes["timestamp"].tolist()]
    novas = []
    for bruto in brutos:
        ts = int(bruto["timestamp"])
        if ts in timestamps:
            evento(logger, conexao, "INFO", "resultado_duplicado", "resultado já gravado", {"timestamp": ts})
            continue
        metrica = features_online.metricas_de_resultado(bruto, base["ttl_baseline"])
        anterior = timestamps[-1] if timestamps else None
        metrica["lacuna"] = features_online.lacuna_entre(anterior, ts)
        classe, motivo = features_online.rotular_linha(metrica, base)
        metrica.update(
            {
                "id_fluxo": par["id_fluxo"],
                "msm_id": int(bruto.get("msm_id") or par.get("msm_id") or 0),
                "probe_id": int(bruto.get("prb_id") or bruto.get("probe_id") or par["origem"]["id"]),
                "classe_real": classe,
                "motivo_rotulagem": motivo,
                "origem": origem_modo,
            }
        )
        if not banco.inserir_medicao(conexao, metrica):
            evento(logger, conexao, "INFO", "resultado_duplicado", "chave msm_id+probe+timestamp já existe", {"timestamp": ts})
            continue
        timestamps.append(ts)
        timestamps.sort()
        novas.append(metrica)
        if metrica["lacuna"]:
            evento(logger, conexao, "AVISO", "lacuna", "intervalo maior que GAP_MAX_S", {"timestamp": ts})
    if not novas:
        evento(logger, conexao, "INFO", "sem_resultado_novo", "nenhuma medição nova", {})
        conexao.commit()
        return 0
    historico = pd.read_sql_query(
        "SELECT * FROM medicoes WHERE id_fluxo = ? ORDER BY timestamp",
        conexao,
        params=(par["id_fluxo"],),
    )
    linhas = historico.to_dict(orient="records")
    quadro = features_online.features_do_historico(par["id_fluxo"], linhas, base)
    digest = hash_modelo()
    classes = list(modelo.classes_)
    for metrica in novas:
        indice = int(quadro.index[quadro["timestamp"] == metrica["timestamp"]][0])
        posicao = timestamps.index(metrica["timestamp"])
        aquecimento = 1 if posicao < config.AQUECIMENTO_N else 0
        vetor = features_online.vetor(quadro, indice, nomes)
        matriz = pd.DataFrame([vetor])[nomes].apply(pd.to_numeric, errors="coerce")
        proba = modelo.predict_proba(matriz)[0]
        mapa = {str(classe): float(prob) for classe, prob in zip(classes, proba)}
        previsto = classes[int(proba.argmax())]
        if posicao > 0:
            anterior_ts = timestamps[posicao - 1]
            banco.fechar_previsao(conexao, par["id_fluxo"], anterior_ts, metrica["classe_real"], metrica["lacuna"])
            evento(logger, conexao, "INFO", "previsao_fechada", "rótulo real de t+1 gravado", {"timestamp_t": anterior_ts, "real": metrica["classe_real"]})
        banco.inserir_previsao(
            conexao,
            {
                "id_fluxo": par["id_fluxo"],
                "timestamp_t": metrica["timestamp"],
                "features": vetor,
                "prob_OK": mapa.get("OK"),
                "prob_RISCO": mapa.get("RISCO"),
                "prob_FALHA": mapa.get("FALHA"),
                "previsto": str(previsto),
                "persistencia": metrica["classe_real"],
                "real": None,
                "acerto": None,
                "aquecimento": aquecimento,
                "lacuna": metrica["lacuna"],
                "modelo_hash": digest,
                "criado_em": agora(),
            },
        )
        tipo = "aquecimento" if aquecimento else "previsao_emitida"
        evento(logger, conexao, "INFO", tipo, f"previsão {previsto} para t+1", {"timestamp": metrica["timestamp"], "aquecimento": aquecimento})
    if config.INTERVALO_COLETA_S != config.INTERVALO_TREINO_S and origem_modo != "mesh":
        evento(logger, conexao, "AVISO", "aviso_escala_tempo", config.FRASE_ESCALA, {"coleta_s": config.INTERVALO_COLETA_S, "treino_s": config.INTERVALO_TREINO_S})
    conexao.commit()
    return len(novas)


def _sinal(_sig, _frame) -> None:
    global _PARAR
    _PARAR = True


def loop(par: dict, confirmar: bool) -> int:
    """Laço de consulta. SIGINT encerra sem derrubar o que já foi gravado."""
    logger = configurar_log()
    conexao = banco.conectar()
    signal.signal(signal.SIGINT, _sinal)
    if config.MODO_COLETA == "novo":
        criado = criar_medicao(par, confirmar)
        if not criado.get("criada") and not criado.get("reaproveitada"):
            conexao.close()
            return 0
        evento(logger, conexao, "INFO", "medicao_criada" if criado.get("criada") else "coleta_ok", "medição pronta", {"msm_id": par.get("msm_id")})
    modelo = carregar_modelo()
    nomes = features_online.nomes_features()
    desde = int(time.time()) - config.BACKFILL_HORAS * 3600
    while not _PARAR:
        controle = _controle()
        if controle.get("pausado"):
            evento(logger, conexao, "AVISO", "controle_pausa", "coleta pausada", {})
            conexao.commit()
            time.sleep(config.POLL_S)
            continue
        try:
            if config.MODO_COLETA == "replay":
                ja = set(pd.read_sql_query("SELECT timestamp FROM medicoes WHERE id_fluxo = ?", conexao, params=(par["id_fluxo"],))["timestamp"].tolist())
                brutos = _resultados_replay(par, ja)
            elif config.MODO_COLETA == "mesh":
                brutos = _resultados_atlas(par, desde, int(time.time()))
            else:
                brutos = _resultados_atlas(par, desde, int(time.time()))
            novas = processar_resultados(par, brutos, conexao, logger, modelo, nomes, config.MODO_COLETA)
            if novas:
                evento(logger, conexao, "INFO", "coleta_ok", f"{novas} medições novas", {"n": novas})
            desde = int(time.time()) - config.INTERVALO_COLETA_S * 2
        except api_ripe.ErroApi as erro:
            tipo = "http_429" if "429" in str(erro) else "erro_rede"
            evento(logger, conexao, "ERRO", tipo, str(erro), {})
            conexao.commit()
        if config.MODO_COLETA == "replay":
            break
        time.sleep(config.POLL_S)
    conexao.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Coletor do monitoramento.")
    parser.add_argument("--confirmar-creditos", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--parar", action="store_true")
    parser.add_argument("--fluxo", default=None)
    args = parser.parse_args(argv)
    if not config.ARQUIVO_PAR.is_file():
        raise SystemExit("Rode selecionar_par.py antes do coletor.")
    par = json.loads(config.ARQUIVO_PAR.read_text(encoding="utf-8"))
    if args.fluxo:
        par["id_fluxo"] = args.fluxo
    if args.parar:
        logger = configurar_log()
        conexao = banco.conectar()
        parar_medicao(par)
        evento(logger, conexao, "AVISO", "medicao_parada", "medição encerrada pela API", {"msm_id": par.get("msm_id")})
        conexao.commit()
        conexao.close()
        return 0
    import verificar

    verificar.antes_da_coleta()
    return loop(par, confirmar=args.confirmar_creditos and not args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
