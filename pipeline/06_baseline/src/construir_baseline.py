"""Calcula o baseline de RTT de cada fluxo usando somente o Período A.

Não há rede. Nenhuma linha do Período B entra nas contas. Mediana, P95 e P99
são limites estatísticos do histórico do próprio fluxo. Não são rótulos.

O percentil usa interpolação linear: a posição é (n − 1) · p, com p entre 0 e 1.
É o mesmo critério do numpy.percentile (method='linear'). Não se arredonda
o valor gravado no CSV.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import shutil
import statistics
import sys
from datetime import datetime, timezone

import config


def preparar_saida():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


def garantir_pastas():
    for pasta in (config.CACHE_DIR, config.PROMPT_DIR, config.DATA_DIR, config.SRC_DIR, config.TEMPLATE_DIR):
        pasta.mkdir(parents=True, exist_ok=True)


def copiar_prompt():
    if config.ARQUIVO_PROMPT_ORIGEM.is_file():
        shutil.copyfile(config.ARQUIVO_PROMPT_ORIGEM, config.ARQUIVO_PROMPT)


def ler_json(caminho):
    return json.loads(caminho.read_text(encoding="utf-8"))


def agora_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def numero(valor):
    if isinstance(valor, bool) or valor is None or valor == "":
        return None
    try:
        convertido = float(valor)
    except (TypeError, ValueError):
        return None
    if convertido != convertido:
        return None
    return convertido


def inteiro(valor):
    convertido = numero(valor)
    if convertido is None:
        return None
    return int(convertido)


def texto_numero(valor):
    """Texto completo do número, sem arredondar para poucas casas."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return ""
    if isinstance(valor, int) or (isinstance(valor, float) and float(valor).is_integer()):
        return str(int(valor))
    return repr(float(valor))


def extrair_rtts(texto):
    """RTTs numéricos de result. Timeout, booleano e texto ficam de fora."""
    if not texto:
        return []
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError:
        return []
    if not isinstance(dados, list):
        return []
    rtts = []
    for item in dados:
        if not isinstance(item, dict):
            continue
        valor = item.get(config.CAMPO_RTT)
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            continue
        rtts.append(float(valor))
    return rtts


def rtt_medio(avg_original, result_texto):
    """RTT médio da execução. Usa avg se for numérico e não negativo.

    Se avg falta ou é a sentinela negativa da API, recalcula a média dos RTTs
    numéricos de result. Sem nenhum RTT válido, devolve None.
    """
    avg = numero(avg_original)
    if avg is not None and avg >= config.AVG_MINIMO:
        return avg
    rtts = extrair_rtts(result_texto)
    if not rtts:
        return None
    return sum(rtts) / len(rtts)


def jitter_execucao(result_texto):
    """Jitter da execução: desvio-padrão populacional dos RTTs numéricos.

    Um único RTT válido vale 0. Nenhum RTT válido devolve None e fica fora
    dos percentis de jitter.
    """
    rtts = extrair_rtts(result_texto)
    if not rtts:
        return None, False
    if len(rtts) == 1:
        return 0.0, True
    return statistics.pstdev(rtts), False


def mediana(valores):
    """Valor central. Com quantidade par, a média dos dois do meio.

    Na série 10, 11, 12, 13, 50 o centro é 12: o 50 quase não a puxa.
    """
    if not valores:
        return None
    return float(statistics.median(valores))


def percentil_linear(valores, percentil):
    """Percentil por interpolação linear, equivalente a numpy.percentile.

    Os valores são ordenados. A posição é (n − 1) · (percentil / 100).
    Se a posição cai entre dois índices i e i+1, o resultado é a reta
    entre eles. Não arredonda.
    """
    if not valores:
        return None
    ordenados = sorted(valores)
    n = len(ordenados)
    if n == 1:
        return float(ordenados[0])
    posicao = (n - 1) * (percentil / config.ESCALA_PERCENTIL)
    inferior = math.floor(posicao)
    superior = math.ceil(posicao)
    if inferior == superior:
        return float(ordenados[inferior])
    peso = posicao - inferior
    return float(ordenados[inferior] * (1 - peso) + ordenados[superior] * peso)


def conferir_exemplo_didatico():
    if mediana(list(config.EXEMPLO_SERIE)) != config.EXEMPLO_MEDIANA:
        raise SystemExit("A mediana do mini-exemplo didático não fechou. O cálculo está incorreto.")


def carregar_metadados():
    documento = ler_json(config.ARQUIVO_METADADOS_ETAPA5)
    periodos = {item["nome"]: item for item in documento["periodos"]}
    if config.PERIODO_BASELINE not in periodos:
        raise SystemExit("metadados.json não traz o Período A.")
    janela = periodos[config.PERIODO_BASELINE]
    inicio = int(datetime.fromisoformat(janela["inicio"]).timestamp())
    fim = int(datetime.fromisoformat(janela["fim"]).timestamp())
    return documento, inicio, fim


