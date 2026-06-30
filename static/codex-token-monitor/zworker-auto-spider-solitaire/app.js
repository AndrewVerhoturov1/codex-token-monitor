(() => {
  'use strict';

  const SUITS = {
    spades: { symbol: '♠', red: false },
    hearts: { symbol: '♥', red: true },
    clubs: { symbol: '♣', red: false },
    diamonds: { symbol: '♦', red: true }
  };
  const RANK_LABELS = { 1: 'A', 11: 'J', 12: 'Q', 13: 'K' };
  const STORAGE_KEY = 'spider-solitaire-v1';

  const elements = {
    tableau: document.querySelector('#tableau'),
    foundations: document.querySelector('#foundations'),
    stockButton: document.querySelector('#stockButton'),
    stockCount: document.querySelector('#stockCount'),
    stockDeals: document.querySelector('#stockDeals'),
    completedCount: document.querySelector('#completedCount'),
    movesCount: document.querySelector('#movesCount'),
    undoButton: document.querySelector('#undoButton'),
    newGameButton: document.querySelector('#newGameButton'),
    playAgainButton: document.querySelector('#playAgainButton'),
    difficulty: document.querySelector('#difficulty'),
    message: document.querySelector('#message'),
    dragLayer: document.querySelector('#dragLayer'),
    winDialog: document.querySelector('#winDialog'),
    winMoves: document.querySelector('#winMoves')
  };

  let state = null;
  let history = [];
  let selected = null;
  let drag = null;
  let messageTimer = null;

  function makeDeck(difficulty) {
    const suits = difficulty === 1
      ? ['spades']
      : difficulty === 2
        ? ['spades', 'hearts']
        : ['spades', 'hearts', 'clubs', 'diamonds'];
    const copiesPerSuit = 8 / suits.length;
    const deck = [];
    let id = 0;

    for (const suit of suits) {
      for (let copy = 0; copy < copiesPerSuit; copy += 1) {
        for (let rank = 1; rank <= 13; rank += 1) {
          deck.push({ id: `${Date.now()}-${id++}`, suit, rank, faceUp: false });
        }
      }
    }
    return shuffle(deck);
  }

  function shuffle(items) {
    const array = [...items];
    for (let index = array.length - 1; index > 0; index -= 1) {
      const randomIndex = Math.floor(Math.random() * (index + 1));
      [array[index], array[randomIndex]] = [array[randomIndex], array[index]];
    }
    return array;
  }

  function createInitialState(difficulty) {
    const deck = makeDeck(difficulty);
    const columns = Array.from({ length: 10 }, () => []);

    for (let round = 0; round < 6; round += 1) {
      for (let columnIndex = 0; columnIndex < 10; columnIndex += 1) {
        if (round === 5 && columnIndex >= 4) continue;
        const card = deck.pop();
        card.faceUp = round === 5 || (round === 4 && columnIndex >= 4);
        columns[columnIndex].push(card);
      }
    }

    return {
      difficulty,
      columns,
      stock: deck,
      completed: [],
      moves: 0,
      won: false
    };
  }

  function cloneState(source = state) {
    return JSON.parse(JSON.stringify(source));
  }

  function saveGame() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ state, history: history.slice(-80) }));
    } catch (error) {
      // Storage is optional; gameplay remains fully functional without it.
    }
  }

  function loadGame() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
      if (!saved || !saved.state || !Array.isArray(saved.state.columns) || saved.state.columns.length !== 10) return false;
      state = saved.state;
      history = Array.isArray(saved.history) ? saved.history : [];
      elements.difficulty.value = String(state.difficulty || 2);
      return true;
    } catch (error) {
      return false;
    }
  }

  function newGame(difficulty = Number(elements.difficulty.value)) {
    cancelInteraction();
    state = createInitialState(difficulty);
    history = [];
    elements.difficulty.value = String(difficulty);
    saveGame();
    render({ animateDeal: true });
    showMessage('Новая игра началась. Удачи!');
  }

  function rankLabel(rank) {
    return RANK_LABELS[rank] || String(rank);
  }

  function cardOffset(column, index) {
    let offset = 0;
    for (let i = 0; i < index; i += 1) {
      offset += column[i].faceUp ? cssNumber('--face-step', 34) : cssNumber('--back-step', 16);
    }
    return offset;
  }

  function cssNumber(property, fallback) {
    const value = parseFloat(getComputedStyle(document.documentElement).getPropertyValue(property));
    return Number.isFinite(value) ? value : fallback;
  }

  function render(options = {}) {
    if (!state) return;
    elements.tableau.innerHTML = '';

    state.columns.forEach((column, columnIndex) => {
      const pile = document.createElement('div');
      pile.className = 'pile';
      pile.dataset.column = String(columnIndex);
      pile.setAttribute('aria-label', `Столбец ${columnIndex + 1}, карт: ${column.length}`);

      column.forEach((card, cardIndex) => {
        const cardElement = createCardElement(card, columnIndex, cardIndex);
        cardElement.style.top = `${cardOffset(column, cardIndex)}px`;
        cardElement.style.zIndex = String(cardIndex + 1);
        if (options.animateDeal) {
          cardElement.classList.add('deal-animation');
          cardElement.style.animationDelay = `${Math.min(cardIndex * 15 + columnIndex * 12, 330)}ms`;
        }
        pile.appendChild(cardElement);
      });

      const height = column.length
        ? cardOffset(column, column.length - 1) + cssNumber('--card-width', 90) * 1.4
        : cssNumber('--card-width', 90) * 1.4;
      pile.style.height = `${Math.max(height, 160)}px`;
      elements.tableau.appendChild(pile);
    });

    renderFoundations();
    updateStats();
    updateSelectionUI();
  }

  function createCardElement(card, columnIndex, cardIndex, ghost = false) {
    const element = document.createElement('div');
    element.className = `card ${card.faceUp ? 'face-up' : 'face-down'}`;
    element.dataset.cardId = card.id;
    element.dataset.column = String(columnIndex);
    element.dataset.index = String(cardIndex);
    element.setAttribute('role', 'button');
    element.tabIndex = card.faceUp && !ghost ? 0 : -1;

    if (card.faceUp) {
      const suit = SUITS[card.suit];
      if (suit.red) element.classList.add('red');
      if (isMovableSequence(columnIndex, cardIndex)) element.classList.add('movable');
      element.setAttribute('aria-label', `${rankLabel(card.rank)} ${suit.symbol}`);
      element.innerHTML = `
        <span class="card-corner"><span>${rankLabel(card.rank)}</span><span class="suit">${suit.symbol}</span></span>
        <span class="card-center">${suit.symbol}</span>
      `;
    } else {
      element.setAttribute('aria-label', 'Закрытая карта');
    }
    return element;
  }

  function renderFoundations() {
    elements.foundations.innerHTML = '';
    for (let index = 0; index < 8; index += 1) {
      const slot = document.createElement('div');
      slot.className = `foundation-slot${index < state.completed.length ? ' filled' : ''}`;
      if (index < state.completed.length) {
        const completedSuit = state.completed[index];
        slot.innerHTML = `<span class="foundation-rank">K–A</span>`;
        slot.style.color = SUITS[completedSuit]?.red ? '#bb2f42' : '#222';
        slot.setAttribute('aria-label', `Собранная последовательность ${index + 1}`);
      } else {
        slot.setAttribute('aria-label', `Пустое место для последовательности ${index + 1}`);
      }
      elements.foundations.appendChild(slot);
    }
  }

  function updateStats() {
    elements.movesCount.textContent = String(state.moves);
    elements.completedCount.textContent = String(state.completed.length);
    elements.stockCount.textContent = String(state.stock.length);
    elements.stockDeals.textContent = String(Math.floor(state.stock.length / 10));
    elements.stockButton.disabled = state.stock.length === 0 || state.won;
    elements.stockButton.setAttribute('aria-label', state.stock.length
      ? `Раздать карты. Осталось раздач: ${Math.floor(state.stock.length / 10)}`
      : 'Резерв пуст');
    elements.undoButton.disabled = history.length === 0;
  }

  function isMovableSequence(columnIndex, startIndex) {
    const column = state?.columns[columnIndex];
    if (!column || !column[startIndex]?.faceUp) return false;
    for (let index = startIndex; index < column.length - 1; index += 1) {
      const current = column[index];
      const next = column[index + 1];
      if (!next.faceUp || current.suit !== next.suit || current.rank !== next.rank + 1) return false;
    }
    return true;
  }

  function canPlace(sourceColumn, sourceIndex, targetColumn) {
    if (sourceColumn === targetColumn || !isMovableSequence(sourceColumn, sourceIndex)) return false;
    const movingCard = state.columns[sourceColumn][sourceIndex];
    const destination = state.columns[targetColumn];
    if (destination.length === 0) return true;
    const targetCard = destination[destination.length - 1];
    return targetCard.faceUp && targetCard.rank === movingCard.rank + 1;
  }

  function validTargets(sourceColumn, sourceIndex) {
    return state.columns
      .map((_, targetColumn) => canPlace(sourceColumn, sourceIndex, targetColumn) ? targetColumn : -1)
      .filter(index => index >= 0);
  }

  function moveCards(sourceColumn, sourceIndex, targetColumn) {
    if (!canPlace(sourceColumn, sourceIndex, targetColumn)) return false;

    pushHistory();
    const moving = state.columns[sourceColumn].splice(sourceIndex);
    state.columns[targetColumn].push(...moving);
    revealTopCard(sourceColumn);
    state.moves += 1;
    selected = null;
    resolveCompletedRuns();
    saveGame();
    render();
    return true;
  }

  function revealTopCard(columnIndex) {
    const column = state.columns[columnIndex];
    const top = column[column.length - 1];
    if (top && !top.faceUp) top.faceUp = true;
  }

  function resolveCompletedRuns() {
    let removedAny = true;
    while (removedAny) {
      removedAny = false;
      for (let columnIndex = 0; columnIndex < state.columns.length; columnIndex += 1) {
        const column = state.columns[columnIndex];
        if (column.length < 13) continue;
        const run = column.slice(-13);
        const suit = run[0].suit;
        const complete = run.every((card, index) =>
          card.faceUp && card.suit === suit && card.rank === 13 - index
        );
        if (!complete) continue;

        column.splice(-13);
        state.completed.push(suit);
        revealTopCard(columnIndex);
        removedAny = true;
        showMessage('Последовательность K–A собрана!');
        break;
      }
    }

    if (state.completed.length === 8) {
      state.won = true;
      window.setTimeout(showWin, 360);
    }
  }

  function dealFromStock() {
    if (!state.stock.length || state.won) return;
    if (state.columns.some(column => column.length === 0)) {
      showMessage('Перед раздачей заполните все пустые столбцы.', true);
      pulseEmptyColumns();
      return;
    }

    pushHistory();
    for (let columnIndex = 0; columnIndex < 10; columnIndex += 1) {
      const card = state.stock.pop();
      card.faceUp = true;
      state.columns[columnIndex].push(card);
    }
    state.moves += 1;
    selected = null;
    resolveCompletedRuns();
    saveGame();
    render({ animateDeal: true });
  }

  function pushHistory() {
    history.push(cloneState());
    if (history.length > 100) history.shift();
  }

  function undo() {
    if (!history.length) return;
    cancelInteraction();
    state = history.pop();
    state.won = false;
    saveGame();
    render();
    showMessage('Последний ход отменён.');
  }

  function pulseEmptyColumns() {
    document.querySelectorAll('.pile').forEach((pile, index) => {
      if (state.columns[index].length === 0) {
        pile.classList.add('invalid-target');
        setTimeout(() => pile.classList.remove('invalid-target'), 700);
      }
    });
  }

  function showMessage(text, error = false) {
    clearTimeout(messageTimer);
    elements.message.textContent = text;
    elements.message.className = `message visible${error ? ' error' : ''}`;
    messageTimer = setTimeout(() => {
      elements.message.classList.remove('visible');
    }, 2500);
  }

  function showWin() {
    elements.winMoves.textContent = String(state.moves);
    if (typeof elements.winDialog.showModal === 'function') {
      elements.winDialog.showModal();
    } else {
      alert(`Пасьянс собран за ${state.moves} ходов!`);
    }
  }

  function selectSequence(columnIndex, cardIndex) {
    if (!isMovableSequence(columnIndex, cardIndex)) {
      showMessage('Можно переносить только непрерывную одно-мастную последовательность.', true);
      return;
    }
    selected = { columnIndex, cardIndex };
    updateSelectionUI();
  }

  function updateSelectionUI() {
    document.querySelectorAll('.card.selected').forEach(card => card.classList.remove('selected'));
    document.querySelectorAll('.pile.valid-target').forEach(pile => pile.classList.remove('valid-target'));
    if (!selected) return;

    const selectedCard = document.querySelector(`.card[data-column="${selected.columnIndex}"][data-index="${selected.cardIndex}"]`);
    selectedCard?.classList.add('selected');
    validTargets(selected.columnIndex, selected.cardIndex).forEach(index => {
      document.querySelector(`.pile[data-column="${index}"]`)?.classList.add('valid-target');
    });
  }

  function onTableClick(event) {
    if (drag?.moved) return;
    const pile = event.target.closest('.pile');
    const card = event.target.closest('.card');
    if (!pile) return;
    const targetColumn = Number(pile.dataset.column);

    if (selected) {
      const clickedSameCard = card
        && Number(card.dataset.column) === selected.columnIndex
        && Number(card.dataset.index) === selected.cardIndex;
      if (clickedSameCard) {
        selected = null;
        updateSelectionUI();
        return;
      }
      if (moveCards(selected.columnIndex, selected.cardIndex, targetColumn)) return;
      if (!card) {
        showMessage('Эту последовательность нельзя положить сюда.', true);
        return;
      }
    }

    if (card && card.classList.contains('face-up')) {
      selectSequence(Number(card.dataset.column), Number(card.dataset.index));
    }
  }

  function onPointerDown(event) {
    if (event.button !== 0 && event.pointerType !== 'touch') return;
    const card = event.target.closest('.card.face-up');
    if (!card) return;
    const sourceColumn = Number(card.dataset.column);
    const sourceIndex = Number(card.dataset.index);
    if (!isMovableSequence(sourceColumn, sourceIndex)) return;

    event.preventDefault();
    card.setPointerCapture?.(event.pointerId);
    drag = {
      pointerId: event.pointerId,
      sourceColumn,
      sourceIndex,
      startX: event.clientX,
      startY: event.clientY,
      offsetX: event.clientX - card.getBoundingClientRect().left,
      offsetY: event.clientY - card.getBoundingClientRect().top,
      moved: false,
      ghost: null
    };
  }

  function onPointerMove(event) {
    if (!drag || drag.pointerId !== event.pointerId) return;
    const distance = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY);
    if (!drag.moved && distance < 5) return;
    if (!drag.moved) beginDrag();
    positionGhost(event.clientX, event.clientY);
    highlightHoveredTarget(event.clientX, event.clientY);
  }

  function beginDrag() {
    drag.moved = true;
    selected = null;
    const ghost = document.createElement('div');
    ghost.className = 'drag-ghost';
    const movingCards = state.columns[drag.sourceColumn].slice(drag.sourceIndex);
    movingCards.forEach((card, index) => {
      const cardElement = createCardElement(card, drag.sourceColumn, drag.sourceIndex + index, true);
      cardElement.style.top = `${index * cssNumber('--face-step', 34)}px`;
      cardElement.style.zIndex = String(index + 1);
      ghost.appendChild(cardElement);
    });
    elements.dragLayer.appendChild(ghost);
    drag.ghost = ghost;

    document.querySelectorAll(`.card[data-column="${drag.sourceColumn}"]`).forEach(card => {
      if (Number(card.dataset.index) >= drag.sourceIndex) card.classList.add('drag-source');
    });
    validTargets(drag.sourceColumn, drag.sourceIndex).forEach(index => {
      document.querySelector(`.pile[data-column="${index}"]`)?.classList.add('valid-target');
    });
  }

  function positionGhost(x, y) {
    if (!drag?.ghost) return;
    drag.ghost.style.left = `${x - drag.offsetX}px`;
    drag.ghost.style.top = `${y - drag.offsetY}px`;
  }

  function highlightHoveredTarget(x, y) {
    document.querySelectorAll('.pile.invalid-target').forEach(pile => pile.classList.remove('invalid-target'));
    const target = document.elementFromPoint(x, y)?.closest('.pile');
    if (!target) return;
    const targetColumn = Number(target.dataset.column);
    if (!canPlace(drag.sourceColumn, drag.sourceIndex, targetColumn)) target.classList.add('invalid-target');
  }

  function onPointerUp(event) {
    if (!drag || drag.pointerId !== event.pointerId) return;
    const activeDrag = drag;
    if (!activeDrag.moved) {
      drag = null;
      return;
    }

    const target = document.elementFromPoint(event.clientX, event.clientY)?.closest('.pile');
    const targetColumn = target ? Number(target.dataset.column) : -1;
    cleanupDragVisuals();
    drag = null;

    if (targetColumn >= 0 && moveCards(activeDrag.sourceColumn, activeDrag.sourceIndex, targetColumn)) return;
    showMessage('Недопустимый ход.', true);
  }

  function cleanupDragVisuals() {
    drag?.ghost?.remove();
    document.querySelectorAll('.drag-source').forEach(card => card.classList.remove('drag-source'));
    document.querySelectorAll('.pile.valid-target, .pile.invalid-target').forEach(pile => {
      pile.classList.remove('valid-target', 'invalid-target');
    });
  }

  function cancelInteraction() {
    cleanupDragVisuals();
    drag = null;
    selected = null;
  }

  function onKeyDown(event) {
    const card = event.target.closest?.('.card.face-up');
    if (card && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault();
      selectSequence(Number(card.dataset.column), Number(card.dataset.index));
      return;
    }
    if (event.key === 'Escape') {
      selected = null;
      updateSelectionUI();
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
      event.preventDefault();
      undo();
    }
  }

  elements.tableau.addEventListener('click', onTableClick);
  elements.tableau.addEventListener('pointerdown', onPointerDown);
  window.addEventListener('pointermove', onPointerMove, { passive: false });
  window.addEventListener('pointerup', onPointerUp);
  window.addEventListener('pointercancel', () => {
    cleanupDragVisuals();
    drag = null;
  });
  document.addEventListener('keydown', onKeyDown);
  elements.stockButton.addEventListener('click', dealFromStock);
  elements.undoButton.addEventListener('click', undo);
  elements.newGameButton.addEventListener('click', () => newGame());
  elements.playAgainButton.addEventListener('click', () => {
    elements.winDialog.close();
    newGame();
  });
  elements.difficulty.addEventListener('change', () => newGame(Number(elements.difficulty.value)));
  window.addEventListener('resize', () => render());

  if (!loadGame()) newGame(2);
  else render();
})();
