"""Seleciona 30 anchors-alvo IPv4 do RIPE Atlas e gera JSON e HTML.

Suposições (os valores numéricos vêm de config.py; nada é presumido da memória):

- probe_status=1, na documentação de GET /anchors/, significa Connected.
  A listagem já aplica esse filtro, então GET /probes/{id}/ não é necessário.
  config.URL_PROBES permanece disponível para consulta pontual.
- include=measurement embute o recurso de GET /measurements/{id}/.
  Família de endereço, is_public, status e interval são lidos desse objeto.
  Se o intervalo não vier embutido, o script consulta config.URL_MEASUREMENTS.
- IDs e intervalos das medições mesh não são fixos: saem da resposta atual.
- Continente e região seguem o geoesquema ONU M49 em config.PAIS_META
  (Turquia e Chipre na Ásia Ocidental; Rússia na Europa Oriental).
- A distância da anchor brasileira até ela mesma é 0 km e cai na faixa curta.
- Se houver várias medições mesh de ping IPv4 para a mesma anchor,
  interval_segundos é o intervalo da medição de menor id.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone

import config


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


def caminho_cache(url):
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return config.CACHE_DIR / f"{digest}.json"


def cache_aproveitavel(payload):
    bruto = payload.get("fetched_at")
    if not bruto or payload.get("url") is None:
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


def obter_json(url, sem_cache):
    em_cache = ler_cache(url, sem_cache)
    if em_cache is not None:
        print(f"cache: {url}", flush=True)
        return em_cache

    ultimo_erro = None
    for tentativa in range(1, config.MAX_TENTATIVAS + 1):
        try:
            requisicao = urllib.request.Request(
                url,
                headers={
                    "User-Agent": config.USER_AGENT,
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(requisicao, timeout=config.TIMEOUT_S) as resposta:
                body = json.loads(resposta.read().decode("utf-8"))
            gravar_cache(url, body)
            print(f"rede: {url}", flush=True)
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
            detalhe = exc.read().decode("utf-8", errors="replace")[:400]
            raise SystemExit(f"HTTP {exc.code} em {url}: {detalhe}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            ultimo_erro = exc
            espera = config.BACKOFF_S * tentativa
            print(
                f"falha de rede ({exc}); nova tentativa em {espera:.0f}s "
                f"({tentativa}/{config.MAX_TENTATIVAS})",
                flush=True,
            )
            time.sleep(espera)
    raise SystemExit(f"Não foi possível consultar {url}: {ultimo_erro}")


def paginar(url_inicial, sem_cache):
    url = url_inicial
    itens = []
    while url:
        pagina = obter_json(url, sem_cache)
        itens.extend(pagina.get("results") or [])
        url = pagina.get("next")
    return itens


def em_andamento(status):
    if not isinstance(status, dict):
        return False
    if status.get("id") is not None:
        return status.get("id") == config.STATUS_MEDICAO_ONGOING
    return status.get("name") == config.NOME_STATUS_ONGOING


def url_medicao(med_id):
    return f"{config.URL_MEASUREMENTS.rstrip('/')}/{med_id}/"


def resolver_medicao(med, sem_cache):
    """Devolve o objeto de GET /measurements/{id}/.

    Com include=measurement a API já embute esse objeto. Se vier só a URL
    ou faltar o intervalo, a medição é buscada em config.URL_MEASUREMENTS.
    """
    if isinstance(med, str) and med.startswith("http"):
        return obter_json(med, sem_cache)
    if not isinstance(med, dict):
        return None
    if med.get("interval") is None and med.get("id") is not None:
        return obter_json(url_medicao(med["id"]), sem_cache)
    return med


def medicao_ping_ipv4_publica(med):
    if not isinstance(med, dict):
        return False
    try:
        familia = int(med.get("af"))
    except (TypeError, ValueError):
        return False
    if familia != config.ADDRESS_FAMILY:
        return False
    if "type" in med and med.get("type") != config.TIPO_MEDICAO_MESH:
        return False
    if config.EXIGIR_MEDICAO_PUBLICA and not med.get("is_public"):
        return False
    if not em_andamento(med.get("status")):
        return False
    if med.get("id") is None or med.get("interval") is None:
        return False
    return True


def id_ancora_alvo(url):
    if not url:
        return None
    ultimo = urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]
    if ultimo.isdigit():
        return int(ultimo)
    return None


def indexar_medicoes(itens, sem_cache):
    grupos = {}
    for item in itens:
        if not item.get("is_mesh") or not item.get("is_active"):
            continue
        if item.get("type") != config.TIPO_MEDICAO_MESH:
            continue
        med = resolver_medicao(item.get("measurement"), sem_cache)
        if not medicao_ping_ipv4_publica(med):
            continue
        ancora_id = id_ancora_alvo(item.get("target"))
        if ancora_id is None:
            continue
        grupos.setdefault(ancora_id, []).append(
            {"id": int(med["id"]), "interval": int(med["interval"])}
        )
    for medicoes in grupos.values():
        medicoes.sort(key=lambda med: med["id"])
    return grupos


def texto_ou_none(valor):
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def coordenadas(bruto):
    geometria = bruto.get("geometry") or {}
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


def preparar_anchors(brutos, medicoes_por_anchor):
    elegiveis = []
    relatorio = Counter()
    paises_desconhecidos = Counter()

    for bruto in brutos:
        if bruto.get("is_disabled"):
            relatorio["desativada"] += 1
            continue
        ip = texto_ou_none(bruto.get("ip_v4") or bruto.get("address_v4"))
        if not ip:
            relatorio["sem_ipv4"] += 1
            continue
        if bruto.get("as_v4") is None:
            relatorio["sem_asn_v4"] += 1
            continue
        medicoes = medicoes_por_anchor.get(bruto.get("id")) or []
        if not medicoes:
            relatorio["sem_mesh_ipv4"] += 1
            continue
        pais = (bruto.get("country") or "").strip().upper()
        meta_pais = config.PAIS_META.get(pais)
        if not meta_pais:
            relatorio["pais_desconhecido"] += 1
            if pais:
                paises_desconhecidos[pais] += 1
            continue
        coords = coordenadas(bruto)
        if coords is None:
            relatorio["sem_coordenadas"] += 1
            continue
        fqdn = texto_ou_none(bruto.get("fqdn"))
        hostname = texto_ou_none(bruto.get("hostname"))
        if not hostname and fqdn:
            hostname = fqdn.split(".")[0]
        if not hostname:
            relatorio["sem_hostname"] += 1
            continue
        intervalos = [med["interval"] for med in medicoes]
        elegiveis.append(
            {
                "id": int(bruto["id"]),
                "hostname": hostname,
                "fqdn": fqdn,
                "ip_v4": ip,
                "city": texto_ou_none(bruto.get("city")),
                "country": pais,
                "company": texto_ou_none(bruto.get("company")),
                "coordinates": coords,
                "asn_v4": int(bruto["as_v4"]),
                "continent": meta_pais["continente"],
                "region": meta_pais["regiao"],
                "mesh_measurement_ids": [med["id"] for med in medicoes],
                "interval_segundos": intervalos[0],
                "intervalos_observados": intervalos,
            }
        )
        relatorio["elegivel"] += 1

    relatorio_txt = dict(relatorio)
    if paises_desconhecidos:
        print(
            "Países sem mapeamento de continente (anchors ignoradas): "
            + ", ".join(f"{pais} ({qtd})" for pais, qtd in sorted(paises_desconhecidos.items())),
            flush=True,
        )
    print(
        "Filtro: "
        + ", ".join(f"{chave}={valor}" for chave, valor in sorted(relatorio_txt.items())),
        flush=True,
    )
    return elegiveis


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


def classificar_faixa(distancia_km):
    limites = sorted(
        ((nome, dados["max_exclusivo"]) for nome, dados in config.FAIXAS_KM.items()),
        key=lambda item: item[1],
    )
    for nome, limite in limites:
        if distancia_km < limite:
            return nome
    return config.FAIXA_LONGA


def selecionar(elegiveis):
    """Amostra estratificada reprodutível.

    A anchor do Brasil é sorteada primeiro (seed do config) e vira a origem
    das distâncias. As demais saem de países diferentes, com no máximo uma
    por ASN. As cotas de continente são preenchidas antes das vagas livres,
    e cada faixa de distância vazia tem prioridade. Se o limite de 1 ASN
    impedir as 30 anchors, a seleção é refeita com o limite de fallback.
    """

    def executar(max_asn):
        rng = random.Random(config.SEED)
        brasil = sorted(
            (
                item
                for item in elegiveis
                if item["country"] == config.PAIS_BRASIL and item["coordinates"]
            ),
            key=lambda item: item["id"],
        )
        if not brasil:
            raise SystemExit("Nenhuma anchor elegível do Brasil com coordenadas.")
        referencia = dict(rng.choice(brasil))
        referencia["distancia_km"] = 0.0
        referencia["faixa_distancia"] = classificar_faixa(0.0)

        candidatos = []
        for item in elegiveis:
            if item["country"] == config.PAIS_BRASIL or item["id"] == referencia["id"]:
                continue
            if not item["coordinates"] or not item["continent"]:
                continue
            copia = dict(item)
            distancia = round(haversine_km(referencia["coordinates"], item["coordinates"]), 1)
            copia["distancia_km"] = distancia
            copia["faixa_distancia"] = classificar_faixa(distancia)
            candidatos.append(copia)
        candidatos.sort(key=lambda item: item["id"])

        selecionadas = [referencia]
        paises = {referencia["country"]}
        ids = {referencia["id"]}
        asns = Counter({referencia["asn_v4"]: 1})
        por_continente = Counter({referencia["continent"]: 1})
        por_faixa = Counter({referencia["faixa_distancia"]: 1})
        asns_reutilizados = []

        def europa_ok(item):
            if item["continent"] != config.CONTINENTE_EUROPA:
                return True
            return por_continente[config.CONTINENTE_EUROPA] < config.MAX_EUROPA

        def escolher(pool):
            base = [
                item
                for item in pool
                if item["country"] not in paises and item["id"] not in ids and europa_ok(item)
            ]
            estritos = [item for item in base if asns[item["asn_v4"]] < config.MAX_ANCHORS_POR_ASN]
            if estritos:
                return rng.choice(estritos), False
            if max_asn > config.MAX_ANCHORS_POR_ASN:
                relaxados = [item for item in base if asns[item["asn_v4"]] < max_asn]
                if relaxados:
                    return rng.choice(relaxados), True
            return None, False

        def adicionar(item, asn_extra):
            selecionadas.append(item)
            paises.add(item["country"])
            ids.add(item["id"])
            asns[item["asn_v4"]] += 1
            por_continente[item["continent"]] += 1
            por_faixa[item["faixa_distancia"]] += 1
            if asn_extra:
                asns_reutilizados.append(item["id"])

        presentes = {item["continent"] for item in candidatos}
        presentes.add(referencia["continent"])
        continentes = [nome for nome, cota in config.COTAS_CONTINENTE.items() if cota > 0]
        if config.COBRIR_TODOS_CONTINENTES:
            for nome in sorted(presentes):
                if nome not in continentes:
                    continentes.append(nome)
        rng.shuffle(continentes)

        for continente in continentes:
            cota = config.COTAS_CONTINENTE.get(continente, 0)
            if config.COBRIR_TODOS_CONTINENTES and continente in presentes:
                cota = max(cota, 1)
            if continente == config.CONTINENTE_EUROPA:
                cota = min(cota, config.MAX_EUROPA)
            while (
                por_continente[continente] < cota
                and len(selecionadas) < config.TOTAL_ANCHORS
            ):
                do_continente = [item for item in candidatos if item["continent"] == continente]
                faixas_abertas = [
                    faixa
                    for faixa in config.ORDEM_FAIXAS
                    if por_faixa[faixa] < config.MIN_POR_FAIXA
                ]
                preferidos = [
                    item for item in do_continente if item["faixa_distancia"] in faixas_abertas
                ]
                escolhido, extra = escolher(preferidos)
                if escolhido is None:
                    escolhido, extra = escolher(do_continente)
                if escolhido is None:
                    break
                adicionar(escolhido, extra)

        for faixa in config.ORDEM_FAIXAS:
            while por_faixa[faixa] < config.MIN_POR_FAIXA and len(selecionadas) < config.TOTAL_ANCHORS:
                escolhido, extra = escolher(
                    [item for item in candidatos if item["faixa_distancia"] == faixa]
                )
                if escolhido is None:
                    break
                adicionar(escolhido, extra)

        while len(selecionadas) < config.TOTAL_ANCHORS:
            faixa_menor = min(
                config.ORDEM_FAIXAS,
                key=lambda faixa: (por_faixa[faixa], config.ORDEM_FAIXAS.index(faixa)),
            )
            escolhido, extra = escolher(
                [item for item in candidatos if item["faixa_distancia"] == faixa_menor]
            )
            if escolhido is None:
                escolhido, extra = escolher(candidatos)
            if escolhido is None:
                break
            adicionar(escolhido, extra)

        return selecionadas, asns_reutilizados

    selecionadas, reutilizados = executar(config.MAX_ANCHORS_POR_ASN)
    justificativa = None
    limite = config.MAX_ANCHORS_POR_ASN
    if not criterios_duros(selecionadas):
        selecionadas, reutilizados = executar(config.MAX_ANCHORS_POR_ASN_FALLBACK)
        limite = config.MAX_ANCHORS_POR_ASN_FALLBACK
        justificativa = (
            f"Com no máximo {config.MAX_ANCHORS_POR_ASN} anchor por ASN não foi "
            f"possível cumprir o total, os países distintos e as três faixas. "
            f"A seleção foi refeita com no máximo {config.MAX_ANCHORS_POR_ASN_FALLBACK} "
            f"anchors por ASN. Anchors que reutilizaram um ASN: {reutilizados or 'nenhuma'}."
        )
    return selecionadas, justificativa, limite


def criterios_duros(selecionadas):
    if len(selecionadas) != config.TOTAL_ANCHORS:
        return False
    paises = [item["country"] for item in selecionadas]
    if len(set(paises)) != config.TOTAL_ANCHORS:
        return False
    if paises.count(config.PAIS_BRASIL) != 1:
        return False
    faixas = {item["faixa_distancia"] for item in selecionadas}
    if any(faixa not in faixas for faixa in config.ORDEM_FAIXAS):
        return False
    europa = sum(1 for item in selecionadas if item["continent"] == config.CONTINENTE_EUROPA)
    if europa > config.MAX_EUROPA:
        return False
    return True


def validar(selecionadas, limite_asn):
    problemas = []
    if len(selecionadas) != config.TOTAL_ANCHORS:
        problemas.append(f"total {len(selecionadas)} em vez de {config.TOTAL_ANCHORS}")
    paises = [item["country"] for item in selecionadas]
    if len(set(paises)) != len(selecionadas):
        problemas.append("há país repetido")
    if paises.count(config.PAIS_BRASIL) != 1:
        problemas.append("a seleção não tem exatamente uma anchor do Brasil")
    faixas = {item["faixa_distancia"] for item in selecionadas}
    for faixa in config.ORDEM_FAIXAS:
        if faixa not in faixas:
            problemas.append(f"faixa ausente: {faixa}")
    europa = sum(1 for item in selecionadas if item["continent"] == config.CONTINENTE_EUROPA)
    if europa > config.MAX_EUROPA:
        problemas.append(f"Europa com {europa} anchors (máximo {config.MAX_EUROPA})")
    contagem_asn = Counter(item["asn_v4"] for item in selecionadas)
    if contagem_asn and max(contagem_asn.values()) > limite_asn:
        problemas.append(f"ASN acima do limite {limite_asn}")
    for item in selecionadas:
        if not item["ip_v4"] or not item["mesh_measurement_ids"]:
            problemas.append(f"anchor {item['id']} sem IPv4 ou sem medição mesh")
        if item["interval_segundos"] is None:
            problemas.append(f"anchor {item['id']} sem intervalo")
        if classificar_faixa(item["distancia_km"]) != item["faixa_distancia"]:
            problemas.append(f"anchor {item['id']} com faixa inconsistente")
    return problemas


def para_publico(item):
    return {
        "id": item["id"],
        "hostname": item["hostname"],
        "fqdn": item["fqdn"],
        "ip_v4": item["ip_v4"],
        "city": item["city"],
        "country": item["country"],
        "company": item["company"],
        "coordinates": item["coordinates"],
        "asn_v4": item["asn_v4"],
        "continent": item["continent"],
        "region": item["region"],
        "mesh_measurement_ids": item["mesh_measurement_ids"],
        "interval_segundos": item["interval_segundos"],
        "estratos": {
            "continente": item["continent"],
            "regiao": item["region"],
            "asn": item["asn_v4"],
            "faixa_distancia": item["faixa_distancia"],
            "distancia_km": item["distancia_km"],
        },
    }


def montar_resumo(anchors):
    por_continente = Counter(item["continent"] for item in anchors)
    por_faixa = Counter(item["estratos"]["faixa_distancia"] for item in anchors)
    por_regiao = Counter(item["region"] for item in anchors)
    por_asn = Counter(item["asn_v4"] for item in anchors)
    intervalos = Counter(str(item["interval_segundos"]) for item in anchors)
    return {
        "por_continente": dict(sorted(por_continente.items())),
        "por_faixa": {faixa: por_faixa.get(faixa, 0) for faixa in config.ORDEM_FAIXAS},
        "por_regiao": dict(sorted(por_regiao.items())),
        "europa": por_continente.get(config.CONTINENTE_EUROPA, 0),
        "paises_distintos": len({item["country"] for item in anchors}),
        "asn_maximo": max(por_asn.values()) if por_asn else 0,
        "intervalos_segundos": dict(sorted(intervalos.items(), key=lambda par: int(par[0]))),
    }


def divergencias_de_intervalo(selecionadas):
    divergentes = []
    for item in selecionadas:
        vistos = sorted(set(item["intervalos_observados"]))
        if len(vistos) > 1:
            divergentes.append(
                {
                    "anchor_id": item["id"],
                    "interval_adotado": item["interval_segundos"],
                    "intervalos": vistos,
                }
            )
    return divergentes


def carregar_json_anterior():
    if not config.ARQUIVO_JSON.is_file():
        return None
    try:
        return json.loads(config.ARQUIVO_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def montar_documento(selecionadas, justificativa, limite_asn):
    anchors = [para_publico(item) for item in selecionadas]
    anchors.sort(key=lambda item: (item["continent"], item["country"], item["id"]))
    gerado_em = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    anterior = carregar_json_anterior()
    if anterior and anterior.get("anchors") == anchors:
        gerado_em = anterior.get("meta", {}).get("gerado_em", gerado_em)

    documento = {
        "meta": {
            "gerado_em": gerado_em,
            "seed": config.SEED,
            "cotas_continente": config.COTAS_CONTINENTE,
            "faixas_km": config.FAIXAS_KM,
            "max_europa": config.MAX_EUROPA,
            "total_anchors": config.TOTAL_ANCHORS,
            "limite_asn": limite_asn,
            "justificativa_asn": justificativa,
            "intervalos_divergentes": divergencias_de_intervalo(selecionadas),
            "resumo": montar_resumo(anchors),
        },
        "pagina": {
            "titulo": config.TITULO_PAGINA,
            "titulo_bloco": config.TITULO_BLOCO_ORIGENS,
            "diagrama": config.DIAGRAMA_ORIGENS,
            "texto_bloco": config.TEXTO_MULTIPLAS_ORIGENS,
            "pais_brasil": config.PAIS_BRASIL,
            "vazio": config.ROTULO_VAZIO,
            "continente_europa": config.CONTINENTE_EUROPA,
            "max_europa": config.MAX_EUROPA,
            "ordem_faixas": config.ORDEM_FAIXAS,
            "colunas": config.ROTULOS_COLUNAS,
            "mapa": config.MAPA_HABILITADO,
            "url_leaflet": config.URL_LEAFLET_CDN if config.URL_LEAFLET_CDN.endswith("/") else config.URL_LEAFLET_CDN + "/",
            "url_tiles": config.URL_TILES,
            "atribuicao_mapa": config.ATRIBUICAO_MAPA,
        },
        "anchors": anchors,
    }
    return documento


def imprimir_resumo(documento):
    meta = documento["meta"]
    resumo = meta["resumo"]
    brasil = next(
        item for item in documento["anchors"] if item["country"] == config.PAIS_BRASIL
    )
    print()
    print("=== Resumo da seleção ===")
    print(f"Anchors: {len(documento['anchors'])}")
    print(f"Seed: {meta['seed']}")
    print(f"Gerado em: {meta['gerado_em']}")
    print(
        f"Brasil: {brasil['hostname']} (id {brasil['id']}, "
        f"{brasil['city'] or config.ROTULO_VAZIO}, ASN {brasil['asn_v4']})"
    )
    print("Por continente:")
    for nome, quantidade in resumo["por_continente"].items():
        cota = config.COTAS_CONTINENTE.get(nome, 0)
        print(f"  {nome}: {quantidade} (cota mínima {cota})")
    print("Por faixa de distância:")
    for faixa, quantidade in resumo["por_faixa"].items():
        print(f"  {faixa}: {quantidade}")
    print(f"Europa: {resumo['europa']} (máximo {config.MAX_EUROPA})")
    print(f"Países distintos: {resumo['paises_distintos']}")
    print(f"Máximo de anchors por ASN: {resumo['asn_maximo']}")
    if meta["justificativa_asn"]:
        print(f"Justificativa ASN: {meta['justificativa_asn']}")
    else:
        print("ASN: uma anchor por ASN, sem fallback.")
    if meta["intervalos_divergentes"]:
        print(f"Intervalos divergentes: {meta['intervalos_divergentes']}")
    print("Intervalos (s):")
    for intervalo, quantidade in resumo["intervalos_segundos"].items():
        print(f"  {intervalo}: {quantidade}")
    print()
    print(f"{'ID':>6}  {'País':<4} {'Continente':<22} {'Faixa':<6} {'km':>10}  Hostname")
    for item in documento["anchors"]:
        estrato = item["estratos"]
        print(
            f"{item['id']:>6}  {item['country']:<4} {item['continent']:<22} "
            f"{estrato['faixa_distancia']:<6} {estrato['distancia_km']:>10.1f}  {item['hostname']}"
        )
    print()


def gravar_json(documento):
    config.ARQUIVO_JSON.write_text(
        json.dumps(documento, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def json_para_html(documento):
    texto = json.dumps(documento, ensure_ascii=False, separators=(",", ":"))
    return (
        texto.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def gerar_html(documento):
    if config.MAPA_HABILITADO:
        mapa = """
    <section class="bloco" id="secao-mapa">
      <h2>Mapa</h2>
      <p id="mapa-aviso" hidden>O mapa precisa de internet para carregar o Leaflet e os tiles. A tabela funciona offline.</p>
      <div id="mapa"></div>
    </section>"""
    else:
        mapa = ""

    pagina = HTML_PAGINA
    substituicoes = {
        "__TITULO__": html.escape(config.TITULO_PAGINA),
        "__BLOCO_TITULO__": html.escape(config.TITULO_BLOCO_ORIGENS),
        "__DIAGRAMA__": html.escape(config.DIAGRAMA_ORIGENS),
        "__TEXTO_BLOCO__": html.escape(config.TEXTO_MULTIPLAS_ORIGENS),
        "__DADOS__": json_para_html(documento),
        "__MAPA__": mapa,
    }
    for origem, destino in substituicoes.items():
        pagina = pagina.replace(origem, destino)
    config.ARQUIVO_HTML.write_text(pagina, encoding="utf-8")


def diagnosticar(elegiveis, selecionadas):
    print("Diagnóstico do pool elegível:", flush=True)
    print(f"  anchors elegíveis: {len(elegiveis)}", flush=True)
    print(
        "  países: "
        + str(len({item['country'] for item in elegiveis})),
        flush=True,
    )
    continentes = Counter(item["continent"] for item in elegiveis)
    for nome, quantidade in sorted(continentes.items()):
        print(f"  {nome}: {quantidade}", flush=True)
    if selecionadas:
        print(
            "  faixas na seleção: "
            + ", ".join(
                f"{faixa}={qtd}"
                for faixa, qtd in Counter(item["faixa_distancia"] for item in selecionadas).items()
            ),
            flush=True,
        )


def main():
    preparar_saida()
    parser = argparse.ArgumentParser(description=config.TITULO_PAGINA)
    parser.add_argument(
        "--sem-cache",
        action="store_true",
        help="Ignora o cache e consulta a API de novo.",
    )
    args = parser.parse_args()
    garantir_pastas()

    url_anchors = montar_url(
        config.URL_ANCHORS,
        {
            "is_disabled": False,
            "probe_status": config.PROBE_STATUS_CONNECTED,
            "page_size": config.TAMANHO_PAGINA,
        },
    )
    url_medicoes = montar_url(
        config.URL_ANCHOR_MEASUREMENTS,
        {
            "is_active": True,
            "include": config.PARAM_INCLUDE_MEASUREMENT,
            "page_size": config.TAMANHO_PAGINA,
        },
    )

    print("Coletando anchors...", flush=True)
    anchors_brutos = paginar(url_anchors, args.sem_cache)
    print(f"Anchors recebidas: {len(anchors_brutos)}", flush=True)
    print("Coletando medições mesh...", flush=True)
    medicoes_brutas = paginar(url_medicoes, args.sem_cache)
    print(f"Medições de anchor recebidas: {len(medicoes_brutas)}", flush=True)

    medicoes = indexar_medicoes(medicoes_brutas, args.sem_cache)
    print(f"Anchors com ping mesh IPv4 público em andamento: {len(medicoes)}", flush=True)
    elegiveis = preparar_anchors(anchors_brutos, medicoes)
    if not elegiveis:
        raise SystemExit("Nenhuma anchor elegível após os filtros.")

    selecionadas, justificativa, limite = selecionar(elegiveis)
    problemas = validar(selecionadas, limite)
    if problemas:
        diagnosticar(elegiveis, selecionadas)
        raise SystemExit("Seleção rejeitada: " + "; ".join(problemas))

    documento = montar_documento(selecionadas, justificativa, limite)
    gravar_json(documento)
    gerar_html(documento)
    imprimir_resumo(documento)
    print(f"JSON: {config.ARQUIVO_JSON}")
    print(f"HTML: {config.ARQUIVO_HTML}")


HTML_PAGINA = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITULO__</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f3f1ea;
      --ink: #1c1915;
      --muted: #5e584e;
      --card: #fffdf8;
      --line: #e4ddd0;
      --accent: #0f6e56;
      --accent-soft: #e5f5ef;
      --br: #c45c26;
      --br-bg: #fff1e6;
      --shadow: 0 10px 30px rgba(40, 32, 20, 0.06);
    }
    html[data-theme="dark"] {
      color-scheme: dark;
      --bg: #12171a;
      --ink: #f3f1ea;
      --muted: #b7b1a6;
      --card: #1c2428;
      --line: #314046;
      --accent: #3dbe9a;
      --accent-soft: #16352c;
      --br: #e5925d;
      --br-bg: #3a2a22;
      --shadow: 0 10px 30px rgba(0, 0, 0, 0.28);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", "Helvetica Neue", sans-serif;
      background: var(--bg);
      color: var(--ink);
      line-height: 1.45;
    }
    header, main { width: min(1180px, calc(100% - 32px)); margin: 0 auto; }
    header { padding: 32px 0 8px; display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
    h1 { font-size: 1.8rem; line-height: 1.15; margin: 0 0 8px; }
    h2 { font-size: 1.15rem; margin: 0 0 12px; }
    p { margin: 0; }
    .sub { color: var(--muted); max-width: 62ch; }
    button, input { font: inherit; color: inherit; }
    #tema {
      border: 1px solid var(--line);
      background: var(--card);
      border-radius: 999px;
      padding: 8px 14px;
      cursor: pointer;
    }
    .bloco, .cartao {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: var(--shadow);
    }
    .grade { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 20px 0; }
    .cartao { padding: 14px 16px; }
    .cartao span { display: block; color: var(--muted); font-size: 0.85rem; }
    .cartao strong { font-size: 1.45rem; }
    .destaque {
      border-color: var(--accent);
      background: linear-gradient(180deg, var(--accent-soft), var(--card) 70%);
      padding: 18px 18px 16px;
      margin-bottom: 16px;
    }
    .diagrama {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 8px 18px;
      align-items: center;
      margin: 14px 0;
    }
    pre {
      margin: 0;
      font-family: "Cascadia Mono", "Consolas", monospace;
      background: var(--card);
      border: 1px dashed var(--line);
      border-radius: 12px;
      padding: 12px 14px;
      line-height: 1.55;
    }
    .ferramentas { display: flex; gap: 12px; align-items: center; margin: 8px 0 12px; }
    #busca {
      flex: 1;
      border: 1px solid var(--line);
      background: var(--card);
      border-radius: 12px;
      padding: 10px 12px;
    }
    .tabela-wrap { overflow: auto; border: 1px solid var(--line); border-radius: 16px; background: var(--card); }
    table { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
    th, td { padding: 8px 10px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; vertical-align: top; }
    th button {
      border: 0;
      background: transparent;
      padding: 0;
      cursor: pointer;
      font-weight: 650;
    }
    tbody tr:hover { background: var(--accent-soft); }
    tr.brasil { background: var(--br-bg); box-shadow: inset 4px 0 0 var(--br); }
    .selo {
      display: inline-block;
      margin-left: 6px;
      padding: 1px 6px;
      border-radius: 999px;
      background: var(--br);
      color: #fff;
      font-size: 0.72rem;
      vertical-align: 1px;
    }
    #mapa { height: 440px; border-radius: 12px; }
    #mapa-aviso { margin-bottom: 10px; color: var(--muted); }
    .listas { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
    ul { margin: 8px 0 0; padding-left: 18px; }
    footer { width: min(1180px, calc(100% - 32px)); margin: 8px auto 28px; color: var(--muted); }
    @media (max-width: 800px) {
      .grade, .listas, .diagrama { grid-template-columns: 1fr; }
      header { flex-direction: column; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1 id="titulo">__TITULO__</h1>
      <p class="sub">Amostra estratificada de anchors-alvo IPv4. Cada anchor será medida por várias origens na etapa seguinte.</p>
    </div>
    <button id="tema" type="button">Tema escuro</button>
  </header>
  <main>
    <section class="grade" id="cartoes"></section>
    <section class="destaque" id="bloco-origens">
      <h2>__BLOCO_TITULO__</h2>
      <div class="diagrama">
        <pre>__DIAGRAMA__</pre>
        <p>__TEXTO_BLOCO__</p>
      </div>
    </section>
    <section class="bloco" style="padding: 16px;">
      <h2>Resumo</h2>
      <div class="listas">
        <div>
          <strong>Continente</strong>
          <ul id="lista-continentes"></ul>
        </div>
        <div>
          <strong>Faixa de distância até o Brasil</strong>
          <ul id="lista-faixas"></ul>
        </div>
      </div>
    </section>
    <section style="margin-top: 16px;">
      <div class="ferramentas">
        <input id="busca" type="search" placeholder="Buscar hostname, país, cidade, ASN, continente…" autocomplete="off">
        <span id="contagem"></span>
      </div>
      <div class="tabela-wrap">
        <table>
          <thead><tr id="cabecalho"></tr></thead>
          <tbody id="corpo"></tbody>
        </table>
      </div>
    </section>
    __MAPA__
  </main>
  <footer id="rodape"></footer>
  <script id="dados-anchors" type="application/json">__DADOS__</script>
  <script>
    const doc = JSON.parse(document.getElementById("dados-anchors").textContent);
    const anchors = doc.anchors;
    const meta = doc.meta;
    const pagina = doc.pagina;
    const vazio = pagina.vazio;

    const raiz = document.documentElement;
    const botaoTema = document.getElementById("tema");
    const temaSalvo = localStorage.getItem("etapa1-tema");
    const temaInicial = temaSalvo || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    aplicarTema(temaInicial);
    botaoTema.addEventListener("click", () => {
      const proximo = raiz.getAttribute("data-theme") === "dark" ? "light" : "dark";
      localStorage.setItem("etapa1-tema", proximo);
      aplicarTema(proximo);
    });
    function aplicarTema(tema) {
      raiz.setAttribute("data-theme", tema);
      botaoTema.textContent = tema === "dark" ? "Tema claro" : "Tema escuro";
    }

    function semValor(valor) {
      return valor === null || valor === undefined || valor === "" || (Array.isArray(valor) && valor.length === 0);
    }
    function textoEstratos(estratos) {
      if (!estratos) return "";
      return "continente: " + estratos.continente
        + "; região: " + estratos.regiao
        + "; asn: " + estratos.asn
        + "; faixa: " + estratos.faixa_distancia
        + "; " + estratos.distancia_km + " km";
    }
    function exibir(anchor, chave) {
      if (chave === "coordinates") {
        if (!anchor.coordinates) return vazio;
        return anchor.coordinates[0].toFixed(4) + ", " + anchor.coordinates[1].toFixed(4);
      }
      if (chave === "mesh_measurement_ids") {
        if (!anchor.mesh_measurement_ids || !anchor.mesh_measurement_ids.length) return vazio;
        return anchor.mesh_measurement_ids.join(", ");
      }
      if (chave === "estratos") {
        const texto = textoEstratos(anchor.estratos);
        return texto || vazio;
      }
      const valor = anchor[chave];
      return semValor(valor) ? vazio : String(valor);
    }
    function bruto(anchor, chave) {
      if (chave === "estratos") return anchor.estratos ? anchor.estratos.distancia_km : null;
      if (chave === "coordinates") return anchor.coordinates ? anchor.coordinates.join(",") : null;
      if (chave === "mesh_measurement_ids") {
        return anchor.mesh_measurement_ids ? anchor.mesh_measurement_ids.join(",") : null;
      }
      return anchor[chave];
    }

    let ordem = {chave: "continent", dir: 1};
    const busca = document.getElementById("busca");
    const corpo = document.getElementById("corpo");
    const cabecalho = document.getElementById("cabecalho");

    pagina.colunas.forEach((coluna) => {
      const th = document.createElement("th");
      const botao = document.createElement("button");
      botao.type = "button";
      botao.textContent = coluna.rotulo;
      botao.addEventListener("click", () => {
        if (ordem.chave === coluna.chave) ordem.dir *= -1;
        else ordem = {chave: coluna.chave, dir: 1};
        desenhar();
      });
      th.appendChild(botao);
      th.dataset.chave = coluna.chave;
      cabecalho.appendChild(th);
    });

    function comparar(a, b) {
      const coluna = pagina.colunas.find((item) => item.chave === ordem.chave);
      const va = bruto(a, ordem.chave);
      const vb = bruto(b, ordem.chave);
      const aVazio = semValor(va);
      const bVazio = semValor(vb);
      if (aVazio && bVazio) return a.id - b.id;
      if (aVazio) return 1;
      if (bVazio) return -1;
      let resultado = 0;
      if (coluna && coluna.tipo === "numero") resultado = Number(va) - Number(vb);
      else resultado = String(va).localeCompare(String(vb), "pt", {numeric: true, sensitivity: "base"});
      if (resultado === 0) return a.id - b.id;
      return resultado * ordem.dir;
    }

    function desenhar() {
      const termo = busca.value.trim().toLocaleLowerCase("pt");
      const linhas = anchors.filter((anchor) => {
        if (!termo) return true;
        return pagina.colunas.some((coluna) => exibir(anchor, coluna.chave).toLocaleLowerCase("pt").includes(termo));
      }).sort(comparar);
      corpo.replaceChildren();
      linhas.forEach((anchor) => {
        const tr = document.createElement("tr");
        const brasil = anchor.country === pagina.pais_brasil;
        if (brasil) tr.className = "brasil";
        pagina.colunas.forEach((coluna) => {
          const td = document.createElement("td");
          td.textContent = exibir(anchor, coluna.chave);
          if (coluna.chave === "hostname" && brasil) {
            const selo = document.createElement("span");
            selo.className = "selo";
            selo.textContent = "Brasil";
            td.appendChild(selo);
          }
          tr.appendChild(td);
        });
        corpo.appendChild(tr);
      });
      document.getElementById("contagem").textContent = linhas.length + " de " + anchors.length;
      cabecalho.querySelectorAll("th").forEach((th) => {
        const botao = th.querySelector("button");
        const coluna = pagina.colunas.find((item) => item.chave === th.dataset.chave);
        const marca = th.dataset.chave === ordem.chave ? (ordem.dir > 0 ? " ▲" : " ▼") : "";
        botao.textContent = coluna.rotulo + marca;
      });
    }
    busca.addEventListener("input", desenhar);
    desenhar();

    const resumo = meta.resumo;
    const cartoes = [
      ["Anchors", String(anchors.length)],
      ["Países", String(resumo.paises_distintos)],
      [pagina.continente_europa, resumo.europa + " / máx. " + pagina.max_europa],
      ["ASN máximo", String(resumo.asn_maximo)]
    ];
    const grade = document.getElementById("cartoes");
    cartoes.forEach(([rotulo, valor]) => {
      const artigo = document.createElement("article");
      artigo.className = "cartao";
      const span = document.createElement("span");
      span.textContent = rotulo;
      const forte = document.createElement("strong");
      forte.textContent = valor;
      artigo.append(span, forte);
      grade.appendChild(artigo);
    });
    const listaContinentes = document.getElementById("lista-continentes");
    Object.keys(resumo.por_continente).sort((a, b) => a.localeCompare(b, "pt")).forEach((nome) => {
      const li = document.createElement("li");
      const cota = meta.cotas_continente[nome];
      li.textContent = nome + ": " + resumo.por_continente[nome] + (cota === undefined ? "" : " (cota mínima " + cota + ")");
      listaContinentes.appendChild(li);
    });
    const listaFaixas = document.getElementById("lista-faixas");
    pagina.ordem_faixas.forEach((faixa) => {
      const li = document.createElement("li");
      li.textContent = faixa + ": " + (resumo.por_faixa[faixa] || 0);
      listaFaixas.appendChild(li);
    });
    const quando = new Date(meta.gerado_em);
    const dataTexto = Number.isNaN(quando.getTime())
      ? meta.gerado_em
      : quando.toLocaleString("pt-BR", {timeZone: "UTC"}) + " UTC";
    document.getElementById("rodape").textContent = "Gerado em " + dataTexto + " · seed " + meta.seed;

    function escapar(valor) {
      return String(valor ?? "").replace(/[&<>"']/g, (caractere) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[caractere]));
    }
    function iniciarMapa(elMapa) {
      const mapa = L.map(elMapa);
      L.tileLayer(pagina.url_tiles, {attribution: pagina.atribuicao_mapa, maxZoom: 18}).addTo(mapa);
      const pontos = [];
      anchors.forEach((anchor) => {
        if (!anchor.coordinates) return;
        const lat = anchor.coordinates[1];
        const lon = anchor.coordinates[0];
        const brasil = anchor.country === pagina.pais_brasil;
        const marca = L.circleMarker([lat, lon], {
          radius: brasil ? 10 : 7,
          color: brasil ? "#c45c26" : "#0f6e56",
          fillColor: brasil ? "#e07a3d" : "#1a9d74",
          fillOpacity: 0.92,
          weight: 2
        }).addTo(mapa);
        const cidade = anchor.city || vazio;
        marca.bindPopup(
          "<strong>" + escapar(anchor.hostname) + "</strong><br>"
          + escapar(cidade) + " · " + escapar(anchor.country) + "<br>"
          + escapar(anchor.estratos.faixa_distancia) + " · "
          + escapar(anchor.estratos.distancia_km) + " km"
        );
        pontos.push([lat, lon]);
      });
      if (pontos.length) mapa.fitBounds(pontos, {padding: [28, 28]});
    }
    const elMapa = document.getElementById("mapa");
    if (elMapa && pagina.mapa) {
      const aviso = document.getElementById("mapa-aviso");
      const css = document.createElement("link");
      css.rel = "stylesheet";
      css.href = pagina.url_leaflet + "leaflet.css";
      document.head.appendChild(css);
      const scriptMapa = document.createElement("script");
      scriptMapa.src = pagina.url_leaflet + "leaflet.js";
      scriptMapa.onload = () => iniciarMapa(elMapa);
      scriptMapa.onerror = () => {
        elMapa.hidden = true;
        if (aviso) aviso.hidden = false;
      };
      document.body.appendChild(scriptMapa);
    }
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
