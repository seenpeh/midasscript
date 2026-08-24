/* The only DOM helpers in the project. */

export const $ = selector => document.querySelector(selector);
export const $$ = selector => Array.from(document.querySelectorAll(selector));

export const field = name => document.getElementById('f_' + name);

let toastTimer;
export function toast(message) {
  let element = $('#toast');
  if (!element) {
    element = document.createElement('div');
    element.id = 'toast';
    document.body.appendChild(element);
  }
  element.textContent = message;
  element.style.display = 'block';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { element.style.display = 'none'; }, 2600);
}
