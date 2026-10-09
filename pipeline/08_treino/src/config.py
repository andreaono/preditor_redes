"""Parâmetros da etapa 8: Naive Bayes, árvore e floresta.

O teste não entra nestes números. As features vêm de features.json da Etapa 7.
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
MODELOS_DIR = DATA_DIR / "modelos"
SRC_DIR = BASE_DIR / "src"
TEMPLATE_DIR = BASE_DIR / "template"
ARQUIVO_DATASET_FINAL_ETAPA7 = RAIZ_PROJETO / "pipeline" / "07_rotulagem" / "data" / "dataset_final.csv"
ARQUIVO_FEATURES_ETAPA7 = RAIZ_PROJETO / "pipeline" / "07_rotulagem" / "data" / "features.json"
ARQUIVO_QUALIDADE_ETAPA7 = RAIZ_PROJETO / "pipeline" / "07_rotulagem" / "data" / "qualidade_rotulagem.json"
ARQUIVO_VALIDACAO = DATA_DIR / "resultados_validacao.json"
ARQUIVO_GRADE = DATA_DIR / "grade_busca.csv"
ARQUIVO_ESCOLHIDO = DATA_DIR / "modelo_escolhido.json"
ARQUIVO_MODELO = MODELOS_DIR / "modelo_escolhido.joblib"
ARQUIVO_ARVORE_ILUSTRATIVA = DATA_DIR / "arvore_ilustrativa.json"
ARQUIVO_ARVORE_PEDACO = DATA_DIR / "arvore_pedaco.json"
ARQUIVO_TESTE = DATA_DIR / "avaliacao_teste.json"
ARQUIVO_LOCK = DATA_DIR / "teste_executado.lock"
ARQUIVO_RESUMO_PAGINA = DATA_DIR / "resumo_pagina.json"
ARQUIVO_VERIFICACAO = DATA_DIR / "verificacao.json"
ARQUIVO_HTML = TEMPLATE_DIR / "modelo.html"
ARQUIVO_INDEX = RAIZ_PROJETO / "index.html"
ARQUIVO_PROMPT_ORIGEM = RAIZ_PROJETO / "8_modelo.md"
ARQUIVO_PROMPT = PROMPT_DIR / "etapa8_prompt.md"

# ---------------------------------------------------------------------------
# Treino
# ---------------------------------------------------------------------------

SEED = 42
CLASSES = ("OK", "RISCO", "FALHA")
CLASSE_OK = "OK"
ALGORITMOS = ("naive_bayes", "arvore_decisao", "random_forest")
METRICA_SELECAO = "macro_f1"
N_JOBS = -1
SPLIT_TREINO = "treino"
SPLIT_VALIDACAO = "validacao"
SPLIT_TESTE = "teste"
SPLITS_AJUSTE = (SPLIT_TREINO, SPLIT_VALIDACAO)
FATIAS = ("geral", "transicoes", "inicio_falha", "sem_anchor_dominante")
PROFUNDIDADE_SEM_LIMITE = None
PROFUNDIDADE_COMPLEXA = 10**9
CLASS_WEIGHT_NENHUM = None
ROTULO_NENHUM = "nenhum"
ROTULO_SEM_LIMITE = "sem_limite"

# Ordem da grade: o primeiro valor de cada lista é o candidato mais simples
# quando a métrica empata.
GRADES = {
    "naive_bayes": {
        "var_smoothing": (1e-9, 1e-6, 1e-3, 1e-1),
    },
    "arvore_decisao": {
        "max_depth": (3, 5, 8, 12, PROFUNDIDADE_SEM_LIMITE),
        "min_samples_leaf": (1, 20, 100),
        "class_weight": (CLASS_WEIGHT_NENHUM, "balanced"),
    },
    "random_forest": {
        "n_estimators": (100, 200),
        "max_depth": (6, 12, PROFUNDIDADE_SEM_LIMITE),
        "min_samples_leaf": (5, 50),
        "max_features": ("sqrt",),
        "class_weight": (CLASS_WEIGHT_NENHUM, "balanced_subsample"),
    },
}

COLUNAS_PROIBIDAS = (
    "anchor_id",
    "probe_id",
    "timestamp",
    "classe",
    "classe_atual",
    "motivo_rotulagem",
    "ttl",
    "ttl_baseline",
    "latencia_ms",
    "rtt_min",
    "rtt_max",
    "rtt_avg",
    "jitter_ms",
    "p95_rtt_A",
    "p99_rtt_A",
    "p95_jitter_A",
)
COLUNAS_GRADE = (
    "familia",
    "hiperparametros",
    "macro_f1_treino",
    "macro_f1_validacao",
    "gap",
    "f1_falha_validacao",
    "recall_falha_validacao",
)
FEATURES_AMOSTRA = (
    "razao_rtt_p95",
    "razao_jitter_p95",
    "perda_media_w3",
    "perdas_consecutivas",
)
FEATURES_DEPENDENTES_RTT = (
    "razao_rtt_p95",
    "razao_rtt_p99",
    "razao_jitter_p95",
    "amplitude_rtt_rel",
    "rtt_p95_max_w3",
    "jitter_p95_max_w3",
    "n_rtt_acima_p95_w3",
    "rtt_p95_max_w6",
    "jitter_p95_max_w6",
    "n_rtt_acima_p95_w6",
    "rtt_p95_max_w12",
    "jitter_p95_max_w12",
    "n_rtt_acima_p95_w12",
)
TOLERANCIA_PERSISTENCIA = 1e-6
TOLERANCIA_SENTINELA = 1e-9
FORMATO_DATA_SPLIT = "%Y-%m-%d %H:%M:%S UTC"

# ---------------------------------------------------------------------------
# Análise
# ---------------------------------------------------------------------------

LIM_OVERFIT_GAP = 0.10
LIM_MACRO_F1_BAIXO = 0.60
LIM_RECALL_FALHA = 0.50
LIM_RECALL_INICIO = 0.50
LIM_GANHO_PEQUENO = 0.03
LIM_ANCHOR_DOMINANTE = 0.50
LIM_QUEDA_TESTE = 0.05

# ---------------------------------------------------------------------------
# Árvore da página
# ---------------------------------------------------------------------------

ARVORE_ILUSTRATIVA_PROFUNDIDADE = 3
ARVORE_NIVEIS_PEDACO = 3
ARVORE_MIN_AMOSTRAS_NO = 1
ARVORE_CASAS_LIMIAR = 2
ARVORE_PASSO_X = 210
ARVORE_PASSO_Y = 128
ARVORE_LARGURA_NO = 176
ARVORE_ALTURA_NO = 92
ROTULO_SIM = "sim"
ROTULO_NAO = "não"
ROTULO_SENTINELA = "sem RTT (sentinela)"
ORIGEM_ARVORE = "arvore_decisao"
ORIGEM_FLORESTA = "random_forest_arvore_0"

# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------

TITULO_PAGINA = "Ciclo de vida do modelo — Etapa 8"
CASAS_DECIMAIS = 3
HTML_MAX_LINHAS = 8
ROTULO_VAZIO = "—"
LINK_INICIO = "../../index.html"
LINK_ETAPA8 = "pipeline/08_treino/template/modelo.html"
ROTULO_ETAPA8 = "Etapa 8"
TITULO_CARTAO = "Modelos"
MARCADOR_ETAPA8_INICIO = "<!-- etapa8:inicio -->"
MARCADOR_ETAPA8_FIM = "<!-- etapa8:fim -->"
MARCADOR_ETAPA7_FIM = "<!-- etapa7:fim -->"
COR_OK = "#1b7f4e"
COR_RISCO = "#a67c00"
COR_FALHA = "#a33b32"
COR_OK_ESCURO = "#3dbe9a"
COR_RISCO_ESCURO = "#e6c35c"
COR_FALHA_ESCURO = "#e07068"
TEXTO_INSUFICIENTE = "Dados insuficientes para este cálculo."
TEXTO_PROBLEMA = (
    "A pergunta é prever o estado do fluxo na medição seguinte, cerca de 4 minutos depois, "
    "a partir do histórico recente."
)
TEXTO_TOTAIS = "{linhas} linhas, {fluxos} fluxos, {features} features."
TEXTO_MATRIZ_VALIDACAO = "Matriz do modelo escolhido na validação. Linha: classe real. Coluna: classe prevista."
TEXTO_MATRIZ_TESTE = "Matriz do modelo escolhido no teste. Linha: classe real. Coluna: classe prevista."
TEXTO_TESTE_AUSENTE = "O teste ainda não foi avaliado; os números acima são de validação."
TEXTO_TESTE_FIXO = (
    "O teste não deve ser usado para novos ajustes. "
    "Ajustar de novo exige outro conjunto de teste ou nova janela de dados."
)
TEXTO_NENHUMA_RESSALVA = "Nenhuma das ressalvas automáticas se aplicou."
TEXTO_ZERO_CONSTRUCAO = "0 (por construção)"
AVISO_AMOSTRA = "Amostra: {mostradas} de {total} linhas. Dados completos em pipeline/07_rotulagem/data/dataset_final.csv."
AVISO_GRADE = "Amostra: melhor candidato de cada família. Grade completa em data/grade_busca.csv."
AVISO_ESCOLHA = "Escolha feita na validação; o teste não entrou nesta conta."
AVISO_NB_SENTINELA = (
    "A sentinela -1 das features de RTT entra no Naive Bayes como um número qualquer da gaussiana. "
    "Isso não foi corrigido: é um limite do algoritmo."
)
AVISO_NB_PESO = "O Naive Bayes não tem class_weight. Ele usa as probabilidades a priori do treino."
AVISO_NB_ESPERADO = (
    "Espera-se que o Naive Bayes renda pouco aqui, porque as janelas de 3, 6 e 12 medições "
    "são muito correlacionadas. Isso faz parte da lição."
)
AVISO_ARVORE_SIMPLIFICADA = (
    "A árvore ilustrativa é uma versão simplificada e não é o modelo escolhido."
)
AVISO_CAUSALIDADE = (
    "Um nó no topo é a feature que mais separa as classes no treino, não a causa da falha. "
    "Importância visual não é causalidade."
)
AVISO_RAZAO = (
    "As features em razão ao baseline valem 1,0 no limite do P95 do próprio fluxo. "
    "Acima de 1,0 o RTT passou do P95 daquele fluxo."
)
AVISO_CONTAGEM_FLORESTA = (
    "As contagens desta árvore foram feitas no treino inteiro, não na amostra bootstrap dela."
)
NOTA_PERSISTENCIA = "Um modelo que não supera a persistência não aprendeu nada útil."
NOTA_DIVISAO = (
    "A divisão é cronológica, nunca aleatória, para não espiar o futuro. "
    "As classes são desbalanceadas."
)
NOTA_CIRCULAR = "Rotular a mesma linha com as features dela seria circular. O alvo é a medição seguinte."
NOTA_FOLHA = "Cada folha é uma regra: o caminho da raiz até ela."
SINTOMAS = (
    ("Overfitting", "Reduzir max_depth e aumentar min_samples_leaf."),
    ("Treino e validação baixos", "Rever features e janelas."),
    ("Recall de FALHA baixo", "Testar class_weight e rever as features."),
    ("Ganho pequeno sobre a persistência", "Rever features e janelas."),
    ("Resultado concentrado num anchor", "Rever a divisão por fluxo ou anchor."),
)
CUIDADOS = (
    "O modelo aprende uma regra operacional adotada neste projeto, não a verdade sobre redes.",
    "O Período B tem só 7 dias.",
    "anchor_id e probe_id ficam fora das features para evitar memorização de fluxos.",
    "Avanços opcionais: XGBoost ou HistGradientBoosting, ajuste de limiar, importância por permutação, divisão por fluxo ou anchor, mais semanas de dados, e a árvore escolhida completa com export_text ou graphviz.",
)
PASSOS_CICLO = (
    "Problema e alvo",
    "Dataset",
    "Divisão",
    "Baseline",
    "Algoritmos",
    "Árvore por dentro",
    "Hiperparâmetros",
    "Métricas",
    "Resultado na validação",
    "Análise e decisões",
    "Teste",
    "O que o teste nos diz",
)
CARTAO_ALGORITMO = {
    "naive_bayes": {
        "nome": "Naive Bayes",
        "ideia": "Estima a chance de cada classe assumindo que as features são independentes.",
        "ensina": "Um modelo probabilístico simples, e o custo de uma suposição que aqui é falsa.",
        "limite": "As janelas de 3, 6 e 12 medições são correlacionadas. A sentinela -1 vira um valor qualquer da gaussiana.",
    },
    "arvore_decisao": {
        "nome": "Árvore de Decisão",
        "ideia": "Faz perguntas sim ou não sobre uma feature e chega a uma regra legível.",
        "ensina": "Dá para ler o caminho. O overfitting aparece quando a profundidade cresce.",
        "limite": "Uma árvore funda decora o treino. A versão da página tem profundidade 3 e não é o modelo escolhido.",
    },
    "random_forest": {
        "nome": "Random Forest",
        "ideia": "Várias árvores votam. Cada uma vê uma amostra e um subconjunto das features.",
        "ensina": "A votação reduz a variância de uma árvore só.",
        "limite": "Custa interpretabilidade e tempo. A página mostra só o topo da primeira árvore.",
    },
}
DEFINICAO_METRICA = (
    ("Precisão", "Entre as linhas previstas como essa classe, quantas realmente eram."),
    ("Recall", "Entre as linhas que realmente eram essa classe, quantas o modelo encontrou."),
    ("F1", "Equilíbrio entre precisão e recall de uma classe."),
    ("Macro-F1", "Média do F1 das classes presentes. É a métrica principal, porque não deixa o OK dominar."),
    ("Acurácia", "Porcentagem de acertos. Engana quando uma classe é a maioria."),
)
ARIA_CICLO = "Ciclo de vida do modelo, do problema ao teste, com retorno da análise para os hiperparâmetros."
ARIA_TEMPO = "Linha do tempo do passado até t e o alvo na medição seguinte."
ARIA_SPLITS = "Barra cronológica com treino, embargo, validação, embargo e teste."
ARIA_ARVORE = "Árvore de decisão com a pergunta de cada nó, as amostras e a classe majoritária."
ARIA_BARRAS = "Macro-F1 de treino e de validação da persistência e dos três algoritmos."
ARIA_DISTRIBUICAO = "Distribuição do alvo em treino, validação e teste."
ARIA_EXEMPLO_PERSISTENCIA = "Exemplo didático: a persistência repete OK, RISCO e FALHA na medição seguinte."
FAMILIA_DIDATICA = "naive_bayes"
ROTULO_PERSISTENCIA = "Persistência"
ROTULO_INDISPONIVEL = "Não disponível"
ETIQUETA_DIDATICA = "ponto de partida didático"
ETIQUETA_ESCOLHIDO = "escolhido"
ROTULO_PISO = "persistência (piso)"
LIM_NB_ABAIXO_PERSISTENCIA = 0.0
TEXTO_PERSISTENCIA_O_QUE = (
    "O modelo mais simples possível. Prevê que a próxima medição (t+1) terá a mesma classe da atual "
    "(previsto = classe_atual). Não aprende nada, só repete o presente."
)
TEXTO_EXEMPLO_DIDATICO = "Exemplo didático"
TEXTO_EXEMPLO_SETA = "agora → previsão para daqui a ~4 min"
TEXTO_PERSISTENCIA_REGUA = "Os fluxos tendem a ficar no mesmo estado de uma medição para a outra."
TEXTO_PERSISTENCIA_FIXA = "Um modelo que não supera a persistência não aprendeu nada além de copiar o presente."
TEXTO_TAXA_IGUALDADE = "Na validação, classe_atual coincide com o alvo em {taxa} das linhas ({iguais} de {total})."
TEXTO_PERSISTENCIA_ERRA = (
    "A persistência erra todas as mudanças de estado, porque nunca prevê mudança. "
    "Na fatia transicoes, a persistência tem macro-F1 = 0 por construção."
)
TEXTO_CONTRASTE_ACURACIA = (
    "Macro-F1 da persistência no treino: {treino}. Na validação: {validacao}. "
    "Acurácia do sempre OK na validação: {sempre_ok}. A acurácia alta não substitui o macro-F1."
)
TEXTO_NB_CARTAO = (
    "Assume que as features são independentes entre si. Aqui isso não vale: as janelas de 3, 6 e 12 "
    "medições carregam quase a mesma informação. Além disso, a sentinela -1 vira um número qualquer da "
    "gaussiana. Espera-se que renda pouco, e isso faz parte da lição."
)
TEXTO_NB_ABAIXO_CARTAO = (
    "O Naive Bayes ficou abaixo da persistência: um algoritmo de ML não garante nada sozinho; "
    "só a comparação com o baseline revela isso."
)
TEXTO_NB_ABAIXO_PERSISTENCIA = (
    "O Naive Bayes ficou {pontos} pontos abaixo da persistência: "
    "a suposição de independência não vale para features em janela."
)
TEXTO_GAP_LEITURA = (
    "Gap alto e positivo = overfitting (vai bem no treino, pior na validação). "
    "Gap próximo de zero ou negativo = a validação ficou igual ou melhor que o treino; não é overfitting."
)
TEXTO_GAP_GRUPO = "gap = {valor}"
ROTULO_COLUNA_ESCOLHIDO = "Escolhido"
COR_BARRA_TREINO = "#0f6e56"
COR_BARRA_VALIDACAO = "#c45c26"
COR_NB_TREINO = "#8a8175"
COR_NB_VALIDACAO = "#c8c2b8"
GRAFICO_ALTURA_EIXO = 220
GRAFICO_BASE = 318
GRAFICO_MARGEM_ESQ = 78
GRAFICO_MARGEM_DIR = 176
GRAFICO_LARGURA_GRUPO = 210
GRAFICO_LARGURA_BARRA = 36
GRAFICO_ESPACO_BARRA = 16
GRAFICO_RODAPE = 96
GRAFICO_FOLGA_ROTULO = 18
GRAFICO_LARGURA_CARACTERE = 7.4
GRAFICO_MARCAS = (0.0, 0.25, 0.5, 0.75, 1.0)
GRAFICO_EIXO_MAX = 1.0
GRAFICO_CASAS_EIXO = 2
