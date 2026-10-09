"""Coleta os resultados ping dos períodos A e B e decide o uso de cada fluxo.

Não escolhe anchors, probes nem medições de novo. O msm_id vem da Etapa 3.
Medição e anchor são baixadas uma vez. Erro num fluxo não interrompe os outros.

fluxo_bruto.csv recebe só as linhas dos fluxos usados naquele período.
Quem não entra continua no metadado, com motivo. O processamento posterior
não é feito aqui e este script não altera o CSV depois de gravá-lo.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

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


def instante_de_texto(texto, nome):
    if texto is None or str(texto).strip() == "":
        raise SystemExit(
            f"O período {nome} está com início ou fim vazio. "
            "Preencha PERIODOS em config.py; a coleta não inventa datas."
        )
    bruto = str(texto).strip()
    if bruto.endswith("Z"):
        bruto = bruto[:-1] + "+00:00"
    try:
        instante = datetime.fromisoformat(bruto)
    except ValueError as exc:
        raise SystemExit(f"Data inválida no período {nome}: {texto}") from exc
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=timezone.utc)
    return instante.astimezone(timezone.utc).replace(microsecond=0)


def carregar_periodos():
    periodos = []
    nomes = []
    for item in config.PERIODOS:
        nome = item.get("nome")
        papel = item.get("papel")
        justificativa = item.get("justificativa")
        if not papel or not justificativa:
            raise SystemExit(f"O período {nome} precisa de papel e justificativa no config.")
        inicio = instante_de_texto(item.get("inicio"), nome)
        fim = instante_de_texto(item.get("fim"), nome)
        if not inicio < fim:
            raise SystemExit(f"O período {nome} precisa ter início anterior ao fim.")
        periodos.append(
            {
                "nome": nome,
                "inicio": inicio,
                "fim": fim,
                "papel": papel,
                "justificativa": justificativa,
                "duracao_s": int((fim - inicio).total_seconds()),
            }
        )
        nomes.append(nome)
    if config.PERIODO_BASELINE not in nomes or config.PERIODO_DATASET not in nomes:
        raise SystemExit("PERIODOS precisa conter os períodos A e B.")
    ordenados = sorted(periodos, key=lambda item: item["inicio"])
    for esquerda, direita in zip(ordenados, ordenados[1:]):
        if esquerda["fim"] > direita["inicio"]:
            raise SystemExit(
                f"Os períodos {esquerda['nome']} e {direita['nome']} se sobrepõem."
            )
    return periodos


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
        texto = "true" if valor is True else "false" if valor is False else str(valor)
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
                raise ErroConsulta(f"resposta com {len(bruto)} bytes excede o limite em {url}")
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


def numero(valor):
    if isinstance(valor, bool) or valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        if isinstance(valor, float) and valor != valor:
            return None
        return valor
    if isinstance(valor, str):
        try:
            return float(valor)
        except ValueError:
            return None
    return None


def nome_status(status):
    if isinstance(status, dict):
        return status.get(config.CAMPO_STATUS_NOME)
    if isinstance(status, str):
        return status
    return None


def recortar(origem, campos):
    return {campo: origem.get(campo) for campo in campos}


def af_da_etapa2():
    etapa2 = ler_json(config.ARQUIVO_MEDICOES_ETAPA2)
    mapa = {}
    for anchor in etapa2.get(config.CHAVE_ANCHORS) or []:
        for medicao in anchor.get(config.CHAVE_MEDICOES) or []:
            msm_id = inteiro(medicao.get(config.CAMPO_ID))
            if msm_id is None:
                continue
            mapa[msm_id] = medicao.get(config.CAMPO_AF)
    return mapa


def carregar_fluxos():
    etapa3 = ler_json(config.ARQUIVO_PROBES_ETAPA3)
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
            fluxos.append(
                {
                    "id_fluxo": id_fluxo,
                    "probe_id": probe_id,
                    "anchor_id": anchor_id,
                    "msm_id": msm_id,
                    "origem_ip_etapa3": probe.get(config.CAMPO_ADDRESS),
                    "origem_pais": probe.get(config.CAMPO_COUNTRY_CODE),
                    "origem_cidade": probe.get(config.CAMPO_CITY) if probe.get(config.CAMPO_IS_ANCHOR) else None,
                    "destino_ip": anchor.get(config.CAMPO_IP),
                    "destino_pais": anchor.get(config.CAMPO_COUNTRY),
                    "destino_cidade": anchor.get(config.CAMPO_CITY),
                    "destino_hostname": anchor.get(config.CAMPO_HOSTNAME),
                    "repetido": id_fluxo in vistos,
                }
            )
            vistos.add(id_fluxo)
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
    nome = nome_status(body.get(config.CAMPO_STATUS))
    recorte[config.CAMPO_STATUS] = {config.CAMPO_STATUS_NOME: nome} if nome else None
    return recorte


def meta_anchor(body):
    return recortar(body, config.CAMPOS_ANCHOR)


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
    divergencias = []
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
            if item.get(config.CAMPO_AF) != config.ADDRESS_FAMILY:
                divergencias.append(
                    {
                        "af": item.get(config.CAMPO_AF),
                        "timestamp": item.get(config.CAMPO_TIMESTAMP),
                        "url": url,
                    }
                )
            itens.append(item)
        url = proxima
    unicos = {}
    duplicatas = 0
    for item in itens:
        chave = (
            inteiro(item.get(config.CAMPO_PRB_ID)) or probe_id,
            inteiro(item.get("msm_id")),
            inteiro(item.get(config.CAMPO_TIMESTAMP)),
        )
        if chave in unicos:
            duplicatas += 1
            continue
        unicos[chave] = item
    return list(unicos.values()), fora, duplicatas, divergencias


def ttl_valido(valor):
    return numero(valor) is not None


def classificar_periodo(nome, n_linhas, esperado, ttl_validos, erro):
    """Decide se o fluxo é usado no período. A cobertura é linhas / esperado."""
    if erro:
        return {
            "linhas": 0,
            "esperado": esperado,
            "cobertura": None,
            "ttl_validos": 0,
            "usado": False,
            "motivo": erro,
        }
    cobertura = None
    if esperado:
        cobertura = round(100.0 * n_linhas / esperado, config.CASAS_COBERTURA)
    if n_linhas == 0:
        motivo = config.MOTIVO_SEM_RESULTADO
        usado = False
    elif cobertura is None or cobertura < config.COBERTURA_MINIMA_PERCENT:
        texto = "sem intervalo" if cobertura is None else f"{cobertura:.{config.CASAS_MOTIVO_COBERTURA}f}"
        motivo = config.MOTIVO_COBERTURA.format(cobertura=texto)
        usado = False
    elif nome == config.PERIODO_BASELINE and ttl_validos < config.MIN_AMOSTRAS_BASELINE:
        motivo = config.MOTIVO_TTL.format(n=config.MIN_AMOSTRAS_BASELINE)
        usado = False
    else:
        motivo = config.MOTIVO_OK
        usado = True
    return {
        "linhas": n_linhas,
        "esperado": esperado,
        "cobertura": cobertura,
        "ttl_validos": ttl_validos,
        "usado": usado,
        "motivo": motivo,
    }


def classe_do_fluxo(uso_a, uso_b):
    if uso_a and uso_b:
        return config.CLASSE_AMBOS
    if uso_b:
        return config.CLASSE_SO_DATASET
    if uso_a:
        return config.CLASSE_SO_BASELINE
    return config.CLASSE_NENHUM


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


def montar_linha(fluxo, periodo, item, medicao, anchor):
    anchor_ip = (anchor or {}).get(config.CAMPO_IP) or item.get(config.CAMPO_DST) or fluxo["destino_ip"]
    packets = (medicao or {}).get(config.CAMPO_PACKETS)
    interval = (medicao or {}).get(config.CAMPO_INTERVAL)
    linha = {
        "id_fluxo": fluxo["id_fluxo"],
        "periodo": periodo,
        "anchor_id": fluxo["anchor_id"],
        "anchor_ip": anchor_ip,
        "probe_id": inteiro(item.get(config.CAMPO_PRB_ID)) or fluxo["probe_id"],
        "probe_ip": item.get(config.CAMPO_SRC),
        "msm_id": inteiro(item.get("msm_id")) or fluxo["msm_id"],
        "packets": packets,
        "interval": interval,
    }
    for campo in config.CAMPOS_RESULTADO_LINHA:
        linha[campo] = item.get(campo)
    return linha


def motivo_medicao(medicao, af_etapa2):
    if not medicao:
        return None
    af = medicao.get(config.CAMPO_AF)
    if af != config.ADDRESS_FAMILY or af != af_etapa2:
        return config.MOTIVO_AF
    tipo = medicao.get(config.CAMPO_TYPE)
    status = nome_status(medicao.get(config.CAMPO_STATUS))
    if tipo != config.TIPO_MEDICAO or status != config.STATUS_ONGOING_NOME:
        return config.MOTIVO_TIPO
    return None


def escolher_pagina(fluxos, classes):
    if config.HTML_FLUXO:
        return config.HTML_FLUXO
    ambos = [
        fluxo["id_fluxo"]
        for fluxo in fluxos
        if not fluxo["repetido"]
        and fluxo["destino_pais"] == config.PAIS_DESTAQUE
        and classes.get(fluxo["id_fluxo"]) == config.CLASSE_AMBOS
    ]
    if ambos:
        return ambos[0]
    quaisquer = [
        fluxo["id_fluxo"]
        for fluxo in fluxos
        if not fluxo["repetido"] and classes.get(fluxo["id_fluxo"]) == config.CLASSE_AMBOS
    ]
    if quaisquer:
        return quaisquer[0]
    return next(fluxo["id_fluxo"] for fluxo in fluxos if not fluxo["repetido"])


def coletar(fluxos, periodos, sem_cache):
    af_map = af_da_etapa2()
    memoria = {}
    medicoes = {}
    anchors = {}
    linhas = []
    divergencias_af = []
    exclusoes = []
    usos = {}
    erros = []
    fora_janela = 0
    duplicatas = 0
    vistos_medicao = set()
    vistos_anchor = set()
    total = len([fluxo for fluxo in fluxos if not fluxo["repetido"]])
    indice = 0

    for fluxo in fluxos:
        id_fluxo = fluxo["id_fluxo"]
        if fluxo["repetido"]:
            usos[id_fluxo] = None
            continue
        indice += 1
        url_m = url_medicao(fluxo["msm_id"])
        url_a = url_anchor(fluxo["anchor_id"])
        fluxo["url_medicao"] = url_m
        fluxo["url_anchor"] = url_a
        estado_m, corpo_m = consultar_uma_vez(url_m, sem_cache, memoria)
        medicao = None
        if estado_m == "ok" and isinstance(corpo_m, dict):
            medicao = meta_medicao(corpo_m)
            if fluxo["msm_id"] not in vistos_medicao:
                medicoes[url_m] = medicao
        elif fluxo["msm_id"] not in vistos_medicao:
            erros.append({"url": url_m, "motivo": corpo_m})
        vistos_medicao.add(fluxo["msm_id"])

        estado_a, corpo_a = consultar_uma_vez(url_a, sem_cache, memoria)
        anchor = None
        if estado_a == "ok" and isinstance(corpo_a, dict):
            anchor = meta_anchor(corpo_a)
            if fluxo["anchor_id"] not in vistos_anchor:
                anchors[url_a] = anchor
        elif fluxo["anchor_id"] not in vistos_anchor:
            erros.append({"url": url_a, "motivo": corpo_a})
        vistos_anchor.add(fluxo["anchor_id"])

        bloqueio = None
        if estado_m != "ok":
            bloqueio = config.MOTIVO_REDE.format(mensagem=corpo_m)
        else:
            bloqueio = motivo_medicao(medicao, af_map.get(fluxo["msm_id"]))
        if anchor and anchor.get(config.CAMPO_IS_DISABLED) is not False and bloqueio is None:
            bloqueio = config.MOTIVO_ANCHOR_DESATIVADA
        if estado_a != "ok" and bloqueio is None:
            bloqueio = config.MOTIVO_REDE.format(mensagem=corpo_a)

        interval = numero((medicao or {}).get(config.CAMPO_INTERVAL))
        resumo_periodos = {}
        urls_resultados = {}
        for periodo in periodos:
            inicio_unix = int(periodo["inicio"].timestamp())
            fim_unix = int(periodo["fim"].timestamp())
            url_r = url_resultados(fluxo["msm_id"], fluxo["probe_id"], inicio_unix, fim_unix)
            urls_resultados[periodo["nome"]] = url_r
            esperado = (periodo["duracao_s"] / interval) if interval else None
            if bloqueio:
                resumo = classificar_periodo(periodo["nome"], 0, esperado, 0, bloqueio)
                resumo_periodos[periodo["nome"]] = resumo
                continue
            try:
                itens, fora, dups, divs = baixar_resultados(
                    url_r, sem_cache, fluxo["probe_id"], inicio_unix, fim_unix
                )
            except ErroConsulta as exc:
                erros.append({"url": url_r, "id_fluxo": id_fluxo, "motivo": str(exc)})
                resumo_periodos[periodo["nome"]] = classificar_periodo(
                    periodo["nome"], 0, esperado, 0, config.MOTIVO_REDE.format(mensagem=str(exc))
                )
                continue
            fora_janela += fora
            duplicatas += dups
            for div in divs:
                div["id_fluxo"] = id_fluxo
                div["msm_id"] = fluxo["msm_id"]
                div["prb_id"] = fluxo["probe_id"]
                div["periodo"] = periodo["nome"]
                divergencias_af.append(div)
            ttl_validos = sum(1 for item in itens if ttl_valido(item.get(config.CAMPO_TTL)))
            resumo = classificar_periodo(periodo["nome"], len(itens), esperado, ttl_validos, None)
            resumo_periodos[periodo["nome"]] = resumo
            if resumo["usado"]:
                for item in itens:
                    linhas.append(montar_linha(fluxo, periodo["nome"], item, medicao, anchor))
        usos[id_fluxo] = {
            "periodos": resumo_periodos,
            "urls": urls_resultados,
            "medicao": medicao,
            "anchor": anchor,
            "bloqueio": bloqueio,
        }
        classe = classe_do_fluxo(
            resumo_periodos[config.PERIODO_BASELINE]["usado"],
            resumo_periodos[config.PERIODO_DATASET]["usado"],
        )
        if bloqueio:
            exclusoes.append(
                {
                    "anchor_id": fluxo["anchor_id"],
                    "probe_id": fluxo["probe_id"],
                    "msm_id": fluxo["msm_id"],
                    "id_fluxo": id_fluxo,
                    "motivo": bloqueio,
                    "n": 0,
                }
            )
        partes = []
        for periodo in periodos:
            item = resumo_periodos[periodo["nome"]]
            partes.append(f"{periodo['nome']}={item['linhas']}")
        print(f"{indice}/{total} {id_fluxo}: {classe} ({', '.join(partes)})", flush=True)

    unicas = {}
    duplicatas_csv = 0
    for linha in linhas:
        chave = (linha["probe_id"], linha["msm_id"], linha["timestamp"])
        if chave in unicas:
            duplicatas_csv += 1
            continue
        unicas[chave] = linha
    ordenadas = sorted(
        unicas.values(),
        key=lambda linha: (
            str(linha["periodo"]),
            inteiro(linha["anchor_id"]) or 0,
            inteiro(linha["probe_id"]) or 0,
            inteiro(linha["timestamp"]) or 0,
        ),
    )
    return {
        "linhas": ordenadas,
        "medicoes": medicoes,
        "anchors": anchors,
        "usos": usos,
        "divergencias_af": divergencias_af,
        "exclusoes": exclusoes,
        "erros": erros,
        "fora_janela": fora_janela,
        "duplicatas": duplicatas + duplicatas_csv,
    }


def ip_origem(fluxo, linhas_fluxo):
    for linha in reversed(linhas_fluxo):
        if linha.get("probe_ip"):
            return linha["probe_ip"]
    return fluxo["origem_ip_etapa3"]


def parametros_comuns(medicoes):
    campos = {
        config.CAMPO_TYPE: [],
        config.CAMPO_AF: [],
        "status": [],
        config.CAMPO_INTERVAL: [],
        config.CAMPO_IS_PUBLIC: [],
    }
    for medicao in medicoes.values():
        campos[config.CAMPO_TYPE].append(medicao.get(config.CAMPO_TYPE))
        campos[config.CAMPO_AF].append(medicao.get(config.CAMPO_AF))
        campos["status"].append(nome_status(medicao.get(config.CAMPO_STATUS)))
        campos[config.CAMPO_INTERVAL].append(medicao.get(config.CAMPO_INTERVAL))
        campos[config.CAMPO_IS_PUBLIC].append(medicao.get(config.CAMPO_IS_PUBLIC))
    comuns = {}
    divergentes = []
    for campo, valores in campos.items():
        distintos = []
        for valor in valores:
            if valor not in distintos:
                distintos.append(valor)
        if len(distintos) == 1:
            comuns[campo] = distintos[0]
        else:
            comuns[campo] = None
            divergentes.append({"campo": campo, "valores": distintos})
    return comuns, divergentes


def montar_documento(fluxos, periodos, coleta):
    classes = {}
    fluxos_meta = {}
    linhas_por_fluxo = {}
    for linha in coleta["linhas"]:
        linhas_por_fluxo.setdefault(linha["id_fluxo"], []).append(linha)
    for fluxo in fluxos:
        if fluxo["repetido"]:
            continue
        uso = coleta["usos"][fluxo["id_fluxo"]]
        classe = classe_do_fluxo(
            uso["periodos"][config.PERIODO_BASELINE]["usado"],
            uso["periodos"][config.PERIODO_DATASET]["usado"],
        )
        classes[fluxo["id_fluxo"]] = classe
        anchor = uso["anchor"] or {}
        por_periodo = {}
        for nome, resumo in uso["periodos"].items():
            por_periodo[nome] = {
                "linhas": resumo["linhas"],
                "esperado": resumo["esperado"],
                "cobertura": resumo["cobertura"],
                "ttl_validos": resumo["ttl_validos"],
                "usado": resumo["usado"],
                "motivo": resumo["motivo"],
                "url_resultados": uso["urls"][nome],
            }
        fluxos_meta[fluxo["id_fluxo"]] = {
            "probe_id": fluxo["probe_id"],
            "anchor_id": fluxo["anchor_id"],
            "msm_id": fluxo["msm_id"],
            "classe": classe,
            "origem": {
                "ip": ip_origem(fluxo, linhas_por_fluxo.get(fluxo["id_fluxo"], [])),
                "pais": fluxo["origem_pais"],
                "cidade": fluxo["origem_cidade"],
            },
            "destino": {
                "ip": anchor.get(config.CAMPO_IP) or fluxo["destino_ip"],
                "pais": anchor.get(config.CAMPO_COUNTRY) or fluxo["destino_pais"],
                "cidade": anchor.get(config.CAMPO_CITY) or fluxo["destino_cidade"],
                "hostname": anchor.get(config.CAMPO_HOSTNAME) or fluxo["destino_hostname"],
            },
            "periodos": por_periodo,
            "url_medicao": fluxo["url_medicao"],
            "url_anchor": fluxo["url_anchor"],
        }
    comuns, divergentes = parametros_comuns(coleta["medicoes"])
    contagem = {nome: 0 for nome in config.ORDEM_CLASSES}
    for classe in classes.values():
        contagem[classe] = contagem.get(classe, 0) + 1
    linhas_periodo = {periodo["nome"]: 0 for periodo in periodos}
    for linha in coleta["linhas"]:
        linhas_periodo[linha["periodo"]] = linhas_periodo.get(linha["periodo"], 0) + 1
    documento = {
        "coletado_em": agora_utc().isoformat(),
        "fuso": config.FUSO,
        "periodos": [
            {
                "nome": periodo["nome"],
                "inicio": periodo["inicio"].isoformat(),
                "fim": periodo["fim"].isoformat(),
                "fuso": config.FUSO,
                "papel": periodo["papel"],
                "justificativa": periodo["justificativa"],
                "duracao_s": periodo["duracao_s"],
            }
            for periodo in periodos
        ],
        "regra_uso": {
            "cobertura_minima_percent": config.COBERTURA_MINIMA_PERCENT,
            "min_amostras_baseline": config.MIN_AMOSTRAS_BASELINE,
            "texto": config.TEXTO_REGRA.format(
                cobertura=config.COBERTURA_MINIMA_PERCENT,
                amostras=config.MIN_AMOSTRAS_BASELINE,
            ),
        },
        "parametros_comuns": comuns,
        "parametros_divergentes": divergentes,
        "pagina": {"id_fluxo": escolher_pagina(fluxos, classes)},
        "fluxos": fluxos_meta,
        "medicoes": coleta["medicoes"],
        "anchors": coleta["anchors"],
        "divergencias_af": coleta["divergencias_af"],
        "exclusoes_medicao": coleta["exclusoes"],
        "erros": coleta["erros"],
        "totais": {
            "fluxos": len(fluxos_meta),
            "por_classe": contagem,
            "linhas_por_periodo": linhas_periodo,
            "linhas_csv": len(coleta["linhas"]),
            "duplicatas_removidas": coleta["duplicatas"],
            "resultados_fora_da_janela": coleta["fora_janela"],
            "divergencias_af": len(coleta["divergencias_af"]),
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
    with config.ARQUIVO_CSV_BRUTO.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(
            arquivo,
            fieldnames=list(config.COLUNAS_CSV_BRUTO),
            lineterminator="\n",
            extrasaction="ignore",
        )
        escritor.writeheader()
        for linha in linhas:
            escritor.writerow({coluna: texto_celula(linha.get(coluna)) for coluna in config.COLUNAS_CSV_BRUTO})


def gravar_metadados(documento):
    config.ARQUIVO_METADADOS.write_text(
        json.dumps(documento, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def imprimir_resumo(documento):
    totais = documento["totais"]
    print()
    print("=== Resumo da coleta (Etapa 5) ===")
    for periodo in documento["periodos"]:
        print(f"Período {periodo['nome']} ({periodo['papel']}): {periodo['inicio']} → {periodo['fim']}")
    print("Fluxos por classe:")
    for classe in config.ORDEM_CLASSES:
        print(f"  {classe}: {totais['por_classe'].get(classe, 0)}")
    print("Linhas no bruto por período:")
    for nome, quantidade in totais["linhas_por_periodo"].items():
        print(f"  {nome}: {quantidade}")
    print(f"Página: {documento['pagina']['id_fluxo']}")
    print(f"CSV: {config.ARQUIVO_CSV_BRUTO}")
    print(f"Metadados: {config.ARQUIVO_METADADOS}")
    print()


def main():
    preparar_saida()
    parser = argparse.ArgumentParser(description="Coleta os períodos A e B dos fluxos da Etapa 3.")
    parser.add_argument("--sem-cache", action="store_true")
    args = parser.parse_args()
    garantir_pastas()
    copiar_prompt()
    periodos = carregar_periodos()
    fluxos = carregar_fluxos()
    print(f"Fluxos na Etapa 3: {sum(1 for fluxo in fluxos if not fluxo['repetido'])}", flush=True)
    for periodo in periodos:
        print(
            f"Período {periodo['nome']}: {periodo['inicio'].isoformat()} → {periodo['fim'].isoformat()}",
            flush=True,
        )
    coleta = coletar(fluxos, periodos, args.sem_cache)
    documento = montar_documento(fluxos, periodos, coleta)
    preservar_coletado_em(documento)
    gravar_csv(coleta["linhas"])
    gravar_metadados(documento)
    imprimir_resumo(documento)


if __name__ == "__main__":
    main()
