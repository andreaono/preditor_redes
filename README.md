# Preditor de Qualidade de Redes com Machine Learning

Classificação antecipada da próxima medição de ping entre uma sonda e uma âncora do [RIPE Atlas](https://atlas.ripe.net/).

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![scikit-learn](https://img.shields.io/badge/scikit--learn-1.5.1-F7931E?logo=scikitlearn&logoColor=white)
![modelo](https://img.shields.io/badge/modelo-Random%20Forest%20rf__v1.0.0-0f6e56)
![status](https://img.shields.io/badge/status-avalia%C3%A7%C3%A3o%20conclu%C3%ADda-informational)

O modelo observa o ping **agora** e estima a classe do ping **seguinte**, cerca de **4 minutos** depois. A previsão não abre medição, não gasta crédito da API e não é uma ordem de intervenção.

---

## O que o sistema faz

Um fluxo é o par `probe_id` + `anchor_id`: uma sonda de origem e uma âncora de destino, em IPv4. A cada 240 segundos o RIPE Atlas publica uma execução de ping com três pacotes. A classe dessa execução sai de uma regra fixa. O Random Forest recebe 21 variáveis dessa medição e devolve `OK`, `RISCO` ou `FALHA` para a execução seguinte.

```text
sonda (probe) ──ping IPv4, 3 pacotes, a cada 240 s──► âncora (anchor)
                              │
                              ▼
                    regra fixa → classe atual
                              │
                    21 variáveis da medição atual
                              │
                              ▼
                    Random Forest rf_v1.0.0
                              │
                              ▼
                    classe prevista da próxima medição
```

A classe atual entra no log e fica fora do vetor de entrada. O rótulo real da próxima medição só aparece depois e não participa do cálculo das variáveis.

## Como a classe é definida

A regra olha a medição nesta ordem. A primeira condição verdadeira encerra a classificação. Os percentis são do próprio fluxo, calculados no período de baseline.

| Ordem | Condição | Classe |
| ---: | --- | --- |
| 1 | Perda de pelo menos 2 dos 3 pacotes | **FALHA** |
| 2 | Latência acima do P99 de RTT do fluxo | **FALHA** |
| 3 | Perda de 1 dos 3 pacotes | **RISCO** |
| 4 | Latência acima do P95 de RTT do fluxo | **RISCO** |
| 5 | Jitter acima do P95 de jitter do fluxo | **RISCO** |
| 6 | Nenhuma das condições acima | **OK** |

| Classe | Leitura |
| --- | --- |
| **OK** | Sem sinais relevantes de degradação nesta execução. |
| **RISCO** | A comunicação existe, mas há instabilidade ou degradação. |
| **FALHA** | Indisponibilidade ou degradação severa nesta execução. |

Com perda de 100% o RTT fica vazio e a classe sai pela perda, sem comparar latência.

## O que entra no modelo

Versão vigente: `rf_v1.0.0`. Família: Random Forest, 200 árvores, profundidade livre, folha mínima de 5 amostras, `max_features=sqrt`, sem peso de classe. Não há scaler: o pré-processamento do artefato é a identidade.

| Grupo | O que descreve | Quantidade |
| --- | --- | ---: |
| Instantânea | Perda, RTT ausente, razões em relação ao P95/P99, amplitude, TTL | 8 |
| Janela | Médias e máximos nas últimas 3, 6 e 12 medições | 12 |
| Dinâmica | Perdas consecutivas | 1 |

A lista completa, os hashes e as métricas copiadas estão em [`producao/modelo/MODEL_CARD.md`](producao/modelo/MODEL_CARD.md).

## Resultados do teste

O conjunto de teste tem **46.105** medições e não foi usado para escolher o modelo. Fonte: [`pipeline/08_treino/data/avaliacao_teste.json`](pipeline/08_treino/data/avaliacao_teste.json).

| Indicador | Modelo | Persistência | Diferença |
| --- | ---: | ---: | ---: |
| Macro-F1 geral | **0,755** | 0,711 | +0,044 |
| Macro-F1 sem a âncora dominante `2026` | **0,750** | 0,712 | +0,038 |
| Recall de FALHA (geral) | **0,695** | 0,681 | +0,015 |
| Recall no início de FALHA | **0,146** | 0,000 | +0,146 |

A validação, usada para escolher o modelo, ficou em macro-F1 **0,767** (46.490 linhas). O teste gravado é **0,755**. [`painel-preditor.html`](painel-preditor.html) mostra uma cópia desses números. Abrir a página não relê o JSON, não recalcula o teste e não retreina o modelo.

A persistência repete a classe atual como previsão da próxima. Ela acerta quando a rede permanece no mesmo estado e erra toda transição. Por isso o ganho do modelo aparece sobretudo quando a classe muda: no início de uma FALHA a persistência tem recall zero, e o modelo antecipa **14,6%** desses inícios (66 de 452).

Matriz do teste, linhas = classe real, colunas = classe prevista:

| Real \ prevista | OK | RISCO | FALHA | Suporte |
| --- | ---: | ---: | ---: | ---: |
| OK | 39.866 | 252 | 132 | 40.250 |
| RISCO | 2.323 | 1.945 | 172 | 4.440 |
| FALHA | 263 | 168 | 984 | 1.415 |

Acurácia geral: **0,928**. A classe OK domina o conjunto, então a acurácia sozinha superestima o desempenho. O macro-F1 trata as três classes com o mesmo peso.

## As nove etapas

O índice visual fica em [`index.html`](index.html). A etapa 9 abre [`painel-preditor.html`](painel-preditor.html), e essa página volta ao índice. As etapas 1 a 8 já estão gravadas. A seção **Monitorar** lê a API local. Ela escolhe um dos cinco pares, acompanha a malha pública e pede a classe seguinte ao modelo já treinado.

```text
1  Âncoras        30 destinos IPv4, um no Brasil e 29 em países distintos
2  Medições       63 pings IPv4 em andamento com essas âncoras
3  Sondas         150 vínculos de origem
4  Fluxos         51.501 linhas de ping origem → destino
5  Períodos       A = baseline de TTL; B = dataset (358.222 linhas)
6  Baseline       137 fluxos com baseline válido
7  Rotulagem      343.172 linhas rotuladas; 333.954 no dataset final
8  Treino         Random Forest rf_v1.0.0
9  Monitoramento  página de avaliação e leitura ao vivo da malha pública
```

| Período | Janela (UTC) | Papel |
| --- | --- | --- |
| A | 2026-09-21 18:00 → 2026-09-28 18:00 | Mediana de TTL e percentis. Nenhuma linha entra no treino. |
| B | 2026-09-28 18:00 → 2026-10-05 18:00 | Linhas do dataset. Intervalo de 240 s. |

A janela é fechada à direita: o fim de A é o início de B, sem sobreposição.

## Como abrir a página

A avaliação gravada abre em [`index.html`](index.html), pela etapa 9, ou direto em [`painel-preditor.html`](painel-preditor.html). O monitoramento ao vivo precisa da API. Há um só processo: a FastAPI. A pasta `9_monitoramento_dash` guarda esse serviço. Use o Python 3.11 do sistema. O ambiente em `producao/venv` não inclui uvicorn.

```powershell
Set-Location 9_monitoramento_dash
$env:PYTHONIOENCODING = "utf-8"
python -m uvicorn api:app --app-dir src --host 127.0.0.1 --port 8001
```

A API lê o modelo e a medição pública. Não cria medição.

| Endereço | O que mostra |
| --- | --- |
| `index.html` | Índice. A etapa 9 abre `painel-preditor.html`. |
| `painel-preditor.html` | Avaliação gravada e Monitorar. |
| http://127.0.0.1:8001/painel-preditor.html | A mesma página, servida pela API. |
| http://127.0.0.1:8001/index.html | O índice, servido pela API. Os cartões das etapas 1 a 8 abrem as páginas do pipeline nesse mesmo endereço. |
| http://127.0.0.1:8001/saude | Estado da API. |
| http://127.0.0.1:8001/docs | Documentação interativa. |

A raiz http://127.0.0.1:8001 responde 404. A porta 8000 pertence a outro programa e não deve ser encerrada.

Na página, a avaliação gravada mostra validação e teste já registrados. **Monitorar** acompanha um fluxo da malha pública, que publica cerca de uma vez a cada 240 s; o primeiro ping pode demorar até esse intervalo. **Começar monitoramento** não cria medição.

A chave, se existir, fica só na variável de ambiente `RIPE_ATLAS_API_KEY`. Ela não entra no código, no HTML nem no JSON da sessão. O coletor que abre medição nova só roda com a confirmação explícita `--confirmar-creditos`.

## Verificação

Na raiz do repositório:

```powershell
powershell -File 9_monitoramento_dash\rodar_verificar.ps1
```

O script não aceita argumentos. Qualquer argumento extra, inclusive `--confirmar-creditos`, termina sem chamar a suíte. A suíte usa o split de validação e recusa filtrar o split de teste para produzir métrica nova.

## Estrutura

```text
pipeline/                  pesquisa, da escolha das âncoras ao treino
  01_anchors/ … 08_treino/ uma pasta por etapa, com src/, data/ e template/
9_monitoramento_dash/      API do monitoramento ao vivo
  src/api.py               FastAPI em 127.0.0.1:8001
  src/stream_publico.py    leitura da malha pública, sem criar medição
  src/coletor.py           coleta nova, só com confirmação explícita de crédito
  rodar_verificar.ps1      suíte da etapa 9, sem argumentos
producao/                  artefato empacotado, só leitura, sem retreino
  modelo/                  joblib, manifesto e ficha do modelo
  src/                     carga, inferência e empacote
index.html                 índice das nove etapas
painel-preditor.html       avaliação gravada e Monitorar
```

## Dependências

A etapa 1 usa só a biblioteca padrão. A API, o pipeline e o lote em `producao/` usam o mesmo [`requirements.txt`](requirements.txt).

```powershell
python -m pip install -r requirements.txt
```

Versões usadas nesta máquina: Python 3.11, scikit-learn 1.5.1, pandas 2.2.2, numpy 2.2.6, joblib 1.4.2, FastAPI 0.123.0, uvicorn 0.41.0, PyYAML 6.0.3, pytest 9.0.2 e pyarrow 23.0.1.

Os resultados das etapas 1 a 8 já estão gravados. Rodar de novo os scripts em `pipeline/*/src/` consulta a API pública ou refaz o dataset. Isso não é necessário para abrir a página.

## O que fica fora do Git

| Item | Motivo |
| --- | --- |
| `*.joblib`, exceto `pipeline/08_treino/data/modelos/modelo_escolhido.joblib` | A cópia solta tem cerca de 297 MB e o GitHub recusa arquivo acima de 100 MB. O arquivo do monitoramento entra compactado, com cerca de 67 MB. |
| `**/cache/` | Respostas da API com endereço de sonda. |
| `**/fluxo_bruto.csv` | Medição bruta com IP de sonda e de âncora; o arquivo tem cerca de 129 MB. |
| `producao/venv/`, `.venv/` | Ambiente local. |
| logs e `sessao_stream.json` | Sessão ao vivo, fora do dataset. |

O monitoramento usa `pipeline/08_treino/data/modelos/modelo_escolhido.joblib`. Esse arquivo vai no repositório, compactado. É a mesma floresta: com uma thread, a classe e a probabilidade de uma linha de validação batem com o arquivo original. O hash desse arquivo está em [`producao/modelo/manifesto.json`](producao/modelo/manifesto.json). A cópia de 297 MB em `producao/modelo/` continua só na máquina local.

## Limitações

- O horizonte é uma medição à frente, cerca de 4 minutos. O modelo não prevê vários intervalos.
- No início de uma FALHA o recall de teste é 14,6%. A maior parte das falhas novas ainda passa despercebida.
- A classe RISCO é a mais difícil no conjunto geral: recall 0,438 no teste.
- A âncora `2026` concentra 16,8% das falhas do teste. Sem ela o macro-F1 permanece em 0,750, acima da persistência, mas o resultado continua ligado à composição dos fluxos observados.
- Parte dos dados brutos está em `cache/`, fora do versionamento. Reproduzir a coleta depende da API pública e desses arquivos locais.
- O teste não deve ser usado para novos ajustes. Ajustar de novo exige outro conjunto de teste ou uma nova janela de dados.

## Licença dos dados

As medições vêm da API do RIPE Atlas e seguem os [RIPE Atlas Service Terms and Conditions](https://www.ripe.net/about-us/legal/ripe-atlas-service-terms-and-conditions/). O RIPE NCC publica esses dados no site e na API. O uso para pesquisa é permitido. Uso comercial depende de autorização prévia do RIPE NCC. A fonte deste trabalho é [RIPE Atlas](https://atlas.ripe.net).

O código da sonda de software do RIPE Atlas é distribuído sob GNU GPL v3. Essa licença cobre a sonda, não os dados nem este repositório.

## Autoria

**Andréa Ono Sakai**
