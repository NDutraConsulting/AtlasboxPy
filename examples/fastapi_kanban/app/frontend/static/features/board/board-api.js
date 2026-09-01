// "board" feature — talks to the backend for one board's columns/cards.
// Never touches the DOM (that's board-ui.js's job).

const boardId = new URLSearchParams(window.location.search).get("id");

async function handleResponse(res) {
  const body = await res.json();
  if (body.status === "error") {
    throw new Error(body.error.message);
  }
  return body.data;
}

export function getBoardId() {
  return boardId;
}

export async function fetchBoard() {
  const res = await fetch(`/api/boards/${boardId}`);
  return handleResponse(res);
}

export async function addColumn(name) {
  const res = await fetch(`/api/boards/${boardId}/columns`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  return handleResponse(res);
}

export async function deleteColumn(columnId) {
  const res = await fetch(`/api/boards/${boardId}/columns/${columnId}`, {
    method: "DELETE",
  });
  return handleResponse(res);
}

export async function createCard(columnId, title, description) {
  const res = await fetch(`/api/boards/${boardId}/cards`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ column_id: columnId, title, description }),
  });
  return handleResponse(res);
}

export async function updateCard(cardId, patch) {
  const res = await fetch(`/api/cards/${cardId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return handleResponse(res);
}

export async function moveCard(cardId, targetColumnId) {
  const res = await fetch(`/api/cards/${cardId}/move`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ column_id: targetColumnId }),
  });
  return handleResponse(res);
}

export async function deleteCard(cardId) {
  const res = await fetch(`/api/cards/${cardId}`, { method: "DELETE" });
  return handleResponse(res);
}
