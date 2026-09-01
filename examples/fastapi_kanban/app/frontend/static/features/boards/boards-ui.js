// "boards" feature — pure DOM rendering. Never calls fetch() (that's
// boards-api.js's job); only takes data in and hands events back out via
// the `handlers` callbacks the controller passes in.

export function renderBoardList(container, boards, handlers) {
  container.innerHTML = "";
  if (boards.length === 0) {
    const empty = document.createElement("li");
    empty.className = "board-empty";
    empty.textContent = "No boards yet — create one above.";
    container.appendChild(empty);
    return;
  }
  for (const board of boards) {
    container.appendChild(renderBoardCard(board, handlers));
  }
}

function renderBoardCard(board, handlers) {
  const li = document.createElement("li");
  li.className = "board-card";

  const title = document.createElement("h2");
  title.textContent = board.name;
  li.appendChild(title);

  const meta = document.createElement("p");
  meta.className = "board-meta";
  meta.textContent = `${board.column_count} columns · ${board.card_count} cards`;
  li.appendChild(meta);

  const actions = document.createElement("div");
  actions.className = "board-card-actions";

  const openBtn = document.createElement("button");
  openBtn.className = "open-btn";
  openBtn.textContent = "Open";
  openBtn.addEventListener("click", () => handlers.onOpen(board.id));
  actions.appendChild(openBtn);

  const deleteBtn = document.createElement("button");
  deleteBtn.className = "delete-btn";
  deleteBtn.textContent = "Delete";
  deleteBtn.addEventListener("click", () => handlers.onDelete(board.id));
  actions.appendChild(deleteBtn);

  li.appendChild(actions);
  return li;
}

export function renderError(el, message) {
  el.textContent = message || "";
  el.hidden = !message;
}

export function resetForm(form) {
  form.reset();
}