def carregar_ttl_etapa5():
    tabela = {}
    with config.ARQUIVO_BASELINE_TTL_ETAPA5.open(encoding="utf-8", newline="") as arquivo:
        for linha in csv.DictReader(arquivo):
            chave = (linha["anchor_id"], linha["probe_id"])
            tabela[chave] = linha
    return tabela


def carregar_exclusoes():
    if not config.ARQUIVO_EXCLUSOES_ETAPA5.is_file():
        return set()
    with config.ARQUIVO_EXCLUSOES_ETAPA5.open(encoding="utf-8", newline="") as arquivo:
        return {
            linha[config.CAMPO_ID_FLUXO]
            for linha in csv.DictReader(arquivo)
            if linha.get(config.CAMPO_ID_FLUXO)
        }


def universo(metadados, exclusoes):
    escolhidos = []
    fora = []
    excluidos = []
    for id_fluxo, fluxo in metadados["fluxos"].items():
        classe = fluxo.get("classe")
        if id_fluxo in exclusoes:
            excluidos.append({"id_fluxo": id_fluxo, "classe": classe})
            continue
        if classe in config.CLASSES_UNIVERSO:
            escolhidos.append((id_fluxo, fluxo))
        elif classe in config.CLASSES_FORA:
            periodos = fluxo.get("periodos") or {}
            fora.append(
                {
                    "id_fluxo": id_fluxo,
                    "classe": classe,
                    "motivo_a": (periodos.get(config.PERIODO_BASELINE) or {}).get("motivo"),
                    "motivo_b": (periodos.get(config.PERIODO_DATASET) or {}).get("motivo"),
                }
            )
    return escolhidos, fora, excluidos


def af_do_fluxo(metadados, fluxo):
    medicao = metadados["medicoes"].get(fluxo.get("url_medicao"), {})
    return medicao.get("af")


def dentro_de_a(timestamp, inicio, fim):
    if timestamp is None:
        return False
    return inicio <= timestamp < fim


def novo_acumulador():
    return {
        "avgs": [],
        "jitters": [],
        "ttls": [],
        "n_amostras": 0,
        "n_perda": 0,
        "n_jitter_um_rtt": 0,
        "msm_ids": set(),
        "amostra": [],
        "fora_janela": 0,
    }


def acumular(acumulador, linha, inicio, fim):
    instante = inteiro(linha.get(config.CAMPO_TIMESTAMP))
    if not dentro_de_a(instante, inicio, fim):
        acumulador["fora_janela"] += 1
        return
    acumulador["n_amostras"] += 1
    msm = linha.get(config.CAMPO_MSM)
    if msm:
        acumulador["msm_ids"].add(msm)
    sent = numero(linha.get(config.CAMPO_SENT))
    rcvd = numero(linha.get(config.CAMPO_RCVD))
    if sent is not None and rcvd is not None and rcvd < sent:
        acumulador["n_perda"] += 1
    avg = rtt_medio(linha.get(config.CAMPO_AVG), linha.get(config.CAMPO_RESULT))
    if avg is not None:
        acumulador["avgs"].append(avg)
    jitter, um_rtt = jitter_execucao(linha.get(config.CAMPO_RESULT))
    if um_rtt:
        acumulador["n_jitter_um_rtt"] += 1
    if jitter is not None:
        acumulador["jitters"].append(jitter)
    ttl = numero(linha.get(config.CAMPO_TTL))
    if ttl is not None:
        acumulador["ttls"].append(ttl)
    if len(acumulador["amostra"]) < config.HTML_MAX_LINHAS:
        acumulador["amostra"].append(
            {
                "timestamp": linha.get(config.CAMPO_TIMESTAMP) or "",
                "avg": linha.get(config.CAMPO_AVG) or "",
                "sent": linha.get(config.CAMPO_SENT) or "",
                "rcvd": linha.get(config.CAMPO_RCVD) or "",
            }
        )


def ler_periodo_a(ids_universo, inicio, fim):
    acumulados = {id_fluxo: novo_acumulador() for id_fluxo in ids_universo}
    lidas = 0
    ignoradas = {"periodo_b": 0, "outro_periodo_ou_tipo": 0, "fora_do_universo": 0}
    vistos_em_a = set()
    with config.ARQUIVO_CSV_BRUTO_ETAPA5.open(encoding="utf-8", newline="") as arquivo:
        for linha in csv.DictReader(arquivo):
            lidas += 1
            periodo = linha.get(config.CAMPO_PERIODO)
            tipo = linha.get(config.CAMPO_TIPO)
            if periodo == config.PERIODO_DATASET:
                ignoradas["periodo_b"] += 1
                continue
            if periodo != config.PERIODO_BASELINE or tipo != config.TIPO_MEDICAO:
                ignoradas["outro_periodo_ou_tipo"] += 1
                continue
            id_fluxo = linha.get(config.CAMPO_ID_FLUXO)
            vistos_em_a.add(id_fluxo)
            acumulador = acumulados.get(id_fluxo)
            if acumulador is None:
                ignoradas["fora_do_universo"] += 1
                continue
            acumular(acumulador, linha, inicio, fim)
    return acumulados, lidas, ignoradas, vistos_em_a


