/**
 * Date utility helpers for local calendar date operations.
 *
 * Prevents UTC timezone skew issues (e.g. UTC midnight boundaries in IST, EST, etc.)
 * when capturing user-entered calendar dates for document headers.
 */

/**
 * Returns a local calendar date formatted as ISO 'YYYY-MM-DD'.
 *
 * Unlike `date.toISOString().split('T')[0]`, which converts the timestamp to UTC
 * (and can result in yesterday's or tomorrow's date depending on local timezone offset),
 * this function reads the local calendar year, month, and day components.
 *
 * @param date Optional Date instance (defaults to current local date/time)
 * @returns Date string formatted as 'YYYY-MM-DD'
 */
export function formatLocalCalendarDate(date: Date = new Date()): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}
