"""Serviço FastAPI. Lê o SQLite e serve o modelo. Não cria medição."""

import hashlib
import json
import threading
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field
import banco
import config
import opcoes
import stream_publico


def _iso_de_unix(valor) -> str | None:
    """Converte unix para ISO 8601 em UTC."""
    if valor is None or (isinstance(valor, float) and not np.isfinite(valor)):
        return None
    return datetime.fromtimestamp(int(valor), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _limpar(valor):
    """Troca NaN e tipos do numpy por JSON. Vazio vira null."""
    if isinstance(valor, dict):
        return {str(chave): _limpar(item) for chave, item in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_limpar(item) for item in valor]
    if isinstance(valor, np.ndarray):
        return _limpar(valor.tolist())
    if isinstance(valor, (np.integer,)):
        return int(valor)
    if isinstance(valor, (np.floating, float)):
        numero = float(valor)
        return numero if np.isfinite(numero) else None
    if valor is None:
        return None
    return valor


def _hash_arquivo(caminho) -> str:
    digest = hashlib.sha256()
    with open(caminho, "rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1 << 20), b""):
            digest.update(bloco)
    return "sha256:" + digest.hexdigest()


def _ler_json(caminho):
    if caminho is None or not caminho.is_file():
        return None
    return json.loads(caminho.read_text(encoding="utf-8"))


def _nomes_features() -> list[str]:
    return list(_ler_json(config.PACOTE_MODELO.features)["features"])


def _desde_para_unix(desde: str | None) -> int | None:
    if desde is None or desde == "":
        return None
    texto = str(desde)
    if texto.isdigit():
        return int(texto)
    momento = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    return int(momento.timestamp())


def _linhas(consulta: str, parametros: tuple = ()) -> list[dict]:
    conexao = banco.conectar_leitura()
    if conexao is None:
        return []
    try:
        quadro = pd.read_sql_query(consulta, conexao, params=parametros)
    finally:
        conexao.close()
    if quadro.empty:
        return []
    return [_limpar(linha) for linha in quadro.to_dict(orient="records")]


class EstadoModelo:
    """O joblib entra na memória uma vez, na subida do processo."""

    def __init__(self) -> None:
        self.modelo = None
        self.hash = None
        self.conferido = False
        self.erro = None
        self.versao = None
        self.familia = None
        self.hiperparametros = None
        self._carregar()

    def _carregar(self) -> None:
        try:
            self.hash = _hash_arquivo(config.PACOTE_MODELO.joblib)
            esperado = None
            manifesto = _ler_json(config.PACOTE_MODELO.manifesto) or {}
            if manifesto.get("modelo_hash"):
                esperado = manifesto["modelo_hash"]
            self.versao = manifesto.get("modelo_versao")
            escolhido = _ler_json(config.PACOTE_MODELO.escolhido) or {}
            self.familia = escolhido.get("familia")
            self.hiperparametros = escolhido.get("hiperparametros_texto")
            if esperado is not None and esperado != self.hash:
                self.erro = "hash do joblib diferente do manifesto da etapa 8"
                return
            modelo = joblib.load(config.PACOTE_MODELO.joblib)
            if isinstance(modelo, dict) and "modelo" in modelo:
                modelo = modelo["modelo"]
            if hasattr(modelo, "set_params"):
                modelo.set_params(n_jobs=1)
            self.modelo = modelo
            self.conferido = True
        except Exception as erro:
            self.erro = str(erro)


ESTADO = EstadoModelo()


class PedidoPrever(BaseModel):
    """Features já calculadas. O serviço não grava essa chamada."""

    features: dict[str, float | int | None] = Field(default_factory=dict)


class PedidoEscolha(BaseModel):
    """Fluxo e duração na página Monitorar. Não cria medição."""

    id_fluxo: str
    duracao_minutos: int


class PedidoConcordancia(BaseModel):
    """Marca humana sobre uma linha RISCO ou FALHA já gravada na sessão."""

    timestamp: int
    id_fluxo: str
    status: str
    motivo: str = ""
    marca: str


_TRAVA_CONCORDANCIA = threading.Lock()


def _exigir_modelo():
    if ESTADO.modelo is None or not ESTADO.conferido:
        raise HTTPException(status_code=503, detail=ESTADO.erro or "modelo indisponível")


def _registrar_concordancia(pedido: PedidoConcordancia) -> dict:
    """Anexa a marca se a sessão tem essa linha. Não altera rótulo, sessão nem modelo."""
    if pedido.status not in ("RISCO", "FALHA"):
        raise HTTPException(status_code=422, detail="O status só pode ser RISCO ou FALHA.")
    if pedido.marca not in config.MARCAS_CONCORDANCIA:
        raise HTTPException(status_code=422, detail="A marca só pode ser concordo, discordo ou nao_sei.")
    sessao = stream_publico.foto()
    id_fluxo = str(sessao.get("id_fluxo") or "")
    motivo_pedido = pedido.motivo or ""
    achada = None
    if pedido.id_fluxo == id_fluxo and id_fluxo:
        for linha in sessao.get("linhas") or []:
            try:
                timestamp = int(linha.get("timestamp"))
            except (TypeError, ValueError):
                continue
            if timestamp != int(pedido.timestamp) or linha.get("status") != pedido.status:
                continue
            if (linha.get("motivo") or "") != motivo_pedido:
                continue
            achada = linha
            break
    if achada is None:
        raise HTTPException(status_code=422, detail="Essa linha não está na sessão atual.")
    registro = {
        "timestamp": int(achada["timestamp"]),
        "id_fluxo": id_fluxo,
        "status": achada["status"],
        "motivo": achada.get("motivo") or "",
        "marca": pedido.marca,
        "gravado_em": _agora(),
    }
    config.garantir_pastas()
    with _TRAVA_CONCORDANCIA:
        with config.ARQUIVO_CONCORDANCIA.open("a", encoding="utf-8") as arquivo:
            arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return registro


class _RedeLocal(BaseHTTPMiddleware):
    """Permite a página aberta como arquivo chamar a API neste computador."""

    async def dispatch(self, request, call_next):
        resposta = await call_next(request)
        resposta.headers["Access-Control-Allow-Private-Network"] = "true"
        return resposta


_PAGINAS_ETAPA = {
    "01_anchors": "etapa1_anchors.html",
    "02_medicoes": "medicoes.html",
    "03_probes": "probes.html",
    "04_fluxos": "fluxo.html",
    "05_periodos": "periodos.html",
    "06_baseline": "baseline.html",
    "07_rotulagem": "rotulagem.html",
    "08_treino": "modelo.html",
}


def criar_api() -> FastAPI:
    """Monta as rotas. O objeto publicado para o uvicorn é `app`."""
    aplicacao = FastAPI(title=config.TITULO_PAGINA, docs_url="/docs")
    aplicacao.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    aplicacao.add_middleware(_RedeLocal)

    @aplicacao.get("/index.html")
    def pagina_indice():
        """O índice das etapas. A etapa 9 abre painel-preditor.html."""
        caminho = config.ARQUIVO_INDEX
        if not caminho.is_file():
            raise HTTPException(status_code=404, detail="sem dados")
        return FileResponse(caminho)

    @aplicacao.get("/painel-preditor.html")
    def pagina_preditor():
        """A página de avaliação e monitoramento. Mesma origem da API."""
        caminho = config.RAIZ_PROJETO / "painel-preditor.html"
        if not caminho.is_file():
            raise HTTPException(status_code=404, detail="sem dados")
        return FileResponse(caminho)

    @aplicacao.get("/pipeline/{etapa}/template/{nome}")
    def pagina_etapa(etapa: str, nome: str):
        """Páginas das etapas 1 a 8. O índice servido pela API aponta para elas."""
        if _PAGINAS_ETAPA.get(etapa) != nome:
            raise HTTPException(status_code=404, detail="sem dados")
        caminho = config.RAIZ_PROJETO / "pipeline" / etapa / "template" / nome
        if not caminho.is_file():
            raise HTTPException(status_code=404, detail="sem dados")
        return FileResponse(caminho)

    @aplicacao.get("/monitorar/opcoes")
    def monitorar_opcoes() -> dict:
        """Cinco fluxos com dados ao vivo do RIPE Atlas."""
        return _limpar(opcoes.listar())

    @aplicacao.get("/monitorar/sessao")
    def monitorar_sessao() -> dict:
        """Resultados já lidos na janela e as métricas do modelo nessa amostra."""
        return _limpar(stream_publico.foto())

    @aplicacao.post("/monitorar/escolher")
    def monitorar_escolher(pedido: PedidoEscolha) -> dict:
        """Grava a escolha e abre a leitura pública. Não envia medição à API do RIPE."""
        if pedido.duracao_minutos not in config.DURACOES_MINUTOS:
            raise HTTPException(status_code=422, detail="O tempo deve ser 5 min, 10 min, 30 min, 1 h, 4 h ou 24 h.")
        try:
            documento = opcoes.gravar_escolha(pedido.id_fluxo)
            documento["duracao_minutos"] = pedido.duracao_minutos
            documento["sessao"] = stream_publico.iniciar(documento, pedido.duracao_minutos)
            return _limpar(documento)
        except ValueError as erro:
            raise HTTPException(status_code=422, detail=str(erro)) from erro

    @aplicacao.post("/monitorar/concordancia")
    def monitorar_concordancia(pedido: PedidoConcordancia) -> dict:
        """Registra concordo, discordo ou nao_sei. Não envia nada ao RIPE Atlas."""
        return _registrar_concordancia(pedido)

    @aplicacao.get("/saude")
    def saude() -> dict:
        """Estado da API, do coletor e do modelo."""
        ultima = _linhas("SELECT MAX(timestamp) AS ts FROM medicoes")
        ts = ultima[0]["ts"] if ultima else None
        atraso = None if ts is None else int(datetime.now(timezone.utc).timestamp()) - int(ts)
        corte = int(datetime.now(timezone.utc).timestamp()) - 86400
        avisos = _linhas(
            "SELECT COUNT(*) AS n FROM eventos_log WHERE ts >= ? AND nivel IN ('AVISO', 'ERRO')",
            (_iso_de_unix(corte),),
        )
        ok = _linhas("SELECT COUNT(*) AS n FROM eventos_log WHERE tipo = 'coleta_ok'")
        falha = _linhas("SELECT COUNT(*) AS n FROM eventos_log WHERE tipo IN ('erro_rede', 'http_429')")
        controle = _ler_json(config.ARQUIVO_CONTROLE) or {"pausado": False}
        return {
            "api": "ok",
            "coletor": {
                "ultima_coleta": _iso_de_unix(ts),
                "atraso_s": atraso,
                "ciclos_ok": int(ok[0]["n"]) if ok else 0,
                "ciclos_falha": int(falha[0]["n"]) if falha else 0,
            },
            "modelo_versao": ESTADO.versao,
            "modelo_hash": ESTADO.hash,
            "modelo_conferido": ESTADO.conferido,
            "familia": ESTADO.familia,
            "hiperparametros": ESTADO.hiperparametros,
            "pausado": bool(controle.get("pausado")),
            "avisos_24h": int(avisos[0]["n"]) if avisos else 0,
            "erro_modelo": ESTADO.erro,
        }

    @aplicacao.get("/par")
    def par() -> dict:
        """Checklist, baseline, modo e custo estimado. Não consulta saldo."""
        documento = _ler_json(config.ARQUIVO_PAR)
        if not documento:
            raise HTTPException(status_code=404, detail="sem dados")
        unitario = config.custo_por_resultado()
        por_dia = config.resultados_por_dia()
        documento = dict(documento)
        documento["stop_time"] = documento.get("stop_time")
        documento["creditos"] = {
            "custo_por_resultado": unitario,
            "resultados_por_dia": por_dia,
            "custo_dia": unitario * por_dia,
            "custo_janela": unitario * (config.DURACAO_MEDICAO_H * 3600 // config.INTERVALO_COLETA_S),
            "teto_dia": config.MAX_CREDITOS_DIA,
            "fonte": config.URL_DOC_CREDITOS,
        }
        documento["parametros"] = {
            "modo": config.MODO_COLETA,
            "intervalo_coleta_s": config.INTERVALO_COLETA_S,
            "intervalo_treino_s": config.INTERVALO_TREINO_S,
            "janelas": [3, 6, 12],
        }
        return _limpar(documento)

    @aplicacao.get("/previsoes")
    def previsoes(desde: str | None = None, limite: int = config.LIMITE_PADRAO, fechadas: int | None = None) -> list:
        """Log de previsões. Lista vazia quando ainda não há coleta."""
        inicio = _desde_para_unix(desde)
        clausulas = []
        parametros: list = []
        if inicio is not None:
            clausulas.append("timestamp_t >= ?")
            parametros.append(inicio)
        if fechadas:
            clausulas.append("real IS NOT NULL")
        onde = (" WHERE " + " AND ".join(clausulas)) if clausulas else ""
        parametros.append(int(limite))
        linhas = _linhas(f"SELECT * FROM previsoes{onde} ORDER BY timestamp_t DESC LIMIT ?", tuple(parametros))
        for linha in linhas:
            linha["timestamp_utc"] = _iso_de_unix(linha.get("timestamp_t"))
            if isinstance(linha.get("features"), str):
                linha["features"] = json.loads(linha["features"])
        return linhas

    @aplicacao.post("/prever")
    def prever(pedido: PedidoPrever) -> dict:
        """Devolve a classe de t+1. Esta rota não grava no SQLite."""
        _exigir_modelo()
        nomes = _nomes_features()
        faltando = [nome for nome in nomes if nome not in pedido.features]
        if faltando:
            raise HTTPException(status_code=422, detail={"faltando": faltando})
        invalidas = [nome for nome in nomes if pedido.features[nome] is None]
        if invalidas:
            raise HTTPException(status_code=422, detail={"invalidas": invalidas})
        vetor = np.array([[float(pedido.features[nome]) for nome in nomes]], dtype=float)
        classes = [str(nome) for nome in ESTADO.modelo.classes_]
        proba = ESTADO.modelo.predict_proba(vetor)[0]
        mapa = {nome: float(proba[indice]) for indice, nome in enumerate(classes)}
        previsto = classes[int(np.argmax(proba))]
        return {
            "previsto": previsto,
            "prob_OK": mapa.get("OK"),
            "prob_RISCO": mapa.get("RISCO"),
            "prob_FALHA": mapa.get("FALHA"),
            "modelo_hash": ESTADO.hash,
        }

    return aplicacao


app = criar_api()
