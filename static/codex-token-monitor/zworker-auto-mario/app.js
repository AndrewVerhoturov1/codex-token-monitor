(() => {
  "use strict";

  const canvas = document.getElementById("gameCanvas");
  const ctx = canvas.getContext("2d");
  const restartButton = document.getElementById("restartButton");
  const messageButton = document.getElementById("messageButton");
  const messagePanel = document.getElementById("messagePanel");
  const messageKicker = document.getElementById("messageKicker");
  const messageTitle = document.getElementById("messageTitle");
  const messageText = document.getElementById("messageText");
  const scoreValue = document.getElementById("scoreValue");
  const coinValue = document.getElementById("coinValue");
  const lifeValue = document.getElementById("lifeValue");

  const W = canvas.width;
  const H = canvas.height;
  const LEVEL_WIDTH = 3720;
  const GRAVITY = 1900;
  const MOVE_ACCEL = 2200;
  const AIR_ACCEL = 1400;
  const MAX_SPEED = 340;
  const GROUND_FRICTION = 0.80;
  const AIR_FRICTION = 0.985;
  const JUMP_SPEED = 720;
  const COYOTE_TIME = 0.11;
  const JUMP_BUFFER = 0.12;

  const keys = new Set();
  let audioContext = null;
  let player;
  let coins;
  let particles;
  let cameraX;
  let score;
  let lives;
  let state;
  let lastTime = 0;
  let elapsed = 0;
  let shake = 0;

  const platforms = [
    { x: 0, y: 466, w: 520, h: 74, kind: "ground" },
    { x: 620, y: 466, w: 550, h: 74, kind: "ground" },
    { x: 1285, y: 466, w: 520, h: 74, kind: "ground" },
    { x: 1910, y: 466, w: 650, h: 74, kind: "ground" },
    { x: 2670, y: 466, w: 1050, h: 74, kind: "ground" },

    { x: 250, y: 370, w: 150, h: 24, kind: "brick" },
    { x: 700, y: 350, w: 120, h: 24, kind: "brick" },
    { x: 875, y: 280, w: 150, h: 24, kind: "brick" },
    { x: 1210, y: 370, w: 120, h: 24, kind: "brick" },
    { x: 1450, y: 330, w: 180, h: 24, kind: "brick" },
    { x: 1700, y: 250, w: 150, h: 24, kind: "brick" },
    { x: 2020, y: 350, w: 130, h: 24, kind: "brick" },
    { x: 2220, y: 285, w: 160, h: 24, kind: "brick" },
    { x: 2510, y: 370, w: 140, h: 24, kind: "brick" },
    { x: 2810, y: 350, w: 180, h: 24, kind: "brick" },
    { x: 3090, y: 275, w: 160, h: 24, kind: "brick" },
    { x: 3360, y: 360, w: 110, h: 24, kind: "brick" },

    { x: 1045, y: 410, w: 58, h: 56, kind: "crate" },
    { x: 1760, y: 398, w: 68, h: 68, kind: "crate" },
    { x: 2440, y: 406, w: 60, h: 60, kind: "crate" }
  ];

  const coinSeeds = [
    [300, 322], [350, 322], [555, 385], [730, 302], [915, 230], [965, 230],
    [1238, 322], [1490, 280], [1540, 280], [1740, 200], [1790, 200], [1975, 400],
    [2055, 302], [2260, 237], [2310, 237], [2590, 320], [2845, 302], [2900, 302],
    [3130, 227], [3180, 227], [3430, 312], [3530, 408], [3590, 408]
  ];

  const clouds = [
    { x: 140, y: 110, s: 1.0 }, { x: 760, y: 155, s: .72 }, { x: 1410, y: 90, s: 1.15 },
    { x: 2120, y: 145, s: .85 }, { x: 2860, y: 105, s: 1.05 }, { x: 3450, y: 160, s: .7 }
  ];

  const hills = [
    { x: -50, y: 380, w: 420, h: 190 }, { x: 460, y: 400, w: 340, h: 160 },
    { x: 960, y: 365, w: 480, h: 210 }, { x: 1590, y: 405, w: 340, h: 155 },
    { x: 2110, y: 370, w: 430, h: 205 }, { x: 2720, y: 395, w: 390, h: 170 },
    { x: 3270, y: 375, w: 420, h: 200 }
  ];

  const flag = { x: 3580, y: 268, w: 24, h: 198 };

  function resetGame() {
    player = {
      x: 80, y: 390, w: 42, h: 58,
      vx: 0, vy: 0,
      onGround: false,
      coyote: 0,
      jumpBuffer: 0,
      facing: 1,
      runFrame: 0,
      invulnerable: 0,
      spawnX: 80,
      spawnY: 390
    };
    coins = coinSeeds.map(([x, y], index) => ({ x, y, r: 13, collected: false, phase: index * .67 }));
    particles = [];
    cameraX = 0;
    score = 0;
    lives = 3;
    state = "playing";
    elapsed = 0;
    shake = 0;
    messagePanel.classList.add("is-hidden");
    updateHud();
  }

  function updateHud() {
    scoreValue.textContent = String(score).padStart(4, "0");
    const collected = coins.filter((coin) => coin.collected).length;
    coinValue.textContent = `${collected}/${coins.length}`;
    lifeValue.textContent = "♥".repeat(Math.max(0, lives));
  }

  function showMessage(kicker, title, text, buttonText) {
    messageKicker.textContent = kicker;
    messageTitle.textContent = title;
    messageText.textContent = text;
    messageButton.textContent = buttonText;
    messagePanel.classList.remove("is-hidden");
  }

  function ensureAudio() {
    if (!audioContext) {
      const AudioCtor = window.AudioContext || window.webkitAudioContext;
      if (AudioCtor) audioContext = new AudioCtor();
    }
    if (audioContext?.state === "suspended") audioContext.resume();
  }

  function beep(frequency, duration, type = "square", volume = 0.035, delay = 0) {
    if (!audioContext) return;
    const start = audioContext.currentTime + delay;
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();
    oscillator.type = type;
    oscillator.frequency.setValueAtTime(frequency, start);
    gain.gain.setValueAtTime(volume, start);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    oscillator.connect(gain);
    gain.connect(audioContext.destination);
    oscillator.start(start);
    oscillator.stop(start + duration);
  }

  function playJumpSound() {
    beep(260, .07, "square", .025);
    beep(390, .08, "square", .022, .055);
  }

  function playCoinSound() {
    beep(740, .06, "square", .03);
    beep(1040, .10, "square", .025, .055);
  }

  function playWinSound() {
    [523, 659, 784, 1047].forEach((note, index) => beep(note, .18, "square", .025, index * .12));
  }

  function rectsOverlap(a, b) {
    return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
  }

  function moveAndCollide(dt) {
    player.x += player.vx * dt;
    for (const platform of platforms) {
      if (!rectsOverlap(player, platform)) continue;
      if (player.vx > 0) player.x = platform.x - player.w;
      else if (player.vx < 0) player.x = platform.x + platform.w;
      player.vx = 0;
    }

    const previousBottom = player.y + player.h;
    player.y += player.vy * dt;
    player.onGround = false;

    for (const platform of platforms) {
      if (!rectsOverlap(player, platform)) continue;
      if (player.vy >= 0 && previousBottom <= platform.y + 8) {
        player.y = platform.y - player.h;
        player.vy = 0;
        player.onGround = true;
      } else if (player.vy < 0) {
        player.y = platform.y + platform.h;
        player.vy = 0;
        shake = Math.max(shake, 2.5);
      }
    }

    if (player.x < 0) {
      player.x = 0;
      player.vx = 0;
    }
    if (player.x + player.w > LEVEL_WIDTH) {
      player.x = LEVEL_WIDTH - player.w;
      player.vx = 0;
    }
  }

  function respawn() {
    lives -= 1;
    updateHud();
    shake = 14;
    beep(120, .25, "sawtooth", .04);

    if (lives <= 0) {
      state = "lost";
      showMessage("ПОПРОБУЙ ЕЩЁ", "GAME OVER", `Счёт: ${score}. До флага оставалось ${Math.max(0, Math.ceil((flag.x - player.x) / 10))} м.`, "НАЧАТЬ ЗАНОВО");
      return;
    }

    player.x = Math.max(40, player.spawnX);
    player.y = player.spawnY;
    player.vx = 0;
    player.vy = 0;
    player.invulnerable = 1.2;
    cameraX = Math.max(0, player.x - 180);
  }

  function spawnParticles(x, y, color, amount = 8) {
    for (let i = 0; i < amount; i += 1) {
      const angle = (Math.PI * 2 * i) / amount + Math.random() * .35;
      const speed = 80 + Math.random() * 150;
      particles.push({
        x, y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed - 55,
        life: .42 + Math.random() * .28,
        maxLife: .7,
        size: 4 + Math.random() * 4,
        color
      });
    }
  }

  function updateParticles(dt) {
    for (let i = particles.length - 1; i >= 0; i -= 1) {
      const particle = particles[i];
      particle.life -= dt;
      particle.vy += 420 * dt;
      particle.x += particle.vx * dt;
      particle.y += particle.vy * dt;
      if (particle.life <= 0) particles.splice(i, 1);
    }
  }

  function update(dt) {
    elapsed += dt;
    updateParticles(dt);
    shake = Math.max(0, shake - 40 * dt);

    if (state !== "playing") return;

    const left = keys.has("ArrowLeft") || keys.has("KeyA");
    const right = keys.has("ArrowRight") || keys.has("KeyD");
    const direction = Number(right) - Number(left);
    const acceleration = player.onGround ? MOVE_ACCEL : AIR_ACCEL;

    if (direction !== 0) {
      player.vx += direction * acceleration * dt;
      player.vx = Math.max(-MAX_SPEED, Math.min(MAX_SPEED, player.vx));
      player.facing = direction;
      player.runFrame += Math.abs(player.vx) * dt * .035;
    } else {
      player.vx *= player.onGround ? Math.pow(GROUND_FRICTION, dt * 60) : Math.pow(AIR_FRICTION, dt * 60);
      if (Math.abs(player.vx) < 2) player.vx = 0;
    }

    player.coyote = player.onGround ? COYOTE_TIME : Math.max(0, player.coyote - dt);
    player.jumpBuffer = Math.max(0, player.jumpBuffer - dt);
    player.invulnerable = Math.max(0, player.invulnerable - dt);

    if (player.jumpBuffer > 0 && player.coyote > 0) {
      player.vy = -JUMP_SPEED;
      player.onGround = false;
      player.coyote = 0;
      player.jumpBuffer = 0;
      playJumpSound();
      spawnParticles(player.x + player.w / 2, player.y + player.h, "#f7f1d0", 5);
    }

    player.vy += GRAVITY * dt;
    player.vy = Math.min(player.vy, 980);
    moveAndCollide(dt);

    if (player.y > H + 130 && player.invulnerable <= 0) respawn();

    for (const coin of coins) {
      if (coin.collected) continue;
      const dx = player.x + player.w / 2 - coin.x;
      const dy = player.y + player.h / 2 - coin.y;
      if (dx * dx + dy * dy < (coin.r + 26) ** 2) {
        coin.collected = true;
        score += 100;
        playCoinSound();
        spawnParticles(coin.x, coin.y, "#ffd84a", 10);
        updateHud();
      }
    }

    if (player.x > 1120) player.spawnX = 1305;
    if (player.x > 1850) player.spawnX = 1930;
    if (player.x > 2600) player.spawnX = 2700;

    if (rectsOverlap(player, { x: flag.x - 12, y: flag.y, w: 70, h: flag.h })) {
      state = "won";
      const collected = coins.filter((coin) => coin.collected).length;
      const timeBonus = Math.max(0, 3000 - Math.floor(elapsed * 45));
      score += 1000 + timeBonus;
      updateHud();
      playWinSound();
      spawnParticles(flag.x + 22, flag.y + 35, "#ff5a9e", 24);
      showMessage(
        "УРОВЕНЬ ПРОЙДЕН",
        "ФИНИШ!",
        `Монеты: ${collected}/${coins.length} · Время: ${elapsed.toFixed(1)} сек. · Счёт: ${score}`,
        "ИГРАТЬ СНОВА"
      );
    }

    const targetCamera = Math.max(0, Math.min(LEVEL_WIDTH - W, player.x - W * .34));
    cameraX += (targetCamera - cameraX) * Math.min(1, dt * 5.5);
  }

  function pixelRect(x, y, w, h, color) {
    ctx.fillStyle = color;
    ctx.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
  }

  function drawCloud(x, y, scale) {
    const sx = x - cameraX * .18;
    pixelRect(sx, y + 16 * scale, 112 * scale, 26 * scale, "#eefaff");
    pixelRect(sx + 20 * scale, y, 42 * scale, 42 * scale, "#eefaff");
    pixelRect(sx + 55 * scale, y + 8 * scale, 38 * scale, 34 * scale, "#eefaff");
    pixelRect(sx + 8 * scale, y + 38 * scale, 94 * scale, 8 * scale, "#c7eafb");
  }

  function drawBackground() {
    const sky = ctx.createLinearGradient(0, 0, 0, H);
    sky.addColorStop(0, "#4ca9e8");
    sky.addColorStop(.62, "#79d0f1");
    sky.addColorStop(1, "#bdeaf4");
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, W, H);

    pixelRect(0, 302, W, 6, "rgba(255,255,255,.2)");

    for (const cloud of clouds) drawCloud(cloud.x, cloud.y, cloud.s);

    for (const hill of hills) {
      const x = hill.x - cameraX * .35;
      ctx.fillStyle = "#4cbb73";
      ctx.beginPath();
      ctx.moveTo(x, hill.y + hill.h);
      ctx.quadraticCurveTo(x + hill.w * .5, hill.y - hill.h * .45, x + hill.w, hill.y + hill.h);
      ctx.closePath();
      ctx.fill();
      ctx.fillStyle = "#2f8f62";
      ctx.beginPath();
      ctx.moveTo(x + hill.w * .48, hill.y + hill.h * .12);
      ctx.quadraticCurveTo(x + hill.w * .62, hill.y + hill.h * .35, x + hill.w * .72, hill.y + hill.h);
      ctx.lineTo(x + hill.w * .52, hill.y + hill.h);
      ctx.closePath();
      ctx.fill();
    }

    for (let x = -((cameraX * .55) % 220) - 80; x < W + 220; x += 220) {
      pixelRect(x, 408, 140, 58, "#2e8a58");
      pixelRect(x + 18, 384, 104, 28, "#49b86a");
      pixelRect(x + 40, 372, 64, 16, "#63ca79");
    }
  }

  function drawPlatform(platform) {
    const x = platform.x - cameraX;
    if (x + platform.w < -40 || x > W + 40) return;

    if (platform.kind === "ground") {
      pixelRect(x, platform.y, platform.w, platform.h, "#9a532b");
      pixelRect(x, platform.y, platform.w, 14, "#55bd4e");
      pixelRect(x, platform.y + 14, platform.w, 8, "#2d813d");
      for (let tx = 0; tx < platform.w; tx += 32) {
        pixelRect(x + tx + 4, platform.y + 32 + ((tx / 32) % 2) * 14, 13, 8, "#71351f");
        pixelRect(x + tx + 19, platform.y + 52 - ((tx / 32) % 2) * 12, 8, 7, "#c67535");
      }
    } else if (platform.kind === "brick") {
      pixelRect(x, platform.y, platform.w, platform.h, "#d96b3f");
      pixelRect(x, platform.y, platform.w, 5, "#ffad5c");
      pixelRect(x, platform.y + platform.h - 5, platform.w, 5, "#81314a");
      for (let tx = 0; tx < platform.w; tx += 30) {
        pixelRect(x + tx + 2, platform.y + 7, 25, 2, "#7f3047");
        pixelRect(x + tx + 13, platform.y + 9, 3, 10, "#7f3047");
      }
    } else {
      pixelRect(x, platform.y, platform.w, platform.h, "#b06a32");
      pixelRect(x + 5, platform.y + 5, platform.w - 10, platform.h - 10, "#d99543");
      pixelRect(x + 11, platform.y + 11, platform.w - 22, 6, "#f3bd62");
      pixelRect(x + 11, platform.y + platform.h - 18, platform.w - 22, 6, "#7f4328");
      pixelRect(x + 14, platform.y + 18, 6, platform.h - 36, "#8c4b2d");
      pixelRect(x + platform.w - 20, platform.y + 18, 6, platform.h - 36, "#8c4b2d");
    }
  }

  function drawCoin(coin) {
    if (coin.collected) return;
    const x = coin.x - cameraX;
    if (x < -30 || x > W + 30) return;
    const bob = Math.sin(elapsed * 6 + coin.phase) * 4;
    const squash = .35 + Math.abs(Math.cos(elapsed * 7 + coin.phase)) * .65;
    const width = coin.r * 2 * squash;
    pixelRect(x - width / 2 - 3, coin.y + bob - coin.r - 3, width + 6, coin.r * 2 + 6, "#9e5e14");
    pixelRect(x - width / 2, coin.y + bob - coin.r, width, coin.r * 2, "#ffd84a");
    if (width > 9) pixelRect(x - Math.max(1, width * .1), coin.y + bob - coin.r + 4, Math.max(2, width * .2), coin.r * 2 - 8, "#fff39a");
  }

  function drawFlag() {
    const x = flag.x - cameraX;
    pixelRect(x, flag.y, 8, flag.h, "#f4e9c5");
    pixelRect(x - 5, flag.y - 9, 18, 18, "#ffd84a");
    pixelRect(x - 2, flag.y - 6, 12, 12, "#fff2a2");
    const wave = Math.sin(elapsed * 5) * 4;
    ctx.fillStyle = "#ff4e91";
    ctx.beginPath();
    ctx.moveTo(x + 8, flag.y + 12);
    ctx.lineTo(x + 72 + wave, flag.y + 30);
    ctx.lineTo(x + 8, flag.y + 58);
    ctx.closePath();
    ctx.fill();
    pixelRect(x + 22, flag.y + 27, 14, 14, "#ffd84a");
    pixelRect(x - 26, flag.y + flag.h - 12, 60, 12, "#e7dcae");
  }

  function drawPlayer() {
    if (player.invulnerable > 0 && Math.floor(player.invulnerable * 12) % 2 === 0) return;

    const x = Math.round(player.x - cameraX);
    const y = Math.round(player.y);
    const dir = player.facing;
    const run = player.onGround && Math.abs(player.vx) > 30 ? Math.floor(player.runFrame) % 2 : 0;
    const jump = !player.onGround;

    ctx.save();
    ctx.translate(x + player.w / 2, 0);
    ctx.scale(dir, 1);
    ctx.translate(-(x + player.w / 2), 0);

    pixelRect(x + 5, y + 5, 29, 8, "#e94170");
    pixelRect(x + 1, y + 12, 39, 8, "#ff5a79");
    pixelRect(x + 8, y + 20, 27, 17, "#f4b15c");
    pixelRect(x + 28, y + 22, 5, 6, "#151a3d");
    pixelRect(x + 3, y + 25, 8, 7, "#8b3f2b");
    pixelRect(x + 11, y + 31, 25, 6, "#8b3f2b");

    pixelRect(x + 8, y + 37, 27, 16, "#2a4fb4");
    pixelRect(x + 3, y + 39, 9, 11, "#f4b15c");
    pixelRect(x + 33, y + 39, 8, 11, "#f4b15c");
    pixelRect(x + 15, y + 37, 6, 10, "#56b8e9");
    pixelRect(x + 28, y + 37, 6, 10, "#56b8e9");

    if (jump) {
      pixelRect(x + 7, y + 50, 13, 8, "#71314c");
      pixelRect(x + 27, y + 48, 12, 8, "#71314c");
    } else if (run === 0) {
      pixelRect(x + 8, y + 51, 12, 7, "#71314c");
      pixelRect(x + 27, y + 51, 12, 7, "#71314c");
    } else {
      pixelRect(x + 3, y + 50, 15, 8, "#71314c");
      pixelRect(x + 29, y + 52, 13, 6, "#71314c");
    }

    ctx.restore();
  }

  function drawParticles() {
    for (const particle of particles) {
      const alpha = Math.max(0, particle.life / particle.maxLife);
      ctx.globalAlpha = alpha;
      pixelRect(particle.x - cameraX, particle.y, particle.size, particle.size, particle.color);
    }
    ctx.globalAlpha = 1;
  }

  function drawPitWarning() {
    const pits = [[520, 620], [1170, 1285], [1805, 1910], [2560, 2670]];
    for (const [start, end] of pits) {
      const x = start - cameraX;
      const width = end - start;
      if (x + width < 0 || x > W) continue;
      pixelRect(x, 504, width, 36, "#1d2451");
      for (let px = 0; px < width; px += 24) {
        pixelRect(x + px, 504 + ((px / 24) % 2) * 8, 12, 6, "#6574b7");
      }
    }
  }

  function render() {
    ctx.save();
    if (shake > 0) ctx.translate((Math.random() - .5) * shake, (Math.random() - .5) * shake);

    drawBackground();
    drawPitWarning();
    for (const platform of platforms) drawPlatform(platform);
    drawFlag();
    for (const coin of coins) drawCoin(coin);
    drawParticles();
    drawPlayer();

    const progress = Math.max(0, Math.min(1, player.x / flag.x));
    pixelRect(24, H - 24, W - 48, 8, "rgba(7,11,36,.38)");
    pixelRect(24, H - 24, (W - 48) * progress, 8, "#ffd84a");
    pixelRect(20 + (W - 48) * progress, H - 30, 12, 18, "#ff5a9e");

    ctx.restore();
  }

  function frame(timestamp) {
    const dt = Math.min(.033, Math.max(0, (timestamp - lastTime) / 1000 || 0));
    lastTime = timestamp;
    update(dt);
    render();
    requestAnimationFrame(frame);
  }

  function queueJump() {
    if (state !== "playing") return;
    player.jumpBuffer = JUMP_BUFFER;
    ensureAudio();
  }

  window.addEventListener("keydown", (event) => {
    const controlled = ["ArrowLeft", "ArrowRight", "ArrowUp", "Space", "KeyA", "KeyD", "KeyW", "KeyR"];
    if (controlled.includes(event.code)) event.preventDefault();
    ensureAudio();

    if (["ArrowUp", "Space", "KeyW"].includes(event.code) && !keys.has(event.code)) queueJump();
    if (event.code === "KeyR") resetGame();
    keys.add(event.code);
  });

  window.addEventListener("keyup", (event) => {
    keys.delete(event.code);
    if (["ArrowUp", "Space", "KeyW"].includes(event.code) && player?.vy < -260) player.vy *= .52;
  });

  window.addEventListener("blur", () => keys.clear());
  restartButton.addEventListener("click", () => { ensureAudio(); resetGame(); });
  messageButton.addEventListener("click", () => { ensureAudio(); resetGame(); });
  canvas.addEventListener("pointerdown", ensureAudio, { once: true });

  resetGame();
  requestAnimationFrame(frame);
})();
