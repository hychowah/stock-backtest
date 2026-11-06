"""Pure saved-session planning. No financial inputs, I/O or ownership policy.

Calendar configuration version 1 is independent of database and result versions.
Decode only the canonical representation; use legacy_configuration explicitly
for old monthly requests. Unknown fields and mixed representations always fail.
"""
from bisect import bisect_left, bisect_right
from calendar import monthrange
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
import random

from backtest.financial import rules

VERSION = 1
LEGACY_MONTHS = (1, 3, 6, 12, 24)


def _day(value):
    """Accept canonical ISO dates only, with one error type at this boundary."""
    if type(value) is not str:
        raise ValueError('Calendar dates must use YYYY-MM-DD.')
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError('Calendar dates must use YYYY-MM-DD.') from None
    if parsed.isoformat() != value:
        raise ValueError('Calendar dates must use YYYY-MM-DD.')
    return parsed


@dataclass(frozen=True)
class Interval:
    """An integer 1..104 calendar weeks or 1..24 calendar months."""
    unit: str
    count: int

    def __post_init__(self):
        maximum = {'week': 104, 'month': 24}.get(self.unit) if type(self.unit) is str else None
        if maximum is None or type(self.count) is not int or not 1 <= self.count <= maximum:
            raise ValueError('Choose 1–104 weeks or 1–24 months with an integer count.')


@dataclass(frozen=True)
class Configuration:
    """Immutable version-1 requested bounds and interval; bounds are inclusive."""
    start: str
    end: str
    interval: Interval
    version: int = VERSION

    def __post_init__(self):
        if type(self.version) is not int or self.version != VERSION:
            raise ValueError('Unsupported calendar configuration version.')
        if type(self.interval) is not Interval:
            raise ValueError('Calendar configuration requires an Interval.')
        lower, upper = _day(self.start), _day(self.end)
        if lower < rules.FIRST_DAY or lower >= upper:
            raise ValueError(f'Choose increasing dates from {rules.FIRST_DAY}.')

    def to_dict(self):
        return dict(version=self.version, start=self.start, end=self.end,
                    interval=dict(unit=self.interval.unit, count=self.interval.count))


def decode_configuration(value):
    """Decode exactly {version,start,end,interval:{unit,count}}; never coerce."""
    if type(value) is Configuration:
        return value
    if not isinstance(value, Mapping) or set(value) != {'version', 'start', 'end', 'interval'}:
        raise ValueError('Expected version, start, end and interval only.')
    interval = value['interval']
    if not isinstance(interval, Mapping) or set(interval) != {'unit', 'count'}:
        raise ValueError('Expected interval unit and count only.')
    return Configuration(value['start'], value['end'], Interval(interval['unit'], interval['count']), value['version'])


def legacy_configuration(value):
    """Map {start,end,months?} to v1 months. Omission means 12; null is invalid.

    Only 1, 3, 6, 12 and 24 are legacy counts. Reject version/interval fields,
    even if they would describe the same monthly schedule. Never rewrite input.
    """
    if not isinstance(value, Mapping) or not {'start', 'end'} <= set(value) or set(value) - {'start', 'end', 'months'}:
        raise ValueError('Expected legacy start, end and optional months only.')
    months = value.get('months', 12)
    if type(months) is not int or months not in LEGACY_MONTHS:
        raise ValueError('Rebalance interval must be 1, 3, 6, 12 or 24 months.')
    return Configuration(value['start'], value['end'], Interval('month', months))


