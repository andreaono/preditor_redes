"""Gera o HTML estático do estado do modelo em produção.

Cada número cita o arquivo de onde saiu. Amostra pequena fica inconclusiva.
A persistência nas transições é 0 por construção e não vira razão.
"""

import html
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sklearn.metrics import f1_score, precision_score, recall_score

from src.ajustes import RAIZ
from src.congelar_criterios import hash_arquivo, pendencias

CLASSES = ("OK", "RISCO", "FALHA")
FRASE_CAUSA = "Importância e drift não provam causalidade"
FRASE_CAMPO = "O teste de campo não ajusta o modelo"
SECOES = (
    "Estado do modelo",
    "Operação",
    "Desempenho no campo",
    "Drift",
    "Alertas",
    "Decisões",
    "Limites",
)


def _agora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ler_jsonl(pasta: Path) -> list[dict]:
    if not pasta.is_dir():
        return []
    linhas = []
    for arquivo in sorted(pasta.glob("*.jsonl")):
        for texto in arquivo.read_text(encoding="utf-8").splitlines():
            if not texto.strip():
                continue
            item = json.loads(texto)
            if pasta.parent.parent in arquivo.parents:
                item["_arquivo"] = str(arquivo.relative_to(pasta.parent.parent)).replace("\\", "/")
            else:
                item["_arquivo"] = arquivo.name
            linhas.append(item)
    return linhas


def _relativo(raiz: Path, caminho: Path) -> str:
    try:
        return str(caminho.relative_to(raiz)).replace("\\", "/")
    except ValueError:
        return caminho.name


def _ultimo(pasta: Path, padrao: str) -> Path | None:
    achados = sorted(pasta.glob(padrao)) if pasta.is_dir() else []
    return achados[-1] if achados else None


def _criterios(raiz: Path) -> dict:
    yaml_path = raiz / "config" / "criterios.yaml"
    lock_path = raiz / "config" / "criterios.lock"
    if not yaml_path.is_file():
        return {"fonte": "config/criterios.yaml", "integridade": "ausente", "pendencias": ["arquivo ausente"], "limiares": {}}
    documento = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    faltas = pendencias(documento)
    if not lock_path.is_file():
        integridade = "ausente"
    else:
        guardado = json.loads(lock_path.read_text(encoding="utf-8"))
        integridade = "integro" if guardado.get("sha256") == hash_arquivo(yaml_path) else "alterado"
    return {
        "fonte": "config/criterios.yaml",
        "fonte_lock": "config/criterios.lock",
        "integridade": integridade,
        "pendencias": faltas,
        "limiares": (documento.get("limiares") or {}),
        "minimo_eventos_falha": documento.get("minimo_eventos_falha"),
        "minimo_fluxos": documento.get("minimo_fluxos"),
        "periodo_minimo_coleta_dias": documento.get("periodo_minimo_coleta_dias"),
    }


def _minimo(raiz: Path) -> int:
    arquivo = raiz / "config" / "drift.yaml"
    if not arquivo.is_file():
        return 30
    documento = yaml.safe_load(arquivo.read_text(encoding="utf-8")) or {}
    return int(documento.get("minimo_amostra") or 30)


def _manifesto(raiz: Path) -> dict:
    caminho = raiz / "modelo" / "modelo_manifest.json"
    if not caminho.is_file():
        return {"fonte": "modelo/modelo_manifest.json", "ausente": True}
    documento = json.loads(caminho.read_text(encoding="utf-8"))
    documento["fonte"] = "modelo/modelo_manifest.json"
    documento["ausente"] = False
    return documento


