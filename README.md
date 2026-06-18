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

## Pré-requisitos

- Python 3.10 ou superior
- Node.js 20+ e npm
- Cadastro mestre de clientes: `TESTE.xlsx` na raiz do projeto (não vai para o Git — dados sensíveis)

## Instalação

### Backend

```powershell
cd logistica
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Frontend

```powershell
cd route-genius-main
npm install
```

## Executar (desenvolvimento)

Terminal 1 — API:

```powershell
cd logistica
.venv\Scripts\Activate.ps1
uvicorn api.main:app --reload --port 8000
```

Terminal 2 — Frontend:

```powershell
cd route-genius-main
npm run dev
```

Acesse: http://localhost:5173

O Vite faz proxy de `/api` → `http://127.0.0.1:8000`.

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

## Publicar no GitHub

```powershell
git init
git add .
git commit -m "feat: MVP logística Superfine — ingestão, quarentena, roteirização e romaneio"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/logistica.git
git push -u origin main
```

Substitua `SEU_USUARIO/logistica` pelo repositório criado no GitHub.
