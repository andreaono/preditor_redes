"""Leitura da Streaming API pública. Não cria medição e não envia a chave."""

import base64
import json
import os
import socket
import ssl
import struct
import threading
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import config
import features_online


class ErroStream(RuntimeError):
    """A Streaming API não completou a assinatura."""


_TRAVA = threading.Lock()
_SESSAO: dict | None = None
_PARAR = threading.Event()
_SOCKET: socket.socket | None = None


def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(int(epoch), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _baseline(documento: dict) -> dict:
    base = documento["baseline"]
    return {
        "p95_rtt_num": float(base["p95_rtt"]),
        "p99_rtt_num": float(base["p99_rtt"]),
        "p95_jitter_num": float(base["p95_jitter"]),
        "ttl_baseline": float(base["ttl_baseline"]),
        "status_baseline": base.get("status_baseline") or config.STATUS_BASELINE_OK,
        "mediana_rtt": float(base["mediana_rtt"]),
    }


def _prever(vetor: dict) -> dict | None:
    """Usa o modelo já carregado pela API. A previsão é da próxima medição."""
    import api

    if api.ESTADO.modelo is None or not api.ESTADO.conferido:
        return None
    nomes = features_online.nomes_features()
    if any(vetor.get(nome) is None for nome in nomes):
        return None
    matriz = np.array([[float(vetor[nome]) for nome in nomes]], dtype=float)
    classes = [str(nome) for nome in api.ESTADO.modelo.classes_]
    proba = api.ESTADO.modelo.predict_proba(matriz)[0]
    mapa = {nome: float(proba[indice]) for indice, nome in enumerate(classes)}
    return {
        "previsto": classes[int(np.argmax(proba))],
        "prob_OK": mapa.get("OK"),
        "prob_RISCO": mapa.get("RISCO"),
        "prob_FALHA": mapa.get("FALHA"),
    }


def _features_json(vetor: dict) -> dict:
    """Copia o vetor já calculado. A sentinela −1 permanece −1."""
    saida = {}
    for nome in features_online.nomes_features():
        valor = vetor.get(nome)
        if valor is None:
            saida[nome] = None
            continue
        numero = float(valor)
        if not np.isfinite(numero):
            saida[nome] = None
        elif numero == config.SENTINELA:
            saida[nome] = config.SENTINELA
        else:
            saida[nome] = numero
    return saida


def interpretar(bruto: dict, baseline: dict, historico: list[dict], id_fluxo: str) -> dict:
    """Latência, jitter, perda e status da regra. O histórico fica só na memória da sessão."""
    metrica = features_online.metricas_de_resultado(bruto, baseline["ttl_baseline"])
    classe, motivo = features_online.rotular_linha(metrica, baseline)
    metrica["classe_real"] = classe
    metrica["motivo_rotulagem"] = motivo
    historico.append(metrica)
    quadro = features_online.features_do_historico(id_fluxo, historico, baseline)
    previsao = None
    features = None
    if not quadro.empty:
        indice = len(quadro) - 1
        vetor = features_online.vetor(quadro, indice, features_online.nomes_features())
        features = _features_json(vetor)
        previsao = _prever(vetor)
    return {
        "timestamp": int(metrica["timestamp"]),
        "hora": _iso(int(metrica["timestamp"])),
        "latencia_ms": None if not np.isfinite(metrica["latencia_ms"]) else float(metrica["latencia_ms"]),
        "jitter_ms": None if not np.isfinite(metrica["jitter_ms"]) else float(metrica["jitter_ms"]),
        "perda_pct": None if not np.isfinite(metrica["perda_pct"]) else float(metrica["perda_pct"]),
        "status": classe,
        "motivo": motivo,
        "previsto": None if previsao is None else previsao["previsto"],
        "prob_OK": None if previsao is None else previsao["prob_OK"],
        "prob_RISCO": None if previsao is None else previsao["prob_RISCO"],
        "prob_FALHA": None if previsao is None else previsao["prob_FALHA"],
        "features": features,
    }


def metricas_da_amostra(linhas: list[dict]) -> dict:
    """Compara a previsão de t com o status real de t+1 nesta janela."""
    from sklearn.metrics import accuracy_score, f1_score, recall_score

    fechadas = []
    for anterior, atual in zip(linhas, linhas[1:]):
        if anterior.get("previsto") and atual.get("status"):
            fechadas.append((anterior["previsto"], anterior["status"], atual["status"]))
    ultima = None
    if linhas and linhas[-1].get("previsto"):
        ultima = {
            "previsto": linhas[-1]["previsto"],
            "prob_OK": linhas[-1].get("prob_OK"),
            "prob_RISCO": linhas[-1].get("prob_RISCO"),
            "prob_FALHA": linhas[-1].get("prob_FALHA"),
            "hora": linhas[-1].get("hora"),
        }
    base = {
        "n": len(linhas),
        "n_fechadas": len(fechadas),
        "aquecimento_oficial": config.AQUECIMENTO_N,
        "abaixo_do_aquecimento": len(linhas) < config.AQUECIMENTO_N,
        "ultima_previsao": ultima,
        "rotulos": list(config.CLASSES),
        "n_transicoes": sum(1 for _previsto, anterior, seguinte in fechadas if anterior != seguinte),
    }
    if not fechadas:
        base["texto"] = "A previsão fecha quando chega a medição seguinte."
        return base
    real = [item[2] for item in fechadas]
    previsto = [item[0] for item in fechadas]
    persistencia = [item[1] for item in fechadas]
    rotulos = list(config.CLASSES)
    macro = float(f1_score(real, previsto, labels=rotulos, average="macro", zero_division=0))
    macro_persistencia = float(f1_score(real, persistencia, labels=rotulos, average="macro", zero_division=0))
    recall = recall_score(real, previsto, labels=["FALHA"], average="macro", zero_division=0)
    ganho = None if macro_persistencia == 0 else macro - macro_persistencia
    base.update(
        {
            "acuracia": float(accuracy_score(real, previsto)),
            "macro_f1": macro,
            "recall_falha": None if "FALHA" not in real else float(recall),
            "acuracia_persistencia": float(accuracy_score(real, persistencia)),
            "macro_f1_persistencia": macro_persistencia,
            "ganho_macro_f1": ganho,
            "texto": None,
        }
    )
    return base


def foto() -> dict:
    """Cópia da sessão para a API. Sem sessão viva, lê o último arquivo gravado."""
    with _TRAVA:
        sessao = None if _SESSAO is None else {chave: valor for chave, valor in _SESSAO.items() if chave != "linhas"}
        linhas = None if _SESSAO is None else list(_SESSAO["linhas"])
    if sessao is None:
        if config.ARQUIVO_SESSAO.is_file():
            return json.loads(config.ARQUIVO_SESSAO.read_text(encoding="utf-8"))
        return {"ativa": False, "medicao_criada": False, "linhas": [], "modelo": metricas_da_amostra([])}
    sessao["linhas"] = linhas
    sessao["modelo"] = metricas_da_amostra(linhas)
    sessao["agora"] = _agora()
    return sessao


def _gravar_estado() -> None:
    config.garantir_pastas()
    config.ARQUIVO_SESSAO.write_text(json.dumps(foto(), ensure_ascii=False, indent=2), encoding="utf-8")


def _anotar(caminho, registro: dict) -> None:
    with caminho.open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")


def _enviar(sock: socket.socket, texto: str) -> None:
    dados = texto.encode("utf-8")
    cabeca = bytearray([0x81])
    tamanho = len(dados)
    if tamanho < 126:
        cabeca.append(0x80 | tamanho)
    elif tamanho < 65536:
        cabeca.append(0x80 | 126)
        cabeca.extend(struct.pack(">H", tamanho))
    else:
        cabeca.append(0x80 | 127)
        cabeca.extend(struct.pack(">Q", tamanho))
    mascara = os.urandom(4)
    cabeca.extend(mascara)
    corpo = bytes(byte ^ mascara[indice % 4] for indice, byte in enumerate(dados))
    sock.sendall(cabeca + corpo)


def _conectar() -> socket.socket:
    bruto = socket.create_connection((config.HOST_STREAM, 443), timeout=config.TIMEOUT_CONEXAO_S)
    contexto = ssl.create_default_context()
    sock = contexto.wrap_socket(bruto, server_hostname=config.HOST_STREAM)
    chave = base64.b64encode(os.urandom(16)).decode("ascii")
    pedido = (
        f"GET {config.CAMINHO_STREAM} HTTP/1.1\r\n"
        f"Host: {config.HOST_STREAM}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {chave}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"User-Agent: {config.USER_AGENT}\r\n"
        "\r\n"
    )
    sock.sendall(pedido.encode("ascii"))
    resposta = b""
    while b"\r\n\r\n" not in resposta:
        pedaco = sock.recv(4096)
        if not pedaco:
            raise ErroStream("A Streaming API fechou antes do aperto de mão.")
        resposta += pedaco
        if len(resposta) > 8192:
            break
    status = resposta.split(b"\r\n", 1)[0]
    if b" 101 " not in status:
        raise ErroStream(status.decode("ascii", errors="replace"))
    sock.settimeout(5)
    return sock


def _ler_exato(sock: socket.socket, buffer: bytearray, tamanho: int, prazo: float, parar: threading.Event) -> bytes:
    while len(buffer) < tamanho:
        if parar.is_set() or time.time() >= prazo:
            raise TimeoutError
        try:
            pedaco = sock.recv(65536)
        except socket.timeout:
            continue
        if not pedaco:
            raise ErroStream("A Streaming API encerrou a conexão.")
        buffer.extend(pedaco)
    saida = bytes(buffer[:tamanho])
    del buffer[:tamanho]
    return saida


def _quadro(sock: socket.socket, buffer: bytearray, prazo: float, parar: threading.Event):
    """Devolve o texto, ou None quando o prazo da sessão acabou."""
    while True:
        if parar.is_set() or time.time() >= prazo:
            return None
        try:
            cabeca = _ler_exato(sock, buffer, 2, prazo, parar)
        except TimeoutError:
            return None
        primeiro, segundo = cabeca[0], cabeca[1]
        opcode = primeiro & 0x0F
        tamanho = segundo & 0x7F
        if tamanho == 126:
            tamanho = struct.unpack(">H", _ler_exato(sock, buffer, 2, prazo, parar))[0]
        elif tamanho == 127:
            tamanho = struct.unpack(">Q", _ler_exato(sock, buffer, 8, prazo, parar))[0]
        if segundo & 0x80:
            mascara = _ler_exato(sock, buffer, 4, prazo, parar)
            dados = bytearray(_ler_exato(sock, buffer, tamanho, prazo, parar))
            for indice, byte in enumerate(dados):
                dados[indice] = byte ^ mascara[indice % 4]
            carga = bytes(dados)
        else:
            carga = _ler_exato(sock, buffer, tamanho, prazo, parar)
        if opcode == 0x8:
            raise ErroStream("A Streaming API encerrou a assinatura.")
        if opcode == 0x9:
            pong = bytearray([0x8A])
            pong.append(0x80 | len(carga))
            mascara = os.urandom(4)
            pong.extend(mascara)
            pong.extend(byte ^ mascara[indice % 4] for indice, byte in enumerate(carga))
            sock.sendall(pong)
            continue
        if opcode == 0xA or opcode == 0x0:
            continue
        if opcode == 0x1:
            return carga.decode("utf-8", errors="replace")


def _loop(documento: dict, probe_id: int, msm_id: int, inicio: int, fim: int, caminho, parar: threading.Event) -> None:
    global _SOCKET
    features_online.etapa5()
    features_online.etapa7()
    baseline = _baseline(documento)
    historico: list[dict] = []
    vistos: set[int] = set()
    while time.time() < fim and not parar.is_set():
        try:
            sock = _conectar()
        except (OSError, ErroStream) as erro:
            _anotar(caminho, {"tipo": "erro", "quando": _agora(), "detalhe": str(erro)})
            with _TRAVA:
                if _SESSAO is not None and _SESSAO.get("inicio_epoch") == inicio:
                    _SESSAO["erro"] = str(erro)
            if parar.is_set():
                break
            time.sleep(2)
            continue
        with _TRAVA:
            _SOCKET = sock
            if _SESSAO is not None and _SESSAO.get("inicio_epoch") == inicio:
                _SESSAO["erro"] = None
                _SESSAO["conectado"] = True
        try:
            _enviar(sock, json.dumps(["atlas_subscribe", {"streamType": "result", "msm": msm_id, "prb": probe_id, "sendBacklog": True}]))
            buffer = bytearray()
            while time.time() < fim and not parar.is_set():
                texto = _quadro(sock, buffer, min(fim, time.time() + 30), parar)
                if texto is None:
                    continue
                try:
                    tipo, carga = json.loads(texto)
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                if tipo == "atlas_error":
                    detalhe = carga.get("detail") if isinstance(carga, dict) else str(carga)
                    _anotar(caminho, {"tipo": "erro", "quando": _agora(), "detalhe": detalhe})
                    with _TRAVA:
                        if _SESSAO is not None and _SESSAO.get("inicio_epoch") == inicio:
                            _SESSAO["erro"] = detalhe
                    continue
                if tipo != "atlas_result" or not isinstance(carga, dict):
                    continue
                if int(carga.get("prb_id") or 0) != probe_id:
                    continue
                if carga.get("type") not in (None, "ping"):
                    continue
                timestamp = int(carga.get("timestamp") or 0)
                if timestamp < inicio or timestamp > fim or timestamp in vistos:
                    continue
                vistos.add(timestamp)
                linha = interpretar(carga, baseline, historico, documento["id_fluxo"])
                with _TRAVA:
                    if _SESSAO is not None and _SESSAO.get("inicio_epoch") == inicio:
                        _SESSAO["linhas"].append(linha)
                        _SESSAO["n"] = len(_SESSAO["linhas"])
                _anotar(caminho, {"tipo": "resultado", **linha})
                _gravar_estado()
        except (OSError, ErroStream, TimeoutError) as erro:
            if time.time() < fim and not parar.is_set():
                _anotar(caminho, {"tipo": "erro", "quando": _agora(), "detalhe": str(erro)})
        finally:
            try:
                sock.close()
            except OSError:
                pass
            with _TRAVA:
                if _SOCKET is sock:
                    _SOCKET = None
        if time.time() < fim and not parar.is_set():
            time.sleep(1)
    with _TRAVA:
        if _SESSAO is not None and _SESSAO.get("inicio_epoch") == inicio:
            _SESSAO["ativa"] = False
            _SESSAO["conectado"] = False
            _SESSAO["encerrado_em"] = _agora()
    _anotar(caminho, {"tipo": "fim", "quando": _agora(), "motivo": "prazo" if time.time() >= fim else "nova_escolha"})
    _gravar_estado()


def iniciar(documento: dict, duracao_minutos: int) -> dict:
    """Abre a janela a partir de agora. A medição pública já existente não é recriada."""
    global _SESSAO, _PARAR, _SOCKET
    if duracao_minutos not in config.DURACOES_MINUTOS:
        raise ValueError("O tempo deve ser 5 min, 10 min, 30 min, 1 h, 4 h ou 24 h.")
    msm_id = documento.get("msm_id_publico")
    probe_id = (documento.get("origem") or {}).get("id")
    if not msm_id or not probe_id:
        raise ValueError("A medição pública ou o probe não está identificado.")
    features_online.etapa5()
    features_online.etapa7()
    agora = int(time.time())
    selo = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    caminho = config.LOGS_DIR / f"stream_{documento['id_fluxo']}_{selo}.jsonl"
    config.garantir_pastas()
    with _TRAVA:
        _PARAR.set()
        sock = _SOCKET
    if sock is not None:
        try:
            sock.close()
        except OSError:
            pass
    time.sleep(0.2)
    with _TRAVA:
        _PARAR = threading.Event()
        _SESSAO = {
            "ativa": True,
            "conectado": False,
            "medicao_criada": False,
            "id_fluxo": documento["id_fluxo"],
            "faixa": documento.get("faixa"),
            "duracao_minutos": int(duracao_minutos),
            "inicio": _iso(agora),
            "fim": _iso(agora + int(duracao_minutos) * 60),
            "inicio_epoch": agora,
            "fim_epoch": agora + int(duracao_minutos) * 60,
            "msm_id_publico": int(msm_id),
            "probe_id": int(probe_id),
            "arquivo_log": caminho.name,
            "erro": None,
            "linhas": [],
            "n": 0,
        }
        parar = _PARAR
    _anotar(
        caminho,
        {
            "tipo": "inicio",
            "id_fluxo": documento["id_fluxo"],
            "duracao_minutos": int(duracao_minutos),
            "inicio": _iso(agora),
            "fim": _iso(agora + int(duracao_minutos) * 60),
            "msm_id_publico": int(msm_id),
            "probe_id": int(probe_id),
            "medicao_criada": False,
        },
    )
    _gravar_estado()
    threading.Thread(
        target=_loop,
        args=(documento, int(probe_id), int(msm_id), agora, agora + int(duracao_minutos) * 60, caminho, parar),
        name="stream-ripe",
        daemon=True,
    ).start()
    return foto()