def _operacao(raiz: Path) -> dict:
    coleta = _ler_jsonl(raiz / "logs" / "coleta")
    vistos: set[tuple] = set()
    linhas = []
    for item in coleta:
        chave = (item.get("_arquivo"), item.get("fluxo_id"))
        if chave in vistos:
            continue
        vistos.add(chave)
        linhas.append(item)
    coletadas = descartadas = timeouts = sem_resultado = 0
    for item in linhas:
        situacoes = item.get("situacoes") or {}
        coletadas += int(situacoes.get("ok") or 0) + int(situacoes.get("timeout") or 0)
        descartadas += int(situacoes.get("invalida") or 0)
        timeouts += int(situacoes.get("timeout") or 0)
        sem_resultado += int(situacoes.get("sem_resultado") or 0)
    estados = []
    pasta_estado = raiz / "logs" / "estado"
    if pasta_estado.is_dir():
        for arquivo in sorted(pasta_estado.glob("*.json")):
            documento = json.loads(arquivo.read_text(encoding="utf-8"))
            estados.append({"fluxo_id": documento.get("fluxo_id"), "estado": documento.get("estado"), "fonte": _relativo(raiz, arquivo)})
    erros = _ler_jsonl(raiz / "logs" / "erros")
    http = [item for item in _ler_jsonl(raiz / "logs" / "coleta_http") if item.get("falha_coleta")]
    execucoes = sorted({item.get("_arquivo") for item in coleta})
    return {
        "fonte_coleta": "logs/coleta",
        "fonte_estado": "logs/estado",
        "fonte_erros": "logs/erros",
        "execucoes": execucoes,
        "n_execucoes": len(execucoes),
        "coletadas": coletadas,
        "descartadas": descartadas,
        "timeouts_medicao": timeouts,
        "sem_resultado": sem_resultado,
        "aquecimento": [item for item in estados if item.get("estado") == "aquecimento"],
        "n_estados": len(estados),
        "falhas_coleta": len(erros) + len(http),
        "n_erros": len(erros),
        "n_http": len(http),
    }


def _predicoes(raiz: Path) -> list[dict]:
    return _ler_jsonl(raiz / "logs" / "predicoes")


def _periodo(predicoes: list[dict]) -> dict:
    instantes = sorted(item["ts_previsao"] for item in predicoes if item.get("ts_previsao"))
    if not instantes:
        return {"inicio": None, "fim": None, "n": 0}
    return {"inicio": instantes[0], "fim": instantes[-1], "n": len(predicoes)}


def _f1_uma(y_true: list[str], y_pred: list[str], classe: str) -> dict:
    suporte = sum(item == classe for item in y_true)
    if not y_true:
        return {"precisao": None, "recall": None, "f1": None, "suporte": 0}
    precisao = float(precision_score(y_true, y_pred, labels=[classe], average="macro", zero_division=0))
    recall = float(recall_score(y_true, y_pred, labels=[classe], average="macro", zero_division=0))
    f1 = float(f1_score(y_true, y_pred, labels=[classe], average="macro", zero_division=0))
    return {"precisao": precisao, "recall": recall, "f1": f1, "suporte": suporte}


def _matriz(y_true: list[str], y_pred: list[str]) -> list[list[int]]:
    return [[sum(real == linha and previsto == coluna for real, previsto in zip(y_true, y_pred)) for coluna in CLASSES] for linha in CLASSES]


def _macro(y_true: list[str], y_pred: list[str]) -> float | None:
    if not y_true:
        return None
    return float(f1_score(y_true, y_pred, average="macro", labels=list(CLASSES), zero_division=0))


def _fatia_de_pares(pares: list[dict], minimo: int, transicoes: bool) -> dict:
    n = len(pares)
    if n < minimo:
        return {"n": n, "status": "INCONCLUSIVO", "persistencia": "0 (por construção)" if transicoes else None}
    reais = [item["rotulo_real"] for item in pares]
    previstos = [item["classe_prevista"] for item in pares]
    base = [item["classe_atual"] for item in pares]
    resultado = {
        "n": n,
        "status": "calculado",
        "macro_f1": _macro(reais, previstos),
        "recall_falha": _f1_uma(reais, previstos, "FALHA")["recall"],
        "por_classe": {classe: _f1_uma(reais, previstos, classe) for classe in CLASSES},
        "matriz": _matriz(reais, previstos),
    }
    if transicoes:
        resultado["persistencia"] = "0 (por construção)"
        resultado["ganho"] = None
    else:
        resultado["macro_f1_persistencia"] = _macro(reais, base)
        if resultado["macro_f1"] is not None and resultado["macro_f1_persistencia"] is not None:
            resultado["ganho"] = resultado["macro_f1"] - resultado["macro_f1_persistencia"]
    return resultado


