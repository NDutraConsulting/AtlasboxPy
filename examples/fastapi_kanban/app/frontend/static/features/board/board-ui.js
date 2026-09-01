// "board" feature — pure DOM rendering for the board detail page. Never
// calls fetch() (that's board-api.js's job); only takes data in and hands
// events back out via the `handlers` callbacks the controller passes in.

export function renderBoard(container, titleEl, board, handlers) {
  titleEl.textContent = board.name;
  container.innerHTML = "";
  board.columns.forEach((column, index) => {
    container.appendChild(renderColumn(column, index, board.columns.length, handlers));
  });
}

function renderColumn(column, index, columnCount, handlers) {
  const el = document.createElement("section");
  el.className = "column";
  el.dataset.columnId = column.id;

  const header = document.createElement("div");
  header.className = "column-header";

  const title = document.createElement("h2");
  title.textContent = `${column.name} (${column.cards.length})`;
  header.appendChild(title);

  const deleteBtn = document.createElement("button");
  deleteBtn.className = "column-delete";
  deleteBtn.textContent = "✕";
  deleteBtn.title = "Delete column";
  deleteBtn.addEventListener("click", () => handlers.onDeleteColumn(column.id));
  header.appendChild(deleteBtn);

  el.appendChild(header);

  const cardList = document.createElement("div");
  cardList.className = "card-list";
  for (const card of column.cards) {
    cardList.appendChild(renderCard(card, index, columnCount, handlers));
  }
  el.appendChild(cardList);

  const addBtn = document.createElement("button");
  addBtn.className = "add-card-btn";
  addBtn.textContent = "+ Add card";
  addBtn.addEventListener("click", () => handlers.onAddCard(column.id));
  el.appendChild(addBtn);

  return el;
}

function renderCard(card, columnIndex, columnCount, handlers) {
  const el = document.createElement("article");
  el.className = "card";
  el.dataset.cardId = card.id;

  const title = document.createElement("h3");
  title.textContent = card.title;
  el.appendChild(title);

  if (card.description) {
    const desc = document.createElement("p");
    desc.textContent = card.description;
    el.appendChild(desc);
  }

  const controls = document.createElement("div");
  controls.className = "card-controls";

  const prevBtn = document.createElement("button");
  prevBtn.textContent = "◀";
  prevBtn.title = "Move to previous column";
  prevBtn.disabled = columnIndex === 0;
  prevBtn.addEventListener("click", () => handlers.onMove(card, -1));
  controls.appendChild(prevBtn);

  const editBtn = document.createElement("button");
  editBtn.textContent = "Edit";
  editBtn.addEventListener("click", () => handlers.onEdit(card));
  controls.appendChild(editBtn);

  const deleteBtn = document.createElement("button");
  deleteBtn.textContent = "Delete";
  deleteBtn.addEventListener("click", () => handlers.onDeleteCard(card.id));
  controls.appendChild(deleteBtn);

  const nextBtn = document.createElement("button");
  nextBtn.textContent = "▶";
  nextBtn.title = "Move to next column";
  nextBtn.disabled = columnIndex === columnCount - 1;
  nextBtn.addEventListener("click", () => handlers.onMove(card, 1));
  controls.appendChild(nextBtn);

  el.appendChild(controls);
  return el;
}

export function renderError(el, message) {
  el.textContent = message || "";
  el.hidden = !message;
}

export function openCardDialog(dialog, form, { title = "", description = "" } = {}) {
  form.elements.title.value = title;
  form.elements.description.value = description;
  dialog.showModal();
}

export function readCardForm(form) {
  const data = new FormData(form);
  return { title: data.get("title"), description: data.get("description") };
}
