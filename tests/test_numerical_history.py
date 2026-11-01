"""Source-derived metric inputs, supported mutations and closed rejection."""
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.financial import metrics
from contextlib import contextmanager
import inspect
import unittest
from unittest.mock import patch

import test_numerical_generation as fixtures
from backtest.engines.numerical.policy import PolicyProgram


class HistoryAdapterTests(unittest.TestCase):
    setUp = fixtures.GenerationTests.setUp

    @contextmanager
    def mutation(self, name, old, new, globals_change=None):
        original = getattr(metrics, name)
        source = inspect.getsource(original)
        self.assertIn(old, source)
        source = source.replace(old, new, 1)
        path = self.root / ('history_' + name + '.py')
        path.write_text(source, encoding='utf8')
        namespace = dict(original.__globals__, **(globals_change or {}))
        exec(compile(source, str(path), 'exec'), namespace)
        with patch.object(metrics, name, namespace[name]):
            yield

    def test_actual_metric_bodies_without_history_and_missing_average(self):
        policy = PolicyProgram()
        observation = dict(fiscal='2014-06-30', enterprise_value=100.,
                           ev_ebitda=20., ebitda_yield=0.05)
        history = [dict(fiscal=f'{year}-06-30', ebitda=5.) for year in (2012, 2013, 2014)]
        values = [0.] * len(policy.output_names)
        values[policy.output_index['metric3_multiple']] = 20.
        values[policy.output_index['metric3_yield']] = 0.05
        self.assertEqual(policy._current(observation), metrics.current_multiple(observation, history))
        self.assertEqual(policy._three(observation, values, 5.), metrics.three_year_multiple(observation, history))
        for average in (None, 0., -1.):
            self.assertIsNone(policy._three(observation, values, average))

    def test_observation_and_average_guards_still_execute_and_change_identity(self):
        base = PolicyProgram()
        mutations = [
            ('current_multiple', "    return observation['ev_ebitda']", "    if observation['ev_ebitda'] < 100:\n        return None\n    return observation['ev_ebitda']"),
            ('three_year_multiple', 'average<=0', 'average<=100')]
        observation = dict(fiscal='2014-06-30', enterprise_value=100., ev_ebitda=20., ebitda_yield=0.05)
        history = [dict(fiscal=f'{year}-06-30', ebitda=5.) for year in (2012, 2013, 2014)]
        for name, old, new in mutations:
            with self.subTest(name=name), self.mutation(name, old, new):
                policy = PolicyProgram()
                self.assertNotEqual(policy.signature, base.signature)
                actual = policy._current(observation) if name == 'current_multiple' else policy._three(observation, [0.] * len(policy.output_names), 5.)
                self.assertIsNone(actual)
                self.assertEqual(actual, getattr(metrics, name)(observation, history))

    def test_direct_alias_capture_and_namespace_history_use_reject_construction(self):
        marker = "    return observation['ev_ebitda'], observation['ebitda_yield']"
        for replacement in (
                '    return history[0]',
                '    alias=history\n    return alias[0]',
                '    return (lambda: history)()',
                '    def hidden():\n        return 1\n' + marker,
                "    return locals()['history']",
                "    return vars()['history']",
                "    return eval('history')",
                "    return observation.__class__"):
            with self.subTest(replacement=replacement), self.mutation('current_multiple', marker, replacement):
                with self.assertRaisesRegex(ValueError, '(Source|Unsupported source) metric'):
                    PolicyProgram()
                self.assertEqual(fixtures.ng._attachments, {})

    def test_three_year_substitution_rejects_changes_before_discarding_them(self):
        cases = [
            ("observation['fiscal'],3", "observation['fiscal'],4"),
            ("observation['fiscal'],3", "'2013-06-30',3"),
            ('multiple=observation', 'multiple=0\n    multiple=observation'),
            ('average=annual_average', 'average=1\n    average=annual_average'),
            ('    return multiple, 1/multiple', '    alias=history\n    return multiple, 1/multiple'),
            ('    return multiple, 1/multiple', '    return multiple+1, 1/multiple')]
        for old, new in cases:
            with self.subTest(new=new), self.mutation('three_year_multiple', old, new):
                with self.assertRaises(ValueError):PolicyProgram()
                self.assertEqual(fixtures.ng._attachments, {})

    def test_average_callback_must_be_the_export_calculator(self):
        with self.mutation('three_year_multiple', 'average<=0', 'average<=0',
                           dict(annual_average=lambda *args: 123.)):
            with self.assertRaisesRegex(ValueError, 'Unsupported prepared source metric'):
                PolicyProgram()


if __name__ == '__main__':unittest.main()
