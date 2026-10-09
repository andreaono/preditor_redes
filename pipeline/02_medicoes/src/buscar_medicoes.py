"""Busca medições ping IPv4 ongoing que têm as anchors da Etapa 1 como destino.

Estratégia e limitações estão em config.py. Este script só baixa metadados:
nunca segue URL de resultados.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import random
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
    return caminho.endswith("/results") or caminho.endswith("results")


def obter_json(url, sem_cache):
    if url_proibida(url):
        raise ErroConsulta(f"bloqueado o download de resultados: {url}")
    em_cache = ler_cache(url, sem_cache)
    if em_cache is not None:
        print(f"cache: {url}", flush=True)
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
        if not isinstance(pagina, dict):
            raise ErroConsulta(f"resposta inesperada em {url}")
        itens.extend(pagina.get("results") or [])
        url = pagina.get("next")
    return itens


def ler_anchors():
    if not config.ARQUIVO_ANCHORS_ETAPA1.is_file():
        raise SystemExit(f"JSON da Etapa 1 não encontrado: {config.ARQUIVO_ANCHORS_ETAPA1}")
    documento = json.loads(config.ARQUIVO_ANCHORS_ETAPA1.read_text(encoding="utf-8"))
    anchors = documento.get(config.CHAVE_LISTA_ANCHORS)
    if not isinstance(anchors, list):
        raise SystemExit("O JSON da Etapa 1 não contém a lista anchors.")
    if len(anchors) != config.TOTAL_ANCHORS:
        raise SystemExit(
            f"A Etapa 1 tem {len(anchors)} anchors; o esperado é {config.TOTAL_ANCHORS}."
        )
    return anchors


def texto(valor):
    if valor is None:
        return None
    if isinstance(valor, str):
        limpo = valor.strip()
        return limpo or None
    return valor


def compativel(med, anchor):
    if not isinstance(med, dict):
        return False
    if med.get("type") != config.TIPO_MEDICAO:
        return False
    try:
        familia = int(med.get("af"))
    except (TypeError, ValueError):
        return False
    if familia != config.ADDRESS_FAMILY:
        return False
    status = med.get("status") or {}
    if status.get("id") != config.STATUS_ONGOING_ID:
        return False
    if status.get("name") != config.STATUS_ONGOING_NOME:
        return False
    fqdn = (anchor.get("fqdn") or "").lower()
    ip = anchor.get("ip_v4") or ""
    alvo = (med.get("target") or "").lower()
    alvo_ip = med.get("target_ip") or ""
    return alvo == fqdn or alvo_ip == ip


def extrair(med):
    status = med.get("status") or {}
    intervalo = med.get("interval")
    if intervalo is not None:
        intervalo = int(intervalo)
    registro = {
        "id": int(med["id"]),
        "type": med.get("type"),
        "status": status.get("name"),
        "af": int(med["af"]),
        "interval": intervalo,
        "is_public": med.get("is_public"),
        "description": texto(med.get("description")),
        "start_time": med.get("start_time"),
        "target": texto(med.get("target")),
        "target_ip": texto(med.get("target_ip")),
        "participant_count": med.get("participant_count"),
    }
    return registro


def url_busca(filtro, valor):
    return montar_url(
        config.URL_MEASUREMENTS,
        {
            "type": config.TIPO_MEDICAO,
            "af": config.ADDRESS_FAMILY,
            "status": config.STATUS_ONGOING_ID,
            filtro: valor,
            "page_size": config.TAMANHO_PAGINA,
        },
    )


def url_medicao(med_id):
    return f"{config.URL_MEASUREMENTS.rstrip('/')}/{int(med_id)}/"


def buscar_anchor(anchor, sem_cache):
    encontradas = {}
    for filtro in config.FILTROS_ALVO:
        campo = config.CAMPO_DO_FILTRO[filtro]
        valor = anchor.get(campo)
        if not valor:
            continue
        for med in paginar(url_busca(filtro, valor), sem_cache):
            if not compativel(med, anchor) or med.get("id") is None:
                continue
            encontradas[int(med["id"])] = extrair(med)
    return encontradas


def completar_mesh(anchor, encontradas, sem_cache, complementos):
    for med_id in anchor.get(config.CAMPO_MESH_IDS) or []:
        if int(med_id) in encontradas:
            continue
        detalhe = obter_json(url_medicao(med_id), sem_cache)
        if compativel(detalhe, anchor):
            encontradas[int(detalhe["id"])] = extrair(detalhe)
            complementos.append({"anchor_id": anchor.get("id"), "measurement_id": int(med_id)})


def ancora_publica(anchor, medicoes):
    return {
        "id": anchor.get("id"),
        "hostname": texto(anchor.get("hostname")),
        "fqdn": texto(anchor.get("fqdn")),
        "ip_v4": texto(anchor.get("ip_v4")),
        "city": texto(anchor.get("city")),
        "country": texto(anchor.get("country")),
        "medicoes": medicoes,
    }


def preferir_fqdn(por_anchor, anchors_por_id):
    """Se o mesmo id cair em duas anchors, fica naquela cujo fqdn é o target."""
    dono = {}
    for anchor_id, medicoes in por_anchor.items():
        for med in medicoes:
            dono.setdefault(med["id"], []).append((anchor_id, med))
    ajustes = []
    for med_id, ocorrencias in dono.items():
        if len(ocorrencias) < 2:
            continue
        alvo = (ocorrencias[0][1].get("target") or "").lower()
        compativeis = [
            anchor_id
            for anchor_id, _med in ocorrencias
            if (anchors_por_id[anchor_id].get("fqdn") or "").lower() == alvo and alvo
        ]
        if len(compativeis) == 1:
            escolhido = compativeis[0]
        else:
            escolhido = sorted(anchor_id for anchor_id, _med in ocorrencias)[0]
        for anchor_id, _med in ocorrencias:
            if anchor_id == escolhido:
                continue
            por_anchor[anchor_id] = [item for item in por_anchor[anchor_id] if item["id"] != med_id]
        ajustes.append(
            {
                "measurement_id": med_id,
                "anchors": [anchor_id for anchor_id, _med in ocorrencias],
                "mantida_em": escolhido,
            }
        )
    return ajustes


def processar(anchors, sem_cache):
    por_anchor = {}
    erros = []
    complementos = []
    for anchor in anchors:
        try:
            encontradas = buscar_anchor(anchor, sem_cache)
            try:
                completar_mesh(anchor, encontradas, sem_cache, complementos)
            except ErroConsulta as exc:
                erros.append({"anchor_id": anchor.get("id"), "erro": str(exc)})
                print(f"erro ao conferir mesh da anchor {anchor.get('id')}: {exc}", flush=True)
        except ErroConsulta as exc:
            encontradas = {}
            erros.append({"anchor_id": anchor.get("id"), "erro": str(exc)})
            print(f"erro na anchor {anchor.get('id')}: {exc}", flush=True)
        medicoes = sorted(encontradas.values(), key=lambda item: item["id"])
        por_anchor[anchor["id"]] = medicoes
        print(
            f"{anchor.get('country')} {anchor.get('hostname')}: {len(medicoes)} medições",
            flush=True,
        )
    anchors_por_id = {anchor["id"]: anchor for anchor in anchors}
    duplicatas = preferir_fqdn(por_anchor, anchors_por_id)
    saida = []
    for anchor in anchors:
        saida.append(ancora_publica(anchor, por_anchor.get(anchor["id"], [])))
    return saida, erros, complementos, duplicatas


def conferencia_mesh(anchors_entrada, anchors_saida):
    por_id = {anchor["id"]: anchor for anchor in anchors_saida}
    ausentes = []
    esperados = 0
    for anchor in anchors_entrada:
        ids_mesh = [int(item) for item in (anchor.get(config.CAMPO_MESH_IDS) or [])]
        esperados += len(ids_mesh)
        presentes = {med["id"] for med in por_id[anchor["id"]]["medicoes"]}
        for med_id in ids_mesh:
            if med_id not in presentes:
                ausentes.append({"anchor_id": anchor["id"], "measurement_id": med_id})
    return {"esperados": esperados, "encontrados": esperados - len(ausentes), "ausentes": ausentes}


def validar(anchors_saida, conferencia):
    problemas = []
    if len(anchors_saida) != config.TOTAL_ANCHORS:
        problemas.append(f"total de anchors {len(anchors_saida)}")
    vistos = []
    for anchor in anchors_saida:
        for campo in config.CAMPOS_ANCHOR:
            if campo not in anchor:
                problemas.append(f"anchor sem {campo}")
        for med in anchor["medicoes"]:
            vistos.append(med["id"])
            for campo in config.CAMPOS_MEDICAO:
                if campo not in med:
                    problemas.append(f"medição {med.get('id')} sem {campo}")
            if med.get("type") != config.TIPO_MEDICAO:
                problemas.append(f"medição {med.get('id')} não é ping")
            if med.get("status") != config.STATUS_ONGOING_NOME:
                problemas.append(f"medição {med.get('id')} não está Ongoing")
            if med.get("af") != config.ADDRESS_FAMILY:
                problemas.append(f"medição {med.get('id')} não é IPv4")
    if len(vistos) != len(set(vistos)):
        problemas.append("há measurement id duplicado")
    if conferencia["ausentes"]:
        problemas.append(f"mesh ausente: {conferencia['ausentes']}")
    return problemas


def montar_documento(anchors_saida, erros, complementos, duplicatas, conferencia):
    total_medicoes = sum(len(anchor["medicoes"]) for anchor in anchors_saida)
    sem_medicao = sum(1 for anchor in anchors_saida if not anchor["medicoes"])
    gerado_em = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if config.ARQUIVO_JSON.is_file():
        try:
            anterior = json.loads(config.ARQUIVO_JSON.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            anterior = None
        if anterior and anterior.get("anchors") == anchors_saida:
            gerado_em = anterior.get("meta", {}).get("gerado_em", gerado_em)
    return {
        "meta": {
            "gerado_em": gerado_em,
            "estrategia_busca": config.ESTRATEGIA_BUSCA,
            "limitacoes": list(config.LIMITACOES),
            "totais": {
                "anchors": len(anchors_saida),
                "medicoes": total_medicoes,
                "anchors_sem_medicao": sem_medicao,
            },
            "anchors_com_erro": erros,
            "complementos_mesh": complementos,
            "duplicatas_resolvidas": duplicatas,
            "conferencia_mesh": conferencia,
        },
        "anchors": anchors_saida,
    }


def amostra(anchors_saida):
    rng = random.Random(config.SEED)
    brasil = [anchor for anchor in anchors_saida if anchor["country"] == config.PAIS_DESTAQUE]
    if len(brasil) != 1:
        raise SystemExit("A amostra precisa de exatamente uma anchor do Brasil.")
    outras = sorted(
        (anchor for anchor in anchors_saida if anchor["country"] != config.PAIS_DESTAQUE),
        key=lambda anchor: anchor["id"],
    )
    quantidade = min(config.HTML_MAX_ANCHORS - 1, len(outras))
    escolhidas = rng.sample(outras, quantidade)
    escolhidas.sort(key=lambda anchor: (anchor["country"], anchor["hostname"] or "", anchor["id"]))
    grupo = []
    for anchor in brasil + escolhidas:
        copia = dict(anchor)
        copia["medicoes"] = sorted(anchor["medicoes"], key=lambda med: med["id"])[
            : config.HTML_MAX_MEDICOES_POR_ANCHOR
        ]
        grupo.append(copia)
    return grupo


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


def gerar_html(documento, grupo):
    embutido = {
        "meta": {
            "gerado_em": documento["meta"]["gerado_em"],
            "totais": documento["meta"]["totais"],
        },
        "amostra": grupo,
        "pagina": {
            "titulo": config.TITULO_PAGINA,
            "pais_destaque": config.PAIS_DESTAQUE,
            "vazio": config.ROTULO_VAZIO,
            "texto_sem_medicao": config.TEXTO_SEM_MEDICAO,
            "caminho_dados": config.CAMINHO_DADOS_AVISO,
            "link_inicio": config.LINK_INICIO,
            "url_medicao": config.URL_PAGINA_MEDICAO,
            "total_anchors": config.TOTAL_ANCHORS,
            "colunas": config.COLUNAS,
        },
    }
    pagina = HTML_PAGINA.replace("__TITULO__", html.escape(config.TITULO_PAGINA))
    pagina = pagina.replace("__LINK_INICIO__", html.escape(config.LINK_INICIO, quote=True))
    pagina = pagina.replace("__DADOS__", json_para_html(embutido))
    config.ARQUIVO_HTML.write_text(pagina, encoding="utf-8")


def cartao_etapa2(total):
    return (
        '<article class="cartao ativo">\n'
        f"      <p class=\"etapa\">{html.escape(config.ROTULO_ETAPA2)}</p>\n"
        "      <h2>Medições ping</h2>\n"
        f"      <p>{total} medições de ping IPv4 em andamento com as anchors da Etapa 1 como destino.</p>\n"
        f'      <a href="{html.escape(config.LINK_ETAPA2, quote=True)}">Abrir página</a>\n'
        "    </article>"
    )


def pagina_inicial(bloco_etapa2):
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(config.TITULO_INDEX)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f3f1ea;
      --ink: #1c1915;
      --muted: #5e584e;
      --card: #fffdf8;
      --line: #e4ddd0;
      --accent: #0f6e56;
      --br: #c45c26;
    }}
    html[data-theme="dark"] {{
      color-scheme: dark;
      --bg: #12171a;
      --ink: #f3f1ea;
      --muted: #b7b1a6;
      --card: #1c2428;
      --line: #314046;
      --accent: #3dbe9a;
      --br: #e5925d;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Helvetica Neue", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }}
    header, main {{ width: min(880px, calc(100% - 32px)); margin: 0 auto; }}
    header {{ padding: 32px 0 8px; display: flex; justify-content: space-between; gap: 16px; }}
    h1 {{ margin: 0 0 8px; font-size: 1.8rem; }}
    .sub {{ color: var(--muted); }}
    button, a {{ font: inherit; }}
    #tema {{
      border: 1px solid var(--line);
      background: var(--card);
      color: var(--ink);
      border-radius: 999px;
      padding: 8px 14px;
      cursor: pointer;
    }}
    .grade {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 24px 0 40px; }}
    .cartao {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px;
    }}
    .cartao.ativo {{ border-color: var(--accent); }}
    .etapa {{ margin: 0; color: var(--accent); font-size: 0.85rem; }}
    h2 {{ margin: 6px 0 8px; }}
    p {{ margin: 0 0 14px; }}
    a {{ color: var(--br); }}
    @media (max-width: 700px) {{ .grade {{ grid-template-columns: 1fr; }} header {{ flex-direction: column; }} }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>{html.escape(config.TITULO_INDEX)}</h1>
      <p class="sub">Dataset de medições de rede com anchors do RIPE Atlas como destino.</p>
    </div>
    <button id="tema" type="button">Tema escuro</button>
  </header>
  <main>
    <div class="grade">
      <article class="cartao">
        <p class="etapa">{html.escape(config.ROTULO_ETAPA1)}</p>
        <h2>Anchors-alvo</h2>
        <p>{html.escape(config.TEXTO_ETAPA1)}</p>
        <a href="{html.escape(config.LINK_ETAPA1, quote=True)}">Abrir página</a>
      </article>
      {bloco_etapa2}
    </div>
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


def atualizar_index(total):
    cartao = cartao_etapa2(total)
    bloco = f"{config.MARCADOR_ETAPA2_INICIO}\n    {cartao}\n    {config.MARCADOR_ETAPA2_FIM}"
    if config.ARQUIVO_INDEX.is_file():
        texto_atual = config.ARQUIVO_INDEX.read_text(encoding="utf-8")
        if config.MARCADOR_ETAPA2_INICIO in texto_atual and config.MARCADOR_ETAPA2_FIM in texto_atual:
            inicio = texto_atual.index(config.MARCADOR_ETAPA2_INICIO)
            fim = texto_atual.index(config.MARCADOR_ETAPA2_FIM) + len(config.MARCADOR_ETAPA2_FIM)
            config.ARQUIVO_INDEX.write_text(
                texto_atual[:inicio] + bloco + texto_atual[fim:],
                encoding="utf-8",
            )
            return
    config.ARQUIVO_INDEX.write_text(pagina_inicial(bloco), encoding="utf-8")


def imprimir_resumo(documento, grupo):
    totais = documento["meta"]["totais"]
    print()
    print("=== Resumo da Etapa 2 ===")
    print(f"Anchors processadas: {totais['anchors']}")
    print(f"Medições: {totais['medicoes']}")
    print(f"Anchors sem medição: {totais['anchors_sem_medicao']}")
    print(f"Amostra na página: {len(grupo)} anchors")
    print(f"Mesh conferidas: {documento['meta']['conferencia_mesh']['encontrados']}")
    print(f"JSON: {config.ARQUIVO_JSON}")
    print(f"HTML: {config.ARQUIVO_HTML}")
    print(f"Início: {config.ARQUIVO_INDEX}")
    print()


def main():
    preparar_saida()
    parser = argparse.ArgumentParser(description=config.TITULO_PAGINA)
    parser.add_argument("--sem-cache", action="store_true", help="Ignora o cache e consulta a API de novo.")
    args = parser.parse_args()
    garantir_pastas()
    copiar_prompt()
    anchors = ler_anchors()
    saida, erros, complementos, duplicatas = processar(anchors, args.sem_cache)
    conferencia = conferencia_mesh(anchors, saida)
    problemas = validar(saida, conferencia)
    if problemas:
        raise SystemExit("Resultado rejeitado: " + "; ".join(problemas))
    documento = montar_documento(saida, erros, complementos, duplicatas, conferencia)
    grupo = amostra(saida)
    gravar_json(documento)
    gerar_html(documento, grupo)
    atualizar_index(documento["meta"]["totais"]["medicoes"])
    imprimir_resumo(documento, grupo)


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
    header, main { width: min(1100px, calc(100% - 32px)); margin: 0 auto; }
    header { padding: 28px 0 8px; display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
    h1 { margin: 8px 0; font-size: 1.7rem; }
    h2 { font-size: 1.05rem; margin: 0 0 10px; }
    a { color: var(--br); }
    .voltar { color: var(--muted); text-decoration: none; }
    button, input, select { font: inherit; color: inherit; }
    #tema, select, input {
      border: 1px solid var(--line);
      background: var(--card);
      border-radius: 12px;
      padding: 8px 12px;
    }
    #tema { border-radius: 999px; cursor: pointer; }
    .aviso, .bloco {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: var(--shadow);
    }
    .aviso { padding: 14px 16px; margin: 16px 0; border-color: var(--accent); background: var(--accent-soft); }
    .grade { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 16px; }
    .cartao { background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 14px 16px; }
    .cartao span { display: block; color: var(--muted); font-size: 0.85rem; }
    .cartao strong { font-size: 1.4rem; }
    .ferramentas { display: flex; gap: 10px; flex-wrap: wrap; margin: 8px 0 12px; }
    #busca { flex: 1; min-width: 220px; }
    .tabela-wrap { overflow: auto; border: 1px solid var(--line); border-radius: 16px; background: var(--card); }
    table { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
    th, td { padding: 8px 10px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }
    th button { border: 0; background: transparent; padding: 0; cursor: pointer; font-weight: 650; }
    tr.brasil { background: var(--br-bg); box-shadow: inset 4px 0 0 var(--br); }
    .selo { margin-left: 6px; padding: 1px 6px; border-radius: 999px; background: var(--br); color: #fff; font-size: 0.72rem; }
    footer { width: min(1100px, calc(100% - 32px)); margin: 12px auto 28px; color: var(--muted); }
    @media (max-width: 800px) { .grade { grid-template-columns: 1fr; } header { flex-direction: column; } }
  </style>
</head>
<body>
  <header>
    <div>
      <a class="voltar" id="inicio" href="__LINK_INICIO__">← Início</a>
      <h1 id="titulo">__TITULO__</h1>
    </div>
    <button id="tema" type="button">Tema escuro</button>
  </header>
  <main>
    <p class="aviso" id="aviso"></p>
    <section class="grade" id="cartoes"></section>
    <div class="ferramentas">
      <input id="busca" type="search" placeholder="Buscar hostname, país, cidade ou medição…" autocomplete="off">
      <select id="pais"></select>
      <span id="contagem"></span>
    </div>
    <div class="tabela-wrap">
      <table>
        <thead><tr id="cabecalho"></tr></thead>
        <tbody id="corpo"></tbody>
      </table>
    </div>
  </main>
  <footer id="rodape"></footer>
  <script id="dados-medicoes" type="application/json">__DADOS__</script>
  <script>
    const doc = JSON.parse(document.getElementById("dados-medicoes").textContent);
    const pagina = doc.pagina;
    const amostra = doc.amostra;
    const vazio = pagina.vazio;
    const linhas = [];
    amostra.forEach((anchor) => {
      if (!anchor.medicoes.length) {
        linhas.push({anchor: anchor, medicao: null});
      } else {
        anchor.medicoes.forEach((medicao) => linhas.push({anchor: anchor, medicao: medicao}));
      }
    });

    const raiz = document.documentElement;
    const botaoTema = document.getElementById("tema");
    const temaSalvo = localStorage.getItem("etapa-tema");
    const temaInicial = temaSalvo || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    aplicarTema(temaInicial);
    botaoTema.addEventListener("click", () => {
      const proximo = raiz.getAttribute("data-theme") === "dark" ? "light" : "dark";
      localStorage.setItem("etapa-tema", proximo);
      aplicarTema(proximo);
    });
    function aplicarTema(tema) {
      raiz.setAttribute("data-theme", tema);
      botaoTema.textContent = tema === "dark" ? "Tema claro" : "Tema escuro";
    }

    function semValor(valor) {
      return valor === null || valor === undefined || valor === "";
    }
    function valorCampo(linha, chave) {
      if (!linha.medicao && (chave === "id" || chave === "type" || chave === "participant_count" || chave === "status")) {
        return chave === "id" ? pagina.texto_sem_medicao : "";
      }
      if (chave === "id" || chave === "type" || chave === "participant_count" || chave === "status") {
        return linha.medicao[chave];
      }
      return linha.anchor[chave];
    }
    function exibir(linha, chave) {
      const valor = valorCampo(linha, chave);
      return semValor(valor) ? vazio : String(valor);
    }

    const mostradas = linhas.filter((linha) => linha.medicao).length;
    document.getElementById("aviso").textContent =
      "Amostra: " + amostra.length + " de " + pagina.total_anchors + " anchors e "
      + mostradas + " de " + doc.meta.totais.medicoes + " medições. Dados completos em `"
      + pagina.caminho_dados + "`.";

    const totais = doc.meta.totais;
    const grade = document.getElementById("cartoes");
    [
      ["Anchors processadas", String(totais.anchors)],
      ["Medições", String(totais.medicoes)],
      ["Anchors sem medição", String(totais.anchors_sem_medicao)]
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

    const selectPais = document.getElementById("pais");
    const opcaoTodos = document.createElement("option");
    opcaoTodos.value = "";
    opcaoTodos.textContent = "Todos os países";
    selectPais.appendChild(opcaoTodos);
    [...new Set(amostra.map((anchor) => anchor.country).filter(Boolean))].sort((a, b) => a.localeCompare(b, "pt")).forEach((pais) => {
      const opcao = document.createElement("option");
      opcao.value = pais;
      opcao.textContent = pais;
      selectPais.appendChild(opcao);
    });

    const cabecalho = document.getElementById("cabecalho");
    const corpo = document.getElementById("corpo");
    const busca = document.getElementById("busca");
    let ordem = {chave: "hostname", dir: 1};
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
      const va = valorCampo(a, ordem.chave);
      const vb = valorCampo(b, ordem.chave);
      const aVazio = semValor(va);
      const bVazio = semValor(vb);
      if (aVazio && bVazio) return (a.anchor.id || 0) - (b.anchor.id || 0);
      if (aVazio) return 1;
      if (bVazio) return -1;
      let resultado = 0;
      if (coluna && coluna.tipo === "numero") resultado = Number(va) - Number(vb);
      else resultado = String(va).localeCompare(String(vb), "pt", {numeric: true, sensitivity: "base"});
      if (resultado === 0) return (a.anchor.id || 0) - (b.anchor.id || 0);
      return resultado * ordem.dir;
    }

    function desenhar() {
      const termo = busca.value.trim().toLocaleLowerCase("pt");
      const pais = selectPais.value;
      const visiveis = linhas.filter((linha) => {
        if (pais && linha.anchor.country !== pais) return false;
        if (!termo) return true;
        return pagina.colunas.some((coluna) => exibir(linha, coluna.chave).toLocaleLowerCase("pt").includes(termo));
      }).sort(comparar);
      corpo.replaceChildren();
      visiveis.forEach((linha) => {
        const tr = document.createElement("tr");
        const brasil = linha.anchor.country === pagina.pais_destaque;
        if (brasil) tr.className = "brasil";
        pagina.colunas.forEach((coluna) => {
          const td = document.createElement("td");
          if (coluna.chave === "id" && linha.medicao) {
            const link = document.createElement("a");
            link.href = pagina.url_medicao.replace("{id}", String(linha.medicao.id));
            link.textContent = String(linha.medicao.id);
            link.rel = "noopener";
            td.appendChild(link);
          } else {
            td.textContent = exibir(linha, coluna.chave);
          }
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
      document.getElementById("contagem").textContent = visiveis.length + " linhas";
      cabecalho.querySelectorAll("th").forEach((th) => {
        const botao = th.querySelector("button");
        const coluna = pagina.colunas.find((item) => item.chave === th.dataset.chave);
        const marca = th.dataset.chave === ordem.chave ? (ordem.dir > 0 ? " ▲" : " ▼") : "";
        botao.textContent = coluna.rotulo + marca;
      });
    }
    busca.addEventListener("input", desenhar);
    selectPais.addEventListener("change", desenhar);
    desenhar();

    const quando = new Date(doc.meta.gerado_em);
    const dataTexto = Number.isNaN(quando.getTime())
      ? doc.meta.gerado_em
      : quando.toLocaleString("pt-BR", {timeZone: "UTC"}) + " UTC";
    document.getElementById("rodape").textContent = "Consulta em " + dataTexto;
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
