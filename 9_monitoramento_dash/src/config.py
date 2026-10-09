"""Parâmetros do monitoramento. Nenhum outro script guarda número fixo."""

from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
RAIZ_PROJETO = BASE_DIR.parent
CACHE_DIR = BASE_DIR / "cache"
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = DATA_DIR / "logs"
SRC_DIR = BASE_DIR / "src"

@dataclass(frozen=True)
class PacoteModelo:
    """Arquivos congelados que o serviço lê. Continuam nas pastas de origem."""

    manifesto: Path
    joblib: Path
    escolhido: Path
    features: Path


PACOTE_MODELO = PacoteModelo(
    manifesto=RAIZ_PROJETO / "producao" / "modelo" / "manifesto.json",
    joblib=RAIZ_PROJETO / "pipeline" / "08_treino" / "data" / "modelos" / "modelo_escolhido.joblib",
    escolhido=RAIZ_PROJETO / "pipeline" / "08_treino" / "data" / "modelo_escolhido.json",
    features=RAIZ_PROJETO / "pipeline" / "07_rotulagem" / "data" / "features.json",
)

# Leituras do pipeline fora do pacote. A verificação e o coletor ainda abrem estes arquivos.
ARQUIVO_ANCHORS_ETAPA1 = RAIZ_PROJETO / "pipeline" / "01_anchors" / "data" / "anchors_selecionadas.json"
ARQUIVO_PROBES_ETAPA3 = RAIZ_PROJETO / "pipeline" / "03_probes" / "data" / "probes_selecionadas.json"
ARQUIVO_METADADOS_ETAPA5 = RAIZ_PROJETO / "pipeline" / "05_periodos" / "data" / "metadados.json"
ARQUIVO_BASELINE_ETAPA6 = RAIZ_PROJETO / "pipeline" / "06_baseline" / "data" / "baseline_rotulacao_por_fluxo.csv"
ARQUIVO_EXCLUSOES_ETAPA5 = RAIZ_PROJETO / "pipeline" / "05_periodos" / "data" / "exclusoes_processamento.csv"
ARQUIVO_CSV_BRUTO_ETAPA5 = RAIZ_PROJETO / "pipeline" / "05_periodos" / "data" / "fluxo_bruto.csv"
ARQUIVO_FINAL_ETAPA7 = RAIZ_PROJETO / "pipeline" / "07_rotulagem" / "data" / "dataset_final.csv"
ARQUIVO_ROTULADO_ETAPA7 = RAIZ_PROJETO / "pipeline" / "07_rotulagem" / "data" / "dataset_rotulado.csv"
PASTA_CODIGO_ETAPA5 = RAIZ_PROJETO / "pipeline" / "05_periodos" / "src"
PASTA_CODIGO_ETAPA7 = RAIZ_PROJETO / "pipeline" / "07_rotulagem" / "src"

ARQUIVO_DB = DATA_DIR / "monitoramento.sqlite"
ARQUIVO_PAR = DATA_DIR / "par_monitorado.json"
ARQUIVO_ESCOLHA = DATA_DIR / "fluxo_escolhido.json"
ARQUIVO_SESSAO = DATA_DIR / "sessao_stream.json"
ARQUIVO_CONCORDANCIA = DATA_DIR / "concordancia_humana.jsonl"
ARQUIVO_CONTROLE = DATA_DIR / "controle.json"
ARQUIVO_INDEX = RAIZ_PROJETO / "index.html"
ARQUIVO_LOG = LOGS_DIR / "coletor.jsonl"

MODO_COLETA = "novo"
FLUXO_MONITORADO = None
ADDRESS_FAMILY = 4
TIPO_MEDICAO = "ping"
INTERVALO_COLETA_S = 180
INTERVALO_TREINO_S = 240
PACOTES = 3
DURACAO_MEDICAO_H = 24
POLL_S = 60
BACKFILL_HORAS = 6
AQUECIMENTO_N = 12
GAP_MAX_S = 600
FORMATO_ID_FLUXO = "{probe_id}_{anchor_id}"
STATUS_ONGOING_NOME = "Ongoing"
STATUS_BASELINE_OK = "VALIDO"
CLASSE_AMBOS = "A+B"
SPLIT_TESTE = "teste"
PERIODO_REPLAY = "B"

