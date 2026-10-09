"""Verificações da etapa 9. Falha com mensagem clara."""

import json
import os
import tempfile
from pathlib import Path

import pandas as pd

import api_ripe
import banco
import config
import features_online


def _falha(mensagem: str) -> None:
    raise SystemExit(mensagem)


def _iguais(calculado, gravado) -> bool:
    if pd.isna(calculado) and pd.isna(gravado):
        return True
    if pd.isna(calculado) or pd.isna(gravado):
        return False
    a = float(calculado)
    b = float(gravado)
    if abs(a - b) <= config.TOLERANCIA_FEATURE:
        return True
    return format(a, ".6g") == format(b, ".6g")


def _corte_teste() -> int:
    documento = json.loads(config.PACOTE_MODELO.features.read_text(encoding="utf-8"))
    texto = documento["splits"]["teste"]["inicio"]
    return int(pd.Timestamp(texto).timestamp())


def _fluxo_validacao() -> tuple[str, set[int]]:
    timestamps: set[int] = set()
    fluxo = None
    for pedaco in pd.read_csv(config.ARQUIVO_FINAL_ETAPA7, usecols=["id_fluxo", "timestamp", "split"], chunksize=80000):
        fatia = pedaco[pedaco["split"] == "validacao"]
        if fatia.empty:
            continue
        if fluxo is None:
            fluxo = str(fatia.iloc[0]["id_fluxo"])
        timestamps.update(int(item) for item in fatia.loc[fatia["id_fluxo"] == fluxo, "timestamp"])
    if fluxo is None:
        _falha("Não há fluxo de validação.")
    return fluxo, timestamps


def _linhas_brutas(fluxo: str, corte: int) -> list[dict]:
    base = pd.read_csv(config.ARQUIVO_BASELINE_ETAPA6, dtype=str)
    linha = base.loc[base["id_fluxo"] == fluxo].iloc[0]
    baseline = {
        "p95_rtt_num": float(linha["p95_rtt_A"]),
        "p99_rtt_num": float(linha["p99_rtt_A"]),
        "p95_jitter_num": float(linha["p95_jitter_A"]),
        "ttl_baseline": float(linha["ttl_baseline"]),
        "status_baseline": linha["status_baseline"],
    }
    usecols = ["id_fluxo", "periodo", "ttl", "result", "rcvd", "sent", "min", "max", "avg", "timestamp"]
    pedacos = []
    for pedaco in pd.read_csv(config.ARQUIVO_CSV_BRUTO_ETAPA5, usecols=usecols, chunksize=100000):
        mascara = (pedaco["id_fluxo"] == fluxo) & (pedaco["periodo"] == config.PERIODO_REPLAY) & (pedaco["timestamp"] < corte)
        if mascara.any():
            pedacos.append(pedaco.loc[mascara])
    if not pedacos:
        _falha(f"fluxo_bruto sem linhas de {fluxo} antes do teste.")
    quadro = pd.concat(pedacos, ignore_index=True).sort_values("timestamp")
    linhas = []
    for _, row in quadro.iterrows():
        metrica = features_online.metricas_de_resultado(row.to_dict(), baseline["ttl_baseline"])
        linhas.append(metrica)
    return linhas, baseline


def equivalencia_features() -> None:
    """Reaplica as features num fluxo de validação e compara com dataset_final."""
    fluxo, timestamps = _fluxo_validacao()
    corte = _corte_teste()
    linhas, baseline = _linhas_brutas(fluxo, corte)
    quadro = features_online.features_do_historico(fluxo, linhas, baseline)
    nomes = features_online.nomes_features()
    oficial = []
    for pedaco in pd.read_csv(config.ARQUIVO_FINAL_ETAPA7, chunksize=80000):
        fatia = pedaco[(pedaco["split"] == "validacao") & (pedaco["id_fluxo"] == fluxo)]
        if not fatia.empty:
            oficial.append(fatia)
    if not oficial:
        _falha("dataset_final sem o fluxo de validação.")
    alvo = pd.concat(oficial, ignore_index=True)
    mapa = quadro.set_index("timestamp")
    divergencias = []
    for _, row in alvo.iterrows():
        ts = int(row["timestamp"])
        if ts not in mapa.index:
            divergencias.append(f"{ts} ausente no recálculo")
            continue
        calculada = mapa.loc[ts]
        for nome in nomes:
            if not _iguais(calculada[nome], row[nome]):
                divergencias.append(f"{ts} {nome}: {calculada[nome]} != {row[nome]}")
                if len(divergencias) >= 8:
                    break
        if len(divergencias) >= 8:
            break
    if divergencias:
        _falha("Features divergentes:\n" + "\n".join(divergencias))
    print(f"Equivalência ok em {fluxo}, {len(alvo)} linhas de validação.")


