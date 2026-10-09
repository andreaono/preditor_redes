"""Regera só o HTML da etapa 8, a partir dos arquivos já gravados.

Não treina, não lê o dataset e não altera nada em data/.
"""

import copy
import html
import sys

import config
import treinar_modelos as treino


def configurar_saida():
    """Garante acentos no terminal do Windows."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def taxa_da_matriz(bloco):
    """Fração em que a diagonal da matriz coincide com o total.

    Na persistência, previsto = classe_atual, então a diagonal é
    classe_atual == alvo. Ausência de matriz ou de n devolve None.
    """
    if not isinstance(bloco, dict):
        return None
    matriz = bloco.get("matriz")
    total = bloco.get("n")
    if not matriz or not total:
        return None
    try:
        iguais = sum(int(linha[indice]) for indice, linha in enumerate(matriz))
        total = int(total)
    except (TypeError, ValueError, IndexError):
        return None
    if total <= 0:
        return None
    return iguais, total, iguais / total


def preparar_pagina(resumo, resultados):
    """Cópia da página com a taxa, o gráfico e a frase do Naive Bayes.

    Não grava o resumo. Os números do gráfico vêm de resultados_validacao.json.
    """
    pagina = copy.deepcopy(resumo)
    persistencia = resultados.get("persistencia") or {}
    familias = resultados.get("familias") or {}
    geral_treino = (persistencia.get(config.SPLIT_TREINO) or {}).get("geral") or {}
    geral_val = (persistencia.get(config.SPLIT_VALIDACAO) or {}).get("geral") or {}
    macro_treino = treino.numero(geral_treino.get("macro_f1"))
    macro_val = treino.numero(geral_val.get("macro_f1"))
    pagina["persistencia"]["treino"] = macro_treino
    pagina["persistencia"]["validacao"] = macro_val
    taxa = taxa_da_matriz(geral_val)
    if taxa is None:
        pagina["taxa_igualdade"] = None
        print("Aviso: a taxa classe_atual == alvo na validação não está na matriz da persistência.")
    else:
        iguais, total, fracao = taxa
        pagina["taxa_igualdade"] = {"iguais": iguais, "total": total, "fracao": fracao}
    nb = familias.get(config.FAMILIA_DIDATICA) or {}
    macro_nb = treino.numero(nb.get("macro_f1_validacao"))
    diferenca = None if macro_nb is None or macro_val is None else macro_val - macro_nb
    abaixo = diferenca is not None and diferenca > config.LIM_NB_ABAIXO_PERSISTENCIA
    pagina["nb_abaixo_persistencia"] = abaixo
    pagina["frase_nb_persistencia"] = (
        config.TEXTO_NB_ABAIXO_PERSISTENCIA.format(pontos=treino.br(diferenca)) if abaixo else None
    )
    series = []
    if macro_treino is None or macro_val is None:
        print("Aviso: macro-F1 da persistência ausente em resultados_validacao.json.")
    series.append(
        {
            "nome": config.ROTULO_PERSISTENCIA,
            "treino": macro_treino,
            "validacao": macro_val,
            "didatico": False,
            "escolhido": False,
        }
    )
    escolhido = resultados.get("escolhido") or pagina.get("escolhido", {}).get("familia")
    for familia in config.ALGORITMOS:
        item = familias.get(familia) or {}
        series.append(
            {
                "nome": config.CARTAO_ALGORITMO[familia]["nome"],
                "treino": treino.numero(item.get("macro_f1_treino")),
                "validacao": treino.numero(item.get("macro_f1_validacao")),
                "didatico": familia == config.FAMILIA_DIDATICA,
                "escolhido": familia == escolhido,
            }
        )
    pagina["series_grafico"] = series
    return pagina


def mostrar(valor, percentual=False):
    """Número brasileiro, ou o aviso de dado ausente."""
    if treino.numero(valor) is None:
        return config.ROTULO_INDISPONIVEL
    if percentual:
        return treino.br_pct(valor)
    return treino.br(valor)


def secao_persistencia(pagina):
    """O que é a persistência, o exemplo e onde ela erra."""
    taxa = pagina.get("taxa_igualdade")
    if taxa is None:
        texto_taxa = config.ROTULO_INDISPONIVEL
    else:
        texto_taxa = config.TEXTO_TAXA_IGUALDADE.format(
            taxa=treino.br_pct(taxa["fracao"]),
            iguais=taxa["iguais"],
            total=taxa["total"],
        )
    sempre = (pagina.get("sempre_ok") or {}).get(config.SPLIT_VALIDACAO)
    contraste = config.TEXTO_CONTRASTE_ACURACIA.format(
        treino=mostrar(pagina["persistencia"].get("treino")),
        validacao=mostrar(pagina["persistencia"].get("validacao")),
        sempre_ok=mostrar(sempre, percentual=True),
    )
    return (
        "<section><h2>5. Baseline: persistência</h2>"
        f"<h3>O que é</h3><p>{html.escape(config.TEXTO_PERSISTENCIA_O_QUE)}</p>"
        f"<h3>{html.escape(config.TEXTO_EXEMPLO_DIDATICO)}</h3>"
        f"{exemplo_persistencia()}"
        f"<h3>Por que é a régua</h3><p>{html.escape(config.TEXTO_PERSISTENCIA_REGUA)} "
        f"{html.escape(texto_taxa)}</p>"
        f"<p>{html.escape(config.TEXTO_PERSISTENCIA_FIXA)}</p>"
        f"<h3>Onde ela erra</h3><p>{html.escape(config.TEXTO_PERSISTENCIA_ERRA)}</p>"
        f"<p>{html.escape(contraste)}</p>"
        "</section>"
    )


def exemplo_persistencia():
    """Três repetições de classe, marcadas como exemplo didático."""
    linhas = []
    y = 58
    for classe, cor in zip(config.CLASSES, (config.COR_OK, config.COR_RISCO, config.COR_FALHA)):
        linhas.append(
            f'<rect x="24" y="{y}" width="88" height="28" rx="8" fill="{cor}"/>'
            f'<text x="68" y="{y + 19}" text-anchor="middle" fill="#fff" font-size="13">{html.escape(classe)}</text>'
            f'<text x="150" y="{y + 19}" fill="currentColor" font-size="16">→</text>'
            f'<rect x="196" y="{y}" width="88" height="28" rx="8" fill="{cor}"/>'
            f'<text x="240" y="{y + 19}" text-anchor="middle" fill="#fff" font-size="13">{html.escape(classe)}</text>'
        )
        y += 40
    return (
        f'<svg viewBox="0 0 320 190" role="img" aria-label="{html.escape(config.ARIA_EXEMPLO_PERSISTENCIA)}">'
        f'<text x="24" y="22" fill="currentColor" font-size="13">{html.escape(config.TEXTO_EXEMPLO_DIDATICO)}</text>'
        f'<text x="24" y="44" fill="currentColor" font-size="13">{html.escape(config.TEXTO_EXEMPLO_SETA)}</text>'
        + "".join(linhas)
        + "</svg>"
    )


def secao_algoritmos(pagina):
    """Três cartões. O Naive Bayes fica como ponto de partida didático."""
    cartoes = []
    for familia in config.ALGORITMOS:
        cartao = config.CARTAO_ALGORITMO[familia]
        if familia == config.FAMILIA_DIDATICA:
            extra = (
                f"<p>{html.escape(config.TEXTO_NB_ABAIXO_CARTAO)}</p>"
                if pagina.get("nb_abaixo_persistencia")
                else ""
            )
            cartoes.append(
                '<article class="cartao didatico">'
                f'<p class="etiqueta">{html.escape(config.ETIQUETA_DIDATICA)}</p>'
                f"<h3>{html.escape(cartao['nome'])}</h3>"
                f"<p>{html.escape(config.TEXTO_NB_CARTAO)}</p>"
                f"{extra}"
                "</article>"
            )
            continue
        cartoes.append(treino.cartao_algoritmo(familia))
    return (
        "<section><h2>6. Algoritmos, do simples ao complexo</h2>"
        '<div class="grade">'
        + "".join(cartoes)
        + "</div></section>"
    )


def tabela_hiperparametros(pagina):
    """O que foi testado e o escolhido, com quebra de linha na célula."""
    linhas = []
    for familia in config.ALGORITMOS:
        testado = "<br>".join(
            html.escape(f"{chave}: {treino.valores_grade(chave, valores)}")
            for chave, valores in config.GRADES[familia].items()
        )
        escolhido = "<br>".join(
            html.escape(parte) for parte in str(pagina["familias"][familia]["hiperparametros"]).split(";")
        )
        linhas.append(
            "<tr>"
            f"<td>{html.escape(config.CARTAO_ALGORITMO[familia]['nome'])}</td>"
            f"<td>{testado}</td>"
            f"<td>{escolhido}</td>"
            "</tr>"
        )
    return (
        '<table class="quebra"><thead><tr>'
        f"<th>Família</th><th>Testado</th><th>{html.escape(config.ROTULO_COLUNA_ESCOLHIDO)}</th>"
        f"</tr></thead><tbody>{''.join(linhas)}</tbody></table>"
    )


def y_grafico(valor):
    """Posição vertical de um macro-F1 no eixo de 0 a 1."""
    limitado = min(config.GRAFICO_EIXO_MAX, max(0.0, float(valor)))
    return config.GRAFICO_BASE - limitado / config.GRAFICO_EIXO_MAX * config.GRAFICO_ALTURA_EIXO


def grafico_f1(pagina):
    """Barras de treino e validação, com piso da persistência e eixo de 0 a 1."""
    series = pagina.get("series_grafico") or []
    largura = config.GRAFICO_MARGEM_ESQ + len(series) * config.GRAFICO_LARGURA_GRUPO + config.GRAFICO_MARGEM_DIR
    altura = config.GRAFICO_BASE + config.GRAFICO_RODAPE
    partes = []
    aria = []
    piso = None
    for item in series:
        if item["nome"] == config.ROTULO_PERSISTENCIA:
            piso = item["validacao"]
        if item["treino"] is None or item["validacao"] is None:
            aria.append(f"{item['nome']} {config.ROTULO_INDISPONIVEL}")
        else:
            aria.append(
                f"{item['nome']} treino {treino.br(item['treino'])} validação {treino.br(item['validacao'])}"
            )
    partes.append(
        f'<svg class="grafico" viewBox="0 0 {largura} {altura}" role="img" '
        f'aria-label="{html.escape(config.ARIA_BARRAS + " " + ". ".join(aria))}">'
    )
    partes.append(
        f'<rect x="{config.GRAFICO_MARGEM_ESQ - 8}" y="16" width="18" height="12" fill="{config.COR_BARRA_TREINO}"/>'
        f'<text x="{config.GRAFICO_MARGEM_ESQ + 16}" y="27" fill="currentColor" font-size="13">treino</text>'
        f'<rect x="{config.GRAFICO_MARGEM_ESQ + 88}" y="16" width="18" height="12" fill="{config.COR_BARRA_VALIDACAO}"/>'
        f'<text x="{config.GRAFICO_MARGEM_ESQ + 112}" y="27" fill="currentColor" font-size="13">validação</text>'
    )
    fim_x = config.GRAFICO_MARGEM_ESQ + len(series) * config.GRAFICO_LARGURA_GRUPO
    for marca in config.GRAFICO_MARCAS:
        y = y_grafico(marca)
        partes.append(
            f'<line x1="{config.GRAFICO_MARGEM_ESQ}" y1="{y:.1f}" x2="{fim_x}" y2="{y:.1f}" '
            f'stroke="currentColor" stroke-opacity="0.25"/>'
        )
        partes.append(
            f'<text x="{config.GRAFICO_MARGEM_ESQ - 12}" y="{y + 4:.1f}" text-anchor="end" '
            f'fill="currentColor" font-size="12">{html.escape(treino.br(marca, config.GRAFICO_CASAS_EIXO))}</text>'
        )
    if piso is not None:
        y_piso = y_grafico(piso)
        partes.append(
            f'<line x1="{config.GRAFICO_MARGEM_ESQ}" y1="{y_piso:.1f}" x2="{fim_x}" y2="{y_piso:.1f}" '
            f'stroke="currentColor" stroke-dasharray="6 5" stroke-width="1.6"/>'
        )
        partes.append(
            f'<text x="{fim_x + 8}" y="{y_piso + 4:.1f}" fill="currentColor" font-size="12">'
            f'{html.escape(config.ROTULO_PISO)}</text>'
        )
    for indice, item in enumerate(series):
        x = config.GRAFICO_MARGEM_ESQ + indice * config.GRAFICO_LARGURA_GRUPO + 28
        if item["didatico"]:
            cor_treino, cor_val = config.COR_NB_TREINO, config.COR_NB_VALIDACAO
        else:
            cor_treino, cor_val = config.COR_BARRA_TREINO, config.COR_BARRA_VALIDACAO
        barras = []
        for deslocamento, valor, cor in (
            (0, item["treino"], cor_treino),
            (config.GRAFICO_LARGURA_BARRA + config.GRAFICO_ESPACO_BARRA, item["validacao"], cor_val),
        ):
            if valor is None:
                barras.append((x + deslocamento, None, cor, config.ROTULO_INDISPONIVEL))
                continue
            topo = y_grafico(valor)
            altura_barra = config.GRAFICO_BASE - topo
            partes.append(
                f'<rect x="{x + deslocamento}" y="{topo:.1f}" width="{config.GRAFICO_LARGURA_BARRA}" '
                f'height="{altura_barra:.1f}" fill="{cor}"/>'
            )
            barras.append((x + deslocamento, topo, cor, treino.br(valor)))
        if item["escolhido"]:
            partes.append(
                f'<rect x="{x - 10}" y="{y_grafico(config.GRAFICO_EIXO_MAX) - 8:.1f}" '
                f'width="{config.GRAFICO_LARGURA_BARRA * 2 + config.GRAFICO_ESPACO_BARRA + 20}" '
                f'height="{config.GRAFICO_ALTURA_EIXO + 16:.1f}" fill="none" stroke="var(--accent)" stroke-width="2" rx="8"/>'
            )
        rotulos = ajustar_rotulos(barras)
        for esquerda, topo, texto in rotulos:
            if topo is None:
                continue
            largura_texto = len(texto) * config.GRAFICO_LARGURA_CARACTERE
            centro = esquerda + config.GRAFICO_LARGURA_BARRA / 2
            partes.append(
                f'<rect x="{centro - largura_texto / 2:.1f}" y="{topo - 13:.1f}" width="{largura_texto:.1f}" '
                f'height="15" fill="var(--card)"/>'
            )
            partes.append(
                f'<text x="{centro:.1f}" y="{topo:.1f}" text-anchor="middle" fill="currentColor" font-size="12">'
                f"{html.escape(texto)}</text>"
            )
        nome_y = config.GRAFICO_BASE + 22
        partes.append(
            f'<text x="{x + config.GRAFICO_LARGURA_BARRA}" y="{nome_y}" text-anchor="middle" '
            f'fill="currentColor" font-size="13">{html.escape(item["nome"])}</text>'
        )
        etiqueta = config.ETIQUETA_ESCOLHIDO if item["escolhido"] else ""
        if item["didatico"]:
            etiqueta = config.ETIQUETA_DIDATICA
        if etiqueta:
            partes.append(
                f'<text x="{x + config.GRAFICO_LARGURA_BARRA}" y="{nome_y + 18}" text-anchor="middle" '
                f'fill="currentColor" font-size="11">{html.escape(etiqueta)}</text>'
            )
        if item["treino"] is None or item["validacao"] is None:
            texto_gap = config.ROTULO_INDISPONIVEL
        else:
            texto_gap = config.TEXTO_GAP_GRUPO.format(valor=treino.br(item["treino"] - item["validacao"]))
        partes.append(
            f'<text x="{x + config.GRAFICO_LARGURA_BARRA}" y="{nome_y + 40}" text-anchor="middle" '
            f'fill="currentColor" font-size="12">{html.escape(texto_gap)}</text>'
        )
    partes.append("</svg>")
    return (
        f'<div class="rolagem">{"".join(partes)}</div>'
        f'<div class="cartao"><p>{html.escape(config.TEXTO_GAP_LEITURA)}</p></div>'
        f"<p>{html.escape(config.AVISO_ESCOLHA)}</p>"
    )


def ajustar_rotulos(barras):
    """Sobe o rótulo da barra mais alta quando os dois valores ficam colados."""
    prontos = []
    tops = []
    for esquerda, topo, _cor, texto in barras:
        if topo is None:
            prontos.append((esquerda, None, texto))
            continue
        tops.append(topo - 8)
        prontos.append((esquerda, topo - 8, texto))
    if len(tops) == 2 and abs(tops[0] - tops[1]) < config.GRAFICO_FOLGA_ROTULO:
        if tops[0] <= tops[1]:
            prontos[0] = (prontos[0][0], prontos[0][1] - config.GRAFICO_FOLGA_ROTULO, prontos[0][2])
        else:
            prontos[1] = (prontos[1][0], prontos[1][1] - config.GRAFICO_FOLGA_ROTULO, prontos[1][2])
    return prontos


def secao_analise(pagina):
    """Frases já gravadas, mais a do Naive Bayes quando ele perde da persistência."""
    frases = list(pagina.get("analise_validacao") or [])
    extra = pagina.get("frase_nb_persistencia")
    if extra:
        frases.append(extra)
    if not frases:
        frases.append(config.TEXTO_NENHUMA_RESSALVA)
    return (
        "<section><h2>11. Análise e decisões</h2><ul>"
        + "".join(f"<li>{html.escape(frase)}</li>" for frase in frases)
        + "</ul>"
        "<p>Observar → decidir → ajustar → repetir. O retorno é para os hiperparâmetros, ainda sem olhar o teste.</p><ul>"
        + "".join(
            f"<li><strong>{html.escape(sintoma)}.</strong> {html.escape(decisao)}</li>"
            for sintoma, decisao in config.SINTOMAS
        )
        + "</ul></section>"
    )


def estilos():
    """CSS da página, com a tabela que quebra linha e o cartão didático."""
    return f"""
    :root {{ color-scheme: light; --bg:#f3f1ea; --ink:#1c1915; --muted:#5e584e; --card:#fffdf8; --line:#e4ddd0; --accent:#0f6e56; --br:#c45c26; --ok:{config.COR_OK}; --risco:{config.COR_RISCO}; --falha:{config.COR_FALHA}; --meta:#8a8175; --feat:#2a6f97; --alvo:#c45c26; }}
    html[data-theme="dark"] {{ color-scheme: dark; --bg:#12171a; --ink:#f3f1ea; --muted:#b7b1a6; --card:#1c2428; --line:#314046; --accent:#3dbe9a; --br:#e5925d; --ok:{config.COR_OK_ESCURO}; --risco:{config.COR_RISCO_ESCURO}; --falha:{config.COR_FALHA_ESCURO}; --meta:#b7b1a6; --feat:#8ecae6; --alvo:#e5925d; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family:"Segoe UI","Helvetica Neue",sans-serif; background:var(--bg); color:var(--ink); font-size:1.08rem; }}
    header, main {{ width:min(1100px, calc(100% - 28px)); margin:0 auto; }}
    header {{ padding:28px 0 8px; display:flex; justify-content:space-between; gap:16px; align-items:flex-start; }}
    h1 {{ margin:8px 0; font-size:2rem; }}
    h2 {{ margin:32px 0 12px; font-size:1.4rem; }}
    h3 {{ margin:18px 0 8px; font-size:1.15rem; }}
    a {{ color:var(--br); }}
    p, li {{ line-height:1.45; }}
    .voltar {{ color:var(--accent); text-decoration:none; }}
    button {{ font:inherit; border:1px solid var(--line); background:var(--card); color:var(--ink); border-radius:999px; padding:8px 14px; cursor:pointer; }}
    .cartao {{ background:var(--card); border:1px solid var(--line); border-radius:16px; padding:16px; }}
    .cartao.didatico {{ background:var(--bg); border-color:var(--muted); }}
    .etiqueta {{ display:inline-block; margin:0 0 8px; padding:2px 8px; border-radius:999px; background:var(--line); color:var(--muted); font-size:.85rem; }}
    .grade {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; }}
    .rolagem {{ overflow-x:auto; border:1px solid var(--line); border-radius:12px; }}
    table {{ width:100%; border-collapse:collapse; background:var(--card); }}
    th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); white-space:nowrap; }}
    table.quebra th, table.quebra td {{ white-space:normal; vertical-align:top; }}
    th.meta, td.meta {{ color:var(--meta); }}
    th.feat, td.feat {{ color:var(--feat); }}
    th.alvo, td.alvo {{ color:var(--alvo); }}
    tr.escolhido {{ outline:2px solid var(--accent); }}
    svg {{ width:100%; height:auto; background:var(--card); border:1px solid var(--line); border-radius:16px; }}
    svg.grafico {{ min-width:{config.GRAFICO_MARGEM_ESQ + 4 * config.GRAFICO_LARGURA_GRUPO + config.GRAFICO_MARGEM_DIR}px; }}
    .ok {{ color:var(--ok); font-weight:700; }}
    .risco {{ color:var(--risco); font-weight:700; }}
    .falha {{ color:var(--falha); font-weight:700; }}
    .selo {{ display:inline-block; padding:0 6px; border-radius:999px; background:var(--line); font-size:.85rem; }}
    code {{ font-family:Consolas,monospace; }}
    @media (max-width:800px) {{ .grade, header {{ display:flex; flex-direction:column; }} }}
    """


def escrever_pagina(pagina):
    """Grava template/modelo.html. Não grava data/ nem o índice."""
    partes = [
        "<!DOCTYPE html>",
        '<html lang="pt-BR">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{html.escape(config.TITULO_PAGINA)}</title>",
        f"<style>{estilos()}</style>",
        "</head><body>",
        "<header><div>",
        f'<a class="voltar" href="{html.escape(config.LINK_INICIO)}">← Início</a>',
        f"<h1>{html.escape(config.TITULO_PAGINA)}</h1>",
        '</div><button id="tema" type="button">Tema escuro</button></header><main>',
        "<section><h2>1. Ciclo de vida do modelo</h2>",
        treino.svg_ciclo(),
        "</section>",
        "<section><h2>2. Problema e alvo</h2>",
        f"<p>{html.escape(config.TEXTO_PROBLEMA)}</p>",
        treino.svg_tempo(),
        f"<p>{html.escape(config.NOTA_CIRCULAR)}</p>",
        "</section>",
        "<section><h2>3. Dataset usado no modelo</h2>",
        f"<p>{html.escape(config.TEXTO_TOTAIS.format(**pagina['totais']))}</p>",
        f"<p>{html.escape(config.AVISO_AMOSTRA.format(mostradas=len(pagina['amostra']), total=pagina['totais']['linhas']))}</p>",
        "<p>Cinza é metadado, azul é feature, laranja é alvo. O valor −1 leva o selo sentinela.</p>",
        treino.tabela_amostra(pagina["amostra"]),
        "</section>",
        "<section><h2>4. Divisão dos dados</h2>",
        treino.svg_splits(pagina),
        treino.barras_alvo(pagina["distribuicao"]),
        f"<p>{html.escape(config.NOTA_DIVISAO)}</p>",
        "</section>",
        secao_persistencia(pagina),
        secao_algoritmos(pagina),
        "<section><h2>7. A árvore por dentro</h2>",
        "<h3>Árvore ilustrativa</h3>",
        f'<div class="rolagem">{pagina["ilustrativa"]["svg"]}</div>',
        f"<p>{html.escape(config.NOTA_FOLHA)} {html.escape(config.AVISO_RAZAO)}</p>",
        f"<p>Como ler o caminho realçado: {html.escape(pagina['ilustrativa']['texto_caminho'])}.</p>",
        treino.secao_pedaco(pagina["pedaco"]),
        f"<p>{html.escape(config.AVISO_ARVORE_SIMPLIFICADA)} "
        f"Macro-F1 da ilustrativa: treino {html.escape(treino.br(pagina['ilustrativa']['macro_f1_treino']))}, "
        f"validação {html.escape(treino.br(pagina['ilustrativa']['macro_f1_validacao']))}.</p>",
        treino.texto_tamanho(pagina),
        f"<p>{html.escape(config.AVISO_CAUSALIDADE)}</p>",
        "</section>",
        "<section><h2>8. Hiperparâmetros</h2>",
        tabela_hiperparametros(pagina),
        grafico_f1(pagina),
        f"<p>{html.escape(config.AVISO_GRADE)}</p>",
        "</section>",
        "<section><h2>9. Métricas de avaliação</h2>",
        "<ul>"
        + "".join(
            f"<li><strong>{html.escape(nome)}.</strong> {html.escape(texto)}</li>"
            for nome, texto in config.DEFINICAO_METRICA
        )
        + "</ul>",
        "<p>A matriz de confusão tem a classe real na linha e a prevista na coluna, na ordem OK, RISCO, FALHA.</p>",
        "<p>Fatias: geral é o split inteiro; transições são as linhas em que a classe muda; início de FALHA é quando a atual não é FALHA e a próxima é; sem anchor dominante tira o anchor que concentra mais FALHA.</p>",
        f"<p>Por que a acurácia engana: prever OK para tudo acerta {html.escape(treino.br_pct(pagina['sempre_ok'][config.SPLIT_VALIDACAO]))} da validação, "
        f"e o macro-F1 da persistência nessa fatia é {html.escape(treino.br(pagina['persistencia']['validacao']))}.</p>",
        "</section>",
        "<section><h2>10. Resultado na validação</h2>",
        treino.tabela_validacao(pagina),
        treino.matriz_html(
            pagina["familias"][pagina["escolhido"]["familia"]]["matriz"],
            pagina["familias"][pagina["escolhido"]["familia"]]["por_classe"],
            config.TEXTO_MATRIZ_VALIDACAO,
        ),
        f"<p>{'O escolhido supera a persistência na validação.' if pagina['supera_persistencia'] else 'O escolhido não supera a persistência na validação. A escolha não muda por isso.'}</p>",
        "</section>",
        secao_analise(pagina),
        "<section><h2>12. Teste</h2>",
        treino.secao_teste(pagina["teste"]),
        "</section>",
        "<section><h2>13. O que o teste nos diz</h2>",
        treino.secao_analise_teste(pagina["teste"]),
        "</section>",
        "<section><h2>14. Cuidados e próximos passos</h2><ul>",
        *[f"<li>{html.escape(frase)}</li>" for frase in config.CUIDADOS],
        "</ul></section>",
        "</main>",
        "<script>const raiz=document.documentElement;const botao=document.getElementById('tema');const salvo=localStorage.getItem('etapa-tema');const inicial=salvo||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');aplicar(inicial);botao.addEventListener('click',()=>{const proximo=raiz.getAttribute('data-theme')==='dark'?'light':'dark';localStorage.setItem('etapa-tema',proximo);aplicar(proximo);});function aplicar(tema){raiz.setAttribute('data-theme',tema);botao.textContent=tema==='dark'?'Tema claro':'Tema escuro';}</script>",
        "</body></html>",
    ]
    config.ARQUIVO_HTML.write_text("\n".join(partes) + "\n", encoding="utf-8")


def main():
    """Lê o resumo e a validação já gravados e reescreve só o HTML."""
    configurar_saida()
    resumo = treino.ler_json(config.ARQUIVO_RESUMO_PAGINA)
    resultados = treino.ler_json(config.ARQUIVO_VALIDACAO)
    pagina = preparar_pagina(resumo, resultados)
    escrever_pagina(pagina)
    taxa = pagina.get("taxa_igualdade")
    if taxa is None:
        print(f"Taxa classe_atual == alvo: {config.ROTULO_INDISPONIVEL}")
    else:
        print(f"Taxa classe_atual == alvo na validação: {taxa['iguais']} de {taxa['total']}")
    if pagina.get("frase_nb_persistencia"):
        print(pagina["frase_nb_persistencia"])
    print(f"HTML: {config.ARQUIVO_HTML}")


if __name__ == "__main__":
    main()
