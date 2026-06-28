(function () {
  'use strict';

  var state = null;
  var els = {};
  var dirNames = ['n', 'e', 's', 'w'];
  var featureNames = { city: 'Город', road: 'Дорога', monastery: 'Монастырь' };
  var featureHints = {
    city: '2 очка за тайл города + 2 за герб после завершения; на финальном счёте — по 1.',
    road: '1 очко за тайл дороги после завершения и на финальном счёте.',
    monastery: '9 очков, когда вокруг монастыря заняты все 8 клеток.'
  };

  function byId(id) { return document.getElementById(id); }

  function init() {
    if (!window.Carcassonne) {
      document.body.innerHTML = '<main class="fatal-error"><h1>Ошибка загрузки</h1><p>game.js не загрузился.</p></main>';
      return;
    }

    els.setupPanel = byId('setup-panel');
    els.playerCount = byId('player-count');
    els.playerNames = byId('player-names');
    els.startGame = byId('start-game');
    els.newGameTop = byId('new-game-top');
    els.board = byId('board');
    els.rotate = byId('rotate-tile');
    els.skip = byId('skip-meeple');
    els.currentTile = byId('current-tile');
    els.tileHint = byId('tile-hint');
    els.rotationStatus = byId('rotation-status');
    els.deckCounter = byId('deck-counter');
    els.phaseLabel = byId('phase-label');
    els.currentPlayerTitle = byId('current-player-title');
    els.featureActions = byId('feature-actions');
    els.scoreboard = byId('scoreboard');
    els.eventLog = byId('event-log');

    els.playerCount.addEventListener('change', renderPlayerInputs);
    els.startGame.addEventListener('click', startGame);
    els.newGameTop.addEventListener('click', function () {
      state = null;
      els.setupPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
      render();
    });
    els.rotate.addEventListener('click', function () { rotateCurrentTileFromUi('button'); });
    els.skip.addEventListener('click', function () {
      if (!state) return;
      window.Carcassonne.skipMeeple(state);
      render();
    });
    document.addEventListener('keydown', function (event) {
      var target = event.target;
      var tag = target && target.tagName ? target.tagName.toLowerCase() : '';
      if (tag === 'input' || tag === 'select' || tag === 'textarea') return;
      if (event.key && event.key.toLowerCase() === 'r') {
        event.preventDefault();
        rotateCurrentTileFromUi('hotkey');
      }
    });

    renderPlayerInputs();
    render();
  }

  function rotateCurrentTileFromUi(source) {
    if (!state || state.phase !== 'place') return;
    var before = placementsSignature(state.validPlacements);
    var ok = window.Carcassonne.rotateCurrentTile(state);
    if (!ok) return;
    var after = placementsSignature(state.validPlacements);
    state.lastRotateSource = source;
    state.lastRotateChangedCells = before !== after;
    render();
    pulse(els.rotate, 'just-rotated');
    pulse(els.currentTile, 'preview-rotated');
    pulse(els.board, 'valids-updated');
  }

  function pulse(el, className) {
    if (!el) return;
    el.classList.remove(className);
    // Force reflow so repeated rotations restart the CSS animation.
    void el.offsetWidth;
    el.classList.add(className);
  }

  function placementsSignature(placements) {
    return placements.map(function (pos) { return pos.col + ':' + pos.row; }).sort().join('|');
  }

  function renderPlayerInputs() {
    var count = Number(els.playerCount.value || 2);
    els.playerNames.innerHTML = '';
    for (var i = 0; i < count; i += 1) {
      var row = document.createElement('label');
      row.className = 'player-name-row';
      var dot = document.createElement('span');
      dot.className = 'player-dot';
      dot.style.backgroundColor = ['#b82f30', '#2f68b8', '#2f7d45', '#7a4ab0', '#c56d17'][i];
      var input = document.createElement('input');
      input.type = 'text';
      input.value = 'Игрок ' + (i + 1);
      input.maxLength = 24;
      input.setAttribute('data-player-name', String(i));
      row.appendChild(dot);
      row.appendChild(input);
      els.playerNames.appendChild(row);
    }
  }

  function startGame() {
    var inputs = Array.prototype.slice.call(els.playerNames.querySelectorAll('input'));
    var names = inputs.map(function (input, index) {
      return input.value.trim() || ('Игрок ' + (index + 1));
    });
    state = window.Carcassonne.createGame(names);
    state.lastRotateSource = '';
    state.lastRotateChangedCells = false;
    render();
  }

  function render() {
    renderHeader();
    renderBoard();
    renderCurrentTile();
    renderFeatureActions();
    renderScoreboard();
    renderLog();
  }

  function renderHeader() {
    if (!state) {
      els.phaseLabel.textContent = 'Фаза: подготовка';
      els.currentPlayerTitle.textContent = 'Нажмите «Начать»';
      els.deckCounter.textContent = '0 в мешке';
      els.rotate.disabled = true;
      els.skip.disabled = true;
      return;
    }
    var player = state.players[state.currentPlayer];
    var phaseText = state.phase === 'place' ? 'размещение тайла' : state.phase === 'meeple' ? 'мипл' : 'финал';
    els.phaseLabel.textContent = 'Фаза: ' + phaseText;
    els.currentPlayerTitle.textContent = state.gameOver ? 'Игра окончена' : ('Ходит ' + player.name);
    els.deckCounter.textContent = state.deck.length + ' в мешке';
    els.rotate.disabled = state.phase !== 'place';
    els.skip.disabled = state.phase !== 'meeple';
  }

  function collectBoardPositions() {
    var positions = [];
    if (state) {
      Object.keys(state.board).forEach(function (boardKey) {
        var parts = boardKey.split(',');
        positions.push({ col: Number(parts[0]), row: Number(parts[1]) });
      });
      state.validPlacements.forEach(function (pos) { positions.push(pos); });
    }
    if (positions.length === 0) positions.push({ col: 0, row: 0 });
    return positions;
  }

  function renderBoard() {
    els.board.innerHTML = '';
    els.board.dataset.rotation = state ? String(state.currentRotation || 0) : '0';
    els.board.dataset.validCount = state ? String(state.validPlacements.length) : '0';
    els.board.dataset.rotationRevision = state ? String(state.rotationRevision || 0) : '0';
    var positions = collectBoardPositions();
    var cols = positions.map(function (p) { return p.col; });
    var rows = positions.map(function (p) { return p.row; });
    var minCol = Math.min.apply(null, cols) - 1;
    var maxCol = Math.max.apply(null, cols) + 1;
    var minRow = Math.min.apply(null, rows) - 1;
    var maxRow = Math.max.apply(null, rows) + 1;
    var colCount = maxCol - minCol + 1;
    var rowCount = maxRow - minRow + 1;
    els.board.style.gridTemplateColumns = 'repeat(' + colCount + ', var(--tile-size))';
    els.board.style.gridTemplateRows = 'repeat(' + rowCount + ', var(--tile-size))';

    for (var row = minRow; row <= maxRow; row += 1) {
      for (var col = minCol; col <= maxCol; col += 1) {
        els.board.appendChild(renderCell(col, row));
      }
    }
  }

  function renderCell(col, row) {
    var cell = document.createElement('button');
    cell.type = 'button';
    cell.className = 'board-cell';
    cell.setAttribute('aria-label', 'Клетка ' + col + ':' + row);

    if (!state) return cell;
    var boardKey = col + ',' + row;
    var placed = state.board[boardKey];
    if (placed) {
      cell.className = 'board-cell occupied';
      cell.disabled = true;
      var tile = renderTile(placed.tile, placed.rotation, placed.meeple, false);
      var coord = document.createElement('span');
      coord.className = 'coord';
      coord.textContent = col + ':' + row;
      tile.appendChild(coord);
      cell.appendChild(tile);
      return cell;
    }

    var valid = state.phase === 'place' && state.validPlacements.some(function (pos) {
      return pos.col === col && pos.row === row;
    });
    if (valid) {
      cell.className = 'board-cell valid';
      cell.title = 'Законная клетка для текущего поворота ' + (state.currentRotation * 90) + '°';
      cell.addEventListener('click', function () {
        window.Carcassonne.placeTile(state, col, row);
        render();
      });
    } else {
      cell.disabled = true;
    }
    return cell;
  }

  function renderTile(tileDef, rotation, meeple, large) {
    var tile = document.createElement('div');
    tile.className = 'tile' + (large ? ' large' : '');
    tile.title = tileDef.title + ' · поворот ' + (rotation * 90) + '°';
    tile.dataset.rotation = String(rotation);
    tile.style.setProperty('--tile-rotation', (rotation * 90) + 'deg');

    var art = document.createElement('span');
    art.className = 'tile-art';
    tileDef.edges.forEach(function (edge, index) {
      var edgeEl = document.createElement('span');
      edgeEl.className = 'tile-edge ' + dirNames[index] + ' edge-' + edge;
      art.appendChild(edgeEl);
    });
    var core = document.createElement('span');
    core.className = 'tile-core core-' + tileDef.center;
    core.textContent = centerIcon(tileDef.center);
    art.appendChild(core);
    if (tileDef.shield) {
      var shield = document.createElement('span');
      shield.className = 'tile-shield';
      shield.textContent = '✦';
      art.appendChild(shield);
    }
    tile.appendChild(art);

    var compass = document.createElement('span');
    compass.className = 'rotation-compass';
    compass.textContent = '▲';
    tile.appendChild(compass);

    if (large) {
      var badge = document.createElement('span');
      badge.className = 'rotation-badge';
      badge.textContent = (rotation * 90) + '°';
      tile.appendChild(badge);
    }

    if (meeple) {
      var m = document.createElement('span');
      m.className = 'meeple';
      m.style.backgroundColor = state.players[meeple.player].color;
      m.title = state.players[meeple.player].name + ' · ' + (featureNames[meeple.type] || meeple.type);
      tile.appendChild(m);
    }
    return tile;
  }

  function centerIcon(center) {
    if (center === 'C') return '♜';
    if (center === 'R') return '•';
    if (center === 'M') return '⌂';
    if (center === 'X') return '✣';
    return '✿';
  }

  function renderCurrentTile() {
    els.currentTile.innerHTML = '';
    if (!state || !state.currentTile) {
      els.currentTile.textContent = state && state.gameOver ? 'Партия завершена' : 'Нет тайла';
      els.tileHint.textContent = state && state.gameOver ? 'Финальный счёт уже добавлен.' : 'Начните новую игру.';
      els.rotationStatus.textContent = state && state.gameOver ? 'Игра завершена.' : 'Поворот появится после начала партии.';
      return;
    }
    els.currentTile.appendChild(renderTile(state.currentTile, state.currentRotation, null, true));
    var rotationText = state.currentRotation * 90;
    var rotateSource = state.lastRotateSource === 'hotkey' ? 'клавишей R' : state.lastRotateSource === 'button' ? 'кнопкой' : 'автоматически при доборе';
    var cellsText = state.validPlacements.length + ' ' + plural(state.validPlacements.length, 'клетка', 'клетки', 'клеток');
    els.rotationStatus.innerHTML = '<strong>Поворот: ' + rotationText + '°</strong><span>Законные клетки: ' + cellsText + '</span><small>Последний поворот: ' + rotateSource + '. Подсветка поля пересчитана.</small>';
    if (state.phase === 'place') {
      els.tileHint.textContent = 'Поворачивайте тайл кнопкой или R: превью вращается, а зелёные клетки на поле обновляются под текущий поворот.';
    } else {
      els.tileHint.textContent = 'Теперь можно поставить одного мипла на только что выложенный тайл или пропустить.';
    }
  }

  function plural(n, one, two, five) {
    var mod10 = n % 10;
    var mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return one;
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return two;
    return five;
  }

  function renderFeatureActions() {
    els.featureActions.innerHTML = '';
    if (!state || state.phase !== 'meeple') return;
    var options = window.Carcassonne.getFeatureOptions(state);
    if (options.length === 0) {
      var empty = document.createElement('p');
      empty.className = 'hint';
      empty.textContent = 'На этом тайле нет объектов для мипла.';
      els.featureActions.appendChild(empty);
      return;
    }
    options.forEach(function (option) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'secondary-button feature-button';
      button.disabled = !option.available;
      button.innerHTML = '<strong>' + (featureNames[option.type] || option.type) + '</strong><br><span>' + featureHints[option.type] + '</span>';
      button.addEventListener('click', function () {
        window.Carcassonne.placeMeeple(state, option);
        render();
      });
      els.featureActions.appendChild(button);
    });
  }

  function renderScoreboard() {
    els.scoreboard.innerHTML = '';
    if (!state) {
      els.scoreboard.innerHTML = '<p class="hint">Счёт появится после начала партии.</p>';
      return;
    }
    state.players.forEach(function (player) {
      var row = document.createElement('div');
      row.className = 'score-row' + (state.currentPlayer === player.id && !state.gameOver ? ' active' : '');
      var dot = document.createElement('span');
      dot.className = 'player-dot';
      dot.style.backgroundColor = player.color;
      var text = document.createElement('div');
      text.innerHTML = '<div class="score-name">' + escapeHtml(player.name) + '</div><div class="score-meta">Миплов: ' + player.meeples + '</div>';
      var score = document.createElement('div');
      score.className = 'score-points';
      score.textContent = String(player.score);
      row.appendChild(dot);
      row.appendChild(text);
      row.appendChild(score);
      els.scoreboard.appendChild(row);
    });
  }

  function renderLog() {
    els.eventLog.innerHTML = '';
    if (!state) {
      els.eventLog.innerHTML = '<li>Журнал появится после начала партии.</li>';
      return;
    }
    state.log.slice(0, 28).forEach(function (item) {
      var li = document.createElement('li');
      li.textContent = item.text;
      els.eventLog.appendChild(li);
    });
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"]/g, function (char) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[char];
    });
  }

  document.addEventListener('DOMContentLoaded', init);
}());