class SessionCalendar:
    """Plan against ordered, unique date objects. Never infer missing sessions.

    Optional checkpoints let an application retain its cancellation policy.
    They are called for each target, explicit trade and random draw. This module
    neither imports that policy nor takes ownership of application resources.
    """
    def __init__(self, sessions):
        try:
            self.sessions = tuple(sessions)
        except TypeError:
            raise ValueError('Trading sessions must be an ordered sequence of dates.') from None
        if not self.sessions or any(type(day) is not date for day in self.sessions):
            raise ValueError('Trading sessions must be a nonempty ordered sequence of dates.')
        if any(left >= right for left, right in zip(self.sessions, self.sessions[1:])):
            raise ValueError('Trading sessions must be increasing and unique.')

    def window(self, start, end):
        """Roll start forward and inclusive end back; require first < final.

        An end after the last saved session is unavailable, even if rolling it
        back would find a price. This operation has no interval dependency.
        """
        lower, upper = _day(start), _day(end)
        if lower < rules.FIRST_DAY or lower >= upper or upper > self.sessions[-1]:
            raise ValueError(f'Choose increasing dates from {rules.FIRST_DAY} through {self.sessions[-1]}.')
        left, right = bisect_left(self.sessions, lower), bisect_right(self.sessions, upper) - 1
        if right < 0 or left >= right:
            raise ValueError('No complete trading interval in the selected dates.')
        return self.sessions[left], self.sessions[right]

    @staticmethod
    def _target(start, interval, number):
        """Derive every target from the original start, never a rolled target."""
        if interval.unit == 'week':
            days = 7 * interval.count * number
            return start + timedelta(days=days) if days <= (date.max - start).days else date.max
        absolute = start.year * 12 + start.month - 1 + interval.count * number
        year, month = divmod(absolute, 12)
        month += 1
        return date(year, month, min(start.day, monthrange(year, month)[1])) if year <= 9999 else date.max

    def _bounds(self, configuration, checkpoint):
        lower = _day(configuration.start)
        _, final = self.window(configuration.start, configuration.end)
        number = 0
        while True:
            if checkpoint is not None:
                checkpoint()
            left = self._target(lower, configuration.interval, number)
            if left >= final:
                return
            yield left, min(self._target(lower, configuration.interval, number + 1), final)
            number += 1

    def fixed(self, configuration, *, checkpoint=None):
        """Return contiguous entry/exit pairs, ending at the common final mark.

        Roll targets forward, deduplicate rolled entries and exclude final from
        entries. Sparse saved sessions can collapse several nominal targets.
        """
        configuration = decode_configuration(configuration)
        _, final = self.window(configuration.start, configuration.end)
        entries = []
        for target, _ in self._bounds(configuration, checkpoint):
            actual = self.sessions[bisect_left(self.sessions, target)]
            if actual < final and (not entries or entries[-1] != actual):
                entries.append(actual)
        return list(zip(entries, entries[1:] + [final]))

    def scheduled_final(self, configuration):
        """Whether the final mark of fixed(configuration) is also a scheduled exit.

        It is when a nominal target rolls forward to the final session.
        Otherwise the last period ends on a mark to date.
        """
        configuration = decode_configuration(configuration)
        _, final = self.window(configuration.start, configuration.end)
        previous = self.sessions[bisect_left(self.sessions, final) - 1]
        lower, number = _day(configuration.start), 1
        while (target := self._target(lower, configuration.interval, number)) <= previous:
            number += 1
        return target <= final

    def sample(self, configuration, trials, seed, *, checkpoint=None):
        """Return a calendar handoff, not a financial result or saved record.

        Nominal blocks are half-open [left,right), clipped at final. Keep a
        nonempty final partial block. Skip empty blocks without consuming a
        draw. Draw trial-major then block-major with Random(seed).choice over
        ascending sessions. Seed is explicit; the caller owns fresh seed policy.
        """
        configuration = decode_configuration(configuration)
        if type(trials) is not int or not 1 <= trials <= 100:
            raise ValueError('Choose between 1 and 100 random-date trials.')
        if type(seed) is not int or not 0 <= seed <= 4294967295:
            raise ValueError('Choose a whole-number seed between 0 and 4294967295.')
        first, final = self.window(configuration.start, configuration.end)
        blocks, populations = [], []
        for left, right in self._bounds(configuration, checkpoint):
            choices = self.sessions[bisect_left(self.sessions, left):bisect_left(self.sessions, right)]
            if choices:
                blocks.append(dict(start=str(left), end=str(right), available=len(choices)))
                populations.append(choices)
        generator = random.Random(seed)
        samples = []
        for _ in range(trials):
            row = []
            for choices in populations:
                if checkpoint is not None:
                    checkpoint()
                row.append(str(generator.choice(choices)))
            samples.append(row)
        return dict(configuration=configuration.to_dict(), seed=seed, requested=trials,
                    window_start=str(first), window_end=str(final), blocks=blocks, samples=samples)

    def explicit(self, dates, start, end, *, checkpoint=None):
        """Return (first, final, periods) without constructing an interval.

        Trades must be nonempty, increasing, unique saved sessions in the common
        window, strictly before final. The last trade exits at the final mark.
        """
        first, final = self.window(start, end)
        if isinstance(dates, (str, bytes)):
            raise ValueError('Explicit trades must be an ordered sequence of dates.')
        try:
            iterator = iter(dates)
        except TypeError:
            raise ValueError('Explicit trades must be an ordered sequence of dates.') from None
        trades = []
        for value in iterator:
            if checkpoint is not None:
                checkpoint()
            day = _day(value)
            index = bisect_left(self.sessions, day)
            if not first <= day < final or self.sessions[index] != day or (trades and trades[-1] >= day):
                raise ValueError('Sampled trades must be increasing cached sessions inside the backtest window.')
            trades.append(day)
        if not trades:
            raise ValueError('Explicit trades must not be empty.')
        return first, final, list(zip(trades, trades[1:] + [final]))