def serie_do_exemplo(id_fluxo, inicio, fim):
    pontos = []
    with config.ARQUIVO_CSV_BRUTO_ETAPA5.open(encoding="utf-8", newline="") as arquivo:
        for linha in csv.DictReader(arquivo):
            if linha.get(config.CAMPO_ID_FLUXO) != id_fluxo:
                continue
            if linha.get(config.CAMPO_PERIODO) != config.PERIODO_BASELINE:
                continue
            if linha.get(config.CAMPO_TIPO) != config.TIPO_MEDICAO:
                continue
            instante = inteiro(linha.get(config.CAMPO_TIMESTAMP))
            if not dentro_de_a(instante, inicio, fim):
                continue
            avg = rtt_medio(linha.get(config.CAMPO_AVG), linha.get(config.CAMPO_RESULT))
            if avg is None or instante is None:
                continue
            pontos.append((instante, avg))
    return pontos


def estatisticas_ttl(valores):
    if len(valores) < config.MIN_AMOSTRAS_BASELINE:
        return {
            "ttl_baseline": "",
            "ttl_min_A": texto_numero(min(valores)) if valores else "",
            "ttl_max_A": texto_numero(max(valores)) if valores else "",
            "n_ttl_distintos_A": texto_numero(len(set(valores))) if valores else "",
        }
    return {
        "ttl_baseline": texto_numero(mediana(valores)),
        "ttl_min_A": texto_numero(min(valores)),
        "ttl_max_A": texto_numero(max(valores)),
        "n_ttl_distintos_A": texto_numero(len(set(valores))),
    }


def estatisticas_rtt(avgs, jitters, valido):
    if not valido:
        return {
            "mediana_rtt_A": "",
            "p95_rtt_A": "",
            "p99_rtt_A": "",
            "mediana_jitter_A": "",
            "p95_jitter_A": "",
            "p99_jitter_A": "",
        }
    p95, p99 = config.PERCENTIS
    jitter_ok = bool(jitters)
    return {
        "mediana_rtt_A": texto_numero(mediana(avgs)),
        "p95_rtt_A": texto_numero(percentil_linear(avgs, p95)),
        "p99_rtt_A": texto_numero(percentil_linear(avgs, p99)),
        "mediana_jitter_A": texto_numero(mediana(jitters)) if jitter_ok else "",
        "p95_jitter_A": texto_numero(percentil_linear(jitters, p95)) if jitter_ok else "",
        "p99_jitter_A": texto_numero(percentil_linear(jitters, p99)) if jitter_ok else "",
    }


def montar_linhas(escolhidos, acumulados, ttl_etapa5):
    linhas = []
    divergencias_ttl = []
    msm_multiplos = []
    insuficientes = []
    perda_por_fluxo = {}
    jitter_um_rtt = 0
    fora_janela = 0
    for id_fluxo, fluxo in escolhidos:
        acc = acumulados[id_fluxo]
        fora_janela += acc["fora_janela"]
        jitter_um_rtt += acc["n_jitter_um_rtt"]
        n_rtt = len(acc["avgs"])
        status = config.STATUS_VALIDO if n_rtt >= config.MIN_AMOSTRAS_BASELINE else config.STATUS_INSUFICIENTE
        if status == config.STATUS_INSUFICIENTE:
            insuficientes.append(id_fluxo)
        ttl = estatisticas_ttl(acc["ttls"])
        registro = {
            "anchor_id": str(fluxo["anchor_id"]),
            "probe_id": str(fluxo["probe_id"]),
            "id_fluxo": id_fluxo,
            "n_amostras_A": str(acc["n_amostras"]),
            "n_rtt_validos_A": str(n_rtt),
            "status_baseline": status,
        }
        registro.update(estatisticas_rtt(acc["avgs"], acc["jitters"], status == config.STATUS_VALIDO))
        registro.update(ttl)
        referencia = ttl_etapa5.get((registro["anchor_id"], registro["probe_id"]))
        if referencia is None:
            divergencias_ttl.append({"id_fluxo": id_fluxo, "motivo": "ausente em baseline_ttl_por_par.csv"})
        else:
            diferentes = {
                campo: {"etapa6": registro[campo], "etapa5": referencia.get(campo, "")}
                for campo in config.COLUNAS_TTL_CONFERIR
                if registro[campo] != (referencia.get(campo) or "")
            }
            if diferentes:
                divergencias_ttl.append({"id_fluxo": id_fluxo, "campos": diferentes})
        if len(acc["msm_ids"]) > 1:
            msm_multiplos.append({"id_fluxo": id_fluxo, "msm_ids": sorted(acc["msm_ids"])})
        perda = (100.0 * acc["n_perda"] / acc["n_amostras"]) if acc["n_amostras"] else None
        perda_por_fluxo[id_fluxo] = None if perda is None else round(perda, 6)
        linhas.append(registro)
    linhas.sort(key=lambda item: (inteiro(item["anchor_id"]) or 0, inteiro(item["probe_id"]) or 0))
    return linhas, {
        "divergencias_ttl": divergencias_ttl,
        "msm_multiplos": msm_multiplos,
        "insuficientes": insuficientes,
        "perda_por_fluxo": perda_por_fluxo,
        "execucoes_jitter_um_rtt": jitter_um_rtt,
        "execucoes_fora_da_janela_a": fora_janela,
    }


