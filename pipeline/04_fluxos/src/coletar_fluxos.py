"""Coleta os resultados ping de cada fluxo origem → destino da Etapa 3.

O msm_id de cada fluxo é o measurement_id já gravado. Não há nova seleção
de anchors, probes ou medições. Medição e anchor são baixadas uma vez e
reaproveitadas. Erro em um fluxo não interrompe os demais.

A cidade da origem, quando a probe é uma anchor, vem do JSON da Etapa 3.
A Etapa 1 não guarda o id da probe das origens.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import config


class ErroConsulta(Exception):
    pass


def preparar_saida():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


def garantir_pastas():
    for pasta in (
        config.CACHE_DIR,
        config.PROMPT_DIR,
        config.DATA_DIR,
        config.SRC_DIR,
        config.TEMPLATE_DIR,
    ):
        pasta.mkdir(parents=True, exist_ok=True)


def copiar_prompt():
    if config.ARQUIVO_PROMPT_ORIGEM.is_file():
        shutil.copyfile(config.ARQUIVO_PROMPT_ORIGEM, config.ARQUIVO_PROMPT)


def agora_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(instante):
    return instante.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def instante_de_argumento(texto):
    bruto = str(texto).strip()
    if bruto.endswith("Z"):
        bruto = bruto[:-1] + "+00:00"
    try:
        numero = float(bruto)
    except ValueError:
        numero = None
    if numero is not None and numero > 10**9:
        return datetime.fromtimestamp(numero, tz=timezone.utc).replace(microsecond=0)
    try:
        instante = datetime.fromisoformat(bruto)
    except ValueError as exc:
        raise SystemExit(f"Instante inválido: {texto}") from exc
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=timezone.utc)
    return instante.astimezone(timezone.utc).replace(microsecond=0)


def resolver_janela(inicio_arg, fim_arg):
    if (inicio_arg is None) != (fim_arg is None):
        raise SystemExit("Informe --inicio e --fim juntos, ou nenhum dos dois.")
    if inicio_arg is None:
        fim = agora_utc().replace(minute=0, second=0, microsecond=0)
        inicio = fim - timedelta(hours=config.JANELA_PADRAO_HORAS)
        return inicio, fim
    inicio = instante_de_argumento(inicio_arg)
    fim = instante_de_argumento(fim_arg)
    if fim <= inicio:
        raise SystemExit("A janela precisa terminar depois de começar.")
    return inicio, fim


def caminho_cache(url):
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return config.CACHE_DIR / f"{digest}.json"


def cache_aproveitavel(payload):
    bruto = payload.get("fetched_at")
    if not bruto:
        return False
    obtido = datetime.fromisoformat(bruto)
    if obtido.tzinfo is None:
        obtido = obtido.replace(tzinfo=timezone.utc)
    idade_horas = (datetime.now(timezone.utc) - obtido).total_seconds() / 3600
    return idade_horas < config.CACHE_TTL_HORAS


def ler_cache(url, sem_cache):
    if sem_cache:
        return None
    caminho = caminho_cache(url)
    if not caminho.is_file():
        return None
    try:
        payload = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("url") != url or not cache_aproveitavel(payload):
        return None
    return payload.get("body")


def gravar_cache(url, body):
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "url": url,
        "fetched_at": agora_utc().isoformat(),
        "body": body,
    }
    caminho_cache(url).write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def montar_url(base, params_ordenados):
    pares = []
    for chave, valor in params_ordenados:
        if isinstance(valor, bool):
            texto = "true" if valor else "false"
        else:
            texto = str(valor)
        pares.append((chave, texto))
    separador = "&" if urllib.parse.urlparse(base).query else "?"
    return base + separador + urllib.parse.urlencode(pares)


def obter_json(url, sem_cache):
    em_cache = ler_cache(url, sem_cache)
    if em_cache is not None:
        return em_cache
    ultimo_erro = None
    for tentativa in range(1, config.MAX_TENTATIVAS + 1):
        try:
            requisicao = urllib.request.Request(
                url,
                headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"},
            )
            with urllib.request.urlopen(requisicao, timeout=config.TIMEOUT_S) as resposta:
                bruto = resposta.read()
            if len(bruto) > config.MAX_BYTES_RESPOSTA:
                raise ErroConsulta(
                    f"resposta com {len(bruto)} bytes excede o limite em {url}"
                )
            body = json.loads(bruto.decode("utf-8"))
            gravar_cache(url, body)
            print(f"rede: {url}", flush=True)
            if config.PAUSA_S:
                time.sleep(config.PAUSA_S)
            return body
        except ErroConsulta:
            raise
        except urllib.error.HTTPError as exc:
            ultimo_erro = exc
            if exc.code == 429 or exc.code >= 500:
                espera = config.BACKOFF_S * tentativa
                print(
                    f"HTTP {exc.code}; nova tentativa em {espera:.0f}s "
                    f"({tentativa}/{config.MAX_TENTATIVAS})",
                    flush=True,
                )
                time.sleep(espera)
                continue
            detalhe = exc.read().decode("utf-8", errors="replace")[:300]
            raise ErroConsulta(f"HTTP {exc.code} em {url}: {detalhe}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            ultimo_erro = exc
            espera = config.BACKOFF_S * tentativa
            print(
                f"falha de rede ({exc}); nova tentativa em {espera:.0f}s "
                f"({tentativa}/{config.MAX_TENTATIVAS})",
                flush=True,
            )
            time.sleep(espera)
    raise ErroConsulta(f"Não foi possível consultar {url}: {ultimo_erro}")


def ler_json(caminho):
    return json.loads(caminho.read_text(encoding="utf-8"))


def inteiro(valor):
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, int):
        return valor
    if isinstance(valor, float) and valor.is_integer():
        return int(valor)
    if isinstance(valor, str) and valor.strip().lstrip("-").isdigit():
        return int(valor.strip())
    return None


def nome_status(status):
    if isinstance(status, dict):
        return status.get(config.CAMPO_STATUS_NOME)
    if isinstance(status, str):
        return status
    return None


def recortar(origem, campos):
    return {campo: origem.get(campo) for campo in campos}


def carregar_fluxos():
    etapa2 = ler_json(config.ARQUIVO_MEDICOES_ETAPA2)
    etapa3 = ler_json(config.ARQUIVO_PROBES_ETAPA3)
    ids_etapa2 = set()
    for anchor in etapa2.get(config.CHAVE_ANCHORS) or []:
        for medicao in anchor.get(config.CHAVE_MEDICOES) or []:
            msm_id = inteiro(medicao.get(config.CAMPO_ID))
            if msm_id is not None:
                ids_etapa2.add(msm_id)
    fluxos = []
    vistos = set()
    for anchor in etapa3.get(config.CHAVE_ANCHORS) or []:
        anchor_id = inteiro(anchor.get(config.CAMPO_ID))
        for probe in anchor.get(config.CHAVE_PROBES) or []:
            probe_id = inteiro(probe.get(config.CAMPO_ID))
            msm_id = inteiro(probe.get(config.CAMPO_MEASUREMENT_ID))
            if anchor_id is None or probe_id is None or msm_id is None:
                continue
            id_fluxo = config.FORMATO_ID_FLUXO.format(probe_id=probe_id, anchor_id=anchor_id)
            fluxo = {
                "id_fluxo": id_fluxo,
                "probe_id": probe_id,
                "anchor_id": anchor_id,
                "msm_id": msm_id,
                "origem_ip_etapa3": probe.get(config.CAMPO_ADDRESS),
                "origem_pais": probe.get(config.CAMPO_COUNTRY_CODE),
                "origem_cidade": probe.get(config.CAMPO_CITY) if probe.get(config.CAMPO_IS_ANCHOR) else None,
                "origem_e_anchor": bool(probe.get(config.CAMPO_IS_ANCHOR)),
                "destino_ip": anchor.get(config.CAMPO_IP),
                "destino_pais": anchor.get(config.CAMPO_COUNTRY),
                "destino_cidade": anchor.get(config.CAMPO_CITY),
                "destino_hostname": anchor.get(config.CAMPO_HOSTNAME),
                "repetido": id_fluxo in vistos,
                "ausente_etapa2": msm_id not in ids_etapa2,
            }
            vistos.add(id_fluxo)
            fluxos.append(fluxo)
    if not fluxos:
        raise SystemExit("O JSON da Etapa 3 não tem fluxos para coletar.")
    return fluxos


def url_medicao(msm_id):
    return config.URL_MEASUREMENTS.format(id=msm_id)


def url_anchor(anchor_id):
    return config.URL_ANCHORS.format(id=anchor_id)


def url_resultados(msm_id, probe_id, inicio_unix, fim_unix):
    base = config.URL_RESULTS.format(msm_id=msm_id)
    valores = {
        config.PARAM_PROBE_IDS: probe_id,
        config.PARAM_START: inicio_unix,
        config.PARAM_STOP: fim_unix,
        config.PARAM_FORMAT: config.FORMATO_RESULTADOS,
    }
    pares = [(chave, valores[chave]) for chave in config.ORDEM_PARAMS_RESULTS]
    return montar_url(base, pares)


def texto_celula(valor):
    if valor is None or valor == "":
        return ""
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, (list, dict)):
        return json.dumps(valor, ensure_ascii=False)
    if isinstance(valor, float):
        if valor != valor:
            return ""
        texto = format(valor, "f").rstrip("0").rstrip(".")
        return texto if texto not in ("", "-") else "0"
    return str(valor)


def numero(valor):
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, (int, float)):
        if isinstance(valor, float) and valor != valor:
            return None
        return valor
    return None


def resultado_tem_timeout(resultado):
    if not isinstance(resultado, list):
        return False
    for item in resultado:
        if isinstance(item, dict) and config.MARCADOR_TIMEOUT in item:
            return True
    return False


def rtt_valido(linha):
    for chave in config.CHAVES_RTT:
        valor = numero(linha.get(chave))
        if valor is None or valor < 0:
            return False
    return not resultado_tem_timeout(linha.get(config.CAMPO_RESULT))


def extrair_lista_resultados(body, url):
    if isinstance(body, list):
        return body, None
    if isinstance(body, dict):
        if body.get("error"):
            raise ErroConsulta(f"{body.get('error')} em {url}")
        itens = body.get("results")
        if isinstance(itens, list):
            return itens, body.get("next")
    raise ErroConsulta(f"formato de resultados inesperado em {url}")


def baixar_resultados(url, sem_cache, probe_id, inicio_unix, fim_unix):
    itens = []
    fora = 0
    visitadas = set()
    while url and url not in visitadas:
        visitadas.add(url)
        body = obter_json(url, sem_cache)
        pagina, proxima = extrair_lista_resultados(body, url)
        for item in pagina:
            if not isinstance(item, dict):
                continue
            prb = inteiro(item.get(config.CAMPO_PRB_ID))
            if prb is not None and prb != probe_id:
                continue
            instante = inteiro(item.get(config.CAMPO_TIMESTAMP))
            if instante is not None and (instante < inicio_unix or instante >= fim_unix):
                fora += 1
                continue
            itens.append(item)
        url = proxima
    return itens, fora


def consultar_uma_vez(url, sem_cache, memoria):
    if url in memoria:
        return memoria[url]
    try:
        memoria[url] = ("ok", obter_json(url, sem_cache))
    except ErroConsulta as exc:
        print(f"erro: {exc}", flush=True)
        memoria[url] = ("erro", str(exc))
    return memoria[url]


def meta_medicao(body):
    recorte = recortar(body, config.CAMPOS_MEDICAO)
    status = body.get(config.CAMPO_STATUS)
    nome = nome_status(status)
    recorte[config.CAMPO_STATUS] = {config.CAMPO_STATUS_NOME: nome} if nome else None
    return recorte


def meta_anchor(body):
    return recortar(body, config.CAMPOS_ANCHOR)


def constantes_resultado(itens):
    if not itens:
        return None
    base = recortar(itens[0], config.CAMPOS_RESULTADO_METADADO)
    variacoes = {}
    for campo in config.CAMPOS_RESULTADO_METADADO:
        valores = []
        for item in itens:
            valor = item.get(campo)
            if valor not in valores:
                valores.append(valor)
        if len(valores) > 1:
            variacoes[campo] = valores
    if variacoes:
        base["variacoes"] = variacoes
    return base


def montar_linha(fluxo, item, medicao):
    anchor_ip = None
    if medicao and medicao.get("anchor"):
        anchor_ip = medicao["anchor"].get(config.CAMPO_IP)
    if not anchor_ip:
        anchor_ip = item.get(config.CAMPO_DST) or fluxo["destino_ip"]
    packets = medicao["medicao"].get(config.CAMPO_PACKETS) if medicao and medicao.get("medicao") else None
    interval = medicao["medicao"].get(config.CAMPO_INTERVAL) if medicao and medicao.get("medicao") else None
    probe_id = inteiro(item.get(config.CAMPO_PRB_ID)) or fluxo["probe_id"]
    msm_id = inteiro(item.get("msm_id")) or fluxo["msm_id"]
    linha = {
        "anchor_id": fluxo["anchor_id"],
        "anchor_ip": anchor_ip,
        "probe_id": probe_id,
        "probe_ip": item.get(config.CAMPO_SRC),
        "msm_id": msm_id,
        "packets": packets,
        "interval": interval,
    }
    for campo in config.CAMPOS_RESULTADO_LINHA:
        linha[campo] = item.get(campo)
    return linha


def perda_alta(linhas):
    enviados = 0
    recebidos = 0
    for linha in linhas:
        sent = numero(linha.get(config.CAMPO_SENT))
        rcvd = numero(linha.get(config.CAMPO_RCVD))
        if sent is None:
            continue
        enviados += sent
        recebidos += rcvd or 0
    if enviados <= 0:
        return False
    perda = 100.0 * (enviados - recebidos) / enviados
    return perda >= config.PERDA_ALTA_PERCENT


def escolher_fluxo_pagina(fluxos, linhas_por_fluxo):
    if config.HTML_FLUXO:
        return config.HTML_FLUXO
    for fluxo in fluxos:
        if fluxo["destino_pais"] != config.PAIS_DESTAQUE or fluxo["repetido"]:
            continue
        if linhas_por_fluxo.get(fluxo["id_fluxo"]):
            return fluxo["id_fluxo"]
    for fluxo in fluxos:
        if fluxo["destino_pais"] == config.PAIS_DESTAQUE and not fluxo["repetido"]:
            return fluxo["id_fluxo"]
    return fluxos[0]["id_fluxo"]


def coletar(fluxos, inicio, fim, sem_cache):
    inicio_unix = int(inicio.timestamp())
    fim_unix = int(fim.timestamp())
    memoria = {}
    medicoes = {}
    anchors = {}
    probes_resultados = {}
    erros = []
    divergencias_af = []
    divergencias_medicao = []
    divergencias_anchor = []
    sem_resultado = []
    linhas = []
    linhas_por_fluxo = {}
    fora_janela = 0
    vistos_medicao = set()
    vistos_anchor = set()

    total = len(fluxos)
    for indice, fluxo in enumerate(fluxos, start=1):
        id_fluxo = fluxo["id_fluxo"]
        url_m = url_medicao(fluxo["msm_id"])
        url_a = url_anchor(fluxo["anchor_id"])
        url_r = url_resultados(fluxo["msm_id"], fluxo["probe_id"], inicio_unix, fim_unix)
        fluxo["url_medicao"] = url_m
        fluxo["url_anchor"] = url_a
        fluxo["url_resultados"] = url_r

        if fluxo["repetido"]:
            sem_resultado.append({"id_fluxo": id_fluxo, "url": url_r, "motivo": config.MOTIVO_ID_REPETIDO})
            print(f"{indice}/{total} {id_fluxo}: id repetido", flush=True)
            continue
        if fluxo["ausente_etapa2"] and fluxo["msm_id"] not in vistos_medicao:
            divergencias_medicao.append(
                {"msm_id": fluxo["msm_id"], "motivo": config.MOTIVO_FORA_ETAPA2, "url": url_m}
            )

        estado_m, corpo_m = consultar_uma_vez(url_m, sem_cache, memoria)
        medicao = None
        if estado_m == "ok" and isinstance(corpo_m, dict):
            medicao = meta_medicao(corpo_m)
            if fluxo["msm_id"] not in vistos_medicao:
                medicoes[url_m] = medicao
                tipo = medicao.get("type")
                status = nome_status(medicao.get(config.CAMPO_STATUS))
                if tipo != config.TIPO_MEDICAO or status != config.STATUS_ONGOING_NOME:
                    divergencias_medicao.append(
                        {
                            "msm_id": fluxo["msm_id"],
                            "type": tipo,
                            "status": status,
                            "url": url_m,
                        }
                    )
        elif fluxo["msm_id"] not in vistos_medicao:
            erros.append({"url": url_m, "motivo": corpo_m})
        vistos_medicao.add(fluxo["msm_id"])

        estado_a, corpo_a = consultar_uma_vez(url_a, sem_cache, memoria)
        anchor = None
        if estado_a == "ok" and isinstance(corpo_a, dict):
            anchor = meta_anchor(corpo_a)
            if fluxo["anchor_id"] not in vistos_anchor:
                anchors[url_a] = anchor
                if anchor.get(config.CAMPO_IS_DISABLED) is not False:
                    divergencias_anchor.append(
                        {
                            "anchor_id": fluxo["anchor_id"],
                            "is_disabled": anchor.get(config.CAMPO_IS_DISABLED),
                            "url": url_a,
                        }
                    )
        elif fluxo["anchor_id"] not in vistos_anchor:
            erros.append({"url": url_a, "motivo": corpo_a})
        vistos_anchor.add(fluxo["anchor_id"])

        contexto = {"medicao": medicao, "anchor": anchor}
        try:
            itens, fora = baixar_resultados(url_r, sem_cache, fluxo["probe_id"], inicio_unix, fim_unix)
        except ErroConsulta as exc:
            itens, fora = [], 0
            erros.append({"url": url_r, "id_fluxo": id_fluxo, "motivo": str(exc)})
            sem_resultado.append({"id_fluxo": id_fluxo, "url": url_r, "motivo": str(exc)})
            print(f"{indice}/{total} {id_fluxo}: erro", flush=True)
            continue
        fora_janela += fora
        if not itens:
            sem_resultado.append({"id_fluxo": id_fluxo, "url": url_r, "motivo": config.MOTIVO_SEM_RESULTADO})
            print(f"{indice}/{total} {id_fluxo}: sem resultado", flush=True)
            continue

        probes_resultados[url_r] = constantes_resultado(itens)
        linhas_fluxo = []
        for item in itens:
            af = item.get(config.CAMPO_AF)
            if af != config.ADDRESS_FAMILY:
                divergencias_af.append(
                    {
                        "id_fluxo": id_fluxo,
                        "msm_id": fluxo["msm_id"],
                        "prb_id": fluxo["probe_id"],
                        "af": af,
                        "timestamp": item.get(config.CAMPO_TIMESTAMP),
                        "url": url_r,
                    }
                )
            linhas_fluxo.append(montar_linha(fluxo, item, contexto))
        linhas.extend(linhas_fluxo)
        linhas_por_fluxo[id_fluxo] = linhas_fluxo
        print(f"{indice}/{total} {id_fluxo}: {len(linhas_fluxo)} resultados", flush=True)

    unicas = {}
    duplicatas = 0
    for linha in linhas:
        chave = (linha["probe_id"], linha["msm_id"], linha["timestamp"])
        if chave in unicas:
            duplicatas += 1
            continue
        unicas[chave] = linha
    ordenadas = sorted(
        unicas.values(),
        key=lambda linha: (
            inteiro(linha["anchor_id"]) or 0,
            inteiro(linha["probe_id"]) or 0,
            inteiro(linha["timestamp"]) or 0,
        ),
    )
    return {
        "linhas": ordenadas,
        "linhas_por_fluxo": {
            id_fluxo: sorted(
                grupo,
                key=lambda linha: inteiro(linha["timestamp"]) or 0,
            )
            for id_fluxo, grupo in linhas_por_fluxo.items()
        },
        "medicoes": medicoes,
        "anchors": anchors,
        "probes_resultados": probes_resultados,
        "erros": erros,
        "divergencias_af": divergencias_af,
        "divergencias_medicao": divergencias_medicao,
        "divergencias_anchor": divergencias_anchor,
        "sem_resultado": sem_resultado,
        "fora_janela": fora_janela,
        "duplicatas": duplicatas,
    }


def bloco_fluxo(fluxo, coleta, anchor):
    constantes = coleta["probes_resultados"].get(fluxo["url_resultados"]) or {}
    ip_origem = constantes.get(config.CAMPO_SRC) or fluxo["origem_ip_etapa3"]
    destino_ip = (anchor or {}).get(config.CAMPO_IP) or fluxo["destino_ip"]
    destino_pais = (anchor or {}).get(config.CAMPO_COUNTRY) or fluxo["destino_pais"]
    destino_cidade = (anchor or {}).get(config.CAMPO_CITY) or fluxo["destino_cidade"]
    destino_hostname = (anchor or {}).get(config.CAMPO_HOSTNAME) or fluxo["destino_hostname"]
    return {
        "probe_id": fluxo["probe_id"],
        "anchor_id": fluxo["anchor_id"],
        "msm_id": fluxo["msm_id"],
        "origem": {
            "ip": ip_origem,
            "pais": fluxo["origem_pais"],
            "cidade": fluxo["origem_cidade"],
        },
        "destino": {
            "ip": destino_ip,
            "pais": destino_pais,
            "cidade": destino_cidade,
            "hostname": destino_hostname,
        },
        "url_medicao": fluxo["url_medicao"],
        "url_anchor": fluxo["url_anchor"],
        "url_resultados": fluxo["url_resultados"],
    }


def montar_documento(fluxos, coleta, inicio, fim):
    por_id = {fluxo["id_fluxo"]: fluxo for fluxo in fluxos if not fluxo["repetido"]}
    fluxos_meta = {}
    for fluxo in fluxos:
        if fluxo["repetido"]:
            continue
        anchor = coleta["anchors"].get(fluxo["url_anchor"])
        fluxos_meta[fluxo["id_fluxo"]] = bloco_fluxo(fluxo, coleta, anchor)

    altos = [
        id_fluxo
        for id_fluxo, grupo in coleta["linhas_por_fluxo"].items()
        if perda_alta(grupo)
    ]
    rtts = sum(1 for linha in coleta["linhas"] if rtt_valido(linha))
    documento = {
        "coletado_em": agora_utc().isoformat(),
        "janela": {
            "inicio": iso(inicio),
            "fim": iso(fim),
            "fuso": config.FUSO,
        },
        "pagina": {"id_fluxo": escolher_fluxo_pagina(fluxos, coleta["linhas_por_fluxo"])},
        "fluxos": fluxos_meta,
        "medicoes": coleta["medicoes"],
        "anchors": coleta["anchors"],
        "probes_resultados": coleta["probes_resultados"],
        "divergencias_af": coleta["divergencias_af"],
        "divergencias_medicao": coleta["divergencias_medicao"],
        "divergencias_anchor": coleta["divergencias_anchor"],
        "fluxos_sem_resultado": coleta["sem_resultado"],
        "erros": coleta["erros"],
        "totais": {
            "fluxos": len(por_id),
            "linhas_csv": len(coleta["linhas"]),
            "rtts_validos": rtts,
            "fluxos_sem_dados": len(coleta["sem_resultado"]),
            "pares_perda_alta": len(altos),
            "pares_perda_alta_ids": altos,
            "divergencias_af": len(coleta["divergencias_af"]),
            "duplicatas_removidas": coleta["duplicatas"],
            "resultados_fora_da_janela": coleta["fora_janela"],
        },
        "limitacoes": list(config.LIMITACOES),
    }
    return documento


def preservar_coletado_em(documento):
    if not config.ARQUIVO_METADADOS.is_file():
        return
    try:
        anterior = ler_json(config.ARQUIVO_METADADOS)
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(anterior, dict) or "coletado_em" not in anterior:
        return
    novo = {chave: valor for chave, valor in documento.items() if chave != "coletado_em"}
    velho = {chave: valor for chave, valor in anterior.items() if chave != "coletado_em"}
    if novo == velho:
        documento["coletado_em"] = anterior["coletado_em"]


def gravar_csv(linhas):
    with config.ARQUIVO_CSV.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(
            arquivo,
            fieldnames=list(config.COLUNAS_CSV),
            lineterminator="\n",
            extrasaction="ignore",
        )
        escritor.writeheader()
        for linha in linhas:
            escritor.writerow({coluna: texto_celula(linha.get(coluna)) for coluna in config.COLUNAS_CSV})


def gravar_metadados(documento):
    config.ARQUIVO_METADADOS.write_text(
        json.dumps(documento, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def esc(valor):
    if valor is None or valor == "":
        return html.escape(config.ROTULO_VAZIO)
    return html.escape(str(valor))


def formatar_rtt(valor):
    numero_rtt = numero(valor)
    if numero_rtt is None:
        return config.ROTULO_VAZIO
    return f"{numero_rtt:.2f}"


def formatar_timestamp(valor):
    instante = inteiro(valor)
    if instante is None:
        return config.ROTULO_VAZIO
    texto = datetime.fromtimestamp(instante, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"{texto} ({instante})"


def valor_parametro(medicao, resultado, nome):
    if nome == "type":
        return (medicao or {}).get("type") or (resultado or {}).get("type")
    if nome == "af":
        return (resultado or {}).get(config.CAMPO_AF)
    if nome == "interval":
        return (medicao or {}).get(config.CAMPO_INTERVAL)
    if nome == "proto":
        return (resultado or {}).get("proto")
    if nome == "is_public":
        valor = (medicao or {}).get("is_public")
        if valor is True:
            return config.ROTULO_SIM
        if valor is False:
            return config.ROTULO_NAO
        return None
    if nome == "status":
        return nome_status((medicao or {}).get(config.CAMPO_STATUS))
    return None


def celula_tabela(linha, chave):
    if chave == "timestamp":
        return formatar_timestamp(linha.get(chave))
    if chave in config.CHAVES_RTT:
        return formatar_rtt(linha.get(chave))
    valor = linha.get(chave)
    if valor is None or valor == "":
        return config.ROTULO_VAZIO
    return str(valor)


def tabela_glossario():
    partes = []
    for secao in config.GLOSSARIO:
        partes.append(f"<h3>{esc(secao['titulo'])}</h3>")
        partes.append("<table><thead><tr>")
        for coluna in config.COLUNAS_GLOSSARIO:
            partes.append(f"<th>{esc(coluna)}</th>")
        partes.append("</tr></thead><tbody>")
        for feature, tipo, descricao, exemplo, utilidade in secao["linhas"]:
            partes.append(
                "<tr>"
                f"<td><code>{esc(feature)}</code></td>"
                f"<td>{esc(tipo)}</td>"
                f"<td>{esc(descricao)}</td>"
                f"<td><code>{esc(exemplo)}</code></td>"
                f"<td>{esc(utilidade)}</td>"
                "</tr>"
            )
        partes.append("</tbody></table>")
    partes.append(f"<h3>{esc(config.TITULO_DIAGRAMA)}</h3>")
    partes.append(f"<pre class=\"diagrama\">{esc(config.DIAGRAMA_RELACAO)}</pre>")
    return "\n".join(partes)


def bloco_json(titulo, url, corpo):
    texto = json.dumps(corpo, ensure_ascii=False, indent=2) if corpo is not None else config.ROTULO_VAZIO
    link = (
        f'<a href="{html.escape(url, quote=True)}">{esc(url)}</a>'
        if url
        else esc(config.ROTULO_VAZIO)
    )
    return (
        "<section class=\"bloco\">"
        f"<h3>{esc(titulo)}</h3>"
        f"<p class=\"url\">{link}</p>"
        f"<pre>{esc(texto)}</pre>"
        "</section>"
    )


def gerar_html(documento, fluxo, linhas_fluxo):
    mostradas = linhas_fluxo[: config.HTML_MAX_LINHAS]
    total = len(linhas_fluxo)
    aviso = config.AVISO_AMOSTRA.format(
        mostradas=len(mostradas),
        total=total,
        caminho=config.CAMINHO_DADOS_AVISO,
    )
    origem = fluxo["origem"]
    destino = fluxo["destino"]
    medicao = documento["medicoes"].get(fluxo["url_medicao"])
    anchor = documento["anchors"].get(fluxo["url_anchor"])
    resultado = documento["probes_resultados"].get(fluxo["url_resultados"])
    parametros = [
        ("type", valor_parametro(medicao, resultado, "type")),
        ("af", valor_parametro(medicao, resultado, "af")),
        ("interval", valor_parametro(medicao, resultado, "interval")),
        ("proto", valor_parametro(medicao, resultado, "proto")),
        ("is_public", valor_parametro(medicao, resultado, "is_public")),
        ("status", valor_parametro(medicao, resultado, "status")),
    ]
    chips = "".join(
        f"<span><code>{esc(nome)}</code> {esc(valor)}</span>" for nome, valor in parametros
    )
    cabecalho = "".join(f"<th>{esc(coluna['rotulo'])}</th>" for coluna in config.COLUNAS_HTML)
    corpo = []
    for linha in mostradas:
        celulas = "".join(
            f"<td>{esc(celula_tabela(linha, coluna['chave']))}</td>" for coluna in config.COLUNAS_HTML
        )
        corpo.append(f"<tr>{celulas}</tr>")
    if not corpo:
        corpo.append(
            f"<tr><td colspan=\"{len(config.COLUNAS_HTML)}\">{esc(config.TEXTO_SEM_LINHAS)}</td></tr>"
        )
    link_probe = config.URL_PAGINA_PROBE.format(id=fluxo["probe_id"])
    link_anchor = config.URL_PAGINA_ANCHOR.format(id=fluxo["anchor_id"])
    link_msm = config.URL_PAGINA_MEDICAO.format(id=fluxo["msm_id"])
    css = """
    :root { color-scheme: light; --bg:#f3f1ea; --ink:#1c1915; --muted:#5e584e; --card:#fffdf8; --line:#e4ddd0; --accent:#0f6e56; --br:#c45c26; }
    html[data-theme="dark"] { color-scheme: dark; --bg:#12171a; --ink:#f3f1ea; --muted:#b7b1a6; --card:#1c2428; --line:#314046; --accent:#3dbe9a; --br:#e5925d; }
    * { box-sizing: border-box; }
    body { margin:0; font-family:"Segoe UI","Helvetica Neue",sans-serif; background:var(--bg); color:var(--ink); }
    header, main { width:min(980px, calc(100% - 32px)); margin:0 auto; }
    header { padding:28px 0 8px; display:flex; justify-content:space-between; gap:16px; align-items:flex-start; }
    h1 { margin:8px 0; font-size:1.7rem; }
    h2 { margin:0 0 8px; font-size:1.15rem; }
    h3 { margin:18px 0 8px; font-size:1rem; }
    a { color:var(--br); }
    p { line-height:1.45; }
    .sub, .aviso, .url { color:var(--muted); }
    button { font:inherit; border:1px solid var(--line); background:var(--card); color:var(--ink); border-radius:999px; padding:8px 14px; cursor:pointer; }
    .voltar { color:var(--accent); text-decoration:none; }
    .fluxo { background:var(--card); border:1px solid var(--accent); border-radius:16px; padding:18px; margin:18px 0; }
    .par { display:flex; gap:12px; align-items:stretch; }
    .cartao { flex:1; border:1px solid var(--line); border-radius:14px; padding:14px; background:var(--bg); }
    .cartao p { margin:4px 0; }
    .papel { margin:0; color:var(--accent); font-size:.8rem; letter-spacing:.04em; }
    .seta { align-self:center; color:var(--accent); font-size:1.6rem; }
    .parametros { display:flex; flex-wrap:wrap; gap:8px; margin-top:8px; }
    .parametros span { border:1px solid var(--line); border-radius:999px; padding:6px 10px; background:var(--card); }
    .rolagem { overflow-x:auto; border:1px solid var(--line); border-radius:12px; }
    table { width:100%; border-collapse:collapse; background:var(--card); }
    th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); white-space:nowrap; vertical-align:top; }
    td { white-space:normal; }
    .glossario td { white-space:normal; }
    pre { white-space:pre-wrap; background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px; overflow:auto; }
    .bloco { margin-top:16px; }
    code { font-family:Consolas,monospace; }
    @media (max-width:700px) {
      header { flex-direction:column; }
      .par { flex-direction:column; }
      .seta { transform:rotate(90deg); align-self:center; }
    }
    """
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(config.TITULO_PAGINA)}</title>
  <style>{css}</style>
</head>
<body>
  <header>
    <div>
      <a class="voltar" href="{html.escape(config.LINK_INICIO, quote=True)}">← Início</a>
      <h1>{esc(config.TITULO_PAGINA)}</h1>
      <p class="aviso">{esc(aviso)}</p>
    </div>
    <button id="tema" type="button">Tema escuro</button>
  </header>
  <main>
    <section class="fluxo">
      <h2>FLUXO {esc(documento['pagina']['id_fluxo'])}</h2>
      <p>{esc(config.TEXTO_FLUXO)}</p>
      <div class="par">
        <article class="cartao">
          <p class="papel">{esc(config.ROTULO_ORIGEM)} (probe <a href="{html.escape(link_probe, quote=True)}">{esc(fluxo['probe_id'])}</a>)</p>
          <p>IP: {esc(origem['ip'])}</p>
          <p>Cidade: {esc(origem['cidade'])}</p>
          <p>País: {esc(origem['pais'])}</p>
        </article>
        <div class="seta" aria-hidden="true">→</div>
        <article class="cartao">
          <p class="papel">{esc(config.ROTULO_DESTINO)} (anchor <a href="{html.escape(link_anchor, quote=True)}">{esc(fluxo['anchor_id'])}</a>)</p>
          <p>IP: {esc(destino['ip'])}</p>
          <p>Cidade: {esc(destino['cidade'])}</p>
          <p>País: {esc(destino['pais'])}</p>
          <p>Hostname: {esc(destino['hostname'])}</p>
        </article>
      </div>
      <p>msm_id: <a href="{html.escape(link_msm, quote=True)}">{esc(fluxo['msm_id'])}</a></p>
    </section>
    <section>
      <h2>{esc(config.ROTULO_PARAMETROS)}</h2>
      <p>{esc(config.TEXTO_PARAMETROS)}</p>
      <div class="parametros">{chips}</div>
    </section>
    <section>
      <h2>Amostra</h2>
      <div class="rolagem">
        <table>
          <thead><tr>{cabecalho}</tr></thead>
          <tbody>
            {''.join(corpo)}
          </tbody>
        </table>
      </div>
    </section>
    <section class="glossario">
      <h2>{esc(config.ROTULO_GLOSSARIO)}</h2>
      {tabela_glossario()}
    </section>
    <section>
      <h2>{esc(config.ROTULO_METADADOS)}</h2>
      {bloco_json(config.ROTULO_MEDICAO, fluxo['url_medicao'], medicao)}
      {bloco_json(config.ROTULO_ANCHOR, fluxo['url_anchor'], anchor)}
      {bloco_json(config.ROTULO_RESULTADO, fluxo['url_resultados'], resultado)}
    </section>
  </main>
  <script>
    const raiz = document.documentElement;
    const botao = document.getElementById("tema");
    const salvo = localStorage.getItem("etapa-tema");
    const inicial = salvo || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    aplicar(inicial);
    botao.addEventListener("click", () => {{
      const proximo = raiz.getAttribute("data-theme") === "dark" ? "light" : "dark";
      localStorage.setItem("etapa-tema", proximo);
      aplicar(proximo);
    }});
    function aplicar(tema) {{
      raiz.setAttribute("data-theme", tema);
      botao.textContent = tema === "dark" ? "Tema claro" : "Tema escuro";
    }}
  </script>
</body>
</html>
"""


