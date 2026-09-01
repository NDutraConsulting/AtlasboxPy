// "boards" feature — orchestrates boards-api.js + boards-ui.js. Owns the
// DOM element lookups and event wiring for this page; delegates actual
// network calls and rendering to its two sibling modules.

import * as api from "./boards-api.js";
import * as ui from "./boards-ui.js";

const listEl = document.getElementById("board-list");
const formEl = document.getElementById("create-board-form");
const errorEl = document.getElementById("boards-error");

async function loadBoards() {
  try {
    const boards = await api.fetchBoards();
    ui.renderBoardList(listEl, boards, { onOpen: openBoard, onDelete: removeBoard });
    ui.renderError(errorEl, "");
  } catch (err) {
    ui.renderError(errorEl, err.message);
  }
}

function openBoard(boardId) {
  window.location.href = `/board.html?id=${encodeURIComponent(boardId)}`;
}

async function removeBoard(boardId) {
  try {
    await api.deleteBoard(boardId);
    await loadBoards();
  } catch (err) {
    ui.renderError(errorEl, err.message);
  }
}

formEl.addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = new FormData(formEl).get("name");
  try {
    await api.createBoard(name);
    ui.resetForm(formEl);
    await loadBoards();
  } catch (err) {
    ui.renderError(errorEl, err.message);
  }
});

loadBoards();