def _desempenho_logs(predicoes: list[dict], minimo: int) -> dict:
    rotuladas = [item for item in predicoes if item.get("rotulo_real") in CLASSES and item.get("classe_atual") in CLASSES]
    transicoes = [item for item in rotuladas if item["rotulo_real"] != item["classe_atual"]]
    return {
        "fonte": "logs/predicoes",
        "n_previsoes": len(predicoes),
        "n_rotulos": len(rotuladas),
        "fatias": {
            "geral": _fatia_de_pares(rotuladas, minimo, False),
            "transicoes": _fatia_de_pares(transicoes, minimo, True),
            "por_continente": {"n": 0, "status": "INCONCLUSIVO"},
            "probe_vs_anchor": {"n": 0, "status": "INCONCLUSIVO"},
            "com_e_sem_anchor_dominante": {"n": 0, "status": "INCONCLUSIVO"},
        },
    }


def _desempenho(raiz: Path, predicoes: list[dict], minimo: int) -> dict:
    caminho = _ultimo(raiz / "relatorios", "campo_*.json")
    if caminho is None:
        calculado = _desempenho_logs(predicoes, minimo)
        calculado["minimo"] = minimo
        return calculado
    documento = json.loads(caminho.read_text(encoding="utf-8"))
    documento["fonte"] = _relativo(raiz, caminho)
    documento["minimo"] = minimo
    documento.setdefault("n_previsoes", documento.get("n"))
    documento.setdefault("n_rotulos", documento.get("n"))
    return documento


def _amostra_curta(fatia: dict, minimo: int) -> bool:
    n = fatia.get("n")
    if n is None or int(n) < minimo:
        return True
    return fatia.get("status") in ("INCONCLUSIVO", "amostra_insuficiente")


def _veredito_criterios(criterios: dict, desempenho: dict, minimo: int) -> str:
    """PASSOU só com lock íntegro, pisos preenchidos e fatias acima do mínimo."""
    if criterios.get("integridade") != "integro" or criterios.get("pendencias"):
        return "INCONCLUSIVO"
    limiares = criterios.get("limiares") or {}
    fatias = desempenho.get("fatias") or {}
    transicoes = fatias.get("transicoes") or {}
    geral = fatias.get("geral") or {}
    if _amostra_curta(transicoes, minimo) and _amostra_curta(geral, minimo):
        return "INCONCLUSIVO"
    comparacoes = (
        (None if _amostra_curta(transicoes, minimo) else transicoes.get("macro_f1"), limiares.get("macro_f1_transicoes_min")),
        (None if _amostra_curta(geral, minimo) else geral.get("recall_falha"), limiares.get("recall_falha_min")),
        (None if _amostra_curta(geral, minimo) else geral.get("ganho"), limiares.get("ganho_sobre_persistencia_min")),
    )
    if any(piso is None for _, piso in comparacoes):
        return "INCONCLUSIVO"
    presentes = [(valor, piso) for valor, piso in comparacoes if valor is not None]
    if not presentes:
        return "INCONCLUSIVO"
    if any(float(valor) < float(piso) for valor, piso in presentes):
        return "FALHOU"
    if len(presentes) < len(comparacoes):
        return "ATENCAO"
    outras = [fatias.get(nome) or {} for nome in ("por_continente", "probe_vs_anchor", "com_e_sem_anchor_dominante")]
    if any(_amostra_curta(item, minimo) for item in outras):
        return "ATENCAO"
    if limiares.get("antecedencia_media_min_minutos") is not None and desempenho.get("antecedencia_media_min") is None:
        return "ATENCAO"
    return "PASSOU"


def _drift(raiz: Path) -> dict:
    caminho = _ultimo(raiz / "relatorios", "drift_*.json")
    if caminho is None:
        return {"fonte": "relatorios/drift_*.json", "ausente": True, "janelas": []}
    documento = json.loads(caminho.read_text(encoding="utf-8"))
    documento["fonte"] = _relativo(raiz, caminho)
    documento["ausente"] = False
    return documento


def _alertas(raiz: Path) -> list[dict]:
    return _ler_jsonl(raiz / "logs" / "alertas")


def _decisoes(raiz: Path) -> list[dict]:
    caminho = raiz / "docs" / "decisoes.md"
    if not caminho.is_file():
        return []
    quando = ""
    linhas = []
    for texto in caminho.read_text(encoding="utf-8").splitlines():
        if texto.startswith("## "):
            quando = texto[3:].strip()
            continue
        if not quando or texto.startswith("#") or not texto.strip():
            continue
        linhas.append({"quando": quando, "texto": texto.strip(), "fonte": "docs/decisoes.md"})
    return linhas


