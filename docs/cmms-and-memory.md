# cmms and the agent memory store

## cmms

Mock maintenance ticket system: FastAPI + SQLite (`/data/cmms.sqlite`, a docker volume). It is
the lab's main **untrusted text source**. Reachable inside the lab as `http://cmms:8000` and
from the host as a small web form at **http://127.0.0.1:8081** (loopback only).

A fresh database is seeded with 10 ordinary, benign tickets (`cmms/seed.py`). `make reset`
clears the volume and re-seeds.

### Ticket fields

`id`, `title`, `asset`, `priority` (`low` | `medium` | `high` | `critical`), `status`
(`open` | `in_progress` | `closed`), `description`, `technician_notes`, `attachments`
(text only), `created_by`, plus `created_at` / `updated_at` (epoch seconds).

### API

| Endpoint | Purpose |
|---|---|
| `GET /` | web form: create a ticket, list all tickets |
| `GET /health` | health check |
| `GET /tickets?status=&asset=` | list tickets |
| `GET /tickets/{id}` | one ticket |
| `POST /tickets` | create (only `title` is required) |
| `PATCH /tickets/{id}` | edit any subset of fields |
| `POST /tickets/{id}/comments` | `{"author", "text"}`, appended to `technician_notes` as `[author] text` |
| `DELETE /tickets/{id}` | delete |

**DVAP-VULN: C01** — none of this is authenticated. `created_by` and the comment `author`
are free text, and any participant can rewrite any ticket. Inputs are size-limited but
otherwise stored verbatim. The web form only ever displays ticket text as text.

```bash
curl -X POST http://127.0.0.1:8081/tickets -H "Content-Type: application/json" -d '{"title": "Check valve V-101", "asset": "V-101", "created_by": "you"}'
```

## Agent memory store

`services/agent-operator/agent_operator/memory.py`. The operator agent's long-term
"operator notes", persisted in SQLite. The agent itself is not built yet; this is the store
it will use.

Each note has `key`, `content`, `source` and `created_at`.

```python
from agent_operator.memory import MemoryStore

memory = MemoryStore("/data/memory.sqlite")
memory.write("valve-v101-slow", "V-101 needs 8 s to travel.", source="ticket:2")
memory.search("how fast is the valve?")   # best match first, each with a BM25 `score`
memory.read("valve-v101-slow"); memory.all(); memory.delete("valve-v101-slow")
```

- **Retrieval** is keyword search ranked by BM25, using SQLite's built-in FTS5 index over
  `key` and `content`. A note matches if it shares *any* word with the query, so long
  questions return loosely related notes too, ranked lower. There is no vector database.
- **Writes** replace any existing note with the same key.
- **DVAP-VULN: C06** — there are no provenance checks. `source` is just a label supplied by
  the caller, so a note "learned" from an attacker's ticket looks the same as one from a
  trusted operator, can overwrite one, and keeps influencing the agent in later sessions.
