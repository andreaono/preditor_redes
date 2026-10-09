"""Seleciona de 3 a 5 probes de origem para cada anchor da Etapa 1.

Os IDs de medição vêm só do JSON da Etapa 2. Os participantes saem de
GET /measurements/{id}/?optional_fields=current_probes (metadado).
Não se baixam resultados.

Desempate: candidatas ordenadas por id; Random(SEED) só escolhe dentro
do grupo que já empatou na estratificação. Anchors na ordem do JSON da
Etapa 2, um único gerador para toda a execução. Com 3 ou 4 elegíveis,
não há sorteio: entram todas.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import random
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
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
    payload = {
        "url": url,
        "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "body": body,
    }
    caminho_cache(url).write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def montar_url(base, params):
    pares = []
    for chave, valor in params.items():
        if isinstance(valor, bool):
            texto = "true" if valor else "false"
        else:
            texto = str(valor)
        pares.append((chave, texto))
    separador = "&" if urllib.parse.urlparse(base).query else "?"
    return base + separador + urllib.parse.urlencode(pares)


def url_proibida(url):
    caminho = urllib.parse.urlparse(url).path.rstrip("/")
    return caminho.endswith("/results")


def obter_json(url, sem_cache):
    if url_proibida(url):
        raise ErroConsulta(f"bloqueado o download de resultados: {url}")
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
                body = json.loads(resposta.read().decode("utf-8"))
            gravar_cache(url, body)
            print(f"rede: {url}", flush=True)
            if config.PAUSA_S:
                time.sleep(config.PAUSA_S)
            return body
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


def paginar(url, sem_cache):
    itens = []
    while url:
        if url_proibida(url):
            raise ErroConsulta(f"paginação apontou para resultados: {url}")
        pagina = obter_json(url, sem_cache)
        itens.extend(pagina.get("results") or [])
        url = pagina.get("next")
    return itens


def texto(valor):
    if valor is None:
        return None
    if isinstance(valor, str):
        limpo = valor.strip()
        return limpo or None
    return valor


def carregar_entradas():
    etapa1 = json.loads(config.ARQUIVO_ANCHORS_ETAPA1.read_text(encoding="utf-8"))
    etapa2 = json.loads(config.ARQUIVO_MEDICOES_ETAPA2.read_text(encoding="utf-8"))
    faixas = etapa1.get("meta", {}).get(config.CHAVE_FAIXAS)
    if not isinstance(faixas, dict) or not faixas:
        raise SystemExit("meta.faixas_km não está no JSON da Etapa 1.")
    por_id = {anchor["id"]: anchor for anchor in etapa1.get(config.CHAVE_ANCHORS) or []}
    anchors = etapa2.get(config.CHAVE_ANCHORS) or []
    if len(anchors) != config.TOTAL_DESTINOS:
        raise SystemExit(f"A Etapa 2 tem {len(anchors)} anchors; o esperado é {config.TOTAL_DESTINOS}.")
    return por_id, anchors, faixas


def medicao_ipv4(med):
    if med.get("type") != config.TIPO_MEDICAO:
        return False
    if med.get("af") != config.ADDRESS_FAMILY:
        return False
    if med.get("status") != config.STATUS_MEDICAO_OK:
        return False
    if config.EXIGIR_MEDICAO_PUBLICA and not med.get("is_public"):
        return False
    return med.get("id") is not None


def url_participantes(med_id):
    base = f"{config.URL_MEASUREMENTS.rstrip('/')}/{int(med_id)}/"
    return montar_url(base, {"optional_fields": config.CAMPO_PARTICIPANTES})


def ids_participantes(corpo):
    atuais = corpo.get(config.CAMPO_PARTICIPANTES)
    if isinstance(atuais, list):
        return [int(item) for item in atuais if isinstance(item, int) or str(item).isdigit()]
    objetos = corpo.get(config.CAMPO_PARTICIPANTES_OBJETOS)
    if isinstance(objetos, list):
        ids = []
        for item in objetos:
            if isinstance(item, dict) and item.get("id") is not None:
                ids.append(int(item["id"]))
            elif isinstance(item, int):
                ids.append(item)
        return ids
    return []


def participantes_por_medicao(med_ids, sem_cache, erros):
    saida = {}
    for med_id in med_ids:
        try:
            corpo = obter_json(url_participantes(med_id), sem_cache)
            saida[med_id] = ids_participantes(corpo)
            print(f"medição {med_id}: {len(saida[med_id])} participantes", flush=True)
        except ErroConsulta as exc:
            saida[med_id] = []
            erros.append({"measurement_id": med_id, "erro": str(exc)})
            print(f"erro na medição {med_id}: {exc}", flush=True)
    return saida


def url_lote_probes(ids):
    return montar_url(
        config.URL_PROBES,
        {"id__in": ",".join(str(item) for item in ids), "page_size": config.TAMANHO_PAGINA},
    )


def buscar_probes(ids, sem_cache, erros):
    detalhes = {}
    ordenados = sorted(set(ids))
    for inicio in range(0, len(ordenados), config.LOTE_PROBES):
        lote = ordenados[inicio : inicio + config.LOTE_PROBES]
        try:
            itens = paginar(url_lote_probes(lote), sem_cache)
        except ErroConsulta as exc:
            erros.append({"probes": lote[:5], "erro": str(exc)})
            print(f"erro no lote de probes: {exc}", flush=True)
            continue
        for probe in itens:
            if probe.get("id") is not None:
                detalhes[int(probe["id"])] = probe
        print(f"probes carregadas: {len(detalhes)}", flush=True)
    return detalhes


def buscar_anchors(sem_cache):
    url = montar_url(config.URL_ANCHORS, {"page_size": max(config.TAMANHO_PAGINA, 500)})
    probe_cidade = {}
    anchor_probe = {}
    for ancora in paginar(url, sem_cache):
        probe_id = ancora.get("probe")
        if probe_id is None:
            continue
        probe_id = int(probe_id)
        anchor_probe[int(ancora["id"])] = probe_id
        cidade = texto(ancora.get("city"))
        if cidade:
            probe_cidade[probe_id] = cidade
    return probe_cidade, anchor_probe


def haversine_km(origem, destino):
    lon1, lat1 = origem
    lon2, lat2 = destino
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * config.RAIO_TERRA_KM * math.asin(math.sqrt(a))


def classificar_faixa(distancia_km, faixas):
    limites = sorted(
        ((nome, dados["max_exclusivo"]) for nome, dados in faixas.items()),
        key=lambda item: item[1],
    )
    for nome, limite in limites:
        if distancia_km < limite:
            return nome
    return config.FAIXA_LONGA


def coordenadas_probe(probe):
    geometria = probe.get("geometry") or {}
    coords = geometria.get("coordinates")
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        return None
    try:
        lon = float(coords[0])
        lat = float(coords[1])
    except (TypeError, ValueError):
        return None
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    return [lon, lat]


def slugs(probe):
    saida = []
    for tag in probe.get("tags") or []:
        if isinstance(tag, dict) and tag.get("slug"):
            saida.append(tag["slug"])
        elif isinstance(tag, str) and tag.strip():
            saida.append(tag.strip())
    return saida


def candidata_de(probe, med_ids, destino, cidade_anchor, faixas):
    coords = coordenadas_probe(probe)
    destino_coords = destino.get("coordinates")
    if coords is None or not destino_coords or len(destino_coords) < 2:
        return None
    distancia = round(haversine_km(coords, destino_coords), 1)
    pais = (probe.get("country_code") or "").upper() or None
    return {
        "id": int(probe["id"]),
        "country_code": pais,
        "description": texto(probe.get("description")),
        "longitude": coords[0],
        "latitude": coords[1],
        "is_anchor": bool(probe.get("is_anchor")),
        "is_public": True,
        "status": (probe.get("status") or {}).get("name"),
        "address_v4": texto(probe.get("address_v4")),
        "asn_v4": probe.get("asn_v4"),
        "tags": slugs(probe),
        "city": cidade_anchor if probe.get("is_anchor") else None,
        "measurement_ids": sorted(med_ids),
        "measurement_id": min(med_ids),
        "distance_km": distancia,
        "distance_band": classificar_faixa(distancia, faixas),
        "continente": config.PAIS_CONTINENTE.get(pais or "", config.CONTINENTE_DESCONHECIDO),
    }


def probe_elegivel(probe, destino, probe_destino_id):
    if not probe.get("is_public"):
        return False
    status = probe.get("status") or {}
    if status.get("name") != config.STATUS_PROBE_OK:
        return False
    if not texto(probe.get("address_v4")):
        return False
    if probe_destino_id is not None and int(probe["id"]) == int(probe_destino_id):
        return False
    if texto(probe.get("address_v4")) == texto(destino.get("ip_v4")):
        return False
    return True


def escolher(candidatas, rng, quantidade):
    selecionadas = []
    asns = set()
    bandas = set()
    continentes = set()
    paises = set()
    while len(selecionadas) < quantidade:
        restantes = [item for item in candidatas if item["id"] not in {p["id"] for p in selecionadas}]
        if not restantes:
            break
        comuns = sum(1 for item in selecionadas if not item["is_anchor"])

        def nota(item):
            falta_comum = comuns < config.MIN_PROBES_COMUNS
            bonus_comum = 0
            if falta_comum:
                bonus_comum = 0 if not item["is_anchor"] else 1
            bonus_asn = 0 if item["asn_v4"] is None or item["asn_v4"] not in asns else 1
            bonus_banda = 0 if item["distance_band"] not in bandas else 1
            bonus_continente = 0 if item["continente"] not in continentes else 1
            bonus_pais = 0 if item["country_code"] not in paises else 1
            return (bonus_comum, bonus_asn, bonus_banda, bonus_continente, bonus_pais)

        melhor = min(nota(item) for item in restantes)
        grupo = sorted((item for item in restantes if nota(item) == melhor), key=lambda item: item["id"])
        escolhida = rng.choice(grupo)
        selecionadas.append(escolhida)
        if escolhida["asn_v4"] is not None:
            asns.add(escolhida["asn_v4"])
        bandas.add(escolhida["distance_band"])
        continentes.add(escolhida["continente"])
        paises.add(escolhida["country_code"])
    return selecionadas


def selecionar(candidatas, rng):
    ordenadas = sorted(candidatas, key=lambda item: item["id"])
    n = len(ordenadas)
    if n == 0:
        return [], False
    if n < config.MIN_PROBES:
        return escolher(ordenadas, rng, config.PROBES_QUANDO_POUCAS), True
    if n < config.MAX_PROBES:
        return ordenadas, False
    return escolher(ordenadas, rng, config.MAX_PROBES), False


def montar_destino(anchor2, anchor1, participantes, detalhes, cidades, probe_destino, faixas, rng, erros_locais):
    medicoes = [med for med in anchor2.get("medicoes") or [] if medicao_ipv4(med)]
    limitacoes = []
    if not medicoes:
        limitacoes.append("sem medição IPv4")
    participacao = {}
    for med in medicoes:
        for probe_id in participantes.get(med["id"], []):
            participacao.setdefault(probe_id, set()).add(med["id"])
    destino = {
        "id": anchor2["id"],
        "country": anchor2.get("country"),
        "city": anchor2.get("city"),
        "hostname": anchor2.get("hostname"),
        "ip_v4": anchor2.get("ip_v4"),
        "coordinates": (anchor1 or {}).get("coordinates"),
    }
    candidatas = []
    sem_coord = 0
    for probe_id, med_ids in participacao.items():
        probe = detalhes.get(probe_id)
        if probe is None:
            continue
        if not probe_elegivel(probe, destino, probe_destino):
            continue
        cidade = cidades.get(probe_id) if probe.get("is_anchor") else None
        pronta = candidata_de(probe, med_ids, destino, cidade, faixas)
        if pronta is None:
            sem_coord += 1
            continue
        candidatas.append(pronta)
    if sem_coord:
        erros_locais.append({"anchor_id": anchor2["id"], "probes_sem_coordenadas": sem_coord})
    if candidatas and not any(not item["is_anchor"] for item in candidatas):
        limitacoes.append("somente anchors como origem")
    escolhidas, poucas = selecionar(candidatas, rng)
    return {
        "id": destino["id"],
        "country": destino["country"],
        "city": destino["city"],
        "hostname": destino["hostname"],
        "ip_v4": destino["ip_v4"],
        "elegiveis": len(candidatas),
        "poucas_origens": poucas,
        "limitacoes": limitacoes,
        "probes": escolhidas,
    }


def processar(sem_cache):
    por_id, anchors, faixas = carregar_entradas()
    erros = []
    med_ids = []
    for anchor in anchors:
        for med in anchor.get("medicoes") or []:
            if medicao_ipv4(med) and med["id"] not in med_ids:
                med_ids.append(med["id"])
    print(f"Medições IPv4 da Etapa 2: {len(med_ids)}", flush=True)
    participantes = participantes_por_medicao(med_ids, sem_cache, erros)
    todos_ids = {probe_id for ids in participantes.values() for probe_id in ids}
    print(f"Probes distintas nas medições: {len(todos_ids)}", flush=True)
    detalhes = buscar_probes(todos_ids, sem_cache, erros)
    cidades, anchor_probe = buscar_anchors(sem_cache)
    rng = random.Random(config.SEED)
    saida = []
    sem_coord = []
    for anchor in anchors:
        anchor1 = por_id.get(anchor["id"])
        probe_destino = anchor_probe.get(anchor["id"])
        saida.append(
            montar_destino(
                anchor, anchor1, participantes, detalhes, cidades, probe_destino, faixas, rng, sem_coord
            )
        )
        print(
            f"{anchor.get('country')} {anchor.get('hostname')}: "
            f"{len(saida[-1]['probes'])} origens "
            f"({saida[-1]['elegiveis']} elegíveis)",
            flush=True,
        )
    return saida, faixas, erros, sem_coord


def validar(anchors):
    problemas = []
    if len(anchors) != config.TOTAL_DESTINOS:
        problemas.append(f"destinos {len(anchors)}")
    for anchor in anchors:
        n = anchor["elegiveis"]
        k = len(anchor["probes"])
        ids = [probe["id"] for probe in anchor["probes"]]
        if len(ids) != len(set(ids)):
            problemas.append(f"anchor {anchor['id']} com probe repetida")
        if n >= config.MAX_PROBES and k != config.MAX_PROBES:
            problemas.append(f"anchor {anchor['id']} deveria ter {config.MAX_PROBES} probes")
        elif config.MIN_PROBES <= n < config.MAX_PROBES and k != n:
            problemas.append(f"anchor {anchor['id']} deveria manter as {n} elegíveis")
        elif 0 < n < config.MIN_PROBES and (k != config.PROBES_QUANDO_POUCAS or not anchor["poucas_origens"]):
            problemas.append(f"anchor {anchor['id']} deveria ter 1 probe e o aviso de poucas origens")
        elif n == 0 and k != 0:
            problemas.append(f"anchor {anchor['id']} sem elegíveis mas com probes")
        for probe in anchor["probes"]:
            if probe["is_public"] is not True or probe["status"] != config.STATUS_PROBE_OK:
                problemas.append(f"probe {probe['id']} fora do filtro")
            if not probe["address_v4"]:
                problemas.append(f"probe {probe['id']} sem IPv4")
            if probe["address_v4"] == anchor["ip_v4"]:
                problemas.append(f"probe {probe['id']} é o destino")
            if probe["measurement_id"] not in probe["measurement_ids"]:
                problemas.append(f"probe {probe['id']} sem medição de origem")
        if n and any(not item["is_anchor"] for item in anchor["probes"]) is False:
            if "somente anchors como origem" not in anchor["limitacoes"] and k:
                problemas.append(f"anchor {anchor['id']} sem probe comum apesar de haver candidatas")
    return problemas


def resumo(anchors):
    vinculos = [probe for anchor in anchors for probe in anchor["probes"]]
    distintas = {probe["id"]: probe for probe in vinculos}
    por_continente = Counter(probe["continente"] for probe in distintas.values())
    por_asn = Counter(probe["asn_v4"] for probe in distintas.values() if probe["asn_v4"] is not None)
    comuns = sum(1 for probe in distintas.values() if not probe["is_anchor"])
    anchors_origem = len(distintas) - comuns
    return {
        "destinos": len(anchors),
        "vinculos": len(vinculos),
        "probes_distintas": len(distintas),
        "anchors_com_uma_probe": sum(1 for anchor in anchors if anchor["poucas_origens"]),
        "anchors_sem_probe": sum(1 for anchor in anchors if not anchor["probes"]),
        "probes_comuns": comuns,
        "probes_anchor": anchors_origem,
        "por_continente": dict(sorted(por_continente.items())),
        "por_asn": {str(asn): qtd for asn, qtd in sorted(por_asn.items(), key=lambda par: (-par[1], par[0]))},
    }


def montar_documento(anchors, faixas, erros, sem_coord):
    gerado_em = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if config.ARQUIVO_JSON.is_file():
        try:
            anterior = json.loads(config.ARQUIVO_JSON.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            anterior = None
        if anterior and anterior.get("anchors") == anchors:
            gerado_em = anterior.get("meta", {}).get("gerado_em", gerado_em)
    numeros = resumo(anchors)
    return {
        "meta": {
            "gerado_em": gerado_em,
            "seed": config.SEED,
            "filtros": {
                "af": config.ADDRESS_FAMILY,
                "tipo": config.TIPO_MEDICAO,
                "status_medicao": config.STATUS_MEDICAO_OK,
                "medicao_publica": config.EXIGIR_MEDICAO_PUBLICA,
                "status_probe": config.STATUS_PROBE_OK,
                "is_public": True,
                "address_v4": True,
            },
            "endpoint_participantes": config.ENDPOINT_PARTICIPANTES,
            "faixas_km": faixas,
            "limitacoes": list(config.LIMITACOES),
            "erros": erros,
            "probes_sem_coordenadas": sem_coord,
            "fallback_resultados": None,
            "totais": {
                "destinos": numeros["destinos"],
                "vinculos": numeros["vinculos"],
                "probes_distintas": numeros["probes_distintas"],
                "anchors_com_uma_probe": numeros["anchors_com_uma_probe"],
                "anchors_sem_probe": numeros["anchors_sem_probe"],
            },
            "resumo": numeros,
        },
        "anchors": anchors,
    }


def destino_html(anchors):
    alvo = config.DESTINO_HTML
    if isinstance(alvo, int) or (isinstance(alvo, str) and str(alvo).isdigit()):
        achados = [anchor for anchor in anchors if anchor["id"] == int(alvo)]
    else:
        achados = [anchor for anchor in anchors if anchor["country"] == alvo]
    if not achados:
        raise SystemExit(f"Destino da página não encontrado: {alvo}")
    return achados[0]


def json_para_html(dados):
    texto_json = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    return (
        texto_json.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def gravar_json(documento):
    config.ARQUIVO_JSON.write_text(
        json.dumps(documento, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def gerar_html(documento, destino):
    embutido = {
        "meta": {
            "gerado_em": documento["meta"]["gerado_em"],
            "seed": documento["meta"]["seed"],
            "totais": documento["meta"]["totais"],
        },
        "destino": destino,
        "pagina": {
            "titulo": config.TITULO_PAGINA,
            "vazio": config.ROTULO_VAZIO,
            "sim": config.ROTULO_SIM,
            "nao": config.ROTULO_NAO,
            "texto_sem_probe": config.TEXTO_SEM_PROBE,
            "texto_poucas": config.TEXTO_POUCAS_ORIGENS,
            "caminho_dados": config.CAMINHO_DADOS_AVISO,
            "link_inicio": config.LINK_INICIO,
            "url_probe": config.URL_PAGINA_PROBE,
            "url_medicao": config.URL_PAGINA_MEDICAO,
            "total_destinos": config.TOTAL_DESTINOS,
            "colunas": config.COLUNAS,
            "cores_faixa": config.CORES_FAIXA,
            "rotulo_faixa": config.ROTULO_FAIXA,
            "ordem_faixas": list(config.ORDEM_FAIXAS),
            "nomes_pais": config.NOMES_PAIS,
        },
    }
    pagina = HTML_PAGINA.replace("__TITULO__", html.escape(config.TITULO_PAGINA))
    pagina = pagina.replace("__LINK_INICIO__", html.escape(config.LINK_INICIO, quote=True))
    pagina = pagina.replace("__DADOS__", json_para_html(embutido))
    config.ARQUIVO_HTML.write_text(pagina, encoding="utf-8")


def cartao_etapa3(vinculos):
    frase = (
        f"{vinculos} vínculos de probes de origem para as "
        f"{config.TOTAL_DESTINOS} anchors de destino."
    )
    return (
        '<article class="cartao ativo">\n'
        f'      <p class="etapa">{html.escape(config.ROTULO_ETAPA3)}</p>\n'
        f"      <h2>{html.escape(config.TITULO_CARTAO)}</h2>\n"
        f"      <p>{html.escape(frase)}</p>\n"
        f'      <a href="{html.escape(config.LINK_ETAPA3, quote=True)}">Abrir página</a>\n'
        "    </article>"
    )


def atualizar_index(vinculos):
    cartao = cartao_etapa3(vinculos)
    bloco = f"{config.MARCADOR_ETAPA3_INICIO}\n    {cartao}\n    {config.MARCADOR_ETAPA3_FIM}"
    texto_atual = config.ARQUIVO_INDEX.read_text(encoding="utf-8")
    if config.MARCADOR_ETAPA3_INICIO in texto_atual and config.MARCADOR_ETAPA3_FIM in texto_atual:
        inicio = texto_atual.index(config.MARCADOR_ETAPA3_INICIO)
        fim = texto_atual.index(config.MARCADOR_ETAPA3_FIM) + len(config.MARCADOR_ETAPA3_FIM)
        config.ARQUIVO_INDEX.write_text(texto_atual[:inicio] + bloco + texto_atual[fim:], encoding="utf-8")
        return
    if config.MARCADOR_ETAPA2_FIM not in texto_atual:
        raise SystemExit("O index.html não tem o cartão da Etapa 2 para preservar o restante da página.")
    config.ARQUIVO_INDEX.write_text(
        texto_atual.replace(config.MARCADOR_ETAPA2_FIM, config.MARCADOR_ETAPA2_FIM + "\n" + bloco, 1),
        encoding="utf-8",
    )


def imprimir_resumo(documento):
    numeros = documento["meta"]["resumo"]
    distintas = numeros["probes_distintas"] or 1
    print()
    print("=== Resumo da Etapa 3 ===")
    print(f"Destinos: {numeros['destinos']}")
    print(f"Vínculos: {numeros['vinculos']}")
    print(f"Probes distintas: {numeros['probes_distintas']}")
    print(f"Anchors com 1 probe: {numeros['anchors_com_uma_probe']}")
    print(f"Anchors sem probe: {numeros['anchors_sem_probe']}")
    print(
        f"Probes comuns: {numeros['probes_comuns']} "
        f"({100 * numeros['probes_comuns'] / distintas:.0f}%) · "
        f"anchors como origem: {numeros['probes_anchor']} "
        f"({100 * numeros['probes_anchor'] / distintas:.0f}%)"
    )
    print("Por continente:")
    for nome, qtd in numeros["por_continente"].items():
        print(f"  {nome}: {qtd}")
    print("Por ASN:")
    for asn, qtd in numeros["por_asn"].items():
        print(f"  AS{asn}: {qtd}")
    print(f"JSON: {config.ARQUIVO_JSON}")
    print(f"HTML: {config.ARQUIVO_HTML}")
    print()


def main():
    preparar_saida()
    parser = argparse.ArgumentParser(description=config.TITULO_PAGINA)
    parser.add_argument("--sem-cache", action="store_true", help="Ignora o cache e consulta a API de novo.")
    args = parser.parse_args()
    garantir_pastas()
    copiar_prompt()
    anchors, faixas, erros, sem_coord = processar(args.sem_cache)
    problemas = validar(anchors)
    if problemas:
        raise SystemExit("Seleção rejeitada: " + "; ".join(problemas[:12]))
    documento = montar_documento(anchors, faixas, erros, sem_coord)
    gravar_json(documento)
    gerar_html(documento, destino_html(anchors))
    atualizar_index(documento["meta"]["totais"]["vinculos"])
    imprimir_resumo(documento)


HTML_PAGINA = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITULO__</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f3f1ea; --ink: #1c1915; --muted: #5e584e; --card: #fffdf8;
      --line: #e4ddd0; --accent: #0f6e56; --accent-soft: #e5f5ef; --br: #c45c26;
      --shadow: 0 10px 30px rgba(40, 32, 20, 0.06);
    }
    html[data-theme="dark"] {
      color-scheme: dark;
      --bg: #12171a; --ink: #f3f1ea; --muted: #b7b1a6; --card: #1c2428;
      --line: #314046; --accent: #3dbe9a; --accent-soft: #16352c; --br: #e5925d;
      --shadow: 0 10px 30px rgba(0, 0, 0, 0.28);
    }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: "Segoe UI", sans-serif; background: var(--bg); color: var(--ink); line-height: 1.45; }
    header, main { width: min(1100px, calc(100% - 32px)); margin: 0 auto; }
    header { padding: 28px 0 8px; display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
    h1 { margin: 8px 0; font-size: 1.7rem; }
    h2 { margin: 0 0 12px; font-size: 1.05rem; }
    a { color: var(--br); }
    .voltar { color: var(--muted); text-decoration: none; }
    button { font: inherit; color: inherit; border: 1px solid var(--line); background: var(--card); border-radius: 999px; padding: 8px 14px; cursor: pointer; }
    .frase { font-size: 1.05rem; }
    .aviso { background: var(--accent-soft); border: 1px solid var(--accent); border-radius: 16px; padding: 14px 16px; }
    .grade { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin: 16px 0; }
    .cartao, .bloco { background: var(--card); border: 1px solid var(--line); border-radius: 16px; box-shadow: var(--shadow); }
    .cartao { padding: 14px; }
    .cartao span { display: block; color: var(--muted); font-size: 0.82rem; }
    .cartao strong { font-size: 1.35rem; }
    .bloco { padding: 16px; margin: 16px 0; }
    .selo { display: inline-block; margin-left: 8px; padding: 2px 8px; border-radius: 999px; background: var(--br); color: #fff; font-size: 0.75rem; vertical-align: 2px; }
    .legenda { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 8px; color: var(--muted); }
    .amostra { width: 14px; height: 14px; border-radius: 4px; display: inline-block; vertical-align: -2px; margin-right: 4px; }
    svg { width: 100%; height: auto; }
    .caixa { fill: var(--card); stroke: var(--line); }
    .rotulo { fill: var(--ink); font-size: 13px; font-family: "Segoe UI", sans-serif; }
    .miudo { fill: var(--muted); font-size: 12px; font-family: "Segoe UI", sans-serif; }
    .tabela-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 16px; background: var(--card); }
    table { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
    th, td { padding: 8px 10px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 999px; background: var(--accent-soft); color: var(--accent); }
    .badge.curta { background: #e5f5ef; color: #0f6e56; }
    .badge.media { background: #fff1e6; color: #c45c26; }
    .badge.longa { background: #e7eef8; color: #3d5a80; }
    footer { width: min(1100px, calc(100% - 32px)); margin: 12px auto 28px; color: var(--muted); }
    @media (max-width: 800px) {
      .grade { grid-template-columns: 1fr 1fr; }
      header { flex-direction: column; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <a class="voltar" href="__LINK_INICIO__">← Início</a>
      <h1 id="titulo">__TITULO__</h1>
      <p class="frase" id="frase"></p>
    </div>
    <button id="tema" type="button">Tema escuro</button>
  </header>
  <main>
    <p class="aviso" id="aviso"></p>
    <section class="grade" id="cartoes"></section>
    <section class="bloco">
      <h2>Fluxo origem → destino</h2>
      <div id="diagrama"></div>
      <div class="legenda" id="legenda"></div>
    </section>
    <div class="tabela-wrap">
      <table>
        <thead><tr id="cabecalho"></tr></thead>
        <tbody id="corpo"></tbody>
      </table>
    </div>
  </main>
  <footer id="rodape"></footer>
  <script id="dados-probes" type="application/json">__DADOS__</script>
  <script>
    const doc = JSON.parse(document.getElementById("dados-probes").textContent);
    const pagina = doc.pagina;
    const destino = doc.destino;
    const probes = destino.probes || [];
    const vazio = pagina.vazio;

    const raiz = document.documentElement;
    const botao = document.getElementById("tema");
    const salvo = localStorage.getItem("etapa-tema");
    aplicar(salvo || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
    botao.addEventListener("click", () => {
      const proximo = raiz.getAttribute("data-theme") === "dark" ? "light" : "dark";
      localStorage.setItem("etapa-tema", proximo);
      aplicar(proximo);
    });
    function aplicar(tema) {
      raiz.setAttribute("data-theme", tema);
      botao.textContent = tema === "dark" ? "Tema claro" : "Tema escuro";
    }
    function semValor(valor) {
      return valor === null || valor === undefined || valor === "";
    }
    function nomePais(codigo) {
      return pagina.nomes_pais[codigo] || codigo || vazio;
    }
    function juntar(lista) {
      if (!lista.length) return "nenhuma probe";
      if (lista.length === 1) return lista[0];
      return lista.slice(0, -1).join(", ") + " e " + lista[lista.length - 1];
    }
    const frase = document.getElementById("frase");
    frase.textContent = nomePais(destino.country) + " (destino · anchor) recebe pacotes de "
      + juntar(probes.map((probe) => String(probe.id))) + " (origem · probes).";
    if (destino.poucas_origens) {
      const selo = document.createElement("span");
      selo.className = "selo";
      selo.textContent = pagina.texto_poucas;
      frase.appendChild(selo);
    }
    document.getElementById("aviso").textContent = "Amostra: 1 de " + pagina.total_destinos
      + " destinos. Dados completos em `" + pagina.caminho_dados + "`.";

    const totais = doc.meta.totais;
    const grade = document.getElementById("cartoes");
    [
      ["Destinos", String(totais.destinos)],
      ["Vínculos", String(totais.vinculos)],
      ["Probes distintas", String(totais.probes_distintas)],
      ["Com 1 probe", String(totais.anchors_com_uma_probe)],
      ["Sem probe", String(totais.anchors_sem_probe)]
    ].forEach(([rotulo, valor]) => {
      const artigo = document.createElement("article");
      artigo.className = "cartao";
      const span = document.createElement("span");
      span.textContent = rotulo;
      const forte = document.createElement("strong");
      forte.textContent = valor;
      artigo.append(span, forte);
      grade.appendChild(artigo);
    });

    const legenda = document.getElementById("legenda");
    pagina.ordem_faixas.forEach((faixa) => {
      const item = document.createElement("span");
      const cor = document.createElement("i");
      cor.className = "amostra";
      cor.style.background = pagina.cores_faixa[faixa];
      item.append(cor, document.createTextNode(pagina.rotulo_faixa[faixa] || faixa));
      legenda.appendChild(item);
    });

    function svgEl(nome) {
      return document.createElementNS("http://www.w3.org/2000/svg", nome);
    }
    function desenhar() {
      const painel = document.getElementById("diagrama");
      painel.replaceChildren();
      if (!probes.length) {
        const aviso = document.createElement("p");
        aviso.textContent = pagina.texto_sem_probe;
        painel.appendChild(aviso);
        return;
      }
      const alturaLinha = 78;
      const altura = probes.length * alturaLinha + 16;
      const svg = svgEl("svg");
      svg.setAttribute("viewBox", "0 0 820 " + altura);
      svg.setAttribute("role", "img");
      const centroDestino = altura / 2;
      probes.forEach((probe, indice) => {
        const y = 16 + indice * alturaLinha;
        const centro = y + 26;
        const cor = pagina.cores_faixa[probe.distance_band] || "#888";
        const forma = svgEl(probe.is_anchor ? "ellipse" : "rect");
        if (probe.is_anchor) {
          forma.setAttribute("cx", "120");
          forma.setAttribute("cy", String(centro));
          forma.setAttribute("rx", "108");
          forma.setAttribute("ry", "28");
        } else {
          forma.setAttribute("x", "16");
          forma.setAttribute("y", String(y));
          forma.setAttribute("width", "208");
          forma.setAttribute("height", "52");
          forma.setAttribute("rx", "12");
        }
        forma.setAttribute("class", "caixa");
        svg.appendChild(forma);
        const linha1 = svgEl("text");
        linha1.setAttribute("class", "rotulo");
        linha1.setAttribute("x", "120");
        linha1.setAttribute("y", String(centro - 4));
        linha1.setAttribute("text-anchor", "middle");
        linha1.textContent = probe.id + " · " + (probe.country_code || vazio);
        const linha2 = svgEl("text");
        linha2.setAttribute("class", "miudo");
        linha2.setAttribute("x", "120");
        linha2.setAttribute("y", String(centro + 14));
        linha2.setAttribute("text-anchor", "middle");
        linha2.textContent = (probe.is_anchor ? "anchor" : "probe") + " · ASN " + (probe.asn_v4 ?? vazio);
        svg.append(linha1, linha2);
        const linha = svgEl("line");
        linha.setAttribute("x1", "230");
        linha.setAttribute("y1", String(centro));
        linha.setAttribute("x2", "560");
        linha.setAttribute("y2", String(centroDestino));
        linha.setAttribute("stroke", cor);
        linha.setAttribute("stroke-width", "2");
        svg.appendChild(linha);
        const rotulo = svgEl("text");
        rotulo.setAttribute("class", "miudo");
        rotulo.setAttribute("x", "390");
        rotulo.setAttribute("y", String((centro + centroDestino) / 2 - 6));
        rotulo.setAttribute("text-anchor", "middle");
        rotulo.setAttribute("fill", cor);
        rotulo.textContent = probe.distance_km + " km";
        svg.appendChild(rotulo);
      });
      const destinoCaixa = svgEl("rect");
      destinoCaixa.setAttribute("class", "caixa");
      destinoCaixa.setAttribute("x", "580");
      destinoCaixa.setAttribute("y", String(centroDestino - 36));
      destinoCaixa.setAttribute("width", "220");
      destinoCaixa.setAttribute("height", "72");
      destinoCaixa.setAttribute("rx", "14");
      svg.appendChild(destinoCaixa);
      const t1 = svgEl("text");
      t1.setAttribute("class", "rotulo");
      t1.setAttribute("x", "690");
      t1.setAttribute("y", String(centroDestino - 8));
      t1.setAttribute("text-anchor", "middle");
      t1.textContent = nomePais(destino.country);
      const t2 = svgEl("text");
      t2.setAttribute("class", "miudo");
      t2.setAttribute("x", "690");
      t2.setAttribute("y", String(centroDestino + 10));
      t2.setAttribute("text-anchor", "middle");
      t2.textContent = destino.city || vazio;
      const t3 = svgEl("text");
      t3.setAttribute("class", "miudo");
      t3.setAttribute("x", "690");
      t3.setAttribute("y", String(centroDestino + 26));
      t3.setAttribute("text-anchor", "middle");
      t3.textContent = destino.hostname || vazio;
      svg.append(t1, t2, t3);
      painel.appendChild(svg);
    }
    desenhar();

    function valor(chave, probe) {
      if (chave === "country") return destino.country;
      if (chave === "city_destino") return destino.city;
      if (chave === "ip_destino") return destino.ip_v4;
      if (!probe) return null;
      return probe[chave];
    }
    const cabecalho = document.getElementById("cabecalho");
    const corpo = document.getElementById("corpo");
    pagina.colunas.forEach((coluna) => {
      const th = document.createElement("th");
      th.textContent = coluna.rotulo;
      cabecalho.appendChild(th);
    });
    if (!probes.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = pagina.colunas.length;
      td.textContent = pagina.texto_sem_probe;
      tr.appendChild(td);
      corpo.appendChild(tr);
    } else {
      probes.forEach((probe) => {
        const tr = document.createElement("tr");
        pagina.colunas.forEach((coluna) => {
          const td = document.createElement("td");
          const bruto = valor(coluna.chave, probe);
          if (coluna.tipo === "link_probe" && probe) {
            const link = document.createElement("a");
            link.href = pagina.url_probe.replace("{id}", String(probe.id));
            link.rel = "noopener";
            link.textContent = String(probe.id);
            td.appendChild(link);
          } else if (coluna.tipo === "link_medicao" && probe) {
            const link = document.createElement("a");
            link.href = pagina.url_medicao.replace("{id}", String(probe.measurement_id));
            link.rel = "noopener";
            link.textContent = String(probe.measurement_id);
            td.appendChild(link);
          } else if (coluna.tipo === "bool") {
            td.textContent = bruto === true ? pagina.sim : bruto === false ? pagina.nao : vazio;
          } else if (coluna.tipo === "badge_status" || coluna.tipo === "badge_faixa") {
            const badge = document.createElement("span");
            badge.className = "badge" + (coluna.tipo === "badge_faixa" ? " " + bruto : "");
            badge.textContent = coluna.tipo === "badge_faixa"
              ? (pagina.rotulo_faixa[bruto] || bruto || vazio)
              : (semValor(bruto) ? vazio : String(bruto));
            td.appendChild(badge);
          } else {
            td.textContent = semValor(bruto) ? vazio : String(bruto);
          }
          tr.appendChild(td);
        });
        corpo.appendChild(tr);
      });
    }
    const quando = new Date(doc.meta.gerado_em);
    document.getElementById("rodape").textContent = "Gerado em " + (Number.isNaN(quando.getTime())
      ? doc.meta.gerado_em
      : quando.toLocaleString("pt-BR", {timeZone: "UTC"}) + " UTC") + " · seed " + doc.meta.seed;
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