def coletar(raiz: Path | None = None) -> dict:
    """Lê os arquivos de produção. Pasta vazia devolve estrutura sem métrica inventada."""
    base = Path(raiz) if raiz is not None else RAIZ
    predicoes = _predicoes(base)
    minimo = _minimo(base)
    criterios = _criterios(base)
    desempenho = _desempenho(base, predicoes, minimo)
    return {
        "gerado_em": _agora(),
        "periodo": _periodo(predicoes),
        "manifesto": _manifesto(base),
        "criterios": criterios,
        "operacao": _operacao(base),
        "desempenho": desempenho,
        "veredito": _veredito_criterios(criterios, desempenho, minimo),
        "drift": _drift(base),
        "alertas": _alertas(base),
        "decisoes": _decisoes(base),
        "minimo": minimo,
    }


def _e(valor) -> str:
    return html.escape("" if valor is None else str(valor))


def _num(valor) -> str:
    if valor is None:
        return "—"
    if isinstance(valor, float):
        return f"{valor:.3f}".replace(".", ",")
    return str(valor)


def _celula_metrica(valor, n: int | None, fonte: str) -> str:
    if n is None:
        return "—"
    if valor is None:
        return f"inconclusivo (n={n}). Origem: {_e(fonte)}"
    return f"{_num(valor)} (n={n}). Origem: {_e(fonte)}"


def _css() -> str:
    return """
    :root { color-scheme: light; }
    body { margin: 0; font: 16px/1.45 Georgia, "Times New Roman", serif; color: #1c1915; background: #f4f1ea; }
    main { max-width: 980px; margin: 0 auto; padding: 1.25rem; }
    h1, h2 { font-family: "Segoe UI", sans-serif; color: #0c2f4a; line-height: 1.2; }
    h2 { margin-top: 2rem; border-bottom: 2px solid #0c2f4a; padding-bottom: 0.2rem; }
    .aviso { background: #0c2f4a; color: #f4f1ea; padding: 0.6rem 0.8rem; margin: 0.4rem 0; }
    .selo { display: inline-block; padding: 0.1rem 0.45rem; font-family: "Segoe UI", sans-serif; font-size: 0.85rem; }
    .INCONCLUSIVO, .ATENCAO, .amostra_insuficiente, .ausente { background: #efe6c9; color: #3d3208; }
    .PASSOU, .estavel, .integro { background: #d9efe4; color: #0d4f32; }
    .FALHOU, .alerta, .alterado { background: #f6d9dc; color: #7a1420; }
    .atencao { background: #efe6c9; color: #3d3208; }
    table { border-collapse: collapse; width: 100%; background: #fffdf8; margin: 0.6rem 0 1rem; }
    th, td { border: 1px solid #c8bfb0; padding: 0.35rem 0.5rem; text-align: left; vertical-align: top; }
    th { background: #e7eef3; color: #0c2f4a; }
    caption { text-align: left; font-size: 0.9rem; margin-bottom: 0.3rem; }
    .rolagem { overflow-x: auto; }
    input { font: 1rem Georgia, serif; padding: 0.3rem; width: min(100%, 24rem); }
    svg { max-width: 100%; height: auto; background: #fffdf8; }
    @media (max-width: 640px) { main { padding: 0.8rem; } h1 { font-size: 1.45rem; } }
    """


def _js() -> str:
    return """
    document.querySelectorAll("table.ordenavel").forEach(function (tabela) {
      tabela.querySelectorAll("th").forEach(function (th, indice) {
        th.tabIndex = 0;
        th.addEventListener("click", function () { ordenar(tabela, indice); });
        th.addEventListener("keydown", function (evento) { if (evento.key === "Enter") ordenar(tabela, indice); });
      });
    });
    function ordenar(tabela, indice) {
      var corpo = tabela.tBodies[0];
      var linhas = Array.prototype.slice.call(corpo.rows);
      var desc = tabela.getAttribute("data-col") === String(indice) && tabela.getAttribute("data-dir") !== "desc";
      linhas.sort(function (a, b) {
        var x = a.cells[indice].innerText;
        var y = b.cells[indice].innerText;
        if (x < y) return desc ? 1 : -1;
        if (x > y) return desc ? -1 : 1;
        return 0;
      });
      linhas.forEach(function (linha) { corpo.appendChild(linha); });
      tabela.setAttribute("data-col", String(indice));
      tabela.setAttribute("data-dir", desc ? "desc" : "asc");
    }
    var busca = document.getElementById("busca-decisoes");
    if (busca) {
      busca.addEventListener("input", function () {
        var termo = busca.value.toLowerCase();
        document.querySelectorAll("#tabela-decisoes tbody tr").forEach(function (linha) {
          linha.hidden = termo && linha.innerText.toLowerCase().indexOf(termo) === -1;
        });
      });
    }
    """