def cartao_etapa4(linhas):
    frase = f"{linhas} linhas de ping coletadas nos fluxos origem → destino."
    return (
        '<article class="cartao ativo">\n'
        f'      <p class="etapa">{html.escape(config.ROTULO_ETAPA4)}</p>\n'
        f"      <h2>{html.escape(config.TITULO_CARTAO)}</h2>\n"
        f"      <p>{html.escape(frase)}</p>\n"
        f'      <a href="{html.escape(config.LINK_ETAPA4, quote=True)}">Abrir página</a>\n'
        "    </article>"
    )


def atualizar_index(linhas):
    cartao = cartao_etapa4(linhas)
    bloco = f"{config.MARCADOR_ETAPA4_INICIO}\n    {cartao}\n    {config.MARCADOR_ETAPA4_FIM}"
    texto_atual = config.ARQUIVO_INDEX.read_text(encoding="utf-8")
    if config.MARCADOR_ETAPA4_INICIO in texto_atual and config.MARCADOR_ETAPA4_FIM in texto_atual:
        inicio = texto_atual.index(config.MARCADOR_ETAPA4_INICIO)
        fim = texto_atual.index(config.MARCADOR_ETAPA4_FIM) + len(config.MARCADOR_ETAPA4_FIM)
        config.ARQUIVO_INDEX.write_text(texto_atual[:inicio] + bloco + texto_atual[fim:], encoding="utf-8")
        return
    if config.MARCADOR_ETAPA3_FIM not in texto_atual:
        raise SystemExit("O index.html não tem o cartão da Etapa 3 para preservar o restante da página.")
    config.ARQUIVO_INDEX.write_text(
        texto_atual.replace(config.MARCADOR_ETAPA3_FIM, config.MARCADOR_ETAPA3_FIM + "\n" + bloco, 1),
        encoding="utf-8",
    )