def escolher_fluxo(linhas, metadados):
    if config.HTML_FLUXO:
        return config.HTML_FLUXO
    por_id = {linha["id_fluxo"]: linha for linha in linhas}
    for id_fluxo, fluxo in metadados["fluxos"].items():
        linha = por_id.get(id_fluxo)
        if not linha or linha["status_baseline"] != config.STATUS_VALIDO:
            continue
        if fluxo["destino"].get("pais") == config.PAIS_DESTAQUE:
            return id_fluxo
    for linha in linhas:
        if linha["status_baseline"] == config.STATUS_VALIDO:
            return linha["id_fluxo"]
    return linhas[0]["id_fluxo"] if linhas else None


def montar_qualidade(metadados, inicio, fim, lidas, ignoradas, escolhidos, fora, excluidos, vistos_em_a, linhas, extra):
    por_status = {config.STATUS_VALIDO: 0, config.STATUS_INSUFICIENTE: 0}
    for linha in linhas:
        por_status[linha["status_baseline"]] = por_status.get(linha["status_baseline"], 0) + 1
    ids_universo = {id_fluxo for id_fluxo, _ in escolhidos}
    fora_dos_dados_a = sorted(id_fluxo for id_fluxo in vistos_em_a if id_fluxo not in ids_universo)
    janela = next(item for item in metadados["periodos"] if item["nome"] == config.PERIODO_BASELINE)
    return {
        "gerado_em": agora_utc().isoformat(),
        "janela_a": {
            "inicio": janela["inicio"],
            "fim": janela["fim"],
            "inicio_unix": inicio,
            "fim_unix": fim,
            "fuso": janela.get("fuso"),
            "fonte": config.FONTE_JANELA,
        },
        "linhas_lidas": lidas,
        "linhas_ignoradas": ignoradas,
        "fluxos_universo": len(linhas),
        "fluxos_por_status": por_status,
        "fluxos_fora_do_universo": fora,
        "fluxos_excluidos": excluidos,
        "fluxos_de_a_fora_do_universo": fora_dos_dados_a,
        "insuficientes": extra["insuficientes"],
        "perda_percent_por_fluxo": extra["perda_por_fluxo"],
        "execucoes_jitter_um_rtt": extra["execucoes_jitter_um_rtt"],
        "execucoes_fora_da_janela_a": extra["execucoes_fora_da_janela_a"],
        "reconciliacao_ttl": extra["divergencias_ttl"],
        "msm_id_multiplos": extra["msm_multiplos"],
        "pagina": {},
        "nota_n_amostras": (
            "n_amostras_A neste arquivo conta execuções de ping. "
            "Em baseline_ttl_por_par.csv da Etapa 5, o mesmo nome conta amostras de TTL."
        ),
    }


def preservar_gerado_em(qualidade):
    if not config.ARQUIVO_QUALIDADE.is_file():
        return
    try:
        anterior = ler_json(config.ARQUIVO_QUALIDADE)
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(anterior, dict) or "gerado_em" not in anterior:
        return
    novo = {chave: valor for chave, valor in qualidade.items() if chave != "gerado_em"}
    velho = {chave: valor for chave, valor in anterior.items() if chave != "gerado_em"}
    if novo == velho:
        qualidade["gerado_em"] = anterior["gerado_em"]


def gravar_csv(linhas):
    with config.ARQUIVO_BASELINE.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(
            arquivo,
            fieldnames=list(config.COLUNAS_BASELINE),
            lineterminator="\n",
            extrasaction="ignore",
        )
        escritor.writeheader()
        for linha in linhas:
            escritor.writerow({coluna: linha.get(coluna, "") for coluna in config.COLUNAS_BASELINE})


