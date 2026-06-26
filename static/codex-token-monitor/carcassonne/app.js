(function () {
  'use strict';

  if (typeof window.Carcassonne === 'undefined') {
    window.addEventListener('DOMContentLoaded', function () {
      var el = document.getElementById('board-container');
      if (el) el.innerHTML = '<div style="color:#e74c3c;padding:20px;">Error: game engine (game.js) failed to load. Please reload the page.</div>';
    });
    return;
  }

  var C = window.Carcassonne;

  var TILE_SIZE = 80;
  var FONT = '12px "Segoe UI", sans-serif';
  var FONT_BOLD = 'bold 12px "Segoe UI", sans-serif';
  var FONT_SMALL = '10px "Segoe UI", sans-serif';

  var state = null;
  var dpr = 1;

  var canvas, ctx;
  var previewCanvas, previewCtx;
  var offsetX = 0, offsetY = 0;
  var scale = 1.0;
  var dragging = false;
  var dragStartX, dragStartY, dragOffsetStartX, dragOffsetStartY;
  var hoveredCol = null, hoveredRow = null;

  function init() {
    canvas = document.getElementById('board-canvas');
    ctx = canvas.getContext('2d');
    previewCanvas = document.getElementById('preview-canvas');
    previewCtx = previewCanvas.getContext('2d');

    resizeCanvas();

    window.addEventListener('resize', function () {
      resizeCanvas();
      render();
    });

    canvas.addEventListener('mousedown', onMouseDown);
    canvas.addEventListener('mousemove', onMouseMove);
    canvas.addEventListener('mouseup', onMouseUp);
    canvas.addEventListener('mouseleave', onMouseUp);
    canvas.addEventListener('wheel', onWheel, { passive: false });
    canvas.addEventListener('click', onClick);

    document.addEventListener('keydown', onKeyDown);

    document.getElementById('btn-rotate').addEventListener('click', rotateTile);
    document.getElementById('btn-skip-meeple').addEventListener('click', skipMeepleAction);
    document.getElementById('btn-end-turn').addEventListener('click', endTurnAction);
    document.getElementById('btn-restart').addEventListener('click', showSetup);
    document.getElementById('btn-help').addEventListener('click', toggleHelp);
    document.getElementById('btn-start-game').addEventListener('click', startGameFromSetup);
    document.getElementById('btn-close-help').addEventListener('click', toggleHelp);

    var playerCountEl = document.getElementById('player-count');
    playerCountEl.addEventListener('change', updatePlayerNameInputs);

    updatePlayerNameInputs();
    showSetup();
  }

  function resizeCanvas() {
    var container = document.getElementById('board-container');
    var w = container.clientWidth;
    var h = container.clientHeight || window.innerHeight - 160;
    if (w < 400) w = 400;
    if (h < 300) h = 300;
    dpr = window.devicePixelRatio || 1;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.imageSmoothingEnabled = true;
  }

  function showSetup() {
    if (state && !state.gameOver) {
      if (!confirm('A game is in progress. Starting a new game will discard the current session. Continue?')) {
        return;
      }
    }
    document.getElementById('setup-modal').classList.remove('hidden');
  }

  function hideSetup() {
    document.getElementById('setup-modal').classList.add('hidden');
  }

  function toggleHelp() {
    var modal = document.getElementById('help-modal');
    modal.classList.toggle('hidden');
  }

  function updatePlayerNameInputs() {
    var count = parseInt(document.getElementById('player-count').value, 10) || 2;
    if (count < 2) count = 2;
    if (count > 5) count = 5;
    document.getElementById('player-count').value = count;

    var container = document.getElementById('player-names');
    container.innerHTML = '';
    var defaults = ['Alice', 'Bob', 'Charlie', 'Diana', 'Eve'];
    for (var i = 0; i < count; i++) {
      var div = document.createElement('div');
      div.className = 'player-name-row';
      var color = C.PLAYER_COLORS[i];
      div.innerHTML = '<span class="color-swatch" style="background:' + color + '"></span>' +
        '<label>Player ' + (i + 1) + ':</label>' +
        '<input type="text" class="player-name-input" value="' + defaults[i] + '" data-index="' + i + '">';
      container.appendChild(div);
    }
  }

  function startGameFromSetup() {
    var count = parseInt(document.getElementById('player-count').value, 10);
    var inputs = document.querySelectorAll('.player-name-input');
    var names = [];
    for (var i = 0; i < count && i < inputs.length; i++) {
      var name = inputs[i].value.trim();
      if (!name) name = 'Player ' + (i + 1);
      names.push(name);
    }

    state = C.createGame(names);
    hideSetup();
    centerBoard();
    updateAllUI();
    render();
  }

  function centerBoard() {
    var container = document.getElementById('board-container');
    var cx = container.clientWidth / 2;
    var cy = container.clientHeight / 2;
    offsetX = cx - TILE_SIZE / 2;
    offsetY = cy - TILE_SIZE / 2;
  }

  function boardToScreen(col, row) {
    return {
      x: offsetX + col * TILE_SIZE * scale,
      y: offsetY + row * TILE_SIZE * scale
    };
  }

  function screenToBoard(sx, sy) {
    return {
      col: Math.floor((sx - offsetX) / (TILE_SIZE * scale)),
      row: Math.floor((sy - offsetY) / (TILE_SIZE * scale))
    };
  }

  function onMouseDown(e) {
    var rect = canvas.getBoundingClientRect();
    var mx = e.clientX - rect.left;
    var my = e.clientY - rect.top;

    if (state && state.phase === 'meeple') {
      var sb = screenToBoard(mx, my);
      var key = C.posKey(sb.col, sb.row);
      if (state.board[key] && state.board[key].meeple === null) {
        handleMeepleClick(sb.col, sb.row, mx, my);
        return;
      }
    }

    dragging = true;
    dragStartX = e.clientX;
    dragStartY = e.clientY;
    dragOffsetStartX = offsetX;
    dragOffsetStartY = offsetY;
  }

  function onMouseMove(e) {
    var rect = canvas.getBoundingClientRect();
    var mx = e.clientX - rect.left;
    var my = e.clientY - rect.top;

    if (dragging) {
      offsetX = dragOffsetStartX + (e.clientX - dragStartX);
      offsetY = dragOffsetStartY + (e.clientY - dragStartY);
      render();
      return;
    }

    var sb = screenToBoard(mx, my);
    if (sb.col !== hoveredCol || sb.row !== hoveredRow) {
      hoveredCol = sb.col;
      hoveredRow = sb.row;
      render();
    }
  }

  function onMouseUp(e) {
    dragging = false;
  }

  function onWheel(e) {
    e.preventDefault();
    var rect = canvas.getBoundingClientRect();
    var mx = e.clientX - rect.left;
    var my = e.clientY - rect.top;

    var oldScale = scale;
    var delta = e.deltaY > 0 ? -0.1 : 0.1;
    scale = Math.max(0.3, Math.min(3.0, scale + delta));

    var ratio = scale / oldScale;
    offsetX = mx - ratio * (mx - offsetX);
    offsetY = my - ratio * (my - offsetY);

    render();
  }

  function onClick(e) {
    if (dragging) return;

    var rect = canvas.getBoundingClientRect();
    var mx = e.clientX - rect.left;
    var my = e.clientY - rect.top;
    var sb = screenToBoard(mx, my);

    if (!state || state.gameOver) return;

    if (state.phase === 'place') {
      var canPlace = false;
      for (var i = 0; i < state.validPlacements.length; i++) {
        var vp = state.validPlacements[i];
        if (vp.col === sb.col && vp.row === sb.row) {
          canPlace = true;
          break;
        }
      }
      if (canPlace) {
        C.placeTile(state, sb.col, sb.row);
        updateAllUI();
        render();
      }
    }
  }

  function handleMeepleClick(col, row, mx, my) {
    var features = C.getTileFeatures(state, col, row);
    if (features.length === 0) return;

    var bs = boardToScreen(col, row);
    var ts = TILE_SIZE * scale;
    var relX = (mx - bs.x) / ts;
    var relY = (my - bs.y) / ts;

    var selectedFeature = null;

    for (var i = 0; i < features.length; i++) {
      var f = features[i];
      if (f.type === 'monastery') {
        var cx = 0.5, cy = 0.5, r = 0.15;
        var dx = relX - cx, dy = relY - cy;
        if (dx * dx + dy * dy <= r * r + 0.02) {
          selectedFeature = f;
          break;
        }
      } else if (f.type === 'city') {
        for (var j = 0; j < f.edges.length; j++) {
          var d = f.edges[j];
          var reg = getEdgeRegion(d, ts);
          var ex = bs.x + reg.cx * ts;
          var ey = bs.y + reg.cy * ts;
          var dist = Math.sqrt((mx - ex) * (mx - ex) + (my - ey) * (my - ey));
          if (dist < ts * 0.18) {
            selectedFeature = f;
            break;
          }
        }
        if (selectedFeature) break;
      } else if (f.type === 'road') {
        for (var k = 0; k < f.edges.length; k++) {
          var rd = f.edges[k];
          var reg2 = getEdgeRegion(rd, ts);
          var rx = bs.x + reg2.cx * ts;
          var ry = bs.y + reg2.cy * ts;
          var dist2 = Math.sqrt((mx - rx) * (mx - rx) + (my - ry) * (my - ry));
          if (dist2 < ts * 0.18) {
            selectedFeature = f;
            break;
          }
        }
        if (selectedFeature) break;
      }
    }

    if (!selectedFeature && features.length > 0) {
      for (var fi = 0; fi < features.length; fi++) {
        if (features[fi].type === 'field') {
          selectedFeature = features[fi];
          break;
        }
      }
    }

    if (!selectedFeature) return;

    var featureEdge = selectedFeature.type === 'monastery' ? 0 :
      selectedFeature.type === 'field' ? getClosestFieldEdge(selectedFeature, relX, relY) :
        (selectedFeature.edges && selectedFeature.edges.length > 0 ? selectedFeature.edges[0] : 0);

    if (C.canPlaceMeepleOnFeature(state, col, row, selectedFeature.type, featureEdge)) {
      C.placeMeeple(state, col, row, selectedFeature.type, featureEdge);
      updateAllUI();
      render();
    }
  }

  function getEdgeRegion(dir, ts) {
    switch (dir) {
      case C.DIR_N: return { cx: 0.5, cy: 0.12 };
      case C.DIR_E: return { cx: 0.88, cy: 0.5 };
      case C.DIR_S: return { cx: 0.5, cy: 0.88 };
      case C.DIR_W: return { cx: 0.12, cy: 0.5 };
    }
    return { cx: 0.5, cy: 0.5 };
  }

  function getClosestFieldEdge(feature, relX, relY) {
    if (!feature.edges || feature.edges.length === 0) return 0;
    var bestDist = Infinity;
    var bestEdge = feature.edges[0];
    for (var i = 0; i < feature.edges.length; i++) {
      var d = feature.edges[i];
      var reg = getEdgeRegion(d);
      var dx = relX - reg.cx;
      var dy = relY - reg.cy;
      var dist = dx * dx + dy * dy;
      if (dist < bestDist) {
        bestDist = dist;
        bestEdge = d;
      }
    }
    return bestEdge;
  }

  function rotateTile() {
    if (!state || state.phase !== 'place') return;
    state.currentRotation = (state.currentRotation + 1) % 4;
    state.validPlacements = C.getValidPlacements(state, state.currentTile, state.currentRotation);
    updateAllUI();
    render();
  }

  function skipMeepleAction() {
    if (!state || state.phase !== 'meeple') return;
    C.skipMeeple(state);
    endTurnAction();
  }

  function endTurnAction() {
    if (!state || state.gameOver) return;
    if (state.phase === 'meeple' || state.phase === 'place') {
      if (state.phase === 'place' && !state.placedMeepleThisTurn) {
        return;
      }
      C.endTurn(state);
      updateAllUI();
      render();
      if (state.phase === 'place') {
        centerBoard();
        render();
      }
    }
  }

  function onKeyDown(e) {
    if (!state || state.gameOver) return;

    if (e.key === 'r' || e.key === 'R') {
      rotateTile();
    } else if (e.key === ' ' || e.key === 'Spacebar') {
      e.preventDefault();
      skipMeepleAction();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      endTurnAction();
    }
  }

  function updateAllUI() {
    updatePlayerPanel();
    updateGameInfo();
    updatePreview();
    updateControls();
    updateLog();
  }

  function updatePlayerPanel() {
    if (!state) return;
    var panel = document.getElementById('players-panel');
    var html = '';
    for (var i = 0; i < state.players.length; i++) {
      var p = state.players[i];
      var active = (i === state.currentPlayer && !state.gameOver) ? ' active' : '';
      var winner = (state.gameOver && state.getWinner && i === 0) ? ' winner' : '';
      var sortedPlayers = state.gameOver ? C.getAllFinalScores(state) : null;
      var isWinner = state.gameOver && sortedPlayers && i === sortedPlayers[0].index;

      html += '<div class="player-card' + active + (isWinner ? ' winner' : '') + '" style="border-left: 4px solid ' + C.getPlayerColor(i) + ';">';
      html += '<div class="player-name">' + escHtml(p.name) + '</div>';
      html += '<div class="player-score">' + p.score + ' pts</div>';
      html += '<div class="player-meeples">Meeples: ' + p.meeples + '</div>';
      html += '</div>';
    }
    panel.innerHTML = html;
  }

  function updateGameInfo() {
    if (!state) return;
    document.getElementById('tiles-left').textContent = Math.max(0, state.deck.length - state.deckIndex);
    var phaseNames = { draw: 'Drawing', place: 'Place Tile', meeple: 'Place Meeple', gameover: 'Game Over' };
    var phaseText = phaseNames[state.phase] || state.phase;
    if (state.currentPlayer < state.players.length && !state.gameOver) {
      phaseText += ' - ' + state.players[state.currentPlayer].name;
    }
    document.getElementById('game-phase').textContent = phaseText;
  }

  function updatePreview() {
    if (!state || !state.currentTile || state.gameOver) {
      previewCtx.clearRect(0, 0, previewCanvas.width, previewCanvas.height);
      return;
    }
    previewCtx.clearRect(0, 0, previewCanvas.width, previewCanvas.height);
    previewCtx.save();
    previewCtx.translate(previewCanvas.width / 2, previewCanvas.height / 2);
    drawTile(previewCtx, state.currentTile, state.currentRotation, previewCanvas.width * 0.42);
    previewCtx.restore();
    previewCtx.fillStyle = '#aaa';
    previewCtx.font = FONT_SMALL;
    previewCtx.textAlign = 'center';
    previewCtx.fillText('Rotation: ' + (state.currentRotation * 90) + '\u00B0', previewCanvas.width / 2, previewCanvas.height - 8);
    var rotDisplay = document.getElementById('rotation-display');
    if (rotDisplay) rotDisplay.textContent = 'Rotation: ' + (state.currentRotation * 90) + '\u00B0';
  }

  function updateControls() {
    var rotateBtn = document.getElementById('btn-rotate');
    var skipBtn = document.getElementById('btn-skip-meeple');
    var endBtn = document.getElementById('btn-end-turn');

    if (!state || state.gameOver) {
      rotateBtn.disabled = true;
      skipBtn.disabled = true;
      endBtn.disabled = true;
    } else {
      rotateBtn.disabled = state.phase !== 'place';
      skipBtn.disabled = state.phase !== 'meeple';
      endBtn.disabled = (state.phase !== 'meeple');
    }
  }

  function updateLog() {
    if (!state) return;
    var entries = document.getElementById('log-entries');
    var html = '';
    var limit = Math.min(20, state.log.length);
    for (var i = 0; i < limit; i++) {
      html += '<div class="log-entry">' + escHtml(state.log[i].text) + '</div>';
    }
    entries.innerHTML = html;
  }

  function render() {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, canvas.width / dpr, canvas.height / dpr);

    ctx.fillStyle = '#1a1a2e';
    ctx.fillRect(0, 0, canvas.width / dpr, canvas.height / dpr);

    if (!state) return;

    drawGrid();

    var boardKeys = Object.keys(state.board);
    for (var i = 0; i < boardKeys.length; i++) {
      var pos = C.parseKey(boardKeys[i]);
      drawPlacedTile(pos.col, pos.row);
    }

    if (state.phase === 'place' && state.currentTile && !state.gameOver) {
      drawValidPlacementHighlights();
    }

    for (var j = 0; j < boardKeys.length; j++) {
      var pos2 = C.parseKey(boardKeys[j]);
      drawMeepleOnTile(pos2.col, pos2.row);
    }

    if (state.phase === 'place' && state.currentTile && !state.gameOver) {
      drawHoverPreview();
    }

    if (state.gameOver) {
      drawGameOverOverlay();
    }
  }

  function drawGrid() {
    var ts = TILE_SIZE * scale;
    var cw = canvas.width / dpr;
    var ch = canvas.height / dpr;
    var startCol = Math.floor((0 - offsetX) / ts) - 1;
    var startRow = Math.floor((0 - offsetY) / ts) - 1;
    var endCol = Math.ceil((cw - offsetX) / ts) + 1;
    var endRow = Math.ceil((ch - offsetY) / ts) + 1;

    ctx.strokeStyle = '#2a2a4a';
    ctx.lineWidth = 0.5;

    for (var col = startCol; col <= endCol; col++) {
      var x = offsetX + col * ts;
      ctx.beginPath();
      ctx.moveTo(x, offsetY + startRow * ts);
      ctx.lineTo(x, offsetY + endRow * ts);
      ctx.stroke();
    }
    for (var row = startRow; row <= endRow; row++) {
      var y = offsetY + row * ts;
      ctx.beginPath();
      ctx.moveTo(offsetX + startCol * ts, y);
      ctx.lineTo(offsetX + endCol * ts, y);
      ctx.stroke();
    }
  }

  function drawPlacedTile(col, row) {
    var key = C.posKey(col, row);
    var placed = state.board[key];
    if (!placed) return;

    var bs = boardToScreen(col, row);
    var ts = TILE_SIZE * scale;

    ctx.save();
    ctx.translate(bs.x, bs.y);
    drawTile(ctx, placed.tile, placed.rotation, ts);
    ctx.restore();
  }

  function drawTile(context, tileDef, rotation, size) {
    var s = size;
    var h = s / 2;

    context.fillStyle = '#7ec850';
    context.fillRect(0, 0, s, s);

    var edges = C.edgeArray(tileDef, rotation);

    var hasCity = false;
    var hasRoad = false;
    for (var d = 0; d < 4; d++) {
      if (edges[d] === C.EDGE_CITY) hasCity = true;
      if (edges[d] === C.EDGE_ROAD) hasRoad = true;
    }

    if (hasCity) {
      drawCityFeature(context, edges, s);
    }

    if (hasRoad) {
      drawRoadFeature(context, edges, s);
    }

    if (tileDef.center === 'M') {
      drawMonastery(context, h, s);
    }

    if (tileDef.shield) {
      drawShield(context, h, s);
    }

    context.strokeStyle = '#333';
    context.lineWidth = 1;
    context.strokeRect(0.5, 0.5, s - 1, s - 1);
  }

  function drawCityFeature(context, edges, s) {
    var h = s / 2;
    var sp = s * 0.22;
    var cityInside = s * 0.18;

    context.save();
    context.beginPath();

    var hasN = edges[C.DIR_N] === C.EDGE_CITY;
    var hasE = edges[C.DIR_E] === C.EDGE_CITY;
    var hasS = edges[C.DIR_S] === C.EDGE_CITY;
    var hasW = edges[C.DIR_W] === C.EDGE_CITY;

    if (hasN) {
      context.fillStyle = '#c8956c';
      context.fillRect(0, 0, s, sp);
      context.fillStyle = '#8b6914';
      context.fillRect(0, 0, s, cityInside);
      context.fillStyle = '#6b6b6b';
      context.fillRect(0, 0, s, 3);
    }
    if (hasE) {
      context.fillStyle = '#c8956c';
      context.fillRect(s - sp, 0, sp, s);
      context.fillStyle = '#8b6914';
      context.fillRect(s - cityInside, 0, cityInside, s);
      context.fillStyle = '#6b6b6b';
      context.fillRect(s - 3, 0, 3, s);
    }
    if (hasS) {
      context.fillStyle = '#c8956c';
      context.fillRect(0, s - sp, s, sp);
      context.fillStyle = '#8b6914';
      context.fillRect(0, s - cityInside, s, cityInside);
      context.fillStyle = '#6b6b6b';
      context.fillRect(0, s - 3, s, 3);
    }
    if (hasW) {
      context.fillStyle = '#c8956c';
      context.fillRect(0, 0, sp, s);
      context.fillStyle = '#8b6914';
      context.fillRect(0, 0, cityInside, s);
      context.fillStyle = '#6b6b6b';
      context.fillRect(0, 0, 3, s);
    }

    context.restore();
  }

  function drawRoadFeature(context, edges, s) {
    var rw = s * 0.12;
    var h = s / 2;
    var roadColor = '#d4b896';
    var roadBorder = '#a08060';

    context.save();

    for (var d = 0; d < 4; d++) {
      if (edges[d] === C.EDGE_ROAD) {
        context.fillStyle = roadColor;
        context.strokeStyle = roadBorder;
        context.lineWidth = 1;

        switch (d) {
          case C.DIR_N:
            context.fillRect(h - rw, 0, rw * 2, h);
            context.strokeRect(h - rw, 0, rw * 2, h);
            break;
          case C.DIR_E:
            context.fillRect(h, h - rw, h, rw * 2);
            context.strokeRect(h, h - rw, h, rw * 2);
            break;
          case C.DIR_S:
            context.fillRect(h - rw, h, rw * 2, h);
            context.strokeRect(h - rw, h, rw * 2, h);
            break;
          case C.DIR_W:
            context.fillRect(0, h - rw, h, rw * 2);
            context.strokeRect(0, h - rw, h, rw * 2);
            break;
        }
      }
    }

    drawRoadConnectors(context, edges, s);

    context.restore();
  }

  function drawRoadConnectors(context, edges, s) {
    var rw = s * 0.12;
    var h = s / 2;
    var roadColor = '#d4b896';
    var roadBorder = '#a08060';
    var count = 0;
    for (var d = 0; d < 4; d++) {
      if (edges[d] === C.EDGE_ROAD) count++;
    }

    if (count >= 2) {
      context.fillStyle = roadColor;
      context.strokeStyle = roadBorder;
      context.lineWidth = 1;

      if (edges[C.DIR_N] === C.EDGE_ROAD && edges[C.DIR_S] === C.EDGE_ROAD) {
        context.fillRect(h - rw, 0, rw * 2, s);
        context.strokeRect(h - rw, 0, rw * 2, s);
      }
      if (edges[C.DIR_E] === C.EDGE_ROAD && edges[C.DIR_W] === C.EDGE_ROAD) {
        context.fillRect(0, h - rw, s, rw * 2);
        context.strokeRect(0, h - rw, s, rw * 2);
      }
      if (edges[C.DIR_N] === C.EDGE_ROAD && edges[C.DIR_E] === C.EDGE_ROAD) {
        context.beginPath();
        context.moveTo(h - rw, 0);
        context.lineTo(h - rw, h - rw);
        context.lineTo(s, h - rw);
        context.lineTo(s, h + rw);
        context.lineTo(h + rw, h + rw);
        context.lineTo(h + rw, 0);
        context.closePath();
        context.fill();
        context.stroke();

        context.beginPath();
        context.moveTo(0, h - rw);
        context.lineTo(h - rw, h - rw);
        context.lineTo(h - rw, s);
        context.lineTo(h + rw, s);
        context.lineTo(h + rw, h + rw);
        context.lineTo(0, h + rw);
        context.closePath();
        context.fill();
        context.stroke();
      }
      if (edges[C.DIR_N] === C.EDGE_ROAD && edges[C.DIR_W] === C.EDGE_ROAD) {
        context.beginPath();
        context.moveTo(h + rw, 0);
        context.lineTo(h + rw, h - rw);
        context.lineTo(0, h - rw);
        context.lineTo(0, h + rw);
        context.lineTo(h - rw, h + rw);
        context.lineTo(h - rw, 0);
        context.closePath();
        context.fill();
        context.stroke();

        context.beginPath();
        context.moveTo(s, h - rw);
        context.lineTo(h + rw, h - rw);
        context.lineTo(h + rw, s);
        context.lineTo(h - rw, s);
        context.lineTo(h - rw, h + rw);
        context.lineTo(s, h + rw);
        context.closePath();
        context.fill();
        context.stroke();
      }
      if (edges[C.DIR_S] === C.EDGE_ROAD && edges[C.DIR_E] === C.EDGE_ROAD) {
        context.beginPath();
        context.moveTo(h - rw, s);
        context.lineTo(h - rw, h + rw);
        context.lineTo(s, h + rw);
        context.lineTo(s, h - rw);
        context.lineTo(h + rw, h - rw);
        context.lineTo(h + rw, s);
        context.closePath();
        context.fill();
        context.stroke();

        context.beginPath();
        context.moveTo(0, h + rw);
        context.lineTo(h - rw, h + rw);
        context.lineTo(h - rw, 0);
        context.lineTo(h + rw, 0);
        context.lineTo(h + rw, h - rw);
        context.lineTo(0, h - rw);
        context.closePath();
        context.fill();
        context.stroke();
      }
      if (edges[C.DIR_S] === C.EDGE_ROAD && edges[C.DIR_W] === C.EDGE_ROAD) {
        context.beginPath();
        context.moveTo(h + rw, s);
        context.lineTo(h + rw, h + rw);
        context.lineTo(0, h + rw);
        context.lineTo(0, h - rw);
        context.lineTo(h - rw, h - rw);
        context.lineTo(h - rw, s);
        context.closePath();
        context.fill();
        context.stroke();

        context.beginPath();
        context.moveTo(s, h + rw);
        context.lineTo(h + rw, h + rw);
        context.lineTo(h + rw, 0);
        context.lineTo(h - rw, 0);
        context.lineTo(h - rw, h - rw);
        context.lineTo(s, h - rw);
        context.closePath();
        context.fill();
        context.stroke();
      }
    }
  }

  function drawMonastery(context, h, s) {
    var ms = s * 0.08;
    context.fillStyle = '#8b7355';
    context.fillRect(h - ms * 1.5, h - ms * 1.5, ms * 3, ms * 3);
    context.fillStyle = '#6b5335';
    context.fillRect(h - ms, h - ms * 2, ms * 2, ms * 4);
    context.fillStyle = '#a08060';
    context.fillRect(h - ms * 0.4, h - ms * 2.5, ms * 0.8, ms * 1);
    context.fillRect(h - ms * 0.4, h + ms * 1.5, ms * 0.8, ms * 0.6);
    context.strokeStyle = '#4a3828';
    context.lineWidth = 0.5;
    context.strokeRect(h - ms * 1.5, h - ms * 1.5, ms * 3, ms * 3);
  }

  function drawShield(context, h, s) {
    var sh = s * 0.1;
    var sw = s * 0.08;
    context.fillStyle = '#4488cc';
    context.beginPath();
    context.moveTo(h - sw, h);
    context.lineTo(h, h  - sh);
    context.lineTo(h + sw, h);
    context.lineTo(h, h + sh);
    context.closePath();
    context.fill();
    context.strokeStyle = '#ffd700';
    context.lineWidth = 1.5;
    context.stroke();
    context.fillStyle = '#ffd700';
    context.beginPath();
    context.arc(h, h, sw * 0.3, 0, Math.PI * 2);
    context.fill();
  }

  function drawValidPlacementHighlights() {
    var ts = TILE_SIZE * scale;
    for (var i = 0; i < state.validPlacements.length; i++) {
      var vp = state.validPlacements[i];
      var bs = boardToScreen(vp.col, vp.row);
      ctx.fillStyle = 'rgba(46, 204, 113, 0.25)';
      ctx.fillRect(bs.x + 1, bs.y + 1, ts - 2, ts - 2);
      ctx.strokeStyle = 'rgba(46, 204, 113, 0.6)';
      ctx.lineWidth = 2;
      ctx.strokeRect(bs.x + 1, bs.y + 1, ts - 2, ts - 2);
    }
  }

  function drawHoverPreview() {
    var ts = TILE_SIZE * scale;
    var hx = hoveredCol, hy = hoveredRow;
    if (hx === null || hy === null) return;

    var valid = false;
    for (var i = 0; i < state.validPlacements.length; i++) {
      var vp = state.validPlacements[i];
      if (vp.col === hx && vp.row === hy) {
        valid = true;
        break;
      }
    }

    if (!valid) return;

    var bs = boardToScreen(hx, hy);
    ctx.save();
    ctx.globalAlpha = 0.6;
    ctx.translate(bs.x, bs.y);
    drawTile(ctx, state.currentTile, state.currentRotation, ts);
    ctx.restore();
  }

  function drawMeepleOnTile(col, row) {
    var key = C.posKey(col, row);
    var placed = state.board[key];
    if (!placed || !placed.meeple) return;

    var bs = boardToScreen(col, row);
    var ts = TILE_SIZE * scale;
    var h = ts / 2;

    var px, py;

    var ft = placed.meeple.featureType;
    var fe = placed.meeple.featureEdge;

    if (ft === 'monastery') {
      px = bs.x + h;
      py = bs.y + h;
    } else if (ft === 'city') {
      var reg = getEdgeRegion(fe, ts);
      px = bs.x + reg.cx * ts;
      py = bs.y + reg.cy * ts;
    } else if (ft === 'road') {
      var reg2 = getEdgeRegion(fe, ts);
      px = bs.x + reg2.cx * ts;
      py = bs.y + reg2.cy * ts;
    } else if (ft === 'field') {
      var reg3 = getEdgeRegion(fe, ts);
      px = bs.x + reg3.cx * ts;
      py = bs.y + reg3.cy * ts;
    } else {
      px = bs.x + h;
      py = bs.y + h;
    }

    var color = C.getPlayerColor(placed.meeple.player);
    var mr = ts * 0.1;
    if (mr < 5) mr = 5;
    if (mr > 12) mr = 12;

    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(px, py, mr, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = mr * 0.25;
    ctx.stroke();

    ctx.fillStyle = '#fff';
    ctx.font = 'bold ' + (mr * 1.2) + 'px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(placed.meeple.player + 1, px, py);
  }

  function drawGameOverOverlay() {
    var cw = canvas.width / dpr;
    var ch = canvas.height / dpr;
    ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
    ctx.fillRect(0, 0, cw, ch);

    var sorted = C.getAllFinalScores(state);
    ctx.fillStyle = '#fff';
    ctx.font = 'bold 28px "Segoe UI", sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Game Over', cw / 2, ch / 2 - 40);

    ctx.font = 'bold 20px "Segoe UI", sans-serif';
    var winner = sorted[0];
    ctx.fillText('Winner: ' + escHtml(winner.name) + ' (' + winner.score + ' pts)', cw / 2, ch / 2 + 10);

    ctx.font = '14px "Segoe UI", sans-serif';
    for (var i = 0; i < sorted.length; i++) {
      var p = sorted[i];
      ctx.fillText((i + 1) + '. ' + escHtml(p.name) + ': ' + p.score + ' pts', cw / 2, ch / 2 + 40 + i * 24);
    }
  }

  function escHtml(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  window.addEventListener('DOMContentLoaded', init);
})();
