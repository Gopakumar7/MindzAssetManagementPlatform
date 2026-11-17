import { formatLocalCalendarDate } from './date.utils';

describe('formatLocalCalendarDate', () => {
  it('generates current local date formatted as YYYY-MM-DD when called without arguments', () => {
    const formatted = formatLocalCalendarDate();
    const now = new Date();
    const expectedYear = now.getFullYear();
    const expectedMonth = String(now.getMonth() + 1).padStart(2, '0');
    const expectedDay = String(now.getDate()).padStart(2, '0');

    expect(formatted).toBe(`${expectedYear}-${expectedMonth}-${expectedDay}`);
    expect(/^\d{4}-\d{2}-\d{2}$/.test(formatted)).toBeTrue();
  });

  it('correctly formats arbitrary dates with zero-padded months and days', () => {
    // March 5, 2026
    const d1 = new Date(2026, 2, 5, 12, 0, 0);
    expect(formatLocalCalendarDate(d1)).toBe('2026-03-05');

    // December 31, 2026
    const d2 = new Date(2026, 11, 31, 23, 59, 59);
    expect(formatLocalCalendarDate(d2)).toBe('2026-12-31');

    // January 1, 2027
    const d3 = new Date(2027, 0, 1, 0, 0, 0);
    expect(formatLocalCalendarDate(d3)).toBe('2027-01-01');
  });

  it('handles the UTC/local date boundary accurately without timezone skew', () => {
    // In timezone regions ahead of UTC (e.g. Asia/Kolkata +05:30), early morning hours (e.g. 02:00 AM)
    // correspond to the previous day in UTC.
    // In timezone regions behind UTC (e.g. America/New_York -05:00), late evening hours (e.g. 11:00 PM)
    // correspond to the next day in UTC.
    //
    // formatLocalCalendarDate must always reflect the user's LOCAL calendar date, not UTC.
    const localMorningDate = new Date(2026, 10, 8, 2, 30, 0); // 2026-11-08 02:30:00 local
    const formattedMorning = formatLocalCalendarDate(localMorningDate);
    expect(formattedMorning).toBe('2026-11-08');

    const localNightDate = new Date(2026, 10, 8, 23, 45, 0); // 2026-11-08 23:45:00 local
    const formattedNight = formatLocalCalendarDate(localNightDate);
    expect(formattedNight).toBe('2026-11-08');
  });

  it('demonstrates resilience compared to toISOString split across timezone boundaries', () => {
    // Create a date at a known UTC time that crosses midnight locally depending on offset
    const testDate = new Date(2026, 10, 8, 1, 0, 0);
    const localResult = formatLocalCalendarDate(testDate);

    // formatLocalCalendarDate must strictly equal local getFullYear, getMonth+1, getDate
    const localExpected = `${testDate.getFullYear()}-${String(testDate.getMonth() + 1).padStart(2, '0')}-${String(testDate.getDate()).padStart(2, '0')}`;
    expect(localResult).toBe(localExpected);
  });
});