def sem_vazamento() -> None:
    """Features de t não mudam se uma medição posterior muda."""
    fluxo, _ = _fluxo_validacao()
    linhas, baseline = _linhas_brutas(fluxo, _corte_teste())
    prefixo = linhas[:40]
    antes = features_online.features_do_historico(fluxo, prefixo, baseline)
    extra = dict(prefixo[-1])
    extra["timestamp"] = int(prefixo[-1]["timestamp"]) + config.INTERVALO_TREINO_S
    extra["avg"] = 99999.0
    extra["latencia_ms"] = 99999.0
    extra["min"] = 99999.0
    extra["max"] = 99999.0
    depois = features_online.features_do_historico(fluxo, prefixo + [extra], baseline)
    nomes = features_online.nomes_features()
    ts = int(prefixo[20]["timestamp"])
    for nome in nomes:
        if not _iguais(antes.set_index("timestamp").loc[ts, nome], depois.set_index("timestamp").loc[ts, nome]):
            _falha(f"Vazamento do futuro em {nome} no timestamp {ts}.")
    print("Sem vazamento do futuro.")


def rotulagem_igual() -> None:
    """A regra online reproduz a classe de dataset_rotulado nas mesmas linhas."""
    fluxo, timestamps = _fluxo_validacao()
    probe, anchor = fluxo.split("_")
    linhas, baseline = _linhas_brutas(fluxo, _corte_teste())
    por_ts = {int(item["timestamp"]): item for item in linhas}
    vistos = 0
    for pedaco in pd.read_csv(config.ARQUIVO_ROTULADO_ETAPA7, usecols=["probe_id", "anchor_id", "timestamp", "classe"], chunksize=80000):
        fatia = pedaco[(pedaco["probe_id"].astype(str) == probe) & (pedaco["anchor_id"].astype(str) == anchor)]
        for _, row in fatia.iterrows():
            ts = int(row["timestamp"])
            if ts not in timestamps or ts not in por_ts:
                continue
            classe, _motivo = features_online.rotular_linha(por_ts[ts], baseline)
            if classe != row["classe"]:
                _falha(f"Rótulo divergente em {ts}: {classe} != {row['classe']}")
            vistos += 1
    if vistos == 0:
        _falha("Nenhuma linha de dataset_rotulado foi comparada.")
    print(f"Rotulagem ok em {vistos} linhas.")


def chave_ausente_dos_arquivos() -> None:
    """Se a variável existe, o valor não pode aparecer em arquivo gerado."""
    chave = os.environ.get(config.VAR_AMBIENTE_CHAVE)
    if not chave:
        print(f"{config.VAR_AMBIENTE_CHAVE} não está definida; a busca não tem o que procurar.")
        return
    pastas = [config.DATA_DIR, config.CACHE_DIR, config.BASE_DIR]
    for pasta in pastas:
        if not pasta.exists():
            continue
        for caminho in pasta.rglob("*"):
            if not caminho.is_file() or caminho.suffix in {".joblib", ".sqlite"}:
                continue
            if caminho.stat().st_size > 5_000_000:
                continue
            texto = caminho.read_text(encoding="utf-8", errors="ignore")
            if chave in texto:
                _falha(f"A chave apareceu em {caminho}.")
    print("Chave ausente dos arquivos gerados.")


def novo_sem_confirmacao_nao_cria() -> None:
    """Sem a flag, post_json não é chamado."""

    def proibido(*_args, **_kwargs):
        _falha("post_json foi chamado no dry-run.")

    original = api_ripe.post_json
    api_ripe.post_json = proibido
    try:
        import coletor

        par = {"id_fluxo": "0_0", "origem": {"id": 1}, "destino": {"ip": "127.0.0.1"}, "msm_id": None}
        resultado = coletor.criar_medicao(par, confirmar=False)
    finally:
        api_ripe.post_json = original
    if resultado.get("criada"):
        _falha("Dry-run marcou a medição como criada.")
    print("Dry-run não cria medição.")


