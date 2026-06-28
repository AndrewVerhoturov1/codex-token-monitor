(function () {
  'use strict';

  var EDGE_CITY = 'C';
  var EDGE_ROAD = 'R';
  var EDGE_FIELD = 'F';
  var DIRS = [
    { name: 'N', dc: 0, dr: -1 },
    { name: 'E', dc: 1, dr: 0 },
    { name: 'S', dc: 0, dr: 1 },
    { name: 'W', dc: -1, dr: 0 }
  ];
  var PLAYER_COLORS = ['#d33f49', '#2f76d2', '#248c4f', '#7f4ac8', '#dd8a18'];

  function key(col, row) { return col + ',' + row; }
  function parseKey(value) {
    var parts = value.split(',');
    return { col: Number(parts[0]), row: Number(parts[1]) };
  }
  function opposite(dir) { return (dir + 2) % 4; }
  function neighbor(col, row, dir) {
    return { col: col + DIRS[dir].dc, row: row + DIRS[dir].dr };
  }
  function localDirFromWorld(rotation, worldDir) { return (worldDir - rotation + 4) % 4; }
  function worldDirFromLocal(rotation, localDir) { return (localDir + rotation) % 4; }
  function edgeAt(tile, rotation, worldDir) { return tile.edges[localDirFromWorld(rotation, worldDir)]; }
  function copyEdges(tile, rotation) {
    var edges = [];
    for (var dir = 0; dir < 4; dir += 1) edges.push(edgeAt(tile, rotation, dir));
    return edges;
  }
  function groupForLocalDir(tile, featureType, localDir) {
    var groups = featureType === 'road' ? tile.roads : tile.cities;
    for (var i = 0; i < groups.length; i += 1) {
      if (groups[i].indexOf(localDir) !== -1) return i;
    }
    return -1;
  }
  function uniqueCountFromNodes(nodes) {
    var seen = {};
    nodes.forEach(function (nodeId) {
      seen[nodeId.split('|')[0]] = true;
    });
    return Object.keys(seen).length;
  }
  function cloneTileDef(def) {
    return {
      id: def.id,
      title: def.title,
      edges: def.edges.slice(),
      center: def.center,
      roads: def.roads.map(function (g) { return g.slice(); }),
      cities: def.cities.map(function (g) { return g.slice(); }),
      monastery: !!def.monastery,
      shield: !!def.shield
    };
  }
  function expandTiles(patterns) {
    var result = [];
    patterns.forEach(function (def) {
      for (var i = 0; i < def.count; i += 1) {
        var copy = cloneTileDef(def);
        copy.id = def.id + '-' + (i + 1);
        result.push(copy);
      }
    });
    return result;
  }
  function shuffle(list) {
    for (var i = list.length - 1; i > 0; i -= 1) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = list[i];
      list[i] = list[j];
      list[j] = tmp;
    }
    return list;
  }

  var TILE_PATTERNS = [
    { id: 'city-full', title: 'Большой город', count: 2, edges: [EDGE_CITY, EDGE_CITY, EDGE_CITY, EDGE_CITY], center: 'C', cities: [[0, 1, 2, 3]], roads: [], shield: true },
    { id: 'city-cap', title: 'Городская стена', count: 5, edges: [EDGE_CITY, EDGE_FIELD, EDGE_FIELD, EDGE_FIELD], center: 'C', cities: [[0]], roads: [], shield: false },
    { id: 'city-cap-road', title: 'Город и дорога', count: 4, edges: [EDGE_CITY, EDGE_FIELD, EDGE_ROAD, EDGE_FIELD], center: 'R', cities: [[0]], roads: [[2]], shield: false },
    { id: 'city-corner', title: 'Угол города', count: 4, edges: [EDGE_CITY, EDGE_CITY, EDGE_FIELD, EDGE_FIELD], center: 'C', cities: [[0, 1]], roads: [], shield: false },
    { id: 'city-corner-shield', title: 'Угол города с гербом', count: 2, edges: [EDGE_CITY, EDGE_CITY, EDGE_FIELD, EDGE_FIELD], center: 'C', cities: [[0, 1]], roads: [], shield: true },
    { id: 'city-line', title: 'Две стены города', count: 3, edges: [EDGE_CITY, EDGE_FIELD, EDGE_CITY, EDGE_FIELD], center: 'F', cities: [[0], [2]], roads: [], shield: false },
    { id: 'city-three', title: 'Три стороны города', count: 3, edges: [EDGE_CITY, EDGE_CITY, EDGE_CITY, EDGE_FIELD], center: 'C', cities: [[0, 1, 2]], roads: [], shield: true },
    { id: 'road-straight', title: 'Прямая дорога', count: 8, edges: [EDGE_ROAD, EDGE_FIELD, EDGE_ROAD, EDGE_FIELD], center: 'R', cities: [], roads: [[0, 2]], shield: false },
    { id: 'road-curve', title: 'Поворот дороги', count: 8, edges: [EDGE_ROAD, EDGE_ROAD, EDGE_FIELD, EDGE_FIELD], center: 'R', cities: [], roads: [[0, 1]], shield: false },
    { id: 'road-t', title: 'Развилка', count: 4, edges: [EDGE_ROAD, EDGE_ROAD, EDGE_ROAD, EDGE_FIELD], center: 'X', cities: [], roads: [[0], [1], [2]], shield: false },
    { id: 'road-cross', title: 'Перекрёсток', count: 2, edges: [EDGE_ROAD, EDGE_ROAD, EDGE_ROAD, EDGE_ROAD], center: 'X', cities: [], roads: [[0], [1], [2], [3]], shield: false },
    { id: 'monastery', title: 'Монастырь', count: 3, edges: [EDGE_FIELD, EDGE_FIELD, EDGE_FIELD, EDGE_FIELD], center: 'M', cities: [], roads: [], monastery: true, shield: false },
    { id: 'monastery-road', title: 'Монастырь с дорогой', count: 3, edges: [EDGE_ROAD, EDGE_FIELD, EDGE_FIELD, EDGE_FIELD], center: 'M', cities: [], roads: [[0]], monastery: true, shield: false },
    { id: 'field', title: 'Луга', count: 5, edges: [EDGE_FIELD, EDGE_FIELD, EDGE_FIELD, EDGE_FIELD], center: 'F', cities: [], roads: [], shield: false },
    { id: 'city-road-left', title: 'Город и поворот дороги', count: 4, edges: [EDGE_CITY, EDGE_ROAD, EDGE_FIELD, EDGE_ROAD], center: 'R', cities: [[0]], roads: [[1, 3]], shield: false },
    { id: 'city-road-corner', title: 'Город и дорога у стены', count: 3, edges: [EDGE_CITY, EDGE_ROAD, EDGE_ROAD, EDGE_FIELD], center: 'R', cities: [[0]], roads: [[1, 2]], shield: false }
  ];

  var START_TILE = {
    id: 'start',
    title: 'Стартовый тайл',
    edges: [EDGE_CITY, EDGE_ROAD, EDGE_ROAD, EDGE_ROAD],
    center: 'R',
    roads: [[1, 2, 3]],
    cities: [[0]],
    monastery: false,
    shield: false
  };

  function createDeck() { return shuffle(expandTiles(TILE_PATTERNS)); }

  function addLog(state, text) {
    state.log.unshift({ text: text, at: new Date().toISOString() });
    if (state.log.length > 80) state.log.length = 80;
  }

  function createPlayers(names) {
    return names.map(function (name, index) {
      return {
        id: index,
        name: name || ('Игрок ' + (index + 1)),
        color: PLAYER_COLORS[index],
        score: 0,
        meeples: 7
      };
    });
  }

  function createGame(names) {
    var playerNames = names && names.length ? names.slice(0, 5) : ['Игрок 1', 'Игрок 2'];
    if (playerNames.length < 2) playerNames = ['Игрок 1', 'Игрок 2'];
    var state = {
      players: createPlayers(playerNames),
      currentPlayer: 0,
      board: {},
      deck: createDeck(),
      currentTile: null,
      currentRotation: 0,
      validPlacements: [],
      phase: 'setup',
      lastPlaced: null,
      log: [],
      skippedTiles: 0,
      rotationRevision: 0,
      gameOver: false
    };
    state.board[key(0, 0)] = { tile: cloneTileDef(START_TILE), rotation: 0, meeple: null };
    addLog(state, 'Партия началась. Стартовый тайл лежит в центре поля.');
    drawNextTile(state);
    return state;
  }

  function boardHasNeighbor(board, col, row) {
    for (var dir = 0; dir < 4; dir += 1) {
      var n = neighbor(col, row, dir);
      if (board[key(n.col, n.row)]) return true;
    }
    return false;
  }

  function canPlaceTile(board, tile, rotation, col, row) {
    if (board[key(col, row)]) return false;
    if (!boardHasNeighbor(board, col, row)) return false;
    for (var dir = 0; dir < 4; dir += 1) {
      var n = neighbor(col, row, dir);
      var neighborTile = board[key(n.col, n.row)];
      if (!neighborTile) continue;
      if (edgeAt(tile, rotation, dir) !== edgeAt(neighborTile.tile, neighborTile.rotation, opposite(dir))) return false;
    }
    return true;
  }

  function candidatePositions(board) {
    var result = {};
    Object.keys(board).forEach(function (boardKey) {
      var pos = parseKey(boardKey);
      for (var dir = 0; dir < 4; dir += 1) {
        var n = neighbor(pos.col, pos.row, dir);
        var nk = key(n.col, n.row);
        if (!board[nk]) result[nk] = { col: n.col, row: n.row };
      }
    });
    return Object.keys(result).map(function (itemKey) { return result[itemKey]; });
  }

  function getValidPlacements(state, tile, rotation) {
    return candidatePositions(state.board).filter(function (pos) {
      return canPlaceTile(state.board, tile, rotation, pos.col, pos.row);
    });
  }

  function getAllValidRotations(state, tile) {
    var rotations = [];
    for (var rotation = 0; rotation < 4; rotation += 1) {
      var placements = getValidPlacements(state, tile, rotation);
      if (placements.length > 0) rotations.push({ rotation: rotation, placements: placements });
    }
    return rotations;
  }

  function drawNextTile(state) {
    state.lastPlaced = null;
    state.currentTile = null;
    state.validPlacements = [];
    if (state.deck.length === 0) {
      finishGame(state);
      return;
    }
    while (state.deck.length > 0) {
      var tile = state.deck.shift();
      var rotations = getAllValidRotations(state, tile);
      if (rotations.length === 0) {
        state.skippedTiles += 1;
        addLog(state, 'Тайл «' + tile.title + '» сброшен: нет законного места.');
        continue;
      }
      state.currentTile = tile;
      state.currentRotation = rotations[0].rotation;
      state.validPlacements = rotations[0].placements;
      state.rotationRevision = 0;
      state.phase = 'place';
      addLog(state, state.players[state.currentPlayer].name + ': разместите «' + tile.title + '».');
      return;
    }
    finishGame(state);
  }

  function rotateCurrentTile(state) {
    if (state.phase !== 'place' || !state.currentTile) return false;
    state.currentRotation = (state.currentRotation + 1) % 4;
    state.validPlacements = getValidPlacements(state, state.currentTile, state.currentRotation);
    state.rotationRevision = (state.rotationRevision || 0) + 1;
    return true;
  }

  function placeTile(state, col, row) {
    if (state.phase !== 'place' || !state.currentTile) return false;
    if (!canPlaceTile(state.board, state.currentTile, state.currentRotation, col, row)) return false;
    state.board[key(col, row)] = { tile: state.currentTile, rotation: state.currentRotation, meeple: null };
    state.lastPlaced = { col: col, row: row };
    state.phase = 'meeple';
    addLog(state, state.players[state.currentPlayer].name + ' поставил(а) тайл на ' + col + ':' + row + '.');
    return true;
  }

  function componentNodeId(tileKey, groupIndex) { return tileKey + '|' + groupIndex; }

  function findComponent(state, startCol, startRow, featureType, groupIndex) {
    var startKey = key(startCol, startRow);
    var queue = [componentNodeId(startKey, groupIndex)];
    var nodes = {};
    var tileKeys = {};
    var meeples = [];
    var openEdges = 0;
    var shieldTiles = {};

    while (queue.length > 0) {
      var nodeId = queue.shift();
      if (nodes[nodeId]) continue;
      nodes[nodeId] = true;
      var parts = nodeId.split('|');
      var tileKey = parts[0];
      var group = Number(parts[1]);
      var placed = state.board[tileKey];
      if (!placed) continue;
      tileKeys[tileKey] = true;
      if (featureType === 'city' && placed.tile.shield) shieldTiles[tileKey] = true;
      if (placed.meeple && placed.meeple.type === featureType && placed.meeple.groupIndex === group) {
        meeples.push({ player: placed.meeple.player, tileKey: tileKey });
      }

      var localEdges = featureType === 'road' ? placed.tile.roads[group] : placed.tile.cities[group];
      for (var i = 0; i < localEdges.length; i += 1) {
        var localDir = localEdges[i];
        var worldDir = worldDirFromLocal(placed.rotation, localDir);
        var pos = parseKey(tileKey);
        var n = neighbor(pos.col, pos.row, worldDir);
        var nk = key(n.col, n.row);
        var neighborTile = state.board[nk];
        if (!neighborTile) {
          openEdges += 1;
          continue;
        }
        var neighborWorldDir = opposite(worldDir);
        if (edgeAt(neighborTile.tile, neighborTile.rotation, neighborWorldDir) !== (featureType === 'road' ? EDGE_ROAD : EDGE_CITY)) {
          openEdges += 1;
          continue;
        }
        var neighborLocalDir = localDirFromWorld(neighborTile.rotation, neighborWorldDir);
        var neighborGroup = groupForLocalDir(neighborTile.tile, featureType, neighborLocalDir);
        if (neighborGroup >= 0) {
          var nextId = componentNodeId(nk, neighborGroup);
          if (!nodes[nextId]) queue.push(nextId);
        }
      }
    }

    return {
      type: featureType,
      nodes: Object.keys(nodes).sort(),
      tileKeys: Object.keys(tileKeys).sort(),
      meeples: meeples,
      openEdges: openEdges,
      shieldCount: Object.keys(shieldTiles).length,
      complete: openEdges === 0
    };
  }

  function monasteryInfo(state, col, row) {
    var filled = 0;
    for (var dc = -1; dc <= 1; dc += 1) {
      for (var dr = -1; dr <= 1; dr += 1) {
        if (dc === 0 && dr === 0) continue;
        if (state.board[key(col + dc, row + dr)]) filled += 1;
      }
    }
    return { adjacent: filled, complete: filled === 8 };
  }

  function getTileFeatures(state, col, row) {
    var placed = state.board[key(col, row)];
    if (!placed) return [];
    var features = [];
    var i;
    for (i = 0; i < placed.tile.cities.length; i += 1) {
      features.push({ type: 'city', groupIndex: i, label: 'город ' + (placed.tile.cities.length > 1 ? (i + 1) : '') });
    }
    for (i = 0; i < placed.tile.roads.length; i += 1) {
      features.push({ type: 'road', groupIndex: i, label: 'дорога ' + (placed.tile.roads.length > 1 ? (i + 1) : '') });
    }
    if (placed.tile.monastery) features.push({ type: 'monastery', groupIndex: 0, label: 'монастырь' });
    return features;
  }

  function canPlaceMeeple(state, feature) {
    if (state.phase !== 'meeple' || !state.lastPlaced) return false;
    var placed = state.board[key(state.lastPlaced.col, state.lastPlaced.row)];
    if (!placed || placed.meeple) return false;
    if (state.players[state.currentPlayer].meeples <= 0) return false;
    if (feature.type === 'monastery') return true;
    var component = findComponent(state, state.lastPlaced.col, state.lastPlaced.row, feature.type, feature.groupIndex);
    return component.meeples.length === 0;
  }

  function placeMeeple(state, feature) {
    if (!canPlaceMeeple(state, feature)) return false;
    var placed = state.board[key(state.lastPlaced.col, state.lastPlaced.row)];
    placed.meeple = { player: state.currentPlayer, type: feature.type, groupIndex: feature.groupIndex };
    state.players[state.currentPlayer].meeples -= 1;
    addLog(state, state.players[state.currentPlayer].name + ' поставил(а) мипла на ' + featureLabel(feature.type) + '.');
    endTurn(state);
    return true;
  }

  function skipMeeple(state) {
    if (state.phase !== 'meeple') return false;
    addLog(state, state.players[state.currentPlayer].name + ' не ставит мипла.');
    endTurn(state);
    return true;
  }

  function featureLabel(type) {
    if (type === 'city') return 'город';
    if (type === 'road') return 'дорогу';
    if (type === 'monastery') return 'монастырь';
    return type;
  }

  function featurePoints(component, finalScoring) {
    if (component.type === 'road') return component.tileKeys.length;
    if (component.type === 'city') {
      var tiles = component.tileKeys.length;
      if (finalScoring) return tiles + component.shieldCount;
      return (tiles * 2) + (component.shieldCount * 2);
    }
    return 0;
  }

  function awardFeature(state, component, points, reason) {
    if (!component.meeples.length || points <= 0) return [];
    var counts = {};
    component.meeples.forEach(function (m) { counts[m.player] = (counts[m.player] || 0) + 1; });
    var max = Math.max.apply(null, Object.keys(counts).map(function (p) { return counts[p]; }));
    var winners = Object.keys(counts).filter(function (p) { return counts[p] === max; }).map(Number);
    winners.forEach(function (playerId) {
      state.players[playerId].score += points;
      addLog(state, state.players[playerId].name + ' получает ' + points + ' очк. за ' + reason + '.');
    });
    return winners;
  }

  function returnMeeplesFromComponent(state, component) {
    component.nodes.forEach(function (nodeId) {
      var tileKey = nodeId.split('|')[0];
      var placed = state.board[tileKey];
      if (placed && placed.meeple && placed.meeple.type === component.type) {
        state.players[placed.meeple.player].meeples += 1;
        placed.meeple = null;
      }
    });
  }

  function canonicalComponentKey(component) { return component.type + ':' + component.nodes.join(';'); }

  function scoreCompletedFeatures(state) {
    var checked = {};
    Object.keys(state.board).forEach(function (tileKey) {
      var placed = state.board[tileKey];
      if (!placed.meeple) return;
      var pos = parseKey(tileKey);
      if (placed.meeple.type === 'monastery') {
        var info = monasteryInfo(state, pos.col, pos.row);
        if (info.complete) {
          state.players[placed.meeple.player].score += 9;
          state.players[placed.meeple.player].meeples += 1;
          placed.meeple = null;
          addLog(state, state.players[state.currentPlayer].name + ' завершил(а) монастырь: +9 очк. владельцу.');
        }
        return;
      }
      var component = findComponent(state, pos.col, pos.row, placed.meeple.type, placed.meeple.groupIndex);
      var compKey = canonicalComponentKey(component);
      if (checked[compKey]) return;
      checked[compKey] = true;
      if (!component.complete) return;
      var points = featurePoints(component, false);
      awardFeature(state, component, points, component.type === 'city' ? 'завершённый город' : 'завершённую дорогу');
      returnMeeplesFromComponent(state, component);
    });
  }

  function endTurn(state) {
    scoreCompletedFeatures(state);
    if (state.gameOver) return;
    state.currentPlayer = (state.currentPlayer + 1) % state.players.length;
    drawNextTile(state);
  }

  function finishGame(state) {
    if (state.gameOver) return;
    state.phase = 'gameover';
    state.currentTile = null;
    state.validPlacements = [];
    state.gameOver = true;
    var checked = {};

    Object.keys(state.board).forEach(function (tileKey) {
      var placed = state.board[tileKey];
      if (!placed.meeple) return;
      var pos = parseKey(tileKey);
      if (placed.meeple.type === 'monastery') {
        var info = monasteryInfo(state, pos.col, pos.row);
        var points = 1 + info.adjacent;
        state.players[placed.meeple.player].score += points;
        state.players[placed.meeple.player].meeples += 1;
        addLog(state, state.players[placed.meeple.player].name + ' получает ' + points + ' очк. за незавершённый монастырь.');
        placed.meeple = null;
        return;
      }
      var component = findComponent(state, pos.col, pos.row, placed.meeple.type, placed.meeple.groupIndex);
      var compKey = canonicalComponentKey(component);
      if (checked[compKey]) return;
      checked[compKey] = true;
      var finalPoints = featurePoints(component, true);
      awardFeature(state, component, finalPoints, component.type === 'city' ? 'незавершённый город' : 'незавершённую дорогу');
      returnMeeplesFromComponent(state, component);
    });

    var leaders = state.players.slice().sort(function (a, b) { return b.score - a.score; });
    addLog(state, 'Игра окончена. Победитель: ' + leaders[0].name + ' (' + leaders[0].score + ' очк.).');
  }

  function getFeatureOptions(state) {
    if (state.phase !== 'meeple' || !state.lastPlaced) return [];
    return getTileFeatures(state, state.lastPlaced.col, state.lastPlaced.row).map(function (feature) {
      return {
        type: feature.type,
        groupIndex: feature.groupIndex,
        label: feature.label.replace(/\s+$/, ''),
        available: canPlaceMeeple(state, feature)
      };
    });
  }

  function sortedPlayers(state) {
    return state.players.slice().sort(function (a, b) {
      if (b.score !== a.score) return b.score - a.score;
      return a.id - b.id;
    });
  }

  window.Carcassonne = {
    constants: { EDGE_CITY: EDGE_CITY, EDGE_ROAD: EDGE_ROAD, EDGE_FIELD: EDGE_FIELD },
    createGame: createGame,
    rotateCurrentTile: rotateCurrentTile,
    placeTile: placeTile,
    placeMeeple: placeMeeple,
    skipMeeple: skipMeeple,
    copyEdges: copyEdges,
    getValidPlacements: getValidPlacements,
    getFeatureOptions: getFeatureOptions,
    getTileFeatures: getTileFeatures,
    sortedPlayers: sortedPlayers,
    canPlaceMeeple: canPlaceMeeple,
    edgeAt: edgeAt
  };
}());
