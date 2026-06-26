(function () {
  'use strict';

  var EDGE_CITY = 'C';
  var EDGE_ROAD = 'R';
  var EDGE_FIELD = 'F';

  var DIR_N = 0;
  var DIR_E = 1;
  var DIR_S = 2;
  var DIR_W = 3;

  var NEIGHBOR_DELTA = [
    { dc: 0, dr: -1 },
    { dc: 1, dr: 0 },
    { dc: 0, dr: 1 },
    { dc: -1, dr: 0 }
  ];

  var START_TILE_ID = 'starter';

  function posKey(c, r) { return c + ',' + r; }

  function parseKey(key) {
    var parts = key.split(',');
    return { col: parseInt(parts[0], 10), row: parseInt(parts[1], 10) };
  }

  function neighborPos(c, r, dir) {
    var d = NEIGHBOR_DELTA[dir];
    return { col: c + d.dc, row: r + d.dr };
  }

  function neighborKey(c, r, dir) {
    var d = NEIGHBOR_DELTA[dir];
    return (c + d.dc) + ',' + (r + d.dr);
  }

  function oppositeDir(dir) {
    return (dir + 2) % 4;
  }

  function effectiveEdge(tileDef, rotation, dir) {
    var idx = (dir - rotation + 4) % 4;
    return tileDef.edges[idx];
  }

  function edgeArray(tileDef, rotation) {
    var arr = [];
    for (var d = 0; d < 4; d++) {
      arr[d] = effectiveEdge(tileDef, rotation, d);
    }
    return arr;
  }

  function shuffle(arr) {
    for (var i = arr.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = arr[i];
      arr[i] = arr[j];
      arr[j] = tmp;
    }
  }

  var TILE_DEFS = [
    { id: 'm1', edges: [EDGE_FIELD, EDGE_FIELD, EDGE_FIELD, EDGE_FIELD], center: 'M', shield: false },
    { id: 'm2', edges: [EDGE_ROAD, EDGE_FIELD, EDGE_FIELD, EDGE_FIELD], center: 'M', shield: false },
    { id: 'm3', edges: [EDGE_ROAD, EDGE_FIELD, EDGE_FIELD, EDGE_FIELD], center: 'M', shield: false },

    { id: 'c1', edges: [EDGE_CITY, EDGE_CITY, EDGE_CITY, EDGE_CITY], center: 'C', shield: true },

    { id: 'c2', edges: [EDGE_CITY, EDGE_CITY, EDGE_CITY, EDGE_FIELD], center: 'C', shield: false },
    { id: 'c3', edges: [EDGE_CITY, EDGE_CITY, EDGE_CITY, EDGE_FIELD], center: 'C', shield: true },

    { id: 'c4', edges: [EDGE_CITY, EDGE_CITY, EDGE_FIELD, EDGE_FIELD], center: 'C', shield: false },
    { id: 'c5', edges: [EDGE_CITY, EDGE_CITY, EDGE_FIELD, EDGE_FIELD], center: 'C', shield: true },
    { id: 'c6', edges: [EDGE_CITY, EDGE_CITY, EDGE_FIELD, EDGE_FIELD], center: 'C', shield: false },

    { id: 'c7', edges: [EDGE_CITY, EDGE_FIELD, EDGE_CITY, EDGE_FIELD], center: 'F', shield: false },
    { id: 'c8', edges: [EDGE_CITY, EDGE_FIELD, EDGE_CITY, EDGE_FIELD], center: 'F', shield: false },

    { id: 'c9', edges: [EDGE_CITY, EDGE_FIELD, EDGE_FIELD, EDGE_FIELD], center: 'C', shield: false },
    { id: 'c10', edges: [EDGE_CITY, EDGE_FIELD, EDGE_FIELD, EDGE_FIELD], center: 'C', shield: false },
    { id: 'c11', edges: [EDGE_CITY, EDGE_FIELD, EDGE_FIELD, EDGE_FIELD], center: 'C', shield: false },
    { id: 'c12', edges: [EDGE_CITY, EDGE_FIELD, EDGE_FIELD, EDGE_FIELD], center: 'C', shield: false },

    { id: 'cr1', edges: [EDGE_CITY, EDGE_ROAD, EDGE_FIELD, EDGE_FIELD], center: 'C', shield: false },
    { id: 'cr2', edges: [EDGE_CITY, EDGE_ROAD, EDGE_FIELD, EDGE_FIELD], center: 'C', shield: false },
    { id: 'cr3', edges: [EDGE_CITY, EDGE_ROAD, EDGE_FIELD, EDGE_ROAD], center: 'C', shield: false },
    { id: 'cr4', edges: [EDGE_CITY, EDGE_ROAD, EDGE_ROAD, EDGE_FIELD], center: 'C', shield: false },
    { id: 'cr5', edges: [EDGE_CITY, EDGE_ROAD, EDGE_FIELD, EDGE_ROAD], center: 'C', shield: false },
    { id: 'cr6', edges: [EDGE_CITY, EDGE_ROAD, EDGE_ROAD, EDGE_FIELD], center: 'C', shield: false },

    { id: 'r1', edges: [EDGE_ROAD, EDGE_FIELD, EDGE_ROAD, EDGE_FIELD], center: 'R', shield: false },
    { id: 'r2', edges: [EDGE_ROAD, EDGE_FIELD, EDGE_ROAD, EDGE_FIELD], center: 'R', shield: false },
    { id: 'r3', edges: [EDGE_ROAD, EDGE_FIELD, EDGE_ROAD, EDGE_FIELD], center: 'R', shield: false },
    { id: 'r4', edges: [EDGE_ROAD, EDGE_FIELD, EDGE_ROAD, EDGE_FIELD], center: 'R', shield: false },
    { id: 'r5', edges: [EDGE_ROAD, EDGE_ROAD, EDGE_FIELD, EDGE_FIELD], center: 'R', shield: false },
    { id: 'r6', edges: [EDGE_ROAD, EDGE_ROAD, EDGE_FIELD, EDGE_FIELD], center: 'R', shield: false },
    { id: 'r7', edges: [EDGE_ROAD, EDGE_ROAD, EDGE_FIELD, EDGE_FIELD], center: 'R', shield: false },
    { id: 'r8', edges: [EDGE_ROAD, EDGE_ROAD, EDGE_FIELD, EDGE_FIELD], center: 'R', shield: false },
    { id: 'r9', edges: [EDGE_ROAD, EDGE_ROAD, EDGE_FIELD, EDGE_FIELD], center: 'R', shield: false },
    { id: 'rx', edges: [EDGE_ROAD, EDGE_ROAD, EDGE_ROAD, EDGE_ROAD], center: 'X', shield: false },

    { id: 'f1', edges: [EDGE_FIELD, EDGE_FIELD, EDGE_FIELD, EDGE_FIELD], center: 'F', shield: false },
    { id: 'f2', edges: [EDGE_ROAD, EDGE_FIELD, EDGE_FIELD, EDGE_FIELD], center: 'F', shield: false },
    { id: 'f3', edges: [EDGE_ROAD, EDGE_FIELD, EDGE_FIELD, EDGE_FIELD], center: 'F', shield: false },
    { id: 'f4', edges: [EDGE_ROAD, EDGE_ROAD, EDGE_FIELD, EDGE_FIELD], center: 'R', shield: false },
    { id: 'f5', edges: [EDGE_ROAD, EDGE_ROAD, EDGE_FIELD, EDGE_FIELD], center: 'R', shield: false },
    { id: 'f6', edges: [EDGE_ROAD, EDGE_FIELD, EDGE_ROAD, EDGE_FIELD], center: 'R', shield: false },
    { id: 'f7', edges: [EDGE_ROAD, EDGE_FIELD, EDGE_ROAD, EDGE_FIELD], center: 'R', shield: false }
  ];

  function buildDeck() {
    var deck = TILE_DEFS.slice();
    shuffle(deck);
    return deck;
  }

  function createStartTile() {
    return {
      id: START_TILE_ID,
      edges: [EDGE_ROAD, EDGE_FIELD, EDGE_ROAD, EDGE_FIELD],
      center: 'R',
      shield: false
    };
  }

  function createGame(playerNames) {
    var players = [];
    for (var i = 0; i < playerNames.length; i++) {
      players.push({
        index: i,
        name: playerNames[i],
        score: 0,
        meeples: 7,
        color: PLAYER_COLORS[i]
      });
    }

    var deck = buildDeck();
    var startTile = createStartTile();

    var board = {};
    board[posKey(0, 0)] = {
      tile: startTile,
      rotation: 0,
      meeple: null
    };

    var state = {
      players: players,
      playerCount: playerNames.length,
      currentPlayer: 0,
      phase: 'draw',
      board: board,
      deck: deck,
      deckIndex: 0,
      currentTile: null,
      currentRotation: 0,
      validPlacements: [],
      gameOver: false,
      log: [],
      placedMeepleThisTurn: false,
      consecutivePasses: 0
    };

    addLog(state, 'Game started with ' + playerNames.length + ' players.');

    var firstTile = deck[0];
    state.deckIndex = 1;
    state.currentTile = firstTile;
    state.currentRotation = 0;
    state.validPlacements = getValidPlacements(state, firstTile, 0);

    if (state.validPlacements.length === 0) {
      state.rotation = 0;
      for (var r = 0; r < 4 && state.validPlacements.length === 0; r++) {
        state.currentRotation = r;
        state.validPlacements = getValidPlacements(state, firstTile, r);
      }
    }

    state.phase = 'place';
    addLog(state, 'Player 1 (' + playerNames[0] + '): place the tile.');

    return state;
  }

  function addLog(state, msg) {
    state.log.unshift({
      text: msg,
      turn: state.currentPlayer,
      time: Date.now()
    });
    if (state.log.length > 50) {
      state.log.length = 50;
    }
  }

  function getValidPlacements(state, tileDef, rotation) {
    var valid = [];
    var board = state.board;
    var candidates = {};

    var boardKeys = Object.keys(board);
    for (var i = 0; i < boardKeys.length; i++) {
      var pos = parseKey(boardKeys[i]);
      for (var d = 0; d < 4; d++) {
        var n = neighborPos(pos.col, pos.row, d);
        var nk = posKey(n.col, n.row);
        if (!(nk in board)) {
          candidates[nk] = true;
        }
      }
    }

    var candKeys = Object.keys(candidates);
    for (var j = 0; j < candKeys.length; j++) {
      var ck = candKeys[j];
      var cp = parseKey(ck);
      if (isValidPlacement(board, tileDef, rotation, cp.col, cp.row)) {
        valid.push({ col: cp.col, row: cp.row });
      }
    }

    return valid;
  }

  function isValidPlacement(board, tileDef, rotation, col, row) {
    var key = posKey(col, row);
    if (key in board) return false;

    var hasAdjacent = false;
    for (var d = 0; d < 4; d++) {
      var nk = neighborKey(col, row, d);
      if (nk in board) {
        hasAdjacent = true;
        var nTile = board[nk];
        var myEdge = effectiveEdge(tileDef, rotation, d);
        var nEdge = effectiveEdge(nTile.tile, nTile.rotation, oppositeDir(d));
        if (myEdge !== nEdge) {
          return false;
        }
      }
    }

    return hasAdjacent;
  }

  function canPlaceTileAt(state, col, row) {
    if (!state.currentTile) return false;
    return isValidPlacement(state.board, state.currentTile, state.currentRotation, col, row);
  }

  function placeTile(state, col, row) {
    var key = posKey(col, row);
    state.board[key] = {
      tile: state.currentTile,
      rotation: state.currentRotation,
      meeple: null
    };
    state.placedMeepleThisTurn = false;
    addLog(state, 'Player ' + (state.currentPlayer + 1) + ' placed tile at (' + col + ',' + row + ').');
    state.phase = 'meeple';
  }

  function getFieldConnectedEdges(tileDef, rotation, entryEdge) {
    var edges = edgeArray(tileDef, rotation);
    var center = tileDef.center;

    if (edges[entryEdge] !== EDGE_FIELD) return [];

    var fieldEdges = [];
    for (var d = 0; d < 4; d++) {
      if (edges[d] === EDGE_FIELD) fieldEdges.push(d);
    }

    if (center === 'F' || center === 'M' || center === 'X') {
      return fieldEdges;
    }

    var barrierEdges = [];
    for (var d = 0; d < 4; d++) {
      if ((center === 'R' && edges[d] === EDGE_ROAD) ||
          (center === 'C' && edges[d] === EDGE_CITY)) {
        barrierEdges.push(d);
      }
    }

    if (barrierEdges.length <= 1) return fieldEdges;

    var sorted = barrierEdges.slice().sort(function (a, b) { return a - b; });

    for (var i = 0; i < sorted.length; i++) {
      var b1 = sorted[i];
      var b2 = sorted[(i + 1) % sorted.length];

      var groupEdges = [];
      for (var d = (b1 + 1) % 4; d !== b2; d = (d + 1) % 4) {
        if (edges[d] === EDGE_FIELD) groupEdges.push(d);
      }

      if (groupEdges.indexOf(entryEdge) !== -1) {
        return groupEdges;
      }
    }

    return [];
  }

  function findFieldComponent(state, col, row, startEdge) {
    var fieldEdges = {};
    var processed = {};

    var tile = state.board[posKey(col, row)];
    if (!tile) return { fieldEdges: {}, tiles: {} };

    var edges = edgeArray(tile.tile, tile.rotation);
    if (edges[startEdge] !== EDGE_FIELD) {
      for (var d = 0; d < 4; d++) {
        if (edges[d] === EDGE_FIELD) { startEdge = d; break; }
      }
      if (edges[startEdge] !== EDGE_FIELD) return { fieldEdges: {}, tiles: {} };
    }

    var queue = [{ col: col, row: row, entryEdge: startEdge }];

    while (queue.length > 0) {
      var item = queue.shift();
      var pk = posKey(item.col, item.row);
      var visitKey = pk + '|' + item.entryEdge;

      if (processed[visitKey]) continue;
      processed[visitKey] = true;

      var pt = state.board[pk];
      if (!pt) continue;

      var connected = getFieldConnectedEdges(pt.tile, pt.rotation, item.entryEdge);

      for (var i = 0; i < connected.length; i++) {
        var outEdge = connected[i];
        var edgeKey = posKey(item.col, item.row, outEdge);
        fieldEdges[edgeKey] = true;

        var n = neighborPos(item.col, item.row, outEdge);
        var nk = posKey(n.col, n.row);
        if (!(nk in state.board)) continue;

        var nt = state.board[nk];
        var inEdge = oppositeDir(outEdge);
        var ntEdge = effectiveEdge(nt.tile, nt.rotation, inEdge);

        if (ntEdge === EDGE_FIELD) {
          queue.push({ col: n.col, row: n.row, entryEdge: inEdge });
        }
      }
    }

    var tiles = {};
    var edgeKeys = Object.keys(fieldEdges);
    for (var j = 0; j < edgeKeys.length; j++) {
      var parts = edgeKeys[j].split(',');
      tiles[parts[0] + ',' + parts[1]] = true;
    }

    return { fieldEdges: fieldEdges, tiles: tiles };
  }

  function getTileFeatures(state, col, row) {
    var key = posKey(col, row);
    var placed = state.board[key];
    if (!placed) return [];

    var effEdges = edgeArray(placed.tile, placed.rotation);
    var features = [];

    if (placed.tile.center === 'M') {
      features.push({ type: 'monastery', label: 'Monastery' });
    }

    var cityEdges = [];
    var roadEdges = [];
    var fieldEdges = [];
    for (var d = 0; d < 4; d++) {
      if (effEdges[d] === EDGE_CITY) cityEdges.push(d);
      if (effEdges[d] === EDGE_ROAD) roadEdges.push(d);
      if (effEdges[d] === EDGE_FIELD) fieldEdges.push(d);
    }

    if (cityEdges.length > 0) {
      features.push({ type: 'city', edges: cityEdges, label: 'City (' + cityEdges.length + ' edges)' });
    }

    if (roadEdges.length > 0) {
      features.push({ type: 'road', edges: roadEdges, label: 'Road (' + roadEdges.length + ' edges)' });
    }

    if (fieldEdges.length > 0) {
      features.push({ type: 'field', edges: fieldEdges, label: 'Field' });
    }

    return features;
  }

  function getFeatureComponentKey(state, pos, featureType, startEdge) {
    if (featureType === 'monastery') {
      return 'monastery:' + posKey(pos.col, pos.row);
    }

    if (featureType === 'field') {
      var fieldResult = findFieldComponent(state, pos.col, pos.row, startEdge);
      if (!fieldResult || Object.keys(fieldResult.fieldEdges).length === 0) return '';
      var keys = Object.keys(fieldResult.fieldEdges);
      keys.sort();
      return 'field:' + keys.join('|');
    }

    var component = findComponent(state, pos.col, pos.row, startEdge);
    if (!component || component.size === 0) return '';

    var keys = [];
    component.forEach(function (k) { keys.push(k); });
    keys.sort();
    return featureType + ':' + keys.join('|');
  }

  function canPlaceMeepleOnFeature(state, col, row, featureType, featureEdge) {
    var placed = state.board[posKey(col, row)];
    if (!placed || placed.meeple) return false;

    var player = state.players[state.currentPlayer];
    if (player.meeples <= 0) return false;

    if (state.placedMeepleThisTurn) return false;

    var claimedFeatures = getAllClaimedFeatureKeys(state);

    var ourKey;
    if (featureType === 'monastery') {
      ourKey = 'monastery:' + posKey(col, row);
    } else {
      ourKey = getFeatureComponentKey(state, { col: col, row: row }, featureType, featureEdge);
    }

    if (ourKey && claimedFeatures[ourKey]) return false;

    return true;
  }

  function getAllClaimedFeatureKeys(state) {
    var claimed = {};
    var boardKeys = Object.keys(state.board);

    for (var i = 0; i < boardKeys.length; i++) {
      var bk = boardKeys[i];
      var pt = state.board[bk];
      if (pt.meeple) {
        var ck = getFeatureComponentKey(state, parseKey(bk), pt.meeple.featureType, pt.meeple.featureEdge);
        if (ck) claimed[ck] = true;
      }
    }

    return claimed;
  }

  function placeMeeple(state, col, row, featureType, featureEdge) {
    var key = posKey(col, row);
    var placed = state.board[key];
    if (!placed) return false;

    if (!canPlaceMeepleOnFeature(state, col, row, featureType, featureEdge)) return false;

    placed.meeple = {
      player: state.currentPlayer,
      featureType: featureType,
      featureEdge: featureEdge
    };

    state.players[state.currentPlayer].meeples--;
    state.placedMeepleThisTurn = true;

    addLog(state, 'Player ' + (state.currentPlayer + 1) + ' placed a meeple on ' + featureType + '.');
    return true;
  }

  function skipMeeple(state) {
    state.placedMeepleThisTurn = true;
    addLog(state, 'Player ' + (state.currentPlayer + 1) + ' skipped meeple placement.');
  }

  function endTurn(state) {
    if (!state.placedMeepleThisTurn && state.phase === 'meeple') {
      skipMeeple(state);
    }

    var scores = scorePlacement(state);

    for (var i = 0; i < scores.length; i++) {
      var s = scores[i];
      state.players[s.player].score += s.points;
      addLog(state, state.players[s.player].name + ' scored ' + s.points + ' pts from ' + s.reason + '.');
    }

    state.currentPlayer = (state.currentPlayer + 1) % state.playerCount;

    if (state.deckIndex >= state.deck.length) {
      var finalScores = finalScoring(state);
      for (var j = 0; j < finalScores.length; j++) {
        var fs = finalScores[j];
        state.players[fs.player].score += fs.points;
        addLog(state, state.players[fs.player].name + ' scored ' + fs.points + ' pts (final) from ' + fs.reason + '.');
      }
      state.gameOver = true;
      state.phase = 'gameover';
      return;
    }

    while (state.deckIndex < state.deck.length) {
      state.currentTile = state.deck[state.deckIndex];
      state.deckIndex++;
      state.currentRotation = 0;
      state.validPlacements = getValidPlacements(state, state.currentTile, 0);

      if (state.validPlacements.length === 0) {
        for (var r = 1; r < 4; r++) {
          state.currentRotation = r;
          state.validPlacements = getValidPlacements(state, state.currentTile, r);
          if (state.validPlacements.length > 0) break;
        }
      }

      if (state.validPlacements.length > 0) {
        state.consecutivePasses = 0;
        state.phase = 'place';
        addLog(state, 'Player ' + (state.currentPlayer + 1) + ' (' + state.players[state.currentPlayer].name + '): place the tile.');
        return;
      }

      addLog(state, 'Player ' + (state.currentPlayer + 1) + ' (' + state.players[state.currentPlayer].name + ') has no valid placements. Tile discarded.');
      state.consecutivePasses++;

      if (state.consecutivePasses >= state.playerCount * 2) {
        state.gameOver = true;
        state.phase = 'gameover';
        return;
      }

      state.currentPlayer = (state.currentPlayer + 1) % state.playerCount;
    }

    state.gameOver = true;
    state.phase = 'gameover';
  }

  function findComponent(state, col, row, edge) {
    var tile = state.board[posKey(col, row)];
    if (!tile) return null;

    var type = effectiveEdge(tile.tile, tile.rotation, edge);
    if (type === EDGE_FIELD) return null;

    var component = {};
    var queue = [posKey(col, row)];
    var processed = {};

    while (queue.length > 0) {
      var pk = queue.shift();
      if (processed[pk]) continue;
      processed[pk] = true;

      var pos = parseKey(pk);
      var pt = state.board[pk];
      if (!pt) continue;

      var edges = edgeArray(pt.tile, pt.rotation);
      var sameEdges = [];
      for (var d = 0; d < 4; d++) {
        if (edges[d] === type) {
          sameEdges.push(d);
        }
      }

      for (var i = 0; i < sameEdges.length; i++) {
        var e = sameEdges[i];
        component[posKey(pos.col, pos.row, e)] = true;

        var nk = neighborKey(pos.col, pos.row, e);
        if (nk in state.board && !processed[nk]) {
          var nt = state.board[nk];
          var ne = oppositeDir(e);
          var neType = effectiveEdge(nt.tile, nt.rotation, ne);
          if (neType === type) {
            queue.push(nk);
          }
        }
      }
    }

    return component;
  }

  function isComponentCompleted(state, component) {
    var keys = Object.keys(component);
    for (var i = 0; i < keys.length; i++) {
      var parts = keys[i].split(',');
      var col = parseInt(parts[0], 10);
      var row = parseInt(parts[1], 10);
      var edge = parseInt(parts[2], 10);
      var nk = neighborKey(col, row, edge);
      if (!(nk in state.board)) {
        return false;
      }
    }
    return true;
  }

  function isMonasteryCompleted(state, col, row) {
    for (var dc = -1; dc <= 1; dc++) {
      for (var dr = -1; dr <= 1; dr++) {
        if (dc === 0 && dr === 0) continue;
        var nk = posKey(col + dc, row + dr);
        if (!(nk in state.board)) return false;
      }
    }
    return true;
  }

  function countMonasteryNeighbors(state, col, row) {
    var count = 0;
    for (var dc = -1; dc <= 1; dc++) {
      for (var dr = -1; dr <= 1; dr++) {
        if (dc === 0 && dr === 0) continue;
        var nk = posKey(col + dc, row + dr);
        if (nk in state.board) count++;
      }
    }
    return count;
  }

  function scorePlacement(state) {
    var scores = [];

    var boardKeys = Object.keys(state.board);
    for (var i = 0; i < boardKeys.length; i++) {
      var pk = boardKeys[i];
      var placed = state.board[pk];
      if (!placed.meeple) continue;

      var pos = parseKey(pk);
      var mp = placed.meeple;

      if (mp.featureType === 'monastery') {
        if (isMonasteryCompleted(state, pos.col, pos.row)) {
          var pts = 9;
          scores.push({ player: mp.player, points: pts, reason: 'monastery at (' + pos.col + ',' + pos.row + ')' });
          placed.meeple = null;
          state.players[mp.player].meeples++;
        }
      } else if (mp.featureType === 'road' || mp.featureType === 'city') {
        var component = findComponent(state, pos.col, pos.row, mp.featureEdge);
        if (component && isComponentCompleted(state, component)) {
          var tileCount = componentTileCount(component);
          var shields = countShieldsInComponent(state, component);
          var pts = 0;
          if (mp.featureType === 'road') {
            pts = tileCount;
          } else if (mp.featureType === 'city') {
            pts = tileCount * 2 + shields * 2;
          }
          if (pts > 0) {
            scores.push({ player: mp.player, points: pts, reason: mp.featureType + ' at (' + pos.col + ',' + pos.row + ')' });
          }
          placed.meeple = null;
          state.players[mp.player].meeples++;
        }
      }
    }

    return combineScores(scores);
  }

  function componentTileCount(component) {
    var tiles = {};
    var keys = Object.keys(component);
    for (var i = 0; i < keys.length; i++) {
      var parts = keys[i].split(',');
      tiles[parts[0] + ',' + parts[1]] = true;
    }
    return Object.keys(tiles).length;
  }

  function countShieldsInComponent(state, component) {
    var tiles = {};
    var keys = Object.keys(component);
    for (var i = 0; i < keys.length; i++) {
      var parts = keys[i].split(',');
      tiles[parts[0] + ',' + parts[1]] = true;
    }
    var count = 0;
    var tileKeys = Object.keys(tiles);
    for (var j = 0; j < tileKeys.length; j++) {
      var pt = state.board[tileKeys[j]];
      if (pt && pt.tile.shield) {
        count++;
      }
    }
    return count;
  }

  function combineScores(scores) {
    var combined = [];
    var byPlayer = {};
    for (var i = 0; i < scores.length; i++) {
      var s = scores[i];
      if (!byPlayer[s.player]) {
        byPlayer[s.player] = { player: s.player, points: 0, reason: '' };
      }
      byPlayer[s.player].points += s.points;
      if (byPlayer[s.player].reason) {
        byPlayer[s.player].reason += ', ';
      }
      byPlayer[s.player].reason += s.reason;
    }
    var pKeys = Object.keys(byPlayer);
    for (var j = 0; j < pKeys.length; j++) {
      combined.push(byPlayer[pKeys[j]]);
    }
    return combined;
  }

  function finalScoring(state) {
    var scores = [];

    var boardKeys = Object.keys(state.board);
    for (var i = 0; i < boardKeys.length; i++) {
      var pk = boardKeys[i];
      var placed = state.board[pk];
      if (!placed.meeple) continue;

      var pos = parseKey(pk);
      var mp = placed.meeple;

      if (mp.featureType === 'monastery') {
        var nCount = countMonasteryNeighbors(state, pos.col, pos.row);
        var pts = nCount + 1;
        scores.push({ player: mp.player, points: pts, reason: 'incomplete monastery' });
        placed.meeple = null;
      } else if (mp.featureType === 'road') {
        var compR = findComponent(state, pos.col, pos.row, mp.featureEdge);
        if (compR) {
          var tc = componentTileCount(compR);
          scores.push({ player: mp.player, points: tc, reason: 'incomplete road' });
        }
        placed.meeple = null;
      } else if (mp.featureType === 'city') {
        var compC = findComponent(state, pos.col, pos.row, mp.featureEdge);
        if (compC) {
          var tc = componentTileCount(compC);
          var sh = countShieldsInComponent(state, compC);
          scores.push({ player: mp.player, points: tc + sh, reason: 'incomplete city' });
        }
        placed.meeple = null;
      } else if (mp.featureType === 'field') {
        var adjCities = findAdjacentCompletedCities(state, pos.col, pos.row, mp.featureEdge);
        var pts = adjCities * 3;
        if (pts > 0) {
          scores.push({ player: mp.player, points: pts, reason: 'field with ' + adjCities + ' completed cities' });
        }
        placed.meeple = null;
      }
    }

    return combineScores(scores);
  }

  function findAdjacentCompletedCities(state, col, row, startEdge) {
    var fieldResult = findFieldComponent(state, col, row, startEdge);
    if (!fieldResult || Object.keys(fieldResult.tiles).length === 0) return 0;

    var countedCities = {};
    var cityCount = 0;

    var tileKeys = Object.keys(fieldResult.tiles);
    for (var i = 0; i < tileKeys.length; i++) {
      var pk = tileKeys[i];
      var pos = parseKey(pk);
      var pt = state.board[pk];
      if (!pt) continue;

      var edges = edgeArray(pt.tile, pt.rotation);
      for (var d = 0; d < 4; d++) {
        if (edges[d] === EDGE_CITY) {
          var cityComp = findComponent(state, pos.col, pos.row, d);
          if (cityComp && isComponentCompleted(state, cityComp)) {
            var cityKey = getSortedComponentKey(cityComp);
            if (!countedCities[cityKey]) {
              countedCities[cityKey] = true;
              cityCount++;
            }
          }
        }
      }
    }

    return cityCount;
  }

  function getSortedComponentKey(component) {
    var keys = Object.keys(component);
    keys.sort();
    return keys.join('|');
  }

  function getCurrentPlayer(state) {
    return state.players[state.currentPlayer];
  }

  function getWinner(state) {
    if (!state.gameOver) return null;
    var sorted = state.players.slice().sort(function (a, b) { return b.score - a.score; });
    return sorted[0];
  }

  function getAllFinalScores(state) {
    return state.players.slice().sort(function (a, b) { return b.score - a.score; });
  }

  var PLAYER_COLORS = ['#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6'];
  var PLAYER_COLORS_LIGHT = ['#f5b7b1', '#aed6f1', '#a9dfbf', '#f9e79f', '#d7bde2'];

  function getPlayerColor(idx) {
    return PLAYER_COLORS[idx % PLAYER_COLORS.length];
  }

  function getPlayerColorLight(idx) {
    return PLAYER_COLORS_LIGHT[idx % PLAYER_COLORS_LIGHT.length];
  }

  function getEdgeDescription(d) {
    return ['N', 'E', 'S', 'W'][d];
  }

  window.Carcassonne = {
    EDGE_CITY: EDGE_CITY,
    EDGE_ROAD: EDGE_ROAD,
    EDGE_FIELD: EDGE_FIELD,
    DIR_N: DIR_N,
    DIR_E: DIR_E,
    DIR_S: DIR_S,
    DIR_W: DIR_W,
    TILE_DEFS: TILE_DEFS,

    posKey: posKey,
    parseKey: parseKey,
    neighborPos: neighborPos,
    effectiveEdge: effectiveEdge,
    edgeArray: edgeArray,

    createGame: createGame,
    getValidPlacements: getValidPlacements,
    isValidPlacement: isValidPlacement,
    canPlaceTileAt: canPlaceTileAt,
    placeTile: placeTile,
    getTileFeatures: getTileFeatures,
    canPlaceMeepleOnFeature: canPlaceMeepleOnFeature,
    placeMeeple: placeMeeple,
    skipMeeple: skipMeeple,
    endTurn: endTurn,
    findComponent: findComponent,
    isComponentCompleted: isComponentCompleted,
    finalScoring: finalScoring,
    getCurrentPlayer: getCurrentPlayer,
    getWinner: getWinner,
    getAllFinalScores: getAllFinalScores,
    getPlayerColor: getPlayerColor,
    getPlayerColorLight: getPlayerColorLight,
    getEdgeDescription: getEdgeDescription,
    getAllClaimedFeatureKeys: getAllClaimedFeatureKeys,
    getFeatureComponentKey: getFeatureComponentKey,
    PLAYER_COLORS: PLAYER_COLORS
  };
})();