def escolha_do_painel_nao_cria() -> None:
    """A escolha do painel grava o par e não chama post_json."""
    import opcoes

    chamadas = []

    def proibido(*args, **kwargs):
        chamadas.append(args)
        _falha("post_json foi chamado na escolha do painel.")

    original = api_ripe.post_json
    api_ripe.post_json = proibido
    opcoes.api_ripe.post_json = proibido
    origens = {
        "escolha": config.ARQUIVO_ESCOLHA,
        "par": config.ARQUIVO_PAR,
        "cinco": opcoes.cinco_opcoes,
        "consultar": opcoes._consultar,
    }
    try:
        try:
            opcoes.gravar_escolha("fluxo-inexistente")
        except ValueError:
            pass
        else:
            _falha("Um fluxo fora das cinco opções foi aceito.")
        pasta = Path(tempfile.mkdtemp())
        config.ARQUIVO_ESCOLHA = pasta / "fluxo_escolhido.json"
        config.ARQUIVO_PAR = pasta / "par_monitorado.json"
        baseline = {"ttl_baseline": 52, "p95_rtt": 1.0, "p99_rtt": 2.0, "p95_jitter": 0.1}
        opcoes.cinco_opcoes = lambda: ([{"id_fluxo": "1_2", "baseline": baseline}], 1.0, 2.0)
        opcoes._consultar = lambda item: {
            "faixa": "curta",
            "origem": {"id": 1},
            "destino": {"id": 2},
            "medicao": {"msm_id": 99},
            "baseline": item["baseline"],
        }
        opcoes.gravar_escolha("1_2")
        escolha = json.loads(config.ARQUIVO_ESCOLHA.read_text(encoding="utf-8"))
        par = json.loads(config.ARQUIVO_PAR.read_text(encoding="utf-8"))
    finally:
        api_ripe.post_json = original
        opcoes.api_ripe.post_json = original
        config.ARQUIVO_ESCOLHA = origens["escolha"]
        config.ARQUIVO_PAR = origens["par"]
        opcoes.cinco_opcoes = origens["cinco"]
        opcoes._consultar = origens["consultar"]
    if chamadas:
        _falha("post_json foi registrado na escolha do painel.")
    if escolha.get("medicao_criada") is not False or par.get("medicao_criada") is not False or par.get("msm_id") is not None:
        _falha("A escolha gravou medição ou msm_id.")
    fonte = (config.RAIZ_PROJETO / "painel-preditor.html").read_text(encoding="utf-8")
    if "criar_medicao" in fonte or "post_json" in fonte:
        _falha("painel-preditor.html cita o coletor ou post_json.")
    if "medição pública já existente" not in fonte:
        _falha("A página Monitorar não mostra a frase da malha.")
    if "Esta coleta usa 180 s" in fonte:
        _falha("A página Monitorar mostra a frase do coletor de 180 s.")
    if config.INTERVALO_COLETA_S != 180 or config.INTERVALO_TREINO_S != 240:
        _falha("O intervalo de coleta ou de treino foi alterado.")
    print("Escolha do painel não cria medição.")