def validar(fluxos, documento, linhas):
    problemas = []
    if list(config.COLUNAS_CSV) != [
        "anchor_id",
        "anchor_ip",
        "probe_id",
        "probe_ip",
        "msm_id",
        "ttl",
        "result",
        "dup",
        "rcvd",
        "sent",
        "min",
        "max",
        "avg",
        "timestamp",
        "type",
        "packets",
        "interval",
    ]:
        problemas.append("COLUNAS_CSV não está na ordem do contrato.")
    ids = [fluxo["id_fluxo"] for fluxo in fluxos if not fluxo["repetido"]]
    if len(ids) != len(set(ids)):
        problemas.append("há id_fluxo repetido.")
    if set(documento["fluxos"]) != set(ids):
        problemas.append("o metadado não cobre todos os fluxos da Etapa 3.")
    with config.ARQUIVO_CSV.open(encoding="utf-8", newline="") as arquivo:
        leitor = csv.reader(arquivo)
        cabecalho = next(leitor)
    if cabecalho != list(config.COLUNAS_CSV):
        problemas.append(f"cabeçalho do CSV: {cabecalho}")
    if linhas and set(linhas[0]) - set(config.COLUNAS_CSV):
        problemas.append("a linha do CSV tem campo fora do contrato.")
    return problemas


