/* A three-line event bus.

   The trade table needs the chart to zoom to a trade; the chart needs the table
   to highlight a row. Wiring them to each other would make either impossible to
   load without the other, so they both talk through here instead. */

const listeners = new Map();

export function on(event, handler) {
  if (!listeners.has(event)) listeners.set(event, []);
  listeners.get(event).push(handler);
}

export function emit(event, payload) {
  for (const handler of listeners.get(event) || []) handler(payload);
}

export const EVENTS = {
  TRADE_SELECTED: 'trade:selected',   // {id} — a trade became the active one
  DATA_RELOADED: 'data:reloaded',     // the dataset was replaced by a new run
};
