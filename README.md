# Agentic SQL Data Analyst

A **Text-to-Action** AI agent that converts natural language questions into SQL queries, executes them against a live database, and automatically generates visual reports — all in a multi-turn conversational interface.

Built with **FastAPI**, **Claude (Anthropic)**, **SQLite**, and **Matplotlib**.

---

## Project aims

This project demonstrates three ideas that matter in modern AI engineering:

**1. Agentic tool use** — rather than a single prompt-response, the system runs an autonomous loop where Claude decides which tools to call, in what order, and how many times, before returning a final answer. This is the architecture behind production AI assistants.

**2. Text-to-SQL with self-correction** — the agent first inspects the live database schema, then writes a query tailored to the actual table and column names. It can catch errors and retry, rather than hallucinating column names.

**3. Multi-turn memory** — conversation history is maintained per session, so follow-up questions like *"now break that down by region"* work without repeating context. The agent remembers what it queried before.

---

## Demo

```
User  → "What are the top 5 products by total revenue?"
Agent → calls get_schema()
      → calls run_sql("SELECT p.name, SUM(oi.quantity * oi.unit_price) ...")
      → returns ranked table + plain-English summary

User  → "Show that as a bar chart"
Agent → calls render_chart(...) using the prior query's results
      → returns base64 PNG embedded in the UI
```

---

## Architecture

```
Browser / curl
      │
      ▼
FastAPI  (main.py)
  ├─ POST /chat     ← main endpoint
  ├─ POST /reset    ← clear session
  ├─ GET  /schema   ← live DB schema for the UI sidebar
  └─ GET  /health

      │  session history + user message
      ▼
Agentic loop  (agent.py)
  ┌─────────────────────────────────────────────┐
  │  while stop_reason != "end_turn":           │
  │    response = claude(history, tools)        │
  │    if tool_use → dispatch → append result  │
  └─────────────────────────────────────────────┘
      │
      ├─ get_schema    →  tools/schema.py   (PRAGMA table_info)
      ├─ run_sql       →  tools/executor.py (read-only SQLite)
      └─ render_chart  →  tools/charter.py  (Matplotlib → base64 PNG)

      │
      ▼
SQLite  (db/sales.db)
  ├─ regions      (5 rows)
  ├─ customers    (200 rows)
  ├─ products     (15 rows)
  ├─ orders       (1 200 rows)
  └─ order_items  (~3 500 rows)
```

---

## Project structure

```
sql-analyst/
├── main.py               # FastAPI app — endpoints, session store, lifespan
├── agent.py              # Agentic loop: Claude ↔ tool dispatch ↔ history
│
├── tools/
│   ├── __init__.py
│   ├── schema.py         # Introspect DB tables and column types
│   ├── executor.py       # Safe SELECT-only SQL runner (two-layer guard)
│   └── charter.py        # Matplotlib chart renderer → base64 PNG
│
├── db/
│   ├── __init__.py
│   ├── seed.py           # Generate and populate sales.db
│   └── sales.db          # SQLite database (auto-created on first run)
│
├── frontend/
│   └── index.html        # Single-file chat UI (vanilla JS, no build step)
│
├── requirements.txt
└── README.md
```

---

## Quickstart

### 1. Clone and install

```bash
git clone https://github.com/your-username/sql-analyst.git
cd sql-analyst
pip install -r requirements.txt
```

### 2. Set your API key

```bash
# macOS / Linux
export ANTHROPIC_API_KEY=sk-ant-...

# Windows (PowerShell)
$env:ANTHROPIC_API_KEY="sk-ant-..."
```

### 3. Run

```bash
uvicorn main:app --reload
```

On first start the server seeds `db/sales.db` automatically. Open `http://localhost:8000` to use the chat UI.

> To reset the database at any time:
> ```bash
> python db/seed.py --force
> ```

---

## API reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/chat`   | Send a message; returns text, SQL, chart, tool trace |
| `POST` | `/reset`  | Clear conversation history for a session |
| `GET`  | `/schema` | Return live DB schema (tables + columns + row counts) |
| `GET`  | `/health` | Liveness check |

**`POST /chat` request body**

```json
{
  "message": "Top 5 products by revenue",
  "session_id": "optional-uuid-for-multi-turn"
}
```

**`POST /chat` response**

```json
{
  "session_id": "uuid",
  "text": "The top 5 products by revenue are...",
  "sql_used": "SELECT p.name, SUM(...) FROM ...",
  "chart_b64": "iVBORw0KGgo...",
  "tool_calls": [
    {"tool": "get_schema", "input": {}},
    {"tool": "run_sql",    "input": {"query": "SELECT ..."}}
  ],
  "turn": 2
}
```

---

## Dataset

The seed script generates a reproducible fictional sales dataset (`random.seed(42)`):

| Table | Rows | Description |
|-------|------|-------------|
| `regions` | 5 | North America, Europe, APAC, LatAm, Middle East |
| `customers` | 200 | Name, email, region, join date |
| `products` | 15 | Electronics, Furniture, Stationery, Training |
| `orders` | 1 200 | Customer, date, status (completed / pending / cancelled) |
| `order_items` | ~3 500 | Order lines with quantity and sale price |

---

## Key engineering decisions

**Two-layer SQL safety** — `executor.py` rejects non-SELECT statements with a regex blocklist, then opens the SQLite connection in URI read-only mode (`?mode=ro`). Even a prompt-injection attack cannot write to the database.

**In-place history mutation** — `agent.py` receives the session's history list by reference and appends to it directly. The FastAPI session store owns the list; no serialisation overhead on each turn.

**Dynamic chart sizing** — `charter.py` scales figure width proportionally to the number of x-axis values so bar charts never look cramped regardless of result set size.

**Session eviction** — the in-memory session store caps at 500 sessions (LRU eviction) and 40 turns per session to bound memory usage without a Redis dependency.

---

## Example questions to try

- `Top 5 products by total revenue`
- `Monthly sales trend for 2024 — line chart`
- `Revenue breakdown by region — pie chart`
- `Which customers placed the most orders?`
- `Compare completed vs cancelled orders by month`
- `Average order value by product category`
- `How many new customers joined each quarter?`

---

## Requirements

- Python 3.11+
- Anthropic API key ([get one here](https://console.anthropic.com))

```
fastapi==0.115.6
uvicorn[standard]==0.32.1
anthropic==0.40.0
matplotlib==3.9.4
pydantic==2.10.4
```

---

## Possible extensions

- **Postgres support** — swap `sqlite3` for `asyncpg` and update `DB_PATH` to a connection string
- **Redis sessions** — replace the in-memory dict with Redis for multi-worker deployments
- **Auth** — add an API key header check in a FastAPI dependency
- **Streaming responses** — use `anthropic.stream()` and FastAPI `StreamingResponse` to stream Claude's answer token-by-token
- **CSV export** — add a `GET /export/{session_id}` endpoint that returns the last query result as a CSV

---

## License

MIT
