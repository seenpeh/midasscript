/* Every call to the server, in one file.

   The viewer reads two static JSON artefacts written by the backtester and
   talks to four endpoints; nothing else in the UI constructs a URL. */

const JSON_HEADERS = {'Content-Type': 'application/json'};

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} ${response.status}`);
  return response.json();
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || ('HTTP ' + response.status));
  }
  return payload;
}

/** The candles + results pair the whole UI is drawn from.
    `bust` defeats the browser cache after a re-run has rewritten the files. */
export async function fetchDataset({bust = false} = {}) {
  const suffix = bust ? '?t=' + Date.now() : '';
  const [candles, results] = await Promise.all([
    getJson('5m_candles_chart.json' + suffix),
    getJson('results.json' + suffix),
  ]);
  return {candles, results};
}

/** Strategy defaults, for the drawer's "Defaults" button. Null if unavailable. */
export async function fetchDefaultParams() {
  try {
    return (await getJson('/api/defaults')).params;
  } catch {
    return null;
  }
}

export const runBacktest = body => postJson('/api/run', body);
export const estimateOptimization = body => postJson('/api/optimize/estimate', body);
export const startOptimization = body => postJson('/api/optimize/start', body);
export const optimizationStatus = () => getJson('/api/optimize/status');