def imprimir_resumo(documento, problemas):
    totais = documento["totais"]
    print()
    print("=== Resumo da Etapa 4 ===")
    print(f"Janela UTC: {documento['janela']['inicio']} → {documento['janela']['fim']}")
    print(f"Fluxos: {totais['fluxos']}")
    print(f"Linhas no CSV: {totais['linhas_csv']}")
    print(f"RTTs válidos: {totais['rtts_validos']}")
    print(f"Fluxos sem dados: {totais['fluxos_sem_dados']}")
    print(f"Pares com perda alta: {totais['pares_perda_alta']}")
    if documento["divergencias_af"]:
        print(f"Divergências de af: {len(documento['divergencias_af'])}")
    if documento["divergencias_medicao"]:
        print(f"Divergências de medição: {len(documento['divergencias_medicao'])}")
    if documento["divergencias_anchor"]:
        print(f"Divergências de anchor: {len(documento['divergencias_anchor'])}")
    if documento["erros"]:
        print(f"Erros de consulta: {len(documento['erros'])}")
    print(f"Página: {documento['pagina']['id_fluxo']}")
    print(f"CSV: {config.ARQUIVO_CSV}")
    print(f"Metadados: {config.ARQUIVO_METADADOS}")
    print(f"HTML: {config.ARQUIVO_HTML}")
    if problemas:
        print("Validação:")
        for problema in problemas:
            print(f"  {problema}")
    print()