def gravar_qualidade(qualidade):
    config.ARQUIVO_QUALIDADE.write_text(
        json.dumps(qualidade, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def esc(valor):
    if valor is None or valor == "":
        return html.escape(config.ROTULO_VAZIO)
    return html.escape(str(valor))


def mostrar(valor):
    if valor is None or valor == "":
        return config.ROTULO_VAZIO
    return str(valor)


def formatar_timestamp(valor):
    instante = inteiro(valor)
    if instante is None:
        return config.ROTULO_VAZIO
    texto = datetime.fromtimestamp(instante, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"{texto} ({instante})"


def exibir_numero(valor):
    if valor is None or valor == "":
        return config.ROTULO_VAZIO
    numero_valor = numero(valor)
    if numero_valor is None:
        return str(valor)
    return f"{numero_valor:.{config.CASAS_EXIBICAO}f}"


def svg_tempo(metadados):
    periodos = metadados["periodos"]
    instantes = []
    for periodo in periodos:
        instantes.append(datetime.fromisoformat(periodo["inicio"]))
        instantes.append(datetime.fromisoformat(periodo["fim"]))
    inicio = min(instantes)
    fim = max(instantes)
    amplitude = (fim - inicio).total_seconds() or 1
    largura = 860

    def x_de(momento):
        return 24 + (momento - inicio).total_seconds() / amplitude * (largura - 48)

    partes = []
    for periodo in periodos:
        começo = datetime.fromisoformat(periodo["inicio"])
        final = datetime.fromisoformat(periodo["fim"])
        x1 = x_de(começo)
        x2 = x_de(final)
        classe = "barra-a" if periodo["nome"] == config.PERIODO_BASELINE else "barra-b"
        partes.append(
            f'<rect class="{classe}" x="{x1:.1f}" y="36" width="{max(x2 - x1, 1):.1f}" height="42" rx="8"/>'
        )
        partes.append(
            f'<text class="rotulo" x="{(x1 + x2) / 2:.1f}" y="62" text-anchor="middle">{esc(periodo["nome"])}</text>'
        )
        partes.append(
            f'<text class="anotacao" x="{x1:.1f}" y="100">{esc(periodo["inicio"][:16].replace("T", " "))}</text>'
        )
    partes.append(
        f'<text class="anotacao" x="{x_de(fim) - 150:.1f}" y="100">{esc(periodos[-1]["fim"][:16].replace("T", " "))}</text>'
    )
    descricao = "Períodos " + " e ".join(
        f"{periodo['nome']} de {periodo['inicio']} a {periodo['fim']}" for periodo in periodos
    )
    return (
        f'<svg viewBox="0 0 {largura} 120" role="img" aria-label="{esc(descricao)}">'
        + "".join(partes)
        + "</svg>"
    )


def svg_serie(pontos, mediana_txt, p95_txt, p99_txt):
    if not pontos:
        return f"<p>{esc(config.TEXTO_INSUFICIENTE)}</p>"
    limites = [valor for valor in (numero(mediana_txt), numero(p95_txt), numero(p99_txt)) if valor is not None]
    avgs = [avg for _, avg in pontos]
    ymin = min(avgs + limites)
    ymax = max(avgs + limites)
    if ymin == ymax:
        ymin -= 1
        ymax += 1
    folga = (ymax - ymin) * 0.08
    ymin -= folga
    ymax += folga
    largura, altura = 920, 320
    esquerda, direita, topo, base = 64, 24, 24, 36

    def x_de(indice):
        if len(pontos) == 1:
            return esquerda
        return esquerda + indice / (len(pontos) - 1) * (largura - esquerda - direita)

    def y_de(valor):
        return topo + (ymax - valor) / (ymax - ymin) * (altura - topo - base)

    coords = " ".join(f"{x_de(i):.1f},{y_de(avg):.1f}" for i, (_, avg) in enumerate(pontos))
    linhas = []
    for valor_txt, classe in ((mediana_txt, "limite-mediana"), (p95_txt, "limite-p95"), (p99_txt, "limite-p99")):
        valor = numero(valor_txt)
        if valor is None:
            continue
        y = y_de(valor)
        linhas.append(
            f'<line class="{classe}" x1="{esquerda}" y1="{y:.1f}" x2="{largura - direita}" y2="{y:.1f}"/>'
        )
    inicio = datetime.fromtimestamp(pontos[0][0], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    final = datetime.fromtimestamp(pontos[-1][0], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    return (
        f'<svg viewBox="0 0 {largura} {altura}" role="img" aria-label="{esc(config.ARIA_GRAFICO)}">'
        f'<polyline class="serie" points="{coords}"/>'
        + "".join(linhas)
        + f'<text class="anotacao" x="{esquerda}" y="{altura - 10}">{esc(inicio)} UTC</text>'
        + f'<text class="anotacao" x="{largura - direita}" y="{altura - 10}" text-anchor="end">{esc(final)} UTC</text>'
        + "</svg>"
    )


def tabela_fluxos(linhas, metadados):
    corpo = []
    for linha in linhas:
        fluxo = metadados["fluxos"][linha["id_fluxo"]]
        destaque = " class=\"destaque\"" if fluxo["destino"].get("pais") == config.PAIS_DESTAQUE else ""
        link = config.URL_PAGINA_PROBE.format(id=linha["probe_id"])
        corpo.append(
            f"<tr{destaque}>"
            f"<td><code>{esc(linha['id_fluxo'])}</code></td>"
            f"<td><a href=\"{html.escape(link, quote=True)}\">{esc(linha['probe_id'])}</a></td>"
            f"<td>{esc(fluxo['origem'].get('pais'))}</td>"
            f"<td>{esc(fluxo['destino'].get('hostname'))}</td>"
            f"<td>{esc(fluxo['destino'].get('pais'))}</td>"
            f"<td>{esc(fluxo['destino'].get('cidade'))}</td>"
            f"<td>{esc(linha['n_amostras_A'])}</td>"
            f"<td>{esc(exibir_numero(linha['mediana_rtt_A']))}</td>"
            f"<td>{esc(exibir_numero(linha['p95_rtt_A']))}</td>"
            f"<td>{esc(exibir_numero(linha['p99_rtt_A']))}</td>"
            f"<td>{esc(linha['status_baseline'])}</td>"
            "</tr>"
        )
    return "\n".join(corpo)


def tabela_amostra(amostra):
    if not amostra:
        return f"<p>{esc(config.TEXTO_INSUFICIENTE)}</p>"
    linhas = []
    for item in amostra:
        linhas.append(
            "<tr>"
            f"<td>{esc(formatar_timestamp(item['timestamp']))}</td>"
            f"<td>{esc(mostrar(item['avg']))}</td>"
            f"<td>{esc(mostrar(item['sent']))}</td>"
            f"<td>{esc(mostrar(item['rcvd']))}</td>"
            "</tr>"
        )
    return (
        "<div class=\"rolagem\"><table><thead><tr>"
        "<th>timestamp (UTC)</th><th>avg</th><th>sent</th><th>rcvd</th>"
        "</tr></thead><tbody>"
        + "".join(linhas)
        + "</tbody></table></div>"
    )


def gerar_html(metadados, linhas, qualidade, exemplo, pontos, amostra, total_execucoes):
    fluxo = metadados["fluxos"].get(exemplo["id_fluxo"], {})
    perda = qualidade["perda_percent_por_fluxo"].get(exemplo["id_fluxo"])
    perda_txt = config.ROTULO_VAZIO if perda is None else f"{perda:.2f}%"
    validos = qualidade["fluxos_por_status"].get(config.STATUS_VALIDO, 0)
    insuficientes = qualidade["fluxos_por_status"].get(config.STATUS_INSUFICIENTE, 0)
    resumo = (
        f"Universo: {qualidade['fluxos_universo']} fluxos. "
        f"Baseline {config.STATUS_VALIDO}: {validos}. "
        f"{config.STATUS_INSUFICIENTE}: {insuficientes}. "
        f"Fora do baseline: {len(qualidade['fluxos_fora_do_universo'])}. "
        f"Excluídos: {len(qualidade['fluxos_excluidos'])}."
    )
    didaticos = []
    for item in config.EXEMPLOS_DIDATICOS:
        didaticos.append(
            "<article class=\"cartao\">"
            f"<p class=\"papel\">{esc(config.ROTULO_DIDATICO)} · {esc(item['nome'])}</p>"
            f"<p>{esc(item['historico'])}</p>"
            f"<p>{esc(item['atual'])}</p>"
            f"<p>{esc(item['leitura'])}</p>"
            "</article>"
        )
    aviso = config.AVISO_AMOSTRA.format(mostradas=len(amostra), total=total_execucoes)
    valores = (
        f"mediana {esc(exibir_numero(exemplo['mediana_rtt_A']))} ms · "
        f"P95 {esc(exibir_numero(exemplo['p95_rtt_A']))} ms · "
        f"P99 {esc(exibir_numero(exemplo['p99_rtt_A']))} ms"
    )
    cuidados = []
    for texto in config.CUIDADOS:
        cuidados.append(f"<li>{esc(texto)}</li>")
    cuidados.append(
        f"<li>Neste fluxo de exemplo, {esc(perda_txt)} das execuções de A tiveram perda (rcvd &lt; sent).</li>"
    )
    css = """
    :root { color-scheme: light; --bg:#f3f1ea; --ink:#1c1915; --muted:#5e584e; --card:#fffdf8; --line:#e4ddd0; --accent:#0f6e56; --br:#c45c26; --cor-a:__COR_A__; --cor-b:__COR_B__; }
    html[data-theme="dark"] { color-scheme: dark; --bg:#12171a; --ink:#f3f1ea; --muted:#b7b1a6; --card:#1c2428; --line:#314046; --accent:#3dbe9a; --br:#e5925d; --cor-a:__COR_A_ESCURO__; --cor-b:__COR_B_ESCURO__; }
    * { box-sizing: border-box; }
    body { margin:0; font-family:"Segoe UI","Helvetica Neue",sans-serif; background:var(--bg); color:var(--ink); font-size:1.12rem; }
    header, main { width:min(1100px, calc(100% - 28px)); margin:0 auto; }
    header { padding:28px 0 8px; display:flex; justify-content:space-between; gap:16px; align-items:flex-start; }
    h1 { margin:8px 0; font-size:2rem; }
    h2 { margin:32px 0 12px; font-size:1.45rem; }
    a { color:var(--br); }
    p, li { line-height:1.45; }
    .voltar { color:var(--accent); text-decoration:none; }
    button { font:inherit; border:1px solid var(--line); background:var(--card); color:var(--ink); border-radius:999px; padding:8px 14px; cursor:pointer; }
    .cartao, .faixa { background:var(--card); border:1px solid var(--line); border-radius:16px; padding:16px; }
    .destaque-texto { border-color:var(--accent); }
    .grade { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:12px; }
    .papel { margin:0 0 8px; color:var(--accent); font-size:.95rem; }
    .rolagem { overflow-x:auto; border:1px solid var(--line); border-radius:12px; }
    table { width:100%; border-collapse:collapse; background:var(--card); }
    th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); white-space:nowrap; }
    tr.destaque { background: color-mix(in srgb, var(--cor-b) 12%, var(--card)); }
    svg { width:100%; height:auto; background:var(--card); border:1px solid var(--line); border-radius:16px; }
    .barra-a { fill:var(--cor-a); fill-opacity:.35; }
    .barra-b { fill:var(--cor-b); fill-opacity:.35; }
    .serie { fill:none; stroke:var(--ink); stroke-width:1.5; }
    .limite-mediana { stroke:var(--cor-a); stroke-width:2; }
    .limite-p95 { stroke:var(--br); stroke-width:2; stroke-dasharray:6 4; }
    .limite-p99 { stroke:var(--ink); stroke-width:2; stroke-dasharray:2 4; }
    .rotulo, .anotacao { font-family:"Segoe UI",sans-serif; }
    .rotulo { fill:var(--ink); font-size:16px; }
    .anotacao { fill:var(--muted); font-size:13px; }
    .legenda span { display:inline-block; margin-right:16px; }
    code { font-family:Consolas,monospace; }
    @media (max-width:800px) { .grade, header { display:flex; flex-direction:column; } }
    """
    css = (
        css.replace("__COR_A_ESCURO__", config.COR_A_ESCURO)
        .replace("__COR_B_ESCURO__", config.COR_B_ESCURO)
        .replace("__COR_A__", config.COR_A)
        .replace("__COR_B__", config.COR_B)
    )
    passos = "".join(f"<p>{esc(texto)}</p>" for texto in config.PASSOS)
    faixas = "".join(f"<li>{esc(texto)}</li>" for texto in config.FAIXAS)
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
    </div>
    <button id="tema" type="button">Tema escuro</button>
  </header>
  <main>
    <section>
      <h2>{esc(config.TITULO_O_QUE_E)}</h2>
      <article class="cartao destaque-texto">
        <p>{esc(config.PERGUNTA_BASELINE)}</p>
        <div class="grade">{''.join(didaticos)}</div>
        <p><strong>{esc(config.DESTAQUE_BASELINE)}</strong></p>
      </article>
    </section>
    <section>
      <h2>{esc(config.TITULO_PERIODO)}</h2>
      <div class="rolagem">{svg_tempo(metadados)}</div>
      <p>{esc(config.LEGENDA_TEMPO)}</p>
    </section>
    <section>
      <h2>{esc(config.TITULO_FLUXOS)}</h2>
      <p>{esc(resumo)}</p>
      <div class="rolagem">
        <table>
          <thead>
            <tr>
              <th>id_fluxo</th><th>probe</th><th>país origem</th>
              <th>hostname</th><th>país destino</th><th>cidade</th>
              <th>n_amostras_A</th><th>mediana_rtt_A</th><th>p95_rtt_A</th><th>p99_rtt_A</th>
              <th>status_baseline</th>
            </tr>
          </thead>
          <tbody>
            {tabela_fluxos(linhas, metadados)}
          </tbody>
        </table>
      </div>
    </section>
    <section>
      <h2>{esc(config.TITULO_COMO)}</h2>
      <p>Fluxo <code>{esc(exemplo['id_fluxo'])}</code> · {esc(fluxo.get('destino', {}).get('hostname'))}</p>
      {passos}
      <p>{esc(aviso)}</p>
      {tabela_amostra(amostra)}
      <p>{esc(config.TEXTO_MEDIANA)}</p>
      <p>{esc(config.TEXTO_P95)}</p>
      <p>{esc(config.TEXTO_P99)}</p>
      <p>{esc(config.TEXTO_EXEMPLO_MEDIANA)}</p>
      <h3>{esc(config.TITULO_GRAFICO)}</h3>
      <div class="rolagem">{svg_serie(pontos, exemplo['mediana_rtt_A'], exemplo['p95_rtt_A'], exemplo['p99_rtt_A'])}</div>
      <p class="legenda">
        <span>mediana</span><span>P95</span><span>P99</span>
      </p>
      <p>{valores}</p>
      <ul>{faixas}</ul>
    </section>
    <section>
      <h2>{esc(config.TITULO_RESULTADO)}</h2>
      <article class="cartao">
        <p>Amostras em A: {esc(exemplo['n_amostras_A'])}. RTTs válidos: {esc(exemplo['n_rtt_validos_A'])}. Status: {esc(exemplo['status_baseline'])}.</p>
        <p>RTT: mediana {esc(exemplo['mediana_rtt_A'])} ms, P95 {esc(exemplo['p95_rtt_A'])} ms, P99 {esc(exemplo['p99_rtt_A'])} ms.</p>
        <p>Jitter: mediana {esc(exemplo['mediana_jitter_A'])} ms, P95 {esc(exemplo['p95_jitter_A'])} ms, P99 {esc(exemplo['p99_jitter_A'])} ms. TTL baseline: {esc(exemplo['ttl_baseline'])}. {esc(config.NOTA_TTL)} {esc(config.NOTA_JITTER)}</p>
      </article>
    </section>
    <section>
      <h2>{esc(config.TITULO_CUIDADOS)}</h2>
      <ul>{''.join(cuidados)}</ul>
    </section>
    <section>
      <h2>{esc(config.TITULO_PROXIMO)}</h2>
      <p>{esc(config.TEXTO_PROXIMO)}</p>
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


def cartao_etapa6(validos):
    frase = f"{validos} fluxos com baseline válido."
    return (
        '<article class="cartao ativo">\n'
        f'      <p class="etapa">{html.escape(config.ROTULO_ETAPA6)}</p>\n'
        f"      <h2>{html.escape(config.TITULO_CARTAO)}</h2>\n"
        f"      <p>{html.escape(frase)}</p>\n"
        f'      <a href="{html.escape(config.LINK_ETAPA6, quote=True)}">Abrir página</a>\n'
        "    </article>"
    )


def atualizar_index(validos):
    bloco = (
        f"{config.MARCADOR_ETAPA6_INICIO}\n    {cartao_etapa6(validos)}\n    {config.MARCADOR_ETAPA6_FIM}"
    )
    texto = config.ARQUIVO_INDEX.read_text(encoding="utf-8")
    if config.MARCADOR_ETAPA6_INICIO in texto and config.MARCADOR_ETAPA6_FIM in texto:
        inicio = texto.index(config.MARCADOR_ETAPA6_INICIO)
        fim = texto.index(config.MARCADOR_ETAPA6_FIM) + len(config.MARCADOR_ETAPA6_FIM)
        config.ARQUIVO_INDEX.write_text(texto[:inicio] + bloco + texto[fim:], encoding="utf-8")
        return
    if config.MARCADOR_ETAPA5_FIM not in texto:
        raise SystemExit("O index.html não tem o cartão da Etapa 5 para preservar o restante da página.")
    config.ARQUIVO_INDEX.write_text(
        texto.replace(config.MARCADOR_ETAPA5_FIM, config.MARCADOR_ETAPA5_FIM + "\n" + bloco, 1),
        encoding="utf-8",
    )


def imprimir_resumo(qualidade):
    print()
    print("=== Resumo da Etapa 6 ===")
    print(f"Janela A: {qualidade['janela_a']['inicio']} → {qualidade['janela_a']['fim']}")
    print(f"Linhas lidas: {qualidade['linhas_lidas']}")
    print(f"Ignoradas: {qualidade['linhas_ignoradas']}")
    print(f"Fluxos do universo: {qualidade['fluxos_universo']}")
    print(f"Por status: {qualidade['fluxos_por_status']}")
    print(f"Fora do baseline: {len(qualidade['fluxos_fora_do_universo'])}")
    print(f"Excluídos: {len(qualidade['fluxos_excluidos'])}")
    print(f"Fluxos de A fora do universo: {len(qualidade['fluxos_de_a_fora_do_universo'])}")
    print(f"Divergências de TTL: {len(qualidade['reconciliacao_ttl'])}")
    print(f"msm_id múltiplos: {len(qualidade['msm_id_multiplos'])}")
    print(f"Página: {qualidade['pagina'].get('id_fluxo')}")
    print(f"CSV: {config.ARQUIVO_BASELINE}")
    print(f"HTML: {config.ARQUIVO_HTML}")
    print()


def main():
    preparar_saida()
    argparse.ArgumentParser(description="Constrói o baseline de RTT do Período A.").parse_args()
    garantir_pastas()
    copiar_prompt()
    conferir_exemplo_didatico()
    metadados, inicio, fim = carregar_metadados()
    ttl_etapa5 = carregar_ttl_etapa5()
    exclusoes = carregar_exclusoes()
    escolhidos, fora, excluidos = universo(metadados, exclusoes)
    ids = [id_fluxo for id_fluxo, fluxo in escolhidos if af_do_fluxo(metadados, fluxo) == config.ADDRESS_FAMILY]
    if len(ids) != len(escolhidos):
        raise SystemExit("Há fluxo do universo cuja medição não é IPv4.")
    acumulados, lidas, ignoradas, vistos_em_a = ler_periodo_a(ids, inicio, fim)
    linhas, extra = montar_linhas(escolhidos, acumulados, ttl_etapa5)
    id_pagina = escolher_fluxo(linhas, metadados)
    qualidade = montar_qualidade(
        metadados, inicio, fim, lidas, ignoradas, escolhidos, fora, excluidos, vistos_em_a, linhas, extra
    )
    qualidade["pagina"] = {"id_fluxo": id_pagina}
    preservar_gerado_em(qualidade)
    gravar_csv(linhas)
    gravar_qualidade(qualidade)
    exemplo = next(linha for linha in linhas if linha["id_fluxo"] == id_pagina)
    pontos = serie_do_exemplo(id_pagina, inicio, fim)
    config.ARQUIVO_HTML.write_text(
        gerar_html(
            metadados,
            linhas,
            qualidade,
            exemplo,
            pontos,
            acumulados[id_pagina]["amostra"],
            acumulados[id_pagina]["n_amostras"],
        ),
        encoding="utf-8",
    )
    validos = qualidade["fluxos_por_status"].get(config.STATUS_VALIDO, 0)
    atualizar_index(validos)
    imprimir_resumo(qualidade)
    if not linhas:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
