"""Parâmetros da etapa 4: coleta dos resultados ping de cada fluxo origem → destino.

Nenhum limite, URL, coluna ou texto da página fica no script. A janela padrão
termina no início da hora UTC para que uma segunda execução na mesma hora
repita as mesmas URLs e acerte o cache.
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
ARQUIVO_ANCHORS_ETAPA1 = RAIZ_PROJETO / "pipeline" / "01_anchors" / "data" / "anchors_selecionadas.json"
ARQUIVO_MEDICOES_ETAPA2 = RAIZ_PROJETO / "pipeline" / "02_medicoes" / "data" / "medicoes_ping_ongoing.json"
ARQUIVO_PROBES_ETAPA3 = RAIZ_PROJETO / "pipeline" / "03_probes" / "data" / "probes_selecionadas.json"
ARQUIVO_CSV = DATA_DIR / "fluxo_bruto.csv"
ARQUIVO_METADADOS = DATA_DIR / "metadados.json"
ARQUIVO_HTML = TEMPLATE_DIR / "fluxo.html"
ARQUIVO_INDEX = RAIZ_PROJETO / "index.html"
ARQUIVO_PROMPT_ORIGEM = RAIZ_PROJETO / "4_medicoes_fluxo.md"
ARQUIVO_PROMPT = PROMPT_DIR / "etapa4_prompt.md"

# ---------------------------------------------------------------------------
# Coleta
# ---------------------------------------------------------------------------

ADDRESS_FAMILY = 4
TIPO_MEDICAO = "ping"
STATUS_ONGOING_NOME = "Ongoing"
JANELA_PADRAO_HORAS = 24
FUSO = "UTC"
FORMATO_ID_FLUXO = "{probe_id}_{anchor_id}"
# Par origem-destino com perda alta: (soma sent − soma rcvd) / soma sent,
# em percentual, na janela. Só entra no resumo; não vira coluna do CSV.
PERDA_ALTA_PERCENT = 20
MARCADOR_TIMEOUT = "x"
CHAVE_ANCHORS = "anchors"
CHAVE_PROBES = "probes"
CHAVE_MEDICOES = "medicoes"
CAMPO_ID = "id"
CAMPO_MEASUREMENT_ID = "measurement_id"
CAMPO_COUNTRY = "country"
CAMPO_COUNTRY_CODE = "country_code"
CAMPO_CITY = "city"
CAMPO_IS_ANCHOR = "is_anchor"
CAMPO_IP = "ip_v4"
CAMPO_ADDRESS = "address_v4"
CAMPO_HOSTNAME = "hostname"
CAMPO_IS_DISABLED = "is_disabled"

COLUNAS_CSV = [
    "anchor_id",
    "anchor_ip",
    "probe_id",
    "probe_ip",
    "msm_id",
    "ttl",
    "result",
    "dup",
    "rcvd",
    "sent",
    "min",
    "max",
    "avg",
    "timestamp",
    "type",
    "packets",
    "interval",
]

# Recortes gravados no metadado, na ordem em que a API os nomeia.
CAMPOS_MEDICAO = ("id", "interval", "is_public", "packets", "target", "target_ip", "type")
CAMPO_STATUS = "status"
CAMPO_STATUS_NOME = "name"
CAMPOS_ANCHOR = (
    "id",
    "hostname",
    "fqdn",
    "probe",
    "ip_v4",
    "city",
    "country",
    "company",
    "geometry",
    "is_disabled",
)
# Constantes do resultado. O que muda a cada execução fica só no CSV.
CAMPOS_RESULTADO_METADADO = ("af", "dst_name", "dst_addr", "src_addr", "proto", "type", "prb_id", "msm_id")
CAMPOS_RESULTADO_LINHA = ("ttl", "result", "dup", "rcvd", "sent", "min", "max", "avg", "timestamp", "type")
CAMPO_AF = "af"
CAMPO_PRB_ID = "prb_id"
CAMPO_SRC = "src_addr"
CAMPO_DST = "dst_addr"
CAMPO_TIMESTAMP = "timestamp"
CAMPO_SENT = "sent"
CAMPO_RCVD = "rcvd"
CAMPO_RESULT = "result"
CAMPO_MIN = "min"
CAMPO_AVG = "avg"
CAMPO_MAX = "max"
CAMPO_PACKETS = "packets"
CAMPO_INTERVAL = "interval"

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

URL_MEASUREMENTS = "https://atlas.ripe.net/api/v2/measurements/{id}/"
URL_ANCHORS = "https://atlas.ripe.net/api/v2/anchors/{id}/"
URL_RESULTS = "https://atlas.ripe.net/api/v2/measurements/{msm_id}/results/"
URL_PAGINA_PROBE = "https://atlas.ripe.net/probes/{id}/"
URL_PAGINA_ANCHOR = "https://atlas.ripe.net/anchors/{id}/"
URL_PAGINA_MEDICAO = "https://atlas.ripe.net/measurements/{id}/"
PARAM_PROBE_IDS = "probe_ids"
PARAM_START = "start"
PARAM_STOP = "stop"
PARAM_FORMAT = "format"
FORMATO_RESULTADOS = "json"
ORDEM_PARAMS_RESULTS = (PARAM_PROBE_IDS, PARAM_START, PARAM_STOP, PARAM_FORMAT)
MAX_BYTES_RESPOSTA = 30_000_000

# ---------------------------------------------------------------------------
# Rede e cache
# ---------------------------------------------------------------------------

TIMEOUT_S = 120
MAX_TENTATIVAS = 5
BACKOFF_S = 2.0
PAUSA_S = 0.4
CACHE_TTL_HORAS = 24
USER_AGENT = "projeto-preditor-redes/etapa4 (coleta de fluxos ping; uso academico)"

# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------

TITULO_PAGINA = "Fluxo de exemplo — Etapa 4"
PAIS_DESTAQUE = "BR"
# None: a anchor do país em destaque e a primeira probe dela, na ordem da
# Etapa 3, que tenha resultados na janela.
HTML_FLUXO = None
HTML_MAX_LINHAS = 10
ROTULO_VAZIO = "—"
ROTULO_SIM = "sim"
ROTULO_NAO = "não"
LINK_INICIO = "../../index.html"
LINK_ETAPA4 = "pipeline/04_fluxos/template/fluxo.html"
ROTULO_ETAPA4 = "Etapa 4"
TITULO_CARTAO = "Medições dos fluxos"
MARCADOR_ETAPA4_INICIO = "<!-- etapa4:inicio -->"
MARCADOR_ETAPA4_FIM = "<!-- etapa4:fim -->"
MARCADOR_ETAPA3_FIM = "<!-- etapa3:fim -->"
CAMINHO_DADOS_AVISO = "data/fluxo_bruto.csv"
TEXTO_FLUXO = (
    "Um fluxo é o par origem → destino: uma probe envia pacotes para uma anchor. "
    "O identificador único junta os dois IDs."
)
TEXTO_PARAMETROS = (
    "Estes parâmetros são constantes, definidos no início do projeto, e por isso não aparecem na tabela."
)
TEXTO_SEM_LINHAS = "Este fluxo não teve resultados na janela de coleta."
AVISO_AMOSTRA = (
    "Amostra: 1 fluxo e as primeiras {mostradas} de {total} linhas. "
    "Dados completos em `{caminho}`."
)
ROTULO_ORIGEM = "ORIGEM"
ROTULO_DESTINO = "DESTINO"
ROTULO_GLOSSARIO = "Glossário"
ROTULO_METADADOS = "Metadados do fluxo"
ROTULO_MEDICAO = "Medição"
ROTULO_ANCHOR = "Anchor"
ROTULO_RESULTADO = "Resultado"
ROTULO_PARAMETROS = "Parâmetros comuns a todos os fluxos"
COLUNAS_HTML = [
    {"chave": "timestamp", "rotulo": "timestamp (UTC)"},
    {"chave": "min", "rotulo": "rtt_min (ms)"},
    {"chave": "avg", "rotulo": "rtt_avg (ms)"},
    {"chave": "max", "rotulo": "rtt_max (ms)"},
    {"chave": "rcvd", "rotulo": "rcvd"},
    {"chave": "sent", "rotulo": "sent"},
    {"chave": "packets", "rotulo": "pacotes"},
    {"chave": "ttl", "rotulo": "ttl"},
]
CHAVES_RTT = ("min", "avg", "max")
COLUNAS_GLOSSARIO = ("Feature", "Tipo esperado", "Descrição", "Exemplo", "Utilidade")

GLOSSARIO = [
    {
        "titulo": "1. Identificação do fluxo",
        "linhas": [
            ("id_fluxo", "String", "Identificador único do par origem → destino (`{probe_id}_{anchor_id}`). Definido pelo projeto.", "6317_1002", "Referenciar o fluxo sem ambiguidade."),
            ("probe_id (prb_id)", "Inteiro", "Probe de origem que gerou o resultado.", "6317", "Identificar a origem."),
            ("probe_ip (src_addr)", "String", "IP de origem usado pela probe.", "130.59.80.2", "Identificar o endereço de origem."),
            ("anchor_id (id)", "Inteiro", "Anchor de destino.", "1002", "Identificar o destino."),
            ("anchor_ip (ip_v4)", "String", "Endereço IPv4 da anchor.", "193.65.45.86", "Identificar o endereço de destino."),
            ("city / country", "String", "Cidade e país (ISO alpha-2) da anchor; da origem, só quando ela é uma anchor.", "Tampere / FI", "Localizar geograficamente origem e destino."),
            ("msm_id", "Inteiro", "Medição associada ao resultado.", "1001", "Ligar o fluxo aos metadados da medição."),
        ],
    },
    {
        "titulo": "2. Dados que variam a cada execução (colunas da tabela)",
        "linhas": [
            ("timestamp", "Inteiro", "Execução em Unix timestamp.", "1789992001", "Ordenar cronologicamente."),
            ("min (rtt_min)", "Decimal", "Menor RTT entre os pacotes recebidos, em ms.", "138.73", "Menor tempo de ida e volta."),
            ("avg (rtt_avg)", "Decimal", "RTT médio dos pacotes recebidos, em ms.", "138.91", "Latência média da execução."),
            ("max (rtt_max)", "Decimal", "Maior RTT entre os pacotes recebidos, em ms.", "139.04", "Maior tempo de ida e volta."),
            ("rcvd", "Inteiro", "Pacotes recebidos.", "3", "Saber quantas respostas chegaram."),
            ("sent", "Inteiro", "Pacotes enviados.", "3", "Saber quantos pacotes saíram."),
            ("packets (pacotes)", "Inteiro", "Pacotes configurados por execução (da medição).", "3", "Conhecer o tamanho da rodada de ping."),
            ("ttl", "Inteiro", "TTL do pacote recebido.", "47", "Informação sobre a resposta recebida."),
        ],
    },
    {
        "titulo": "3. Parâmetros comuns a todos os fluxos",
        "linhas": [
            ("type", "String", "Tipo de medição.", "ping", "Confirmar que o teste é ping."),
            ("af", "Inteiro", "Address family (4 = IPv4).", "4", "Confirmar que o fluxo é IPv4."),
            ("interval", "Inteiro", "Intervalo, em segundos, entre execuções.", "240", "Conhecer a frequência da medição."),
            ("proto", "String", "Protocolo da medição.", "ICMP", "Em ping, normalmente ICMP."),
            ("is_public", "Booleano", "Se a medição e seus resultados são públicos.", "true", "Verificar se os dados são consultáveis."),
            ("status.name", "String", "Estado da medição.", "Ongoing", "Verificar se está ativa."),
        ],
    },
]

DIAGRAMA_RELACAO = """MEDIÇÃO (id, interval, is_public, packets, status.name, target, target_ip, type)
    │ msm_id
    ▼
