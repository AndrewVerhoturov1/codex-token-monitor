(() => {
  'use strict';

  const screen = document.querySelector('.screen');
  const button = document.querySelector('#tuneButton');
  const status = document.querySelector('#signalStatus');
  const hint = document.querySelector('#hint');

  if (!screen || !button || !status || !hint) {
    return;
  }

  let tuning = false;
  let tuned = false;

  function tuneChannel() {
    if (tuning) return;

    tuning = true;
    button.disabled = true;
    screen.classList.remove('is-tuned');
    screen.classList.add('is-tuning');
    status.textContent = 'TUNING...';
    hint.textContent = 'Поиск несущей частоты';

    window.setTimeout(() => {
      tuned = !tuned;
      screen.classList.remove('is-tuning');
      screen.classList.toggle('is-tuned', tuned);
      status.textContent = tuned ? 'SIGNAL FOUND' : 'SIGNAL LOCKED';
      hint.textContent = tuned
        ? 'Канал настроен · нажмите ещё раз для сброса'
        : 'Нажмите кнопку или клавишу Enter';
      button.querySelector('.tune-button__label').textContent = tuned
        ? 'СБРОСИТЬ СИГНАЛ'
        : 'НАСТРОИТЬ КАНАЛ';
      button.disabled = false;
      tuning = false;
      button.focus({ preventScroll: true });
    }, 780);
  }

  button.addEventListener('click', tuneChannel);

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && document.activeElement !== button) {
      event.preventDefault();
      tuneChannel();
    }
  });
})();
