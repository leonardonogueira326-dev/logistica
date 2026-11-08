# Superfine Logística

Sistema de ingestão, quarentena (validação), roteirização e exportação de romaneio para operação logística diária.

## Stack

| Camada | Tecnologia |
|--------|------------|
| Backend | Python 3.10+, FastAPI, pdfplumber, openpyxl |
| Frontend | React, TanStack Router/Query, Vite, shadcn/ui |
| Alternativo | Streamlit (`app_streamlit.py`) |

## Estrutura

```
logistica/
├── api/                    # FastAPI (sessões, ingestão, roteirização, romaneio)
├── data/
│   ├── aprendizado_regras.json   # Memória heurística (regras do operador)
│   └── sessions/                 # Sessões UUID (gerado em runtime — não versionar)
├── route-genius-main/      # Frontend React
├── motor_ingestao.py       # PDF + XLSB + MSG → consolidados
├── motor_logistica.py      # Alocação de frota e Kanban
├── gerador_romaneio.py     # Export Excel por veículo
└── requirements.txt
```

## Como rodar (Windows)

Pré-requisitos (uma vez só): [Python 3.10+](https://www.python.org/downloads/) (marque *Add python.exe to PATH*), [Node.js 20+](https://nodejs.org/) e, opcional para a IA, [Ollama](https://ollama.com).

1. **Instalar:** dois cliques em `instalar.bat` (cria o `.venv`, instala as dependências e baixa o modelo de IA).
2. **Usar:** dois cliques em `iniciar.bat`. Abrem duas janelas (API e Tela) — não feche — e o navegador em http://localhost:5173.
3. **Testar:** `rodar_testes.bat`. Para incluir os PDFs reais nos testes, copie-os para `dados_teste\`.

Arquivos que ficam só no PC (o `.gitignore` bloqueia — são dados da empresa):
`base-de-clientes.xlsx`, `base-transportadoras.xlsx`, PDFs, XLSB, MSG, `ROTA DIARIA*.xlsx`, `data/cadastro_mestre_geolocalizado.json`, `data/sessions/`.

### Rodar manualmente (sem os .bat)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt pytest
uvicorn api.main:app --reload --port 8000          # terminal 1
cd route-genius-main; npm install; npm run dev     # terminal 2
```

O Vite faz proxy de `/api` → `http://127.0.0.1:8000`.

### IA local

A IA **ajuda, não decide**: só é consultada quando regras aprendidas, memória e regex não resolvem, e a sugestão sempre passa pela conferência. Sem Ollama o sistema funciona normalmente.
Modelo padrão: `qwen2.5:3b` (troque em `iniciar.bat` via `LOGISTICA_OLLAMA_MODEL`).

## Testes e catálogo de pegadinhas

`tests/test_pegadinhas.py` é o catálogo das armadilhas das observações comerciais
(pagamento antecipado, "não faturar antes da data", "não enviar parcial", NF no fim do mês…).
**Achou uma pegadinha nova? Adicione a frase e o resultado esperado ali** — vira regra testada para sempre.

## Fluxo diário

1. **Upload** — PDF de faturamento, XLSB de retenções, MSG de canhotos
2. **Ingestão** — consolidação e classificação de frete (regex + aprendizado local)
3. **Quarentena** (`/validacao`) — revisão de endereços, status de frete, regras aprendidas
4. **Roteirização** (`/roteirizar`) — Kanban por veículo, backlog e coletas
5. **Romaneio** — botão *Exportar Romaneios* → Excel `.xlsx` por caminhão

## Arquivos de configuração

- `parametros_operacionais.json` — frota, rotas, jornada
- `data/aprendizado_regras.json` — regras `codigo_palavra → status` ensinadas na quarentena

## Dados que não entram no Git

Por segurança e tamanho, **não versionamos**:

- PDFs, XLSB, MSG de produção
- `TESTE.xlsx` (cadastro de clientes)
- `data/sessions/*` (sessões de upload)

Copie esses arquivos manualmente em cada ambiente.

## API — endpoints principais

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/api/sessions/upload` | Upload de arquivos |
| POST | `/api/sessions/{id}/ingest` | Executar ingestão |
| GET | `/api/sessions/{id}/consolidados` | Listar consolidados |
| POST | `/api/sessions/{id}/validacao/confirmar` | Confirmar quarentena |
| POST | `/api/sessions/{id}/roteirizar` | Alocar frota |
| GET | `/api/sessions/{id}/exportar-romaneio` | Download Excel romaneio |

Documentação interativa: http://127.0.0.1:8000/docs