VAR_AMBIENTE_CHAVE = "RIPE_ATLAS_API_KEY"
MAX_CREDITOS_DIA = 2000
# Ping periódico: N * (int(S/1500) + 1). S=48 é o padrão da documentação.
# https://atlas.ripe.net/docs/getting-started/credits
TAMANHO_PACOTE_S = 48
# A página de definições não publica mínimo para interval. Quem recusa é a API.
INTERVALO_MINIMO_S = None
URL_DOC_CREDITOS = "https://atlas.ripe.net/docs/getting-started/credits"
URL_DOC_MEDICAO = "https://atlas.ripe.net/docs/apis/rest-api-manual/measurements/creating-measurements/definitions/"

URL_MEASUREMENTS = "https://atlas.ripe.net/api/v2/measurements/"
URL_MEASUREMENT = "https://atlas.ripe.net/api/v2/measurements/{id}/"
URL_ANCHORS = "https://atlas.ripe.net/api/v2/anchors/{id}/"
URL_PROBES = "https://atlas.ripe.net/api/v2/probes/{id}/"
URL_RESULTS = "https://atlas.ripe.net/api/v2/measurements/{msm_id}/results/"
URL_STREAM = "wss://atlas-stream.ripe.net/stream/?client=projeto-preditor-redes-etapa9"
HOST_STREAM = "atlas-stream.ripe.net"
CAMINHO_STREAM = "/stream/?client=projeto-preditor-redes-etapa9"
URL_CREDITS = "https://atlas.ripe.net/api/v2/credits/"
URL_PAGINA_MEDICAO = "https://atlas.ripe.net/measurements/{id}/"

TIMEOUT_S = 30
TIMEOUT_CONEXAO_S = 10
MAX_TENTATIVAS = 5
BACKOFF_S = 2
PAUSA_S = 0.4
CACHE_TTL_HORAS = 6
USER_AGENT = "projeto-preditor-redes/etapa9 (monitoramento IPv4; uso academico)"

SPLIT_PREVISTO = "validacao"
SENTINELA = -1
TOLERANCIA_FEATURE = 1e-6
CLASSES = ("OK", "RISCO", "FALHA")

LOG_MAX_MB = 5
LOG_NIVEL = "INFO"
LOG_BACKUP = 3

TITULO_PAGINA = "Monitoramento do modelo"
PAIS_DESTAQUE = "BR"
HOST = "127.0.0.1"
# O prompt pede 8000. Nesta máquina essa porta já serve outro programa local.
API_PORTA = 8001
URL_API = f"http://{HOST}:{API_PORTA}"
TIMEOUT_API_S = 10
TIMEOUT_OPCOES_S = 90
N_OPCOES_MONITORAR = 5
DURACOES_MINUTOS = (5, 10, 30, 60, 240, 1440)
ROTULO_DURACAO = {5: "5 min", 10: "10 min", 30: "30 min", 60: "1 h", 240: "4 h", 1440: "24 h"}
REFRESH_S = 30
REFRESH_AMOSTRA_S = 5
CASAS_DECIMAIS = 3
LINHAS_POR_PAGINA = 20
LIMITE_PADRAO = 500
HTML_MAX_LINHAS_LOG = 50
TEXTO_API = "API indisponível"
TEXTO_SEM_DADOS = "sem dados"
TEXTO_VAZIO = "—"
FRASE_ESCALA = (
    "O modelo foi treinado com medições a cada 240 s. "
    "Esta coleta usa 180 s. As janelas contam medições, não minutos: "
    "no modo de 180 s elas cobrem cerca de 9, 18 e 36 min, e o alvo é a medição 3 min à frente. "
    "Isso é um desvio de distribuição esperado."
)
FRASE_CONCORDANCIA = (
    "Esta marca não altera o rótulo nem o modelo. "
    "Ela fica só neste arquivo local."
)
MARCAS_CONCORDANCIA = ("concordo", "discordo", "nao_sei")


def garantir_pastas() -> None:
    """Cria cache, dados e logs se ainda não existirem."""
    for pasta in (CACHE_DIR, DATA_DIR, LOGS_DIR):
        pasta.mkdir(parents=True, exist_ok=True)


def custo_por_resultado(pacotes: int | None = None, tamanho: int | None = None, oneoff: bool = False) -> int:
    """Custo em créditos de um resultado de ping, pela fórmula publicada."""
    n = PACOTES if pacotes is None else pacotes
    s = TAMANHO_PACOTE_S if tamanho is None else tamanho
    unitario = int(n) * (int(s) // 1500 + 1)
    return unitario * 2 if oneoff else unitario


def resultados_por_dia(intervalo_s: int | None = None) -> int:
    """Quantos resultados um probe entrega em 24 h nesse intervalo."""
    intervalo = INTERVALO_COLETA_S if intervalo_s is None else intervalo_s
    if intervalo <= 0:
        raise ValueError("intervalo de coleta inválido")
    return 86400 // int(intervalo)