def _estado(dados: dict) -> str:
    manifesto = dados["manifesto"]
    criterios = dados["criterios"]
    if manifesto.get("ausente"):
        corpo = "<p>Não há manifesto. Origem esperada: modelo/modelo_manifest.json.</p>"
    else:
        corpo = (
            "<table class='ordenavel'><caption>Origem: modelo/modelo_manifest.json</caption><tbody>"
            f"<tr><th scope='row'>Versão</th><td>{_e(manifesto.get('modelo_versao'))}</td></tr>"
            f"<tr><th scope='row'>Hash</th><td>{_e(manifesto.get('sha256'))}</td></tr>"
            f"<tr><th scope='row'>Data</th><td>{_e(manifesto.get('treinado_em'))}. {_e(manifesto.get('origem_treinado_em'))}</td></tr>"
            "</tbody></table>"
        )
    limiares = criterios.get("limiares") or {}
    linhas = "".join(
        f"<tr><td>{_e(nome)}</td><td>{'vazio' if valor is None else _e(valor)}</td></tr>"
        for nome, valor in limiares.items()
    ) or "<tr><td colspan='2'>Não há limiares no arquivo.</td></tr>"
    return (
        "<section id='estado'><h2>Estado do modelo</h2>"
        + corpo
        + f"<p>Lock dos critérios: <span class='selo {_e(criterios.get('integridade'))}'>{_e(criterios.get('integridade'))}</span>. "
        + f"Origem: {_e(criterios.get('fonte'))} e {_e(criterios.get('fonte_lock'))}.</p>"
        + ("<p>Pendências: " + _e(", ".join(criterios.get("pendencias") or [])) + ".</p>" if criterios.get("pendencias") else "")
        + "<div class='rolagem'><table class='ordenavel'><caption>Critérios. Vazio significa que o piso ainda não foi decidido.</caption>"
        + "<thead><tr><th>Piso</th><th>Valor</th></tr></thead><tbody>"
        + linhas
        + "</tbody></table></div></section>"
    )


def _operacao_html(html_dados: dict) -> str:
    op = html_dados["operacao"]
    aquecimento = op["aquecimento"]
    lista = "".join(f"<li>{_e(item['fluxo_id'])}. Origem: {_e(item['fonte'])}</li>" for item in aquecimento)
    if not lista:
        lista = "<li>Nenhum fluxo em aquecimento.</li>"
    execucoes = ", ".join(op["execucoes"]) if op["execucoes"] else "nenhuma"
    return (
        "<section id='operacao'><h2>Operação</h2>"
        "<div class='rolagem'><table><caption>Contagens deduplicadas por arquivo e fluxo. "
        f"Origem: {_e(op['fonte_coleta'])}.</caption>"
        "<thead><tr><th>Medida</th><th>Valor</th><th>n</th></tr></thead><tbody>"
        f"<tr><td>Execuções</td><td>{_e(execucoes)}</td><td>{op['n_execucoes']}</td></tr>"
        f"<tr><td>Linhas coletadas</td><td>{op['coletadas']}</td><td>{op['coletadas']}</td></tr>"
        f"<tr><td>Linhas descartadas</td><td>{op['descartadas']}</td><td>{op['descartadas']}</td></tr>"
        f"<tr><td>Timeout de medição</td><td>{op['timeouts_medicao']}</td><td>{op['timeouts_medicao']}</td></tr>"
        f"<tr><td>Sem resultado</td><td>{op['sem_resultado']}</td><td>{op['sem_resultado']}</td></tr>"
        f"<tr><td>Falhas de coleta</td><td>{op['falhas_coleta']}</td><td>{op['falhas_coleta']}. Origem: {_e(op['fonte_erros'])} e logs/coleta_http</td></tr>"
        "</tbody></table></div>"
        f"<h3>Fluxos em aquecimento (n={len(aquecimento)})</h3><ul>{lista}</ul>"
        "</section>"
    )


