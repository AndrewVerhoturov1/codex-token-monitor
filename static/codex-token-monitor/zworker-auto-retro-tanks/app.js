(() => {
  'use strict';

  const canvas = document.getElementById('game');
  const ctx = canvas.getContext('2d', { alpha: false });
  ctx.imageSmoothingEnabled = false;

  const ui = {
    score: document.getElementById('score'),
    lives: document.getElementById('lives'),
    enemies: document.getElementById('enemies'),
    wave: document.getElementById('wave'),
    base: document.getElementById('base'),
    message: document.getElementById('message'),
    restart: document.getElementById('restart')
  };

  const W = canvas.width;
  const H = canvas.height;
  const TILE = 48;
  const COLS = W / TILE;
  const ROWS = H / TILE;
  const TANK = 38;
  const BULLET = 8;
  const keys = new Set();

  const COLORS = {
    bg: '#101512', grid: '#151d18', brick: '#a4422f', brickHi: '#e06945',
    steel: '#76828c', steelHi: '#c0cad1', player: '#f4d35e', playerHi: '#fff1a8',
    enemy: '#e84545', enemyHi: '#ff8c72', enemyAlt: '#7ddc7a', bullet: '#fff7c2',
    base: '#f2c14e', white: '#f5f1dc', black: '#080a09'
  };

  // 16 x 14: 0 empty, B destructible brick, S indestructible steel.
  const LEVEL = [
    '0000000000000000',
    '0B00B0000B00B000',
    '0B00B0SS0B00B0B0',
    '0000000000000000',
    'BB0BBB00BBB0BB00',
    '000B000000B00000',
    '0S0B0SS00B0S0S00',
    '000000BB00000000',
    '0BB0B0000B0BB0B0',
    '0000B0SS0B000000',
    'BB0000000000BB00',
    '000B0BBBB0B00000',
    '0B0000B0B0000B00',
    '000000BEB0000000'
  ];

  let state;
  let gameSerial = 0;
  let lastTime = 0;
  let accumulator = 0;
  const STEP = 1 / 60;

  const rand = (min, max) => Math.random() * (max - min) + min;
  const clamp = (v, min, max) => Math.max(min, Math.min(max, v));
  const rectsOverlap = (a, b, pad = 0) =>
    a.x + pad < b.x + b.w && a.x + a.w - pad > b.x &&
    a.y + pad < b.y + b.h && a.y + a.h - pad > b.y;

  function tileRect(col, row) { return { x: col * TILE, y: row * TILE, w: TILE, h: TILE }; }

  function buildWalls() {
    const walls = [];
    let base = { x: 7 * TILE + 6, y: 13 * TILE + 6, w: 36, h: 36, alive: true };
    LEVEL.forEach((line, row) => [...line].forEach((cell, col) => {
      if (cell === 'B' || cell === 'S') walls.push({ ...tileRect(col, row), type: cell === 'B' ? 'brick' : 'steel', hp: cell === 'B' ? 2 : Infinity });
      if (cell === 'E') base = { x: col * TILE + 6, y: row * TILE + 6, w: 36, h: 36, alive: true };
    }));
    return { walls, base };
  }

  function makeTank(x, y, kind, dir = 'up') {
    return {
      x, y, w: TANK, h: TANK, kind, dir,
      speed: kind === 'player' ? 150 : rand(72, 98),
      cooldown: kind === 'player' ? 0 : rand(.3, 1.2),
      think: rand(.2, 1.2),
      invincible: kind === 'player' ? 2.3 : .65,
      alive: true,
      flash: 0
    };
  }

  function resetGame() {
    const built = buildWalls();
    state = {
      id: ++gameSerial,
      player: makeTank(7 * TILE + 5, 12 * TILE + 5, 'player'),
      enemies: [], bullets: [], sparks: [], walls: built.walls, base: built.base,
      score: 0, lives: 3, remaining: 12, spawned: 0, wave: 1,
      spawnTimer: .2, paused: false, gameOver: false, victory: false,
      shake: 0, banner: 1.8
    };
    keys.clear();
    updateHud();
    hideMessage();
  }

  function updateHud() {
    ui.score.textContent = String(state.score).padStart(6, '0');
    ui.lives.textContent = state.lives;
    ui.enemies.textContent = state.remaining;
    ui.wave.textContent = String(state.wave).padStart(2, '0');
    ui.base.textContent = state.base.alive ? 'OK' : 'LOST';
    ui.base.style.color = state.base.alive ? '#7ee787' : '#ef3d32';
  }

  function showMessage(title, subtitle = '') {
    ui.message.innerHTML = `${title}${subtitle ? `<small>${subtitle}</small>` : ''}`;
    ui.message.classList.add('show');
  }
  function hideMessage() { ui.message.classList.remove('show'); }

  function obstacleAt(rect, ignore = null) {
    if (rect.x < 0 || rect.y < 0 || rect.x + rect.w > W || rect.y + rect.h > H) return true;
    if (state.walls.some(w => rectsOverlap(rect, w, 2))) return true;
    if (state.base.alive && rectsOverlap(rect, state.base, 1)) return true;
    const tanks = [state.player, ...state.enemies];
    return tanks.some(t => t !== ignore && t.alive && rectsOverlap(rect, t, 5));
  }

  function moveTank(tank, dx, dy, dt) {
    if (!tank.alive) return false;
    const nextX = { ...tank, x: tank.x + dx * tank.speed * dt };
    let moved = false;
    if (!obstacleAt(nextX, tank)) { tank.x = nextX.x; moved = true; }
    const nextY = { ...tank, y: tank.y + dy * tank.speed * dt };
    if (!obstacleAt(nextY, tank)) { tank.y = nextY.y; moved = true; }
    tank.x = Math.round(tank.x * 10) / 10;
    tank.y = Math.round(tank.y * 10) / 10;
    return moved;
  }

  function directionVector(dir) {
    return ({ up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] })[dir];
  }

  function fire(tank) {
    if (!tank.alive || tank.cooldown > 0) return;
    const [dx, dy] = directionVector(tank.dir);
    const cx = tank.x + tank.w / 2;
    const cy = tank.y + tank.h / 2;
    state.bullets.push({
      x: cx - BULLET / 2 + dx * 24,
      y: cy - BULLET / 2 + dy * 24,
      w: BULLET, h: BULLET, dx, dy,
      speed: tank.kind === 'player' ? 390 : 265,
      owner: tank.kind,
      alive: true
    });
    tank.cooldown = tank.kind === 'player' ? .24 : rand(1.05, 1.7);
  }

  function spawnEnemy() {
    if (state.spawned >= 12 || state.enemies.length >= 4) return;
    const spots = [1, 7, 14].sort(() => Math.random() - .5);
    for (const col of spots) {
      const enemy = makeTank(col * TILE + 5, 5, 'enemy', 'down');
      if (!obstacleAt(enemy)) {
        enemy.variant = state.spawned % 3 === 2 ? 'alt' : 'red';
        state.enemies.push(enemy);
        state.spawned++;
        state.spawnTimer = rand(.8, 1.35);
        burst(enemy.x + 19, enemy.y + 19, '#f5f1dc', 10);
        break;
      }
    }
  }

  function updatePlayer(dt) {
    const p = state.player;
    if (!p.alive) return;
    let dx = 0, dy = 0;
    if (keys.has('ArrowUp') || keys.has('KeyW')) { dy = -1; p.dir = 'up'; }
    else if (keys.has('ArrowDown') || keys.has('KeyS')) { dy = 1; p.dir = 'down'; }
    else if (keys.has('ArrowLeft') || keys.has('KeyA')) { dx = -1; p.dir = 'left'; }
    else if (keys.has('ArrowRight') || keys.has('KeyD')) { dx = 1; p.dir = 'right'; }
    moveTank(p, dx, dy, dt);
    if (keys.has('Space') || keys.has('Enter')) fire(p);
  }

  function clearShot(enemy, target) {
    const ecx = enemy.x + enemy.w / 2;
    const ecy = enemy.y + enemy.h / 2;
    const tcx = target.x + target.w / 2;
    const tcy = target.y + target.h / 2;
    const vertical = Math.abs(ecx - tcx) < 22;
    const horizontal = Math.abs(ecy - tcy) < 22;
    if (!vertical && !horizontal) return false;
    const ray = vertical
      ? { x: ecx - 3, y: Math.min(ecy, tcy), w: 6, h: Math.abs(tcy - ecy) }
      : { x: Math.min(ecx, tcx), y: ecy - 3, w: Math.abs(tcx - ecx), h: 6 };
    return !state.walls.some(w => rectsOverlap(ray, w)) && !(state.base.alive && rectsOverlap(ray, state.base));
  }

  function updateEnemies(dt) {
    for (const e of state.enemies) {
      e.cooldown -= dt; e.think -= dt; e.invincible -= dt; e.flash -= dt;
      if (!e.alive) continue;
      const target = Math.random() < .22 ? state.base : state.player;
      if (clearShot(e, target) && Math.random() < .045) {
        const dx = target.x - e.x, dy = target.y - e.y;
        e.dir = Math.abs(dx) > Math.abs(dy) ? (dx < 0 ? 'left' : 'right') : (dy < 0 ? 'up' : 'down');
        fire(e);
      }
      if (e.think <= 0) {
        const toPlayerX = state.player.x - e.x;
        const toPlayerY = state.player.y - e.y;
        const choices = Math.random() < .58
          ? (Math.abs(toPlayerX) > Math.abs(toPlayerY)
            ? [toPlayerX < 0 ? 'left' : 'right', toPlayerY < 0 ? 'up' : 'down']
            : [toPlayerY < 0 ? 'up' : 'down', toPlayerX < 0 ? 'left' : 'right'])
          : ['up', 'down', 'left', 'right'].sort(() => Math.random() - .5);
        e.dir = choices[0];
        e.think = rand(.3, 1.15);
        if (Math.random() < .32) fire(e);
      }
      const [dx, dy] = directionVector(e.dir);
      const moved = moveTank(e, dx, dy, dt);
      if (!moved) { e.think = 0; e.dir = ['up', 'down', 'left', 'right'][Math.floor(Math.random() * 4)]; }
    }
  }

  function bulletHitWall(b) {
    const wall = state.walls.find(w => rectsOverlap(b, w));
    if (!wall) return false;
    if (wall.type === 'brick') {
      wall.hp--;
      burst(b.x, b.y, COLORS.brickHi, 6);
      if (wall.hp <= 0) state.walls.splice(state.walls.indexOf(wall), 1);
    } else burst(b.x, b.y, COLORS.steelHi, 5);
    state.shake = Math.max(state.shake, 2.5);
    return true;
  }

  function destroyPlayer() {
    const p = state.player;
    if (!p.alive || p.invincible > 0) return;
    p.alive = false;
    state.lives--;
    state.shake = 8;
    burst(p.x + 19, p.y + 19, COLORS.player, 24);
    updateHud();
    if (state.lives <= 0) endGame(false, 'ТАНК УНИЧТОЖЕН');
    else {
      const activeGameId = state.id;
      setTimeout(() => {
        if (state.id !== activeGameId || state.gameOver) return;
        state.player = makeTank(7 * TILE + 5, 12 * TILE + 5, 'player');
      }, 900);
    }
  }

  function destroyEnemy(enemy) {
    if (!enemy.alive || enemy.invincible > 0) return;
    enemy.alive = false;
    state.score += enemy.variant === 'alt' ? 250 : 100;
    state.remaining--;
    state.shake = 6;
    burst(enemy.x + 19, enemy.y + 19, enemy.variant === 'alt' ? COLORS.enemyAlt : COLORS.enemy, 20);
    updateHud();
  }

  function destroyBase() {
    if (!state.base.alive) return;
    state.base.alive = false;
    state.shake = 11;
    burst(state.base.x + 18, state.base.y + 18, COLORS.base, 30);
    updateHud();
    endGame(false, 'БАЗА РАЗРУШЕНА');
  }

  function updateBullets(dt) {
    for (const b of state.bullets) {
      if (!b.alive) continue;
      b.x += b.dx * b.speed * dt;
      b.y += b.dy * b.speed * dt;
      if (b.x < -10 || b.y < -10 || b.x > W + 10 || b.y > H + 10) { b.alive = false; continue; }
      if (bulletHitWall(b)) { b.alive = false; continue; }
      if (state.base.alive && rectsOverlap(b, state.base)) { b.alive = false; destroyBase(); continue; }
      if (b.owner === 'player') {
        const enemy = state.enemies.find(e => e.alive && rectsOverlap(b, e, 4));
        if (enemy) { b.alive = false; destroyEnemy(enemy); }
      } else if (state.player.alive && rectsOverlap(b, state.player, 4)) {
        b.alive = false; destroyPlayer();
      }
    }
    // Bullets cancel each other.
    for (let i = 0; i < state.bullets.length; i++) for (let j = i + 1; j < state.bullets.length; j++) {
      const a = state.bullets[i], b = state.bullets[j];
      if (a.alive && b.alive && a.owner !== b.owner && rectsOverlap(a, b)) {
        a.alive = b.alive = false; burst(a.x, a.y, COLORS.white, 4);
      }
    }
    state.bullets = state.bullets.filter(b => b.alive);
    state.enemies = state.enemies.filter(e => e.alive);
  }

  function burst(x, y, color, amount) {
    for (let i = 0; i < amount; i++) state.sparks.push({
      x, y, vx: rand(-115, 115), vy: rand(-115, 115),
      life: rand(.18, .55), max: .55, color, size: Math.random() < .5 ? 4 : 7
    });
  }

  function updateSparks(dt) {
    state.sparks.forEach(s => { s.x += s.vx * dt; s.y += s.vy * dt; s.vx *= .95; s.vy *= .95; s.life -= dt; });
    state.sparks = state.sparks.filter(s => s.life > 0);
  }

  function endGame(victory, reason) {
    state.gameOver = true;
    state.victory = victory;
    showMessage(victory ? 'РУБЕЖ УДЕРЖАН!' : reason, 'R или кнопка «Новая игра»');
  }

  function update(dt) {
    if (state.paused || state.gameOver) { updateSparks(dt); return; }
    state.banner -= dt;
    state.shake = Math.max(0, state.shake - 25 * dt);
    state.player.cooldown -= dt;
    state.player.invincible -= dt;
    state.player.flash -= dt;
    updatePlayer(dt);
    updateEnemies(dt);
    updateBullets(dt);
    updateSparks(dt);

    state.spawnTimer -= dt;
    if (state.spawnTimer <= 0) spawnEnemy();
    if (state.remaining === 0 && state.spawned >= 12) endGame(true, '');
  }

  function drawBackground() {
    ctx.fillStyle = COLORS.bg;
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = COLORS.grid;
    for (let y = 0; y < ROWS; y++) for (let x = 0; x < COLS; x++) {
      if ((x + y) % 2 === 0) ctx.fillRect(x * TILE, y * TILE, TILE, TILE);
    }
    ctx.globalAlpha = .28;
    ctx.fillStyle = '#334136';
    for (let y = 10; y < H; y += 24) for (let x = (y / 24 % 2) * 12; x < W; x += 48) ctx.fillRect(x, y, 3, 3);
    ctx.globalAlpha = 1;
  }

  function drawWall(w) {
    if (w.type === 'brick') {
      ctx.fillStyle = '#54251d'; ctx.fillRect(w.x, w.y, w.w, w.h);
      ctx.fillStyle = COLORS.brick;
      for (let yy = 3; yy < 48; yy += 12) for (let xx = (yy / 12 % 2) * 12 + 2; xx < 48; xx += 24) {
        ctx.fillRect(w.x + xx, w.y + yy, 20, 8);
        ctx.fillStyle = COLORS.brickHi; ctx.fillRect(w.x + xx, w.y + yy, 20, 2); ctx.fillStyle = COLORS.brick;
      }
      if (w.hp === 1) { ctx.fillStyle = COLORS.black; ctx.fillRect(w.x + 18, w.y + 4, 5, 18); ctx.fillRect(w.x + 22, w.y + 18, 15, 5); }
    } else {
      ctx.fillStyle = '#3f4850'; ctx.fillRect(w.x, w.y, 48, 48);
      for (let y = 3; y < 48; y += 24) for (let x = 3; x < 48; x += 24) {
        ctx.fillStyle = COLORS.steel; ctx.fillRect(w.x + x, w.y + y, 18, 18);
        ctx.fillStyle = COLORS.steelHi; ctx.fillRect(w.x + x + 3, w.y + y + 3, 10, 3);
        ctx.fillStyle = '#242b31'; ctx.fillRect(w.x + x + 13, w.y + y + 13, 3, 3);
      }
    }
  }

  function drawBase() {
    const b = state.base;
    if (!b.alive) {
      ctx.fillStyle = '#3a1914'; ctx.fillRect(b.x, b.y, b.w, b.h);
      ctx.fillStyle = '#090a09'; ctx.fillRect(b.x + 7, b.y + 7, 9, 22); ctx.fillRect(b.x + 21, b.y + 3, 7, 27);
      return;
    }
    ctx.fillStyle = '#4b2e0b'; ctx.fillRect(b.x, b.y, b.w, b.h);
    ctx.fillStyle = COLORS.base;
    ctx.fillRect(b.x + 4, b.y + 4, 28, 28);
    ctx.fillStyle = '#5a350c';
    ctx.fillRect(b.x + 15, b.y + 7, 6, 22);
    ctx.fillRect(b.x + 9, b.y + 13, 18, 6);
    ctx.fillRect(b.x + 7, b.y + 25, 22, 4);
  }

  function drawTank(t) {
    if (!t.alive) return;
    if (t.invincible > 0 && Math.floor(t.invincible * 12) % 2 === 0) ctx.globalAlpha = .35;
    const c = t.kind === 'player' ? COLORS.player : (t.variant === 'alt' ? COLORS.enemyAlt : COLORS.enemy);
    const hi = t.kind === 'player' ? COLORS.playerHi : COLORS.enemyHi;
    ctx.save();
    ctx.translate(Math.round(t.x + t.w / 2), Math.round(t.y + t.h / 2));
    const angles = { up: 0, right: Math.PI / 2, down: Math.PI, left: -Math.PI / 2 };
    ctx.rotate(angles[t.dir]);
    ctx.fillStyle = '#161a17'; ctx.fillRect(-19, -19, 9, 38); ctx.fillRect(10, -19, 9, 38);
    ctx.fillStyle = c; ctx.fillRect(-8, -16, 16, 29); ctx.fillRect(-14, -11, 28, 21);
    ctx.fillStyle = hi; ctx.fillRect(-10, -9, 20, 4); ctx.fillRect(-5, -14, 5, 5);
    ctx.fillStyle = '#111412'; ctx.fillRect(-5, -7, 10, 10);
    ctx.fillStyle = c; ctx.fillRect(-3, -24, 6, 20);
    ctx.fillStyle = hi; ctx.fillRect(-2, -24, 2, 17);
    for (let y = -15; y <= 12; y += 9) {
      ctx.fillStyle = '#58605b'; ctx.fillRect(-18, y, 6, 4); ctx.fillRect(12, y, 6, 4);
    }
    ctx.restore();
    ctx.globalAlpha = 1;
  }

  function drawBullet(b) {
    ctx.fillStyle = '#9a6612'; ctx.fillRect(Math.round(b.x - 2), Math.round(b.y - 2), b.w + 4, b.h + 4);
    ctx.fillStyle = COLORS.bullet; ctx.fillRect(Math.round(b.x), Math.round(b.y), b.w, b.h);
  }

  function drawSparks() {
    state.sparks.forEach(s => {
      ctx.globalAlpha = clamp(s.life / s.max, 0, 1);
      ctx.fillStyle = s.color;
      ctx.fillRect(Math.round(s.x), Math.round(s.y), s.size, s.size);
    });
    ctx.globalAlpha = 1;
  }

  function draw() {
    ctx.save();
    if (state.shake > 0) ctx.translate(rand(-state.shake, state.shake), rand(-state.shake, state.shake));
    drawBackground();
    state.walls.forEach(drawWall);
    drawBase();
    state.bullets.forEach(drawBullet);
    drawTank(state.player);
    state.enemies.forEach(drawTank);
    drawSparks();

    // Enemy markers at the top edge.
    for (let i = 0; i < state.remaining; i++) {
      const x = 6 + (i % 12) * 12;
      ctx.fillStyle = i < 12 ? '#d9503f' : '#9a3a30';
      ctx.fillRect(x, 5, 8, 8); ctx.fillRect(x + 2, 2, 4, 4);
    }

    if (state.banner > 0 && !state.gameOver) {
      ctx.globalAlpha = clamp(state.banner, 0, 1);
      ctx.fillStyle = 'rgba(0,0,0,.78)'; ctx.fillRect(210, 290, 348, 92);
      ctx.strokeStyle = COLORS.white; ctx.lineWidth = 4; ctx.strokeRect(214, 294, 340, 84);
      ctx.fillStyle = COLORS.white; ctx.font = 'bold 31px monospace'; ctx.textAlign = 'center'; ctx.fillText('ВОЛНА 01', W / 2, 336);
      ctx.fillStyle = COLORS.player; ctx.font = 'bold 17px monospace'; ctx.fillText('ЗАЩИТИТЕ БАЗУ', W / 2, 363);
      ctx.globalAlpha = 1;
    }
    ctx.restore();
  }

  function frame(now) {
    const delta = Math.min(.05, (now - lastTime) / 1000 || 0);
    lastTime = now;
    accumulator += delta;
    while (accumulator >= STEP) { update(STEP); accumulator -= STEP; }
    draw();
    requestAnimationFrame(frame);
  }

  function togglePause() {
    if (state.gameOver) return;
    state.paused = !state.paused;
    state.paused ? showMessage('ПАУЗА', 'P — продолжить') : hideMessage();
  }

  const blockKeys = new Set(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Space']);
  window.addEventListener('keydown', e => {
    if (blockKeys.has(e.code)) e.preventDefault();
    if ((e.code === 'KeyP' || e.code === 'Escape') && !e.repeat) togglePause();
    if (e.code === 'KeyR' && !e.repeat) resetGame();
    if (state.gameOver && e.code === 'Enter') resetGame();
    keys.add(e.code);
  });
  window.addEventListener('keyup', e => keys.delete(e.code));
  window.addEventListener('blur', () => { keys.clear(); if (!state.gameOver && !state.paused) togglePause(); });
  ui.restart.addEventListener('click', resetGame);

  document.querySelectorAll('[data-key]').forEach(button => {
    const code = button.dataset.key;
    const press = e => { e.preventDefault(); keys.add(code); button.classList.add('pressed'); };
    const release = e => { e.preventDefault(); keys.delete(code); button.classList.remove('pressed'); };
    button.addEventListener('pointerdown', press);
    button.addEventListener('pointerup', release);
    button.addEventListener('pointercancel', release);
    button.addEventListener('pointerleave', release);
  });

  resetGame();
  requestAnimationFrame(frame);
})();
