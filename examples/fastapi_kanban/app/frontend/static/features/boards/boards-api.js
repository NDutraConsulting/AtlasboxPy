// "boards" feature — talks to the backend, returns plain data or throws.
// Never touches the DOM (that's boards-ui.js's job).

const BASE_URL = "/api/boards";

async function handleResponse(res) {
  const body = await res.json();
  if (body.status === "error") {
    throw new Error(body.error.message);
  }
  return body.data;
}

export async function fetchBoards() {
  const res = await fetch(BASE_URL);
  return handleResponse(res);
}

export async function createBoard(name) {
  const res = await fetch(BASE_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  return handleResponse(res);
}

export async function deleteBoard(boardId) {
  const res = await fetch(`${BASE_URL}/${boardId}`, { method: "DELETE" });
  return handleResponse(res);
}
