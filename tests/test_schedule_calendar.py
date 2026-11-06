"""Calendar policy against fictional sessions, independent of financial imports."""

# Resolve the importable package for direct-file commands and spawned fixtures.
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[1]))
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest import calendar as c


def days(first, last, weekdays=False):
    first, last = date.fromisoformat(first), date.fromisoformat(last)
    return [first + timedelta(days=n) for n in range((last-first).days+1)
            if not weekdays or (first+timedelta(days=n)).weekday() < 5]


def config(unit='week', count=1, start='2020-01-01', end='2020-02-03'):
    return dict(version=1, start=start, end=end, interval=dict(unit=unit, count=count))


class ConfigurationTests(unittest.TestCase):
    def test_every_supported_count_roundtrips_without_conversion(self):
        for unit, maximum in [('week', 104), ('month', 24)]:
            for count in range(1, maximum+1):
                value = config(unit, count)
                parsed = c.decode_configuration(value)
                self.assertEqual(parsed.to_dict(), value)
                self.assertEqual(parsed.interval, c.Interval(unit, count))
                with self.assertRaises(FrozenInstanceError): parsed.interval.count = 2
                with self.assertRaises(FrozenInstanceError): parsed.start = '2020-01-02'

    def test_strict_count_unit_version_and_shape_validation(self):
        for unit, maximum in [('week', 104), ('month', 24)]:
            for count in [True, False, 1., '1', None, 0, -1, maximum+1, [], {}]:
                with self.subTest(unit=unit, count=count), self.assertRaises(ValueError):
                    c.decode_configuration(config(unit, count))
        for unit in ['weeks', 'months', 'Week', 'day', '', 1, None, []]:
            with self.assertRaises(ValueError): c.decode_configuration(config(unit))
        for version in [True, False, None, 1., '1', 0, 2]:
            with self.assertRaises(ValueError): c.decode_configuration(dict(config(), version=version))
        for value in [None, [], 'calendar', {}, dict(config(), months=1), dict(config(), extra=0),
                      dict(config(), interval=None), dict(config(), interval={'unit':'week'}),
                      dict(config(), interval={'unit':'week','count':1,'months':1})]:
            with self.assertRaises(ValueError): c.decode_configuration(value)
        for key in config():
            value = config(); del value[key]
            with self.assertRaises(ValueError): c.decode_configuration(value)

    def test_legacy_default_and_mapping_are_explicit(self):
        original = dict(start='2020-01-01', end='2021-01-01')
        self.assertEqual(c.legacy_configuration(original).interval, c.Interval('month', 12))
        self.assertNotIn('months', original)
        for months in (1, 3, 6, 12, 24):
            self.assertEqual(c.legacy_configuration(dict(original, months=months)).to_dict(),
                             config('month', months, **original))
        for months in [None, True, 12., '12', 0, 2, 23, 25]:
            with self.assertRaises(ValueError): c.legacy_configuration(dict(original, months=months))
        for extra in [dict(version=1), dict(interval={'unit':'month','count':12}), dict(other=1)]:
            with self.assertRaises(ValueError): c.legacy_configuration(dict(original, **extra))
        with self.assertRaises(ValueError): c.decode_configuration(dict(original, months=12))

    def test_dates_are_canonical_and_increasing(self):
        for start in [None, date(2020,1,1), '20200101', '2020-W01-3', '2020-02-30', '1995-12-31']:
            with self.assertRaises(ValueError): c.decode_configuration(config(start=start))
        for end in [None, 'bad', '2020-01-01', '2019-12-31']:
            with self.assertRaises(ValueError): c.decode_configuration(config(end=end))