def _tabela_fatia(nome: str, fatia: dict, fonte: str, minimo: int) -> str:
    n = fatia.get("n")
    curta = n is None or int(n) < minimo or fatia.get("status") in ("INCONCLUSIVO", "amostra_insuficiente")
    if curta or (fatia.get("macro_f1") is None and nome != "transicoes"):
        extra = ""
        if nome == "transicoes":
            extra = " Persistência: 0 (por construção). A razão não é calculada."
        return (
            f"<h3>{_e(nome)}</h3><p><span class='selo INCONCLUSIVO'>INCONCLUSIVO</span> "
            f"(n={0 if n is None else n}).{_e(extra)} Origem: {_e(fonte)}.</p>"
        )
    if nome == "transicoes":
        texto_base = "0 (por construção). A razão não é calculada."
    else:
        texto_base = _celula_metrica(fatia.get("macro_f1_persistencia"), n, fonte)
    classes = fatia.get("por_classe") or {}
    linhas_classe = ""
    for classe in CLASSES:
        item = classes.get(classe) or {}
        linhas_classe += (
            f"<tr><td>{classe}</td><td>{_celula_metrica(item.get('precisao'), item.get('suporte'), fonte)}</td>"
            f"<td>{_celula_metrica(item.get('recall'), item.get('suporte'), fonte)}</td>"
            f"<td>{_celula_metrica(item.get('f1'), item.get('suporte'), fonte)}</td></tr>"
        )
    matriz = fatia.get("matriz") or []
    corpo_matriz = ""
    for indice, linha in enumerate(matriz):
        corpo_matriz += "<tr><th scope='row'>" + CLASSES[indice] + "</th>" + "".join(f"<td>{_e(valor)} (n={n})</td>" for valor in linha) + "</tr>"
    ic = fatia.get("ic_macro_f1")
    texto_ic = "IC não calculado" if not ic else f"[{_num(ic[0])}, {_num(ic[1])}] (n={n})"
    return (
        f"<h3>{_e(nome)}</h3>"
        f"<p>Macro-F1 do modelo: {_celula_metrica(fatia.get('macro_f1'), n, fonte)}</p>"
        f"<p>Macro-F1 da persistência: {_e(texto_base) if nome == 'transicoes' else texto_base}</p>"
        f"<p>Intervalo do macro-F1: {_e(texto_ic)}. Origem: {_e(fonte)}.</p>"
        + "<div class='rolagem'><table class='ordenavel'><caption>Métricas por classe.</caption>"
        + "<thead><tr><th>Classe</th><th>Precisão</th><th>Recall</th><th>F1</th></tr></thead><tbody>"
        + linhas_classe
        + "</tbody></table></div>"
        + ("<div class='rolagem'><table><caption>Matriz de confusão. Linha é o rótulo real, coluna é a previsão.</caption>"
           + "<thead><tr><th>real \\ prevista</th><th>OK</th><th>RISCO</th><th>FALHA</th></tr></thead><tbody>"
           + corpo_matriz + "</tbody></table></div>" if matriz else "")
    )


def _desempenho_html(dados: dict) -> str:
    desempenho = dados["desempenho"]
    fonte = desempenho.get("fonte") or "logs/predicoes"
    fatias = desempenho.get("fatias") or {}
    blocos = "".join(
        _tabela_fatia(nome, fatias.get(nome) or {"n": 0, "status": "INCONCLUSIVO"}, fonte, dados["minimo"])
        for nome in (
        "geral", "transicoes", "por_continente", "probe_vs_anchor", "com_e_sem_anchor_dominante"
    ))
    return (
        "<section id='desempenho'><h2>Desempenho no campo</h2>"
        f"<p>Veredito dos critérios: <span class='selo {_e(dados['veredito'])}'>{_e(dados['veredito'])}</span>. "
        f"Rótulos disponíveis: n={desempenho.get('n_rotulos')}. Mínimo configurado: n={dados['minimo']}. Origem: {_e(fonte)}.</p>"
        + blocos
        + "</section>"
    )


