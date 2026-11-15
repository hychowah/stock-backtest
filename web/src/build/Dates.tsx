import { PRESETS, type ScheduleForm } from "../draft.ts";

/** Dates and frequency, for a dated test: the window inside the market's
 *  sessions, the interval (a preset, or a custom count of weeks or months),
 *  and one fixed schedule or random trials with an optional repeated date
 *  set. A copied test's trade dates are a third choice of Date testing. A
 *  control that is hidden or does not apply is disabled, so its range never
 *  blocks the form. A count or trials number is taken from 1, a date set
 *  from 0; other typing keeps the last number taken. */
export function Dates({ hidden, form, sessions, change }: {
  hidden: boolean;
  form: ScheduleForm;
  sessions: { first: string; last: string } | null;
  change: (change: Partial<ScheduleForm>) => void;
}) {
  const random = !hidden && form.testing === "random";
  const noInterval = hidden || form.testing === "dates";
  const whole = (key: "count" | "trials" | "seed", least: number) => (event: { currentTarget: HTMLInputElement }) => {
    const typed = event.currentTarget.valueAsNumber;
    if (Number.isSafeInteger(typed) && typed >= least) change({ [key]: typed });
  };
  return (
    <section id="schedule-controls" class="extra-filters" aria-labelledby="schedule-title" hidden={hidden}>
      <div class="section-heading">
        <h3 id="schedule-title">Dates and frequency</h3>
        <p class="hint">Dates roll to the next cached session of the selected market. All returns use USD and compare with SPY.</p>
      </div>
      <div class="schedule-row">
        <label>
          First trade date
          <input id="trade-start" type="date" disabled={hidden} min={sessions?.first} max={sessions?.last} value={form.start} onInput={(event) => change({ start: event.currentTarget.value })} />
        </label>
        <label>
          End / mark date
          <input id="trade-end" type="date" disabled={hidden} min={sessions?.first} max={sessions?.last} value={form.end || sessions?.last || ""} onInput={(event) => change({ end: event.currentTarget.value })} />
        </label>
        <label>
          Rebalance frequency
          <select id="rebalance-months" disabled={form.custom || noInterval} value={String(form.months)} onChange={(event) => change({ months: Number(event.currentTarget.value) })}>
            {PRESETS.map(({ months, label }) => (
              <option value={String(months)} key={months}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <div id="calendar-controls">
          <label class="check">
            <input id="calendar-custom" type="checkbox" disabled={noInterval} checked={form.custom} onChange={(event) => change({ custom: event.currentTarget.checked })} /> Custom week/month interval
          </label>
          <div id="calendar-interval" hidden={!form.custom}>
            <label class="narrow">
              Interval count
              <input id="calendar-count" type="number" min={1} max={form.unit === "week" ? 104 : 24} step={1} required disabled={!form.custom || noInterval} value={form.count} onInput={whole("count", 1)} />
            </label>
            <label class="narrow">
              Interval unit
              <select id="calendar-unit" disabled={noInterval} value={form.unit} onChange={(event) => change({ unit: event.currentTarget.value as "week" | "month" })}>
                <option value="week">Weeks</option>
                <option value="month">Months</option>
              </select>
            </label>
          </div>
        </div>
      </div>
      <div class="schedule-row">
        <label class="wide">
          Date testing
          <select id="date-testing" disabled={hidden} value={form.testing} onChange={(event) => change({ testing: event.currentTarget.value as ScheduleForm["testing"] })}>
            <option value="single">One fixed schedule</option>
            <option value="random">Random date at every rebalance</option>
            {form.dates.length > 0 && <option value="dates">The copied test's {form.dates.length} trade dates</option>}
          </select>
        </label>
        <div id="random-controls" hidden={form.testing !== "random"}>
          <label class="narrow">
            Random trials
            <input id="random-trials" type="number" min={1} max={1000} step={1} required disabled={!random} value={form.trials} onInput={whole("trials", 1)} />
          </label>
          <details class="random-advanced">
            <summary>Advanced: repeat the same random dates</summary>
            <div class="schedule-row">
              <label class="check">
                <input id="repeat-random" type="checkbox" disabled={!random} checked={form.repeat} onChange={(event) => change({ repeat: event.currentTarget.checked })} /> Repeat the same dates
              </label>
              <label>
                Random date set
                <input id="random-seed" type="number" min={0} max={4294967295} step={1} required disabled={!random || !form.repeat} value={form.seed} onInput={whole("seed", 0)} />
              </label>
            </div>
            <p class="hint">
              Fresh random dates are picked on every run by default. Enable repeat mode to compare strategies on identical dates, or enter a previous result’s date-set number.
            </p>
          </details>
        </div>
      </div>
      <details class="how-it-works">
        <summary>How this works</summary>
        <p class="hint">
          The final mark rolls back to a cached session. SPY is the S&amp;P 500 total-return proxy. For HK/Japan, its comparison uses the latest completed US close available at the local close.
          Month-end dates keep the original day anchor. Equal weights reset at each rebalance.
        </p>
        <p class="hint">
          Random testing samples one trading date independently inside each rebalance block for every trial. Trial count defaults to 24 and is configurable (1–1,000). Each run draws fresh dates;
          repeating a date set is optional under Advanced. Actual holding intervals vary around the selected frequency; both strategy and paired SPY hold cash until the first sampled trade.
        </p>
        <p class="hint">Custom week/month interval: weeks support 1–104. Months support 1–24. Clear this option to use the frequency preset.</p>
      </details>
    </section>
  );
}