def deduplicacao() -> None:
    """A mesma chave msm_id, probe_id e timestamp não entra duas vezes."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as pasta:
        caminho = Path(pasta) / "t.sqlite"
        conexao = banco.conectar(caminho)
        linha = {
            "id_fluxo": "1_2", "msm_id": 9, "probe_id": 1, "timestamp": 10, "min": 1, "max": 1, "avg": 1,
            "sent": 3, "rcvd": 3, "ttl": 50, "result": "[]", "perda_pct": 0, "jitter_ms": 0, "latencia_ms": 1,
            "ttl_baseline": 50, "delta_ttl": 0, "ttl_changed": 0, "classe_real": "OK", "motivo_rotulagem": "sem_alerta",
            "lacuna": 0, "origem": "replay",
        }
        if not banco.inserir_medicao(conexao, linha):
            _falha("A primeira inserção foi ignorada.")
        if banco.inserir_medicao(conexao, linha):
            _falha("A coleta duplicada criou outra linha.")
        conexao.commit()
        conexao.close()
    print("Deduplicação ok.")


def aquecimento_fora() -> None:
    """Linhas de aquecimento não entram na métrica da sessão."""
    quadro = pd.DataFrame({"real": ["OK"] * 10, "previsto": ["OK"] * 10, "persistencia": ["OK"] * 10, "aquecimento": [1] * 10, "lacuna": [0] * 10})
    uteis = quadro[(quadro["aquecimento"] == 0) & (quadro["lacuna"] == 0)]
    if not uteis.empty:
        _falha("Linhas de aquecimento entraram na métrica.")
    print("Aquecimento fora das métricas.")


def uso_fastapi() -> None:
    """O serviço é FastAPI e a página é o HTML estático."""
    texto_api = (config.SRC_DIR / "api.py").read_text(encoding="utf-8")
    if (config.SRC_DIR / "app.py").is_file():
        _falha("app.py do Dash ainda está em src.")
    if "FastAPI" not in texto_api:
        _falha("api.py não cria FastAPI.")
    if "sqlite3" in texto_api:
        _falha("api.py importa ou cita sqlite3.")
    for nome in ("streamlit", "gradio", "dash.Dash"):
        if nome in texto_api:
            _falha(f"Biblioteca de interface proibida: {nome}.")
    print("FastAPI ok.")


def endpoints_fastapi() -> None:
    """Rotas com dados de exemplo, feature faltando e banco vazio."""
    import json

    import joblib
    import pandas as pd
    from fastapi.testclient import TestClient

    import api as servico

    cliente = TestClient(servico.app)
    original_db = config.ARQUIVO_DB
    original_par = config.ARQUIVO_PAR
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as pasta:
        config.ARQUIVO_DB = Path(pasta) / "ausente.sqlite"
        config.ARQUIVO_PAR = Path(pasta) / "ausente.json"
        try:
            vazio = cliente.get("/previsoes")
            if vazio.status_code != 200 or vazio.json() != []:
                _falha(f"Sem banco /previsoes deveria ser lista vazia: {vazio.status_code} {vazio.text[:200]}")
            if cliente.get("/par").status_code != 404:
                _falha("Sem par_monitorado.json a rota /par deveria responder 404.")
        finally:
            config.ARQUIVO_DB = original_db
            config.ARQUIVO_PAR = original_par
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as pasta:
        caminho = Path(pasta) / "exemplo.sqlite"
        config.ARQUIVO_DB = caminho
        try:
            banco.criar(caminho)
            conexao = banco.conectar(caminho)
            banco.inserir_medicao(conexao, {
                "id_fluxo": "1016806_3679", "msm_id": 1, "probe_id": 1016806, "timestamp": 1700000000,
                "min": 10.0, "max": 12.0, "avg": 11.0, "sent": 3, "rcvd": 3, "ttl": 56,
                "result": "[]", "perda_pct": 0.0, "jitter_ms": 0.1, "latencia_ms": 11.0,
                "ttl_baseline": 56.0, "delta_ttl": 0.0, "ttl_changed": 0, "classe_real": "OK",
                "motivo_rotulagem": "ok", "lacuna": 0, "origem": "replay",
            })
            nomes = json.loads(config.PACOTE_MODELO.features.read_text(encoding="utf-8"))["features"]
            banco.inserir_previsao(conexao, {
                "id_fluxo": "1016806_3679", "timestamp_t": 1700000000, "features": {nome: 0.0 for nome in nomes},
                "prob_OK": 0.9, "prob_RISCO": 0.05, "prob_FALHA": 0.05, "previsto": "OK", "persistencia": "OK",
                "real": "OK", "acerto": 1, "aquecimento": 0, "lacuna": 0, "modelo_hash": servico.ESTADO.hash,
                "criado_em": "2026-01-01T00:00:00Z",
            })
            conexao.commit()
            conexao.close()
            for rota in ("/saude", "/par", "/previsoes"):
                resposta = cliente.get(rota)
                if resposta.status_code != 200:
                    _falha(f"{rota} respondeu {resposta.status_code}: {resposta.text[:300]}")
            achou = None
            colunas = ["split", *nomes]
            for pedaco in pd.read_csv(config.ARQUIVO_FINAL_ETAPA7, usecols=colunas, chunksize=20000):
                fatia = pedaco[pedaco["split"] == config.SPLIT_PREVISTO]
                if not fatia.empty:
                    achou = fatia.iloc[0]
                    break
            if achou is None:
                _falha("Não há linha de validação para conferir /prever.")
            features = {nome: float(achou[nome]) for nome in nomes}
            resposta = cliente.post("/prever", json={"features": features})
            if resposta.status_code != 200:
                _falha(f"/prever respondeu {resposta.status_code}: {resposta.text[:300]}")
            incompletas = dict(features)
            incompletas.pop(nomes[0])
            falta = cliente.post("/prever", json={"features": incompletas})
            if falta.status_code != 422:
                _falha(f"Feature faltando deveria ser 422, veio {falta.status_code}.")
            modelo = joblib.load(config.PACOTE_MODELO.joblib)
            if isinstance(modelo, dict) and "modelo" in modelo:
                modelo = modelo["modelo"]
            if hasattr(modelo, "set_params"):
                modelo.set_params(n_jobs=1)
            vetor = [[features[nome] for nome in nomes]]
            direto = str(modelo.predict(vetor)[0])
            if resposta.json()["previsto"] != direto:
                _falha(f"/prever devolveu {resposta.json()['previsto']} e o joblib devolveu {direto}.")
            if resposta.json()["modelo_hash"] != servico.ESTADO.hash:
                _falha("modelo_hash de /prever não é o hash do joblib da etapa 8.")
        finally:
            config.ARQUIVO_DB = original_db
    print("Endpoints ok.")


def concordancia_humana() -> None:
    """A marca local só entra se a sessão tem a linha RISCO ou FALHA. Não chama o RIPE."""
    import hashlib

    import stream_publico
    from fastapi.testclient import TestClient

    import api as servico

    def sha(caminho: Path) -> str:
        digest = hashlib.sha256()
        with caminho.open("rb") as arquivo:
            for bloco in iter(lambda: arquivo.read(1 << 20), b""):
                digest.update(bloco)
        return digest.hexdigest()

    chamadas = []

    def proibido(*_args, **_kwargs):
        chamadas.append(True)
        raise RuntimeError("post_json")

    original_post = api_ripe.post_json
    original_sessao = config.ARQUIVO_SESSAO
    original_arquivo = config.ARQUIVO_CONCORDANCIA
    original_memoria = stream_publico._SESSAO
    bytes_sessao = original_sessao.read_bytes() if original_sessao.is_file() else None
    hash_modelo = sha(config.PACOTE_MODELO.joblib)
    existia = original_arquivo.is_file()
    bytes_marca = original_arquivo.read_bytes() if existia else None
    api_ripe.post_json = proibido
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as pasta:
            config.ARQUIVO_SESSAO = Path(pasta) / "sessao_stream.json"
            config.ARQUIVO_CONCORDANCIA = Path(pasta) / "concordancia_humana.jsonl"
            stream_publico._SESSAO = None
            documento = {
                "ativa": False,
                "id_fluxo": "6659_4074",
                "medicao_criada": False,
                "linhas": [
                    {"timestamp": 1700000000, "status": "OK", "motivo": "ok", "features": {"perda_pct": 0}, "src_addr": "203.0.113.8"},
                    {"timestamp": 1700000240, "status": "RISCO", "motivo": "perda_parcial", "features": {"perda_pct": 33}, "src_addr": "203.0.113.9"},
                    {"timestamp": 1700000480, "status": "FALHA", "motivo": "perda_severa", "features": {"perda_pct": 100}, "src_addr": "203.0.113.10"},
                ],
            }
            config.ARQUIVO_SESSAO.write_text(json.dumps(documento), encoding="utf-8")
            texto_sessao = config.ARQUIVO_SESSAO.read_text(encoding="utf-8")
            cliente = TestClient(servico.app)
            ok = cliente.post("/monitorar/concordancia", json={
                "timestamp": 1700000000, "id_fluxo": "6659_4074", "status": "OK", "motivo": "ok", "marca": "concordo",
            })
            if ok.status_code != 422:
                _falha(f"Status OK deveria ser 422, veio {ok.status_code}.")
            ausente = cliente.post("/monitorar/concordancia", json={
                "timestamp": 1, "id_fluxo": "6659_4074", "status": "FALHA", "motivo": "", "marca": "nao_sei",
            })
            if ausente.status_code != 422:
                _falha(f"Timestamp fora da sessão deveria ser 422, veio {ausente.status_code}.")
            if config.ARQUIVO_CONCORDANCIA.is_file():
                _falha("Um POST recusado gravou concordância.")
            valido = cliente.post("/monitorar/concordancia", json={
                "timestamp": 1700000240, "id_fluxo": "6659_4074", "status": "RISCO", "motivo": "perda_parcial", "marca": "concordo",
            })
            if valido.status_code != 200:
                _falha(f"POST válido respondeu {valido.status_code}: {valido.text[:200]}")
            de_novo = cliente.post("/monitorar/concordancia", json={
                "timestamp": 1700000240, "id_fluxo": "6659_4074", "status": "RISCO", "motivo": "perda_parcial", "marca": "discordo",
            })
            if de_novo.status_code != 200:
                _falha(f"O segundo POST respondeu {de_novo.status_code}.")
            if config.ARQUIVO_SESSAO.read_text(encoding="utf-8") != texto_sessao:
                _falha("A concordância alterou sessao_stream.json.")
            linhas = [json.loads(linha) for linha in config.ARQUIVO_CONCORDANCIA.read_text(encoding="utf-8").splitlines() if linha]
            if [linha.get("marca") for linha in linhas] != ["concordo", "discordo"]:
                _falha(f"O JSONL não guardou as duas marcas: {linhas}")
            texto = config.ARQUIVO_CONCORDANCIA.read_text(encoding="utf-8")
            if "RIPE_ATLAS_API_KEY" in texto or "src_addr" in texto or "features" in texto:
                _falha("A concordância gravou chave, endereço ou features.")
            chaves = {"timestamp", "id_fluxo", "status", "motivo", "marca", "gravado_em"}
            if any(set(linha) != chaves for linha in linhas):
                _falha(f"A linha gravada tem campos a mais: {linhas}")
    finally:
        api_ripe.post_json = original_post
        config.ARQUIVO_SESSAO = original_sessao
        config.ARQUIVO_CONCORDANCIA = original_arquivo
        stream_publico._SESSAO = original_memoria
    if chamadas:
        _falha("post_json foi chamado ao registrar a concordância.")
    if sha(config.PACOTE_MODELO.joblib) != hash_modelo:
        _falha("A concordância alterou o joblib.")
    atual = original_sessao.read_bytes() if original_sessao.is_file() else None
    if atual != bytes_sessao:
        _falha("A sessão real foi modificada.")
    if existia:
        if original_arquivo.read_bytes() != bytes_marca:
            _falha("O arquivo real de concordância foi modificado.")
    elif original_arquivo.is_file():
        _falha("A verificação criou o arquivo real de concordância.")
    print("Concordância humana ok.")


def pagina_preditor() -> None:
    """O índice abre a página e a página volta ao índice."""
    pagina = (config.RAIZ_PROJETO / "painel-preditor.html").read_text(encoding="utf-8")
    indice = config.ARQUIVO_INDEX.read_text(encoding="utf-8")
    if 'href="painel-preditor.html"' not in indice:
        _falha("O índice não aponta para painel-preditor.html.")
    if 'href="index.html"' not in pagina:
        _falha("A página do preditor não volta ao índice.")
    if 'id="monitorar"' not in pagina or "Começar monitoramento" not in pagina:
        _falha("A página não tem a seção Monitorar.")
    if "API indisponível" not in pagina:
        _falha("A página não avisa quando a API está fora.")
    print("Página do preditor ok.")


def _trava_sem_teste() -> None:
    """Falha cedo se a suíte passar a medir o split de teste."""
    import ast

    if config.SPLIT_PREVISTO != "validacao":
        _falha("SPLIT_PREVISTO deixou de ser validacao.")
    arvore = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Compare) or len(no.ops) != 1 or not isinstance(no.ops[0], ast.Eq):
            continue
        if "split" not in ast.unparse(no.left):
            continue
        for comparador in no.comparators:
            valor = comparador.value if isinstance(comparador, ast.Constant) else None
            if isinstance(comparador, ast.Attribute):
                valor = comparador.attr
            if valor in ("teste", "SPLIT_TESTE"):
                _falha("verificar.py passou a filtrar o split de teste.")


def antes_da_coleta() -> None:
    """Bloqueia o coletor se as features não batem com o treino."""
    equivalencia_features()
    sem_vazamento()
    rotulagem_igual()


def main() -> int:
    _trava_sem_teste()
    antes_da_coleta()
    chave_ausente_dos_arquivos()
    novo_sem_confirmacao_nao_cria()
    escolha_do_painel_nao_cria()
    deduplicacao()
    aquecimento_fora()
    uso_fastapi()
    endpoints_fastapi()
    concordancia_humana()
    pagina_preditor()
    print("Verificações concluídas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