def _barras(features: dict, n: int, fonte: str) -> str:
    itens = [(nome, info) for nome, info in features.items() if info.get("psi") is not None]
    if not itens:
        return f"<p><span class='selo INCONCLUSIVO'>INCONCLUSIVO</span> Sem PSI por feature (n={n}). Origem: {_e(fonte)}.</p>"
    altura = 22
    escala = 520
    linhas = [
        "<svg role='img' aria-label='PSI por feature' viewBox='0 0 760 "
        + str(36 + altura * len(itens))
        + "'>"
    ]
    linhas.append("<rect x='200' y='8' width='104' height='12' fill='#d9efe4'></rect><text x='200' y='18' font-size='11'>estável &lt; 0,1</text>")
    linhas.append("<rect x='310' y='8' width='156' height='12' fill='#efe6c9'></rect><text x='314' y='18' font-size='11'>atenção</text>")
    linhas.append("<rect x='466' y='8' width='260' height='12' fill='#f6d9dc'></rect><text x='470' y='18' font-size='11'>alerta &gt; 0,25</text>")
    for indice, (nome, info) in enumerate(itens):
        psi = min(float(info["psi"]), 0.5)
        y = 28 + indice * altura
        largura_barra = max(1, int(psi / 0.5 * escala))
        linhas.append(f"<text x='0' y='{y + 14}' font-size='12'>{_e(nome)}</text>")
        linhas.append(f"<rect x='200' y='{y}' width='{largura_barra}' height='16' fill='#0c2f4a'></rect>")
        linhas.append(f"<text x='{206 + largura_barra}' y='{y + 13}' font-size='12'>{_num(info['psi'])} (n={n})</text>")
    linhas.append("</svg>")
    linhas.append(f"<p>Origem: {_e(fonte)}. As faixas são 0,1 e 0,25.</p>")
    return "\n".join(linhas)


def _drift_html(dados: dict) -> str:
    drift = dados["drift"]
    fonte = drift.get("fonte") or "relatorios/drift_*.json"
    if drift.get("ausente"):
        return f"<section id='drift'><h2>Drift</h2><p>Não há relatório de drift. Origem esperada: {_e(fonte)}.</p></section>"
    blocos = []
    for janela in drift.get("janelas") or []:
        n = int(janela.get("n") or 0)
        status = (janela.get("data_drift") or {}).get("status") or "amostra_insuficiente"
        features = (janela.get("data_drift") or {}).get("features") or {}
        fatias = "".join(
            f"<tr><td>{_e(item.get('tipo'))}</td><td>{_e(item.get('chave'))}</td><td>{_e(item.get('n'))}</td>"
            f"<td><span class='selo { _e(item.get('status')) }'>{_e(item.get('status'))}</span></td></tr>"
            for item in janela.get("fatias") or []
        ) or "<tr><td colspan='4'>Sem fatias.</td></tr>"
        blocos.append(
            f"<h3>{_e(janela.get('nome'))} (n={n})</h3>"
            f"<p>Status dos dados: <span class='selo {_e(status)}'>{_e(status)}</span>.</p>"
            + (_barras(features, n, fonte) if status != "amostra_insuficiente" else
               f"<p><span class='selo INCONCLUSIVO'>INCONCLUSIVO</span> Amostra insuficiente para PSI (n={n}). Origem: {_e(fonte)}.</p>")
            + "<div class='rolagem'><table class='ordenavel'><caption>Fatias.</caption>"
            + "<thead><tr><th>Tipo</th><th>Chave</th><th>n</th><th>Status</th></tr></thead><tbody>"
            + fatias + "</tbody></table></div>"
        )
    return "<section id='drift'><h2>Drift</h2>" + "".join(blocos) + "</section>"