RESULTADO DO PROBE (prb_id, src_addr, dst_addr, af, proto, ttl, result, dup,
                    rcvd, sent, min, max, avg, timestamp, type, msm_id)
    │ prb_id
    ▼
PROBE / ORIGEM
    │ medição
    ▼
ANCHOR / DESTINO (id, hostname, fqdn, probe, ip_v4, city, country, company,
                  geometry, is_disabled)"""

TITULO_DIAGRAMA = "4. Relação entre os conjuntos de dados"

LIMITACOES = [
    "A API de probes não informa a cidade. Quando a origem é uma anchor, a cidade vem do campo city já gravado na Etapa 3, preenchido naquela etapa a partir de GET /anchors/. A Etapa 1 só lista as 30 anchors de destino e não guarda o id da probe, então não cobre as outras origens. Origem que não é anchor fica com cidade null, exibida como —.",
    "Ensaio de coleta na janela padrão. fluxo_bruto.csv guarda só campos originais da API; perda alta aparece apenas no resumo do terminal.",
    "Campo ausente no resultado vira célula vazia. Timeout em result permanece {\"x\": \"*\"}, sem conversão.",
]

MOTIVO_SEM_RESULTADO = "nenhum resultado na janela"
MOTIVO_ID_REPETIDO = "id_fluxo repetido na Etapa 3; a segunda ocorrência não foi coletada"
MOTIVO_FORA_ETAPA2 = "measurement_id da Etapa 3 não aparece nas medições da Etapa 2"