class CalendarTests(unittest.TestCase):
    def setUp(self):
        # Deliberate holiday/missing-session gaps; no exchange inference.
        self.calendar = c.SessionCalendar([date.fromisoformat('2020-'+day) for day in
            ['01-03','01-06','01-07','01-10','01-13','01-14','01-20','01-21',
             '01-24','01-27','01-28','01-31','02-03']])

    def entries(self, value):
        return [str(a) for a, b in self.calendar.fixed(value)]

    def test_one_and_two_weeks_anchor_to_calendar_days(self):
        self.assertEqual(self.entries(config()), ['2020-01-03','2020-01-10','2020-01-20','2020-01-24','2020-01-31'])
        self.assertEqual(self.entries(config(count=2)), ['2020-01-03','2020-01-20','2020-01-31'])
        sampled = self.calendar.sample(config(count=2), 2, 42)
        self.assertEqual(sampled['blocks'], [dict(start='2020-01-01',end='2020-01-15',available=6),
            dict(start='2020-01-15',end='2020-01-29',available=5),
            dict(start='2020-01-29',end='2020-02-03',available=1)])
        self.assertEqual(sampled['samples'], [['2020-01-14','2020-01-20','2020-01-31'],
                                            ['2020-01-14','2020-01-24','2020-01-31']])
        self.assertEqual((sampled['window_start'],sampled['window_end']), ('2020-01-03','2020-02-03'))

    def test_final_is_a_scheduled_exit_only_when_a_target_rolls_to_it(self):
        # Weekly targets from 1 January: 8, 15, 22, 29 January and 5 February.
        self.assertFalse(self.calendar.scheduled_final(config()))  # 3 February: a mark.
        self.assertTrue(self.calendar.scheduled_final(config(end='2020-01-31')))  # 29 January rolls to 31.
        self.assertFalse(self.calendar.scheduled_final(config(end='2020-01-28')))
        self.assertTrue(self.calendar.scheduled_final(config(start='2020-01-06', end='2020-01-13')))
        self.assertEqual(self.calendar.fixed(config(end='2020-01-31'))[-1], (date(2020,1,24), date(2020,1,31)))

    def test_all_supported_counts_plan_within_independent_bounds(self):
        calendar = c.SessionCalendar(days('2019-01-01','2025-01-03',weekdays=True))
        for unit, maximum in [('week',104),('month',24)]:
            for count in range(1,maximum+1):
                value = config(unit,count,start='2020-02-29',end='2024-12-29')
                pairs = calendar.fixed(value)
                self.assertEqual(pairs[0][0],date(2020,3,2))
                self.assertEqual(pairs[-1][1],date(2024,12,27))
                self.assertTrue(all(a<b for a,b in pairs))
                sampled = calendar.sample(value,2,4294967295)
                self.assertEqual(sampled['window_start'],'2020-03-02')
                self.assertEqual(sampled['window_end'],'2024-12-27')
                for sample in sampled['samples']:
                    self.assertEqual(sample,sorted(set(sample)))
                    for day, block in zip(sample,sampled['blocks']):
                        self.assertTrue(block['start']<=day<block['end'])

    def test_intermediate_month_and_leap_anchor_without_drift(self):
        calendar = c.SessionCalendar(days('2020-01-01','2025-01-01'))
        pairs = calendar.fixed(config('month',2,start='2020-01-31',end='2020-11-30'))
        self.assertEqual([str(a) for a,b in pairs],['2020-01-31','2020-03-31','2020-05-31','2020-07-31','2020-09-30'])
        pairs = calendar.fixed(config('month',1,start='2020-01-31',end='2020-05-31'))
        self.assertEqual([str(a) for a,b in pairs],['2020-01-31','2020-02-29','2020-03-31','2020-04-30'])
        months = calendar.fixed(config('month',24,start='2020-02-29',end='2024-03-01'))
        weeks = calendar.fixed(config('week',104,start='2020-02-29',end='2024-03-01'))
        self.assertEqual([str(a) for a,b in months],['2020-02-29','2022-02-28','2024-02-29'])
        self.assertEqual([str(a) for a,b in weeks],['2020-02-29','2022-02-26','2024-02-24'])

    def test_sparse_rolls_deduplicate_and_empty_blocks_consume_no_draw(self):
        calendar = c.SessionCalendar([date.fromisoformat('2020-'+day) for day in
            ['01-02','01-03','01-24','01-27','02-03','02-04','02-10']])
        value = config(end='2020-02-10')
        pairs = calendar.fixed(value)
        self.assertEqual([(str(a),str(b)) for a,b in pairs],
            [('2020-01-02','2020-01-24'),('2020-01-24','2020-02-03'),('2020-02-03','2020-02-10')])
        sampled = calendar.sample(value,3,11)
        self.assertEqual([(b['start'],b['end']) for b in sampled['blocks']],
            [('2020-01-01','2020-01-08'),('2020-01-22','2020-01-29'),('2020-01-29','2020-02-05')])
        self.assertEqual(sampled['samples'], [['2020-01-03','2020-01-27','2020-02-04'],
            ['2020-01-02','2020-01-24','2020-02-04'],['2020-01-02','2020-01-24','2020-02-04']])

    def test_window_rejects_unavailable_pairs_deliberately(self):
        for sessions in [[],None,['2020-01-01'],[datetime(2020,1,1)],
                         [date(2020,1,2),date(2020,1,2)], [date(2020,1,2),date(2020,1,1)]]:
            with self.assertRaises(ValueError): c.SessionCalendar(sessions)
        for start,end in [('2019-01-01','2019-12-31'),('2020-01-01','2020-01-03'),
                          ('2020-02-01','2020-02-03'),('2020-01-01','2020-02-04')]:
            with self.assertRaises(ValueError): self.calendar.window(start,end)
        singleton = c.SessionCalendar([date(2020,1,3)])
        with self.assertRaises(ValueError): singleton.window('2020-01-01','2020-01-03')
        self.assertEqual(self.calendar.window('2019-12-01','2020-01-12'),(date(2020,1,3),date(2020,1,10)))

    def test_explicit_trades_have_no_interval_dependency(self):
        first,final,pairs = self.calendar.explicit(['2020-01-07','2020-01-24'],'2020-01-01','2020-02-02')
        self.assertEqual((first,final),(date(2020,1,3),date(2020,1,31)))
        self.assertEqual(pairs,[(date(2020,1,7),date(2020,1,24)),(date(2020,1,24),date(2020,1,31))])
        for trades in [[],None,'2020-01-07',['2020-01-07','2020-01-07'],['2020-01-24','2020-01-07'],
                       ['2020-01-08'],['2020-01-31'],['2019-12-31'],[None]]:
            with self.assertRaises(ValueError): self.calendar.explicit(trades,'2020-01-01','2020-02-02')

    def test_sampling_validates_before_any_draw_and_checkpoints_propagate(self):
        for trials, seed in [(0,1),(101,1),(True,1),(1.,1),(None,1),(1,None),(1,True),(1,1.),(1,-1),(1,2**32)]:
            with self.assertRaises(ValueError): self.calendar.sample(config(),trials,seed)
        class Stop(Exception): pass
        def stop(): raise Stop()
        for operation in [lambda:self.calendar.fixed(config(),checkpoint=stop),
                          lambda:self.calendar.sample(config(),1,1,checkpoint=stop),
                          lambda:self.calendar.explicit(['2020-01-07'],'2020-01-01','2020-02-03',checkpoint=stop)]:
            with self.assertRaises(Stop): operation()


if __name__ == '__main__':
    unittest.main()