def _alertas_html(dados: dict) -> str:
    alertas = dados["alertas"]
    if not alertas:
        return "<section id='alertas'><h2>Alertas</h2><p>Não há alertas em logs/alertas.</p></section>"
    linhas = []
    for item in alertas:
        evidencia = json.dumps(item.get("evidencia"), ensure_ascii=False)
        linhas.append(
            f"<tr><td>{_e(item.get('id'))}</td><td>{_e(item.get('regra'))}</td><td>{_e(item.get('gravidade'))}</td>"
            f"<td>{_e(item.get('status'))}</td><td>{_e(evidencia)}. Origem: {_e(item.get('_arquivo'))}</td></tr>"
        )
    abertos = sum(item.get("status") == "aberto" for item in alertas)
    resolvidos = sum(item.get("status") == "resolvido" for item in alertas)
    return (
        "<section id='alertas'><h2>Alertas</h2>"
        f"<p>Abertos: n={abertos}. Resolvidos: n={resolvidos}. Total: n={len(alertas)}. Origem: logs/alertas.</p>"
        "<div class='rolagem'><table class='ordenavel'><thead><tr><th>Id</th><th>Regra</th><th>Gravidade</th><th>Status</th><th>Evidência</th></tr></thead><tbody>"
        + "".join(linhas) + "</tbody></table></div></section>"
    )


def _decisoes_html(dados: dict) -> str:
    linhas = dados["decisoes"]
    if not linhas:
        corpo = "<p>Não há decisões em docs/decisoes.md.</p>"
    else:
        corpo = (
            "<label for='busca-decisoes'>Pesquisar decisões</label> "
            "<input id='busca-decisoes' type='search'>"
            "<div class='rolagem'><table class='ordenavel' id='tabela-decisoes'><caption>Origem: docs/decisoes.md. "
            f"n={len(linhas)}.</caption><thead><tr><th>Quando</th><th>Texto</th></tr></thead><tbody>"
            + "".join(f"<tr><td>{_e(item['quando'])}</td><td>{_e(item['texto'])}</td></tr>" for item in linhas)
            + "</tbody></table></div>"
        )
    return "<section id='decisoes'><h2>Decisões</h2>" + corpo + "</section>"


def _limites(dados: dict) -> str:
    n_rotulos = dados["desempenho"].get("n_rotulos") or 0
    n_falha = 0
    geral = (dados["desempenho"].get("fatias") or {}).get("geral") or {}
    por_classe = geral.get("por_classe") or {}
    if por_classe.get("FALHA"):
        n_falha = por_classe["FALHA"].get("suporte") or 0
    return (
        "<section id='limites'><h2>Limites</h2><ul>"
        f"<li>Rótulos reais preenchidos: n={n_rotulos}. Sem rótulo, o desempenho do campo é inconclusivo.</li>"
        f"<li>FALHA com rótulo na fatia geral: n={n_falha}. Poucas FALHAS não sustentam o recall.</li>"
        f"<li>Período coberto: n={dados['periodo']['n']} previsões"
        f" de {_e(dados['periodo']['inicio'])} a {_e(dados['periodo']['fim'])}. Janela curta não fecha o campo.</li>"
        f"<li>Fatia com n abaixo de {dados['minimo']} aparece como inconclusiva e não como alerta.</li>"
        "<li>Os pisos de aceite continuam vazios enquanto o lock não existir. O relatório não os preenche.</li>"
        "</ul></section>"
    )


def renderizar(dados: dict) -> str:
    """Monta a página. O conteúdo essencial está no HTML, sem depender de script."""
    periodo = dados["periodo"]
    if periodo["inicio"] is None:
        texto_periodo = f"Período coberto: sem previsões (n={periodo['n']})."
    else:
        texto_periodo = f"Período coberto: {_e(periodo['inicio'])} a {_e(periodo['fim'])} (n={periodo['n']})."
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Relatório de produção</title>
<style>{_css()}</style>
</head>
<body>
<main>
<h1>Relatório de produção</h1>
<p>Gerado em {_e(dados['gerado_em'])} UTC.</p>
<p>{texto_periodo}</p>
<p class="aviso">{FRASE_CAUSA}</p>
<p class="aviso">{FRASE_CAMPO}</p>
{_estado(dados)}
{_operacao_html(dados)}
{_desempenho_html(dados)}
{_drift_html(dados)}
{_alertas_html(dados)}
{_decisoes_html(dados)}
{_limites(dados)}
</main>
<script>{_js()}</script>
</body>
</html>
"""


def gerar(raiz: Path | None = None, destino: Path | None = None) -> Path:
    """Lê a pasta de produção e grava um único HTML."""
    base = Path(raiz) if raiz is not None else RAIZ
    caminho = Path(destino) if destino is not None else base / "relatorios" / "producao.html"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(renderizar(coletar(base)), encoding="utf-8")
    return caminho


def main() -> int:
    caminho = gerar()
    print(caminho)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
