"""Parâmetros da etapa 6: baseline de RTT do Período A.

Não há datas aqui. A janela vem de metadados.json da Etapa 5. Esta etapa
não consulta a API.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
RAIZ_PROJETO = BASE_DIR.parent.parent
CACHE_DIR = BASE_DIR / "cache"
PROMPT_DIR = BASE_DIR / "prompt"
DATA_DIR = BASE_DIR / "data"
SRC_DIR = BASE_DIR / "src"
TEMPLATE_DIR = BASE_DIR / "template"
ARQUIVO_CSV_BRUTO_ETAPA5 = RAIZ_PROJETO / "pipeline" / "05_periodos" / "data" / "fluxo_bruto.csv"
ARQUIVO_METADADOS_ETAPA5 = RAIZ_PROJETO / "pipeline" / "05_periodos" / "data" / "metadados.json"
ARQUIVO_BASELINE_TTL_ETAPA5 = RAIZ_PROJETO / "pipeline" / "05_periodos" / "data" / "baseline_ttl_por_par.csv"
ARQUIVO_EXCLUSOES_ETAPA5 = RAIZ_PROJETO / "pipeline" / "05_periodos" / "data" / "exclusoes_processamento.csv"
ARQUIVO_BASELINE = DATA_DIR / "baseline_rotulacao_por_fluxo.csv"
ARQUIVO_QUALIDADE = DATA_DIR / "baseline_qualidade.json"
ARQUIVO_HTML = TEMPLATE_DIR / "baseline.html"
ARQUIVO_INDEX = RAIZ_PROJETO / "index.html"
ARQUIVO_PROMPT_ORIGEM = RAIZ_PROJETO / "6_determinar_baseline.md"
ARQUIVO_PROMPT = PROMPT_DIR / "etapa6_prompt.md"
FONTE_JANELA = "pipeline/05_periodos/data/metadados.json"

# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------

PERIODO_BASELINE = "A"
PERIODO_DATASET = "B"
TIPO_MEDICAO = "ping"
ADDRESS_FAMILY = 4
MIN_AMOSTRAS_BASELINE = 30
PERCENTIS = (95, 99)
ESCALA_PERCENTIL = 100
# avg negativo é a sentinela da API quando não há resposta. Não é um RTT.
AVG_MINIMO = 0
STATUS_VALIDO = "VALIDO"
STATUS_INSUFICIENTE = "INSUFICIENTE"
CLASSES_UNIVERSO = ("A+B", "A")
CLASSES_FORA = ("B", "nenhum")
FORMATO_ID_FLUXO = "{probe_id}_{anchor_id}"
CAMPO_PERIODO = "periodo"
CAMPO_TIPO = "type"
CAMPO_AVG = "avg"
CAMPO_RESULT = "result"
CAMPO_RTT = "rtt"
CAMPO_TTL = "ttl"
CAMPO_SENT = "sent"
CAMPO_RCVD = "rcvd"
CAMPO_TIMESTAMP = "timestamp"
CAMPO_MSM = "msm_id"
CAMPO_ID_FLUXO = "id_fluxo"
CAMPO_ANCHOR = "anchor_id"
CAMPO_PROBE = "probe_id"
MARCADOR_TIMEOUT = "x"
COLUNAS_TTL_CONFERIR = ("ttl_baseline", "ttl_min_A", "ttl_max_A", "n_ttl_distintos_A")
# Na Etapa 5, n_amostras_A conta TTLs. Aqui conta execuções. Não se comparam.
COLUNA_AMOSTRAS_TTL_ETAPA5 = "n_amostras_A"

COLUNAS_BASELINE = [
    "anchor_id",
    "probe_id",
    "id_fluxo",
    "n_amostras_A",
    "n_rtt_validos_A",
    "mediana_rtt_A",
    "p95_rtt_A",
    "p99_rtt_A",
    "mediana_jitter_A",
    "p95_jitter_A",
    "p99_jitter_A",
    "ttl_baseline",
    "ttl_min_A",
    "ttl_max_A",
    "n_ttl_distintos_A",
    "status_baseline",
]

# Série didática da página. Não é medição do projeto.
EXEMPLO_SERIE = (10, 11, 12, 13, 50)
EXEMPLO_MEDIANA = 12

# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------

TITULO_PAGINA = "Baseline do Período A — Etapa 6"
PAIS_DESTAQUE = "BR"
HTML_FLUXO = None
HTML_MAX_LINHAS = 10
ROTULO_VAZIO = "—"
LINK_INICIO = "../../index.html"
LINK_ETAPA6 = "pipeline/06_baseline/template/baseline.html"
ROTULO_ETAPA6 = "Etapa 6"
TITULO_CARTAO = "Baseline do Período A"
MARCADOR_ETAPA6_INICIO = "<!-- etapa6:inicio -->"
MARCADOR_ETAPA6_FIM = "<!-- etapa6:fim -->"
MARCADOR_ETAPA5_FIM = "<!-- etapa5:fim -->"
URL_PAGINA_PROBE = "https://atlas.ripe.net/probes/{id}/"
COR_A = "#0f6e56"
COR_B = "#c45c26"
COR_A_ESCURO = "#3dbe9a"
COR_B_ESCURO = "#e5925d"
CASAS_EXIBICAO = 2
TITULO_O_QUE_E = "O que é o baseline e para que serve"
PERGUNTA_BASELINE = "Como sabemos se 180 ms é bom ou ruim?"
DESTAQUE_BASELINE = (
    "O valor absoluto da latência não basta: precisamos do histórico do próprio fluxo. "
    "O baseline é o comportamento normal de cada fluxo."
)
ROTULO_DIDATICO = "Exemplo didático"
EXEMPLOS_DIDATICOS = (
    {
        "nome": "Fluxo X",
        "historico": "histórico ≈ 15 ms",
        "atual": "medição atual 80 ms",
        "leitura": "mudança relevante para esse fluxo",
    },
    {
        "nome": "Fluxo Y",
        "historico": "histórico ≈ 175 ms",
        "atual": "medição atual 180 ms",
        "leitura": "dentro do que já é normal para esse fluxo",
    },
)
TITULO_PERIODO = "O baseline vem só do Período A"
LEGENDA_TEMPO = (
    "A: aprende o comportamento normal; B: será classificado depois. "
    "Nenhuma linha de A entra no dataset final, nem dados de B entram no baseline "
    "(evita vazamento de dados)."
)
TITULO_FLUXOS = "Quais fluxos fazem parte do baseline"
TITULO_COMO = "Como os valores normais de RTT foram obtidos"
PASSOS = (
    "Passo 1. Cada execução de ping do Período A tem um RTT médio, o campo avg, em ms.",
    "Passo 2. Estas são as primeiras execuções do fluxo. O cálculo usa todas, não só esta amostra.",
    "Passo 3. Os avg do fluxo são ordenados. A mediana é o centro. O P95 e o P99 são posições altas dessa lista.",
)
TEXTO_MEDIANA = "Mediana: metade das medições do histórico fica abaixo e metade acima. Um valor extremo mexe pouco nela."
TEXTO_P95 = "P95: valor abaixo do qual ficam cerca de 95% das medições deste fluxo. Acima dele, o RTT é incomum para esse histórico."
TEXTO_P99 = "P99: valor abaixo do qual ficam cerca de 99% das medições deste fluxo. Acima dele, o RTT é muito incomum para esse histórico."
TEXTO_EXEMPLO_MEDIANA = "Mini-exemplo: 10, 11, 12, 13, 50 → mediana = 12. A mediana é pouco sensível a valores extremos."
AVISO_AMOSTRA = "Amostra: {mostradas} de {total} execuções do fluxo."
TITULO_GRAFICO = "RTT histórico e limites de referência do fluxo"
FAIXAS = (
    "Abaixo do P95: onde está a maior parte do histórico deste fluxo.",
    "Entre o P95 e o P99: incomum para este fluxo.",
    "Acima do P99: muito raro neste histórico.",
    "São limites estatísticos de referência. Ainda não são rótulos.",
)
TITULO_RESULTADO = "Resultado do fluxo de exemplo"
NOTA_TTL = "O TTL não é número de hops; ttl_changed não é falha."
NOTA_JITTER = "O jitter de cada execução usa os poucos pacotes daquela rodada (em geral 3)."
TITULO_CUIDADOS = "Cuidados"
CUIDADOS = (
    "P95 e P99 descrevem este conjunto de dados. Não são leis da Internet.",
    "Poucas amostras produzem percentis pouco representativos. Por isso o baseline exige um mínimo de amostras de RTT.",
    "O Período A também contém degradações: perda e RTT alto entram nos percentis e podem elevar P95 e P99.",
    "O jitter de cada execução depende de poucos pacotes, em geral 3.",
)
TITULO_PROXIMO = "Próximo passo"
TEXTO_PROXIMO = (
    "Definir o significado de OK, RISCO e FALHA, usando baseline_rotulacao_por_fluxo.csv."
)
TEXTO_INSUFICIENTE = "Dados insuficientes para este cálculo."
ARIA_GRAFICO = (
    "Série do RTT médio do fluxo no Período A, com três linhas horizontais: "
    "mediana, P95 e P99. São limites de referência, não classes."
)
