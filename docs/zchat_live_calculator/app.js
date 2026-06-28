"use strict";

const expressionEl = document.querySelector("#expression");
const resultEl = document.querySelector("#result");
const keysEl = document.querySelector(".keys");

let expression = "";
let justSolved = false;

const operators = new Set(["+", "-", "*", "/"]);

function pretty(value) {
  return value
    .replace(/\*/g, "×")
    .replace(/\//g, "÷")
    .replace(/-/g, "−");
}

function setDisplay(message) {
  const visibleExpression = expression ? pretty(expression) : "0";
  expressionEl.textContent = message || visibleExpression;
  resultEl.textContent = message ? "—" : previewResult();
}

function previewResult() {
  if (!expression) {
    return "0";
  }

  try {
    const value = calculate(expression);
    return formatNumber(value);
  } catch {
    return pretty(expression);
  }
}

function formatNumber(value) {
  if (!Number.isFinite(value)) {
    throw new Error("Result is not finite");
  }

  const rounded = Math.abs(value) < 1e-12 ? 0 : value;
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 10
  }).format(rounded);
}

function appendValue(value) {
  if (justSolved && !operators.has(value)) {
    expression = "";
  }
  justSolved = false;

  if (operators.has(value)) {
    appendOperator(value);
    return;
  }

  if (value === ".") {
    appendDecimal();
    return;
  }

  expression += value;
  setDisplay();
}

function appendDecimal() {
  const currentNumber = expression.split(/[+\-*/]/).pop() || "";
  if (!currentNumber.includes(".")) {
    expression += currentNumber ? "." : "0.";
  }
  setDisplay();
}

function appendOperator(operator) {
  if (!expression) {
    if (operator === "-") {
      expression = "-";
    }
    setDisplay();
    return;
  }

  const last = expression.at(-1);
  if (operators.has(last)) {
    expression = expression.slice(0, -1) + operator;
  } else {
    expression += operator;
  }

  setDisplay();
}

function clearAll() {
  expression = "";
  justSolved = false;
  setDisplay();
}

function backspace() {
  expression = expression.slice(0, -1);
  justSolved = false;
  setDisplay();
}

function toggleSign() {
  if (!expression || operators.has(expression.at(-1))) {
    expression += "-";
    setDisplay();
    return;
  }

  const match = expression.match(/(-?\d*\.?\d+)$/);
  if (!match) {
    return;
  }

  const numberText = match[0];
  const start = expression.length - numberText.length;
  const changed = numberText.startsWith("-") ? numberText.slice(1) : `-${numberText}`;
  expression = expression.slice(0, start) + changed;
  setDisplay();
}

function solve() {
  if (!expression) {
    setDisplay();
    return;
  }

  try {
    const value = calculate(expression);
    expression = String(Number(value.toPrecision(14)));
    justSolved = true;
    expressionEl.textContent = "Result";
    resultEl.textContent = formatNumber(value);
  } catch {
    setDisplay("Check expression");
  }
}

function tokenize(source) {
  const tokens = [];
  let index = 0;

  while (index < source.length) {
    const char = source[index];

    if (/\s/.test(char)) {
      index += 1;
      continue;
    }

    const previous = tokens[tokens.length - 1];
    const unaryMinus = char === "-" && (!previous || previous.type === "operator");

    if (/\d/.test(char) || char === "." || unaryMinus) {
      let numberText = unaryMinus ? "-" : "";
      index += unaryMinus ? 1 : 0;

      while (index < source.length && /[\d.]/.test(source[index])) {
        numberText += source[index];
        index += 1;
      }

      if (numberText === "-" || numberText.split(".").length > 2) {
        throw new Error("Invalid number");
      }

      tokens.push({ type: "number", value: Number(numberText) });
      continue;
    }

    if (operators.has(char)) {
      tokens.push({ type: "operator", value: char });
      index += 1;
      continue;
    }

    throw new Error("Invalid character");
  }

  return tokens;
}

function calculate(source) {
  const tokens = tokenize(source);
  const output = [];
  const stack = [];
  const precedence = { "+": 1, "-": 1, "*": 2, "/": 2 };

  for (const token of tokens) {
    if (token.type === "number") {
      output.push(token);
      continue;
    }

    while (
      stack.length &&
      precedence[stack.at(-1).value] >= precedence[token.value]
    ) {
      output.push(stack.pop());
    }
    stack.push(token);
  }

  while (stack.length) {
    output.push(stack.pop());
  }

  const values = [];
  for (const token of output) {
    if (token.type === "number") {
      values.push(token.value);
      continue;
    }

    const right = values.pop();
    const left = values.pop();
    if (left === undefined || right === undefined) {
      throw new Error("Bad expression");
    }

    if (token.value === "+") values.push(left + right);
    if (token.value === "-") values.push(left - right);
    if (token.value === "*") values.push(left * right);
    if (token.value === "/") {
      if (right === 0) {
        throw new Error("Division by zero");
      }
      values.push(left / right);
    }
  }

  if (values.length !== 1) {
    throw new Error("Bad expression");
  }

  return values[0];
}

function flashButton(value) {
  const selector = value.length === 1
    ? `[data-value="${CSS.escape(value)}"]`
    : `[data-action="${CSS.escape(value)}"]`;
  const button = document.querySelector(selector);
  if (!button) return;

  button.classList.add("is-active");
  window.setTimeout(() => button.classList.remove("is-active"), 120);
}

keysEl.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;

  const value = button.dataset.value;
  const action = button.dataset.action;

  if (value) appendValue(value);
  if (action === "clear") clearAll();
  if (action === "backspace") backspace();
  if (action === "sign") toggleSign();
  if (action === "equals") solve();
});

window.addEventListener("keydown", (event) => {
  const key = event.key;

  if (/\d/.test(key)) {
    appendValue(key);
    flashButton(key);
    return;
  }

  if (["+", "-", "*", "/"].includes(key)) {
    appendValue(key);
    flashButton(key);
    return;
  }

  if (key === "." || key === ",") {
    appendValue(".");
    flashButton(".");
    return;
  }

  if (key === "Enter" || key === "=") {
    event.preventDefault();
    solve();
    flashButton("equals");
    return;
  }

  if (key === "Backspace") {
    backspace();
    flashButton("backspace");
    return;
  }

  if (key === "Escape") {
    clearAll();
    flashButton("clear");
  }
});

setDisplay();
