// "board" feature — orchestrates board-api.js + board-ui.js. Owns the DOM
// element lookups, event wiring, and the small bit of page-level state
// (which card is currently open in the dialog); delegates network calls
// and rendering to its two sibling modules.

import * as api from "./board-api.js";
import * as ui from "./board-ui.js";

const columnsEl = document.getElementById("columns");
const titleEl = document.getElementById("board-title");
const errorEl = document.getElementById("board-error");
const addColumnForm = document.getElementById("add-column-form");
const cardDialog = document.getElementById("card-dialog");
const cardForm = document.getElementById("card-form");
const cardDialogTitle = document.getElementById("card-dialog-title");

let currentBoard = null;
let pendingCard = null; // { mode: "create", columnId } | { mode: "edit", card }

async function refresh() {
  try {
    currentBoard = await api.fetchBoard();
    ui.renderBoard(columnsEl, titleEl, currentBoard, {
      onDeleteColumn: handleDeleteColumn,
      onAddCard: handleAddCardRequest,
      onEdit: handleEditCardRequest,
      onDeleteCard: handleDeleteCard,
      onMove: handleMove,
    });
    ui.renderError(errorEl, "");
  } catch (err) {
    ui.renderError(errorEl, err.message);
  }
}

async function handleDeleteColumn(columnId) {
  try {
    await api.deleteColumn(columnId);
    await refresh();
  } catch (err) {
    ui.renderError(errorEl, err.message);
  }
}

function handleAddCardRequest(columnId) {
  pendingCard = { mode: "create", columnId };
  cardDialogTitle.textContent = "New card";
  ui.openCardDialog(cardDialog, cardForm);
}

function handleEditCardRequest(card) {
  pendingCard = { mode: "edit", card };
  cardDialogTitle.textContent = "Edit card";
  ui.openCardDialog(cardDialog, cardForm, card);
}

async function handleDeleteCard(cardId) {
  try {
    await api.deleteCard(cardId);
    await refresh();
  } catch (err) {
    ui.renderError(errorEl, err.message);
  }
}

async function handleMove(card, direction) {
  const columnIds = currentBoard.columns.map((column) => column.id);
  const targetId = columnIds[columnIds.indexOf(card.column_id) + direction];
  if (!targetId) return;
  try {
    await api.moveCard(card.id, targetId);
    await refresh();
  } catch (err) {
    ui.renderError(errorEl, err.message);
  }
}

addColumnForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = new FormData(addColumnForm).get("name");
  try {
    await api.addColumn(name);
    addColumnForm.reset();
    await refresh();
  } catch (err) {
    ui.renderError(errorEl, err.message);
  }
});

cardForm.addEventListener("submit", async () => {
  const { title, description } = ui.readCardForm(cardForm);
  try {
    if (pendingCard.mode === "create") {
      await api.createCard(pendingCard.columnId, title, description);
    } else {
      await api.updateCard(pendingCard.card.id, { title, description });
    }
    pendingCard = null;
    await refresh();
  } catch (err) {
    ui.renderError(errorEl, err.message);
  }
});

if (!api.getBoardId()) {
  ui.renderError(errorEl, "No board id in the URL — go back and open a board.");
} else {
  refresh();
}