def main():
    preparar_saida()
    parser = argparse.ArgumentParser(description="Coleta os resultados ping dos fluxos da Etapa 3.")
    parser.add_argument("--sem-cache", action="store_true")
    parser.add_argument("--inicio", default=None, help="Início da janela em Unix ou ISO 8601 (UTC).")
    parser.add_argument("--fim", default=None, help="Fim da janela em Unix ou ISO 8601 (UTC).")
    args = parser.parse_args()
    garantir_pastas()
    copiar_prompt()
    inicio, fim = resolver_janela(args.inicio, args.fim)
    fluxos = carregar_fluxos()
    print(f"Fluxos na Etapa 3: {len(fluxos)}", flush=True)
    print(f"Janela UTC: {iso(inicio)} → {iso(fim)}", flush=True)
    coleta = coletar(fluxos, inicio, fim, args.sem_cache)
    documento = montar_documento(fluxos, coleta, inicio, fim)
    preservar_coletado_em(documento)
    gravar_csv(coleta["linhas"])
    gravar_metadados(documento)
    id_pagina = documento["pagina"]["id_fluxo"]
    fluxo_pagina = documento["fluxos"][id_pagina]
    gerar = gerar_html(documento, fluxo_pagina, coleta["linhas_por_fluxo"].get(id_pagina, []))
    config.ARQUIVO_HTML.write_text(gerar, encoding="utf-8")
    atualizar_index(documento["totais"]["linhas_csv"])
    problemas = validar(fluxos, documento, coleta["linhas"])
    imprimir_resumo(documento, problemas)
    if problemas:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
