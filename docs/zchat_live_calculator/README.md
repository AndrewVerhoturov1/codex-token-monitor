# Stylish Calculator

A polished, offline, self-contained static calculator website.

## Files

- `index.html` — accessible page shell and calculator buttons.
- `styles.css` — responsive glass-style UI, gradients, animation, hover and focus states.
- `app.js` — vanilla JavaScript calculator logic and keyboard support.
- `change_summary.md` — summary of delivered changes.
- `context_readback.md` — source readback and fact separation.
- `verification/check_result.py` — optional text-review verification helper.

## Features

- Basic arithmetic: addition, subtraction, multiplication, and division.
- Keyboard input: digits, operators, Enter, Backspace, and Escape.
- Responsive layout for desktop and mobile widths.
- Offline operation with local files only.
- Vanilla JavaScript, no frameworks, libraries, remote assets, or network activity.

## Notes for reviewers

The calculator uses a small hand-written arithmetic tokenizer and precedence evaluator. It is intended as a static front-end demo under `docs/zchat_live_calculator/`.
