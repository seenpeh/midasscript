/* Number and date formatting for the UI. Every figure the user reads goes
   through one of these, so "—" for missing data looks the same everywhere. */

export const fmt = (n, decimals = 2) =>
  (n == null || isNaN(n)) ? '—'
    : Number(n).toLocaleString('en-US',
        {minimumFractionDigits: decimals, maximumFractionDigits: decimals});

export const fmtInt = n => (n == null) ? '—' : Number(n).toLocaleString('en-US');

export const signed = (n, decimals = 2) =>
  (n >= 0 ? '+' : '') + fmt(n, decimals);

export const signClass = n => n > 0 ? 'pos' : (n < 0 ? 'neg' : '');

/* "2004-06-11 08:10" -> "04-06-11 08:10" (the table has no room for centuries) */
export const shortDt = s => s ? s.slice(2) : '';

/* epoch seconds -> "YYYY-MM-DD HH:MM" in UTC */
export const utcMinute = epoch =>
  new Date(epoch * 1000).toISOString().slice(0, 16).replace('T', ' ');
