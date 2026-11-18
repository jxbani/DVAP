"""Mock CMMS (maintenance ticket system). Simulated lab service.

DVAP-VULN: C01 - there is no authentication anywhere in this API. Any lab participant can
create, edit and comment on tickets, and the operator agent later reads that text as if it
came from plant staff. Published to the host on 127.0.0.1:8081 only.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from cmms.seed import seed
from cmms.store import TicketStore

Priority = Literal["low", "medium", "high", "critical"]
Status = Literal["open", "in_progress", "closed"]
# Size limits only: the content itself is deliberately not checked or sanitised (C01).
Short = Annotated[str, Field(max_length=200)]
Long = Annotated[str, Field(max_length=20_000)]


class TicketIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(min_length=1, max_length=200)]
    asset: Short = ""
    priority: Priority = "medium"
    status: Status = "open"
    description: Long = ""
    technician_notes: Long = ""
    attachments: Long = ""  # text only
    created_by: Short = "anonymous"


class TicketPatch(BaseModel):
    """Any subset of the ticket fields."""

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    asset: Short | None = None
    priority: Priority | None = None
    status: Status | None = None
    description: Long | None = None
    technician_notes: Long | None = None
    attachments: Long | None = None
    created_by: Short | None = None


class Comment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    author: Short = "anonymous"  # free text, not verified (C01)
    text: Annotated[str, Field(min_length=1, max_length=5000)]


# Replaced in the lifespan (and by tests).
store = TicketStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global store
    store = TicketStore(os.environ.get("CMMS_DB", "/data/cmms.sqlite"))
    seed(store)
    yield


app = FastAPI(title="DVAP CMMS", lifespan=lifespan)


def _existing(ticket_id: int) -> dict:
    ticket = store.get(ticket_id)
    if ticket is None:
        raise HTTPException(404, f"no ticket {ticket_id}")
    return ticket


@app.get("/")
def form() -> FileResponse:
    return FileResponse(Path(__file__).with_name("static") / "index.html")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/reset")
async def reset() -> dict:
    """Wipe all tickets and restore the benign seed set (used by a challenge reset)."""
    store.clear()
    seed(store)
    return {"ok": True, "tickets": store.count()}


@app.get("/tickets")
async def list_tickets(status: Status | None = None, asset: str | None = None) -> list[dict]:
    return store.list(status, asset)


@app.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: int) -> dict:
    return _existing(ticket_id)


# DVAP-VULN: C01 - the three write endpoints below take no credentials at all.
@app.post("/tickets", status_code=201)
async def create_ticket(ticket: TicketIn) -> dict:
    return store.create(**ticket.model_dump())


@app.patch("/tickets/{ticket_id}")
async def edit_ticket(ticket_id: int, patch: TicketPatch) -> dict | None:
    _existing(ticket_id)
    return store.update(ticket_id, **patch.model_dump(exclude_none=True))


@app.post("/tickets/{ticket_id}/comments", status_code=201)
async def comment(ticket_id: int, comment: Comment) -> dict | None:
    """Append a line to the ticket's technician notes."""
    notes = _existing(ticket_id)["technician_notes"]
    line = f"[{comment.author}] {comment.text}"
    return store.update(ticket_id, technician_notes=f"{notes}\n{line}" if notes else line)


@app.delete("/tickets/{ticket_id}", status_code=204)
async def delete_ticket(ticket_id: int) -> None:
    if not store.delete(ticket_id):
        raise HTTPException(404, f"no ticket {ticket_id}")
