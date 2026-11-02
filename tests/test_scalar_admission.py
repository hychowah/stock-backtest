"""Formula capability fails before readiness/financial execution; source binding."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from copy import deepcopy
import hashlib
import tempfile
import unittest
from unittest.mock import Mock,patch
from backtest import selection
from backtest.application.calculations import Selectable
from backtest.application.candidate_calculations import Candidate
from backtest.engines.numerical.policy import PolicyProgram,require_supported


class AdmissionTests(unittest.TestCase):
    def test_formula_intent_including_empty_payloads_is_explicitly_unsupported(self):
        fields=('strategy_version','variables','ranking','conditions','selection',
                'scalar_selection','selection_plan','program','definition','formula','bundle')
        for field in fields:
            for value in (None,{},[]):
                options={field:value};before=deepcopy(options)
                with self.assertRaisesRegex(ValueError,'UNSUPPORTED_CAPABILITY.*custom formula'):
                    require_supported(options)
                self.assertEqual(options,before)
        for name in ('scalar-selection-plan','scalar-selection','formula-program',
                     'variable-definition','variable-bundle','formula-evaluation'):
            with self.assertRaisesRegex(ValueError,'UNSUPPORTED_CAPABILITY'):
                require_supported(dict(format=name,version=1))
        with self.assertRaisesRegex(ValueError,'UNSUPPORTED_CAPABILITY'):
            require_supported(dict(filters=[dict(variable_id='draft:x',revision='fixture',op='gt',value=0.)]))
        require_supported(dict(metric='ev_ebitda',selection_order='rank_first'))

    def test_selectable_rejects_submitted_and_recorded_formula_before_readiness(self):
        owner=Selectable(Mock());self.addCleanup(owner.retire);self.addCleanup(owner.close)
        options=dict(engine='experimental',start='2015-01-01',end='2016-12-30',months=3)
        with patch.object(owner,'ready_for',side_effect=AssertionError('readiness touched')), \
             patch.object(owner.experimental,'calculate',side_effect=AssertionError('dispatch touched')):
            for intent in (dict(variables={}),dict(selection_plan={}),dict(ranking={})):
                with self.assertRaisesRegex(ValueError,'UNSUPPORTED_CAPABILITY'):
                    owner.calculate('custom',dict(options,**intent),None,None)
            recorded=dict(start=options['start'],end=options['end'],months=3,
                requested=1,seed=42,options=dict(conditions=[]))
            before=deepcopy(recorded)
            with self.assertRaisesRegex(ValueError,'UNSUPPORTED_CAPABILITY'):
                owner.calculate('random',options,None,None,planned=recorded)
            self.assertEqual(recorded,before)
        owner.preparation.status.assert_not_called();owner.preparation._runtime.assert_not_called()
        self.assertEqual(owner.preflight({}),'original')

    def test_candidate_direct_and_bounded_calls_reject_before_preparation(self):
        preparation=Mock();owner=Candidate(preparation)
        self.addCleanup(owner.retire);self.addCleanup(owner.close)
        for call in (lambda:owner.calculate('custom',dict(variables={}),None,None),
                     lambda:owner.calculate('random',{},None,None,planned=dict(options=dict(ranking={}))),
                     lambda:owner.calculate_into('custom',dict(selection_plan={}),Path('unused'),None,None)):
            with self.assertRaisesRegex(ValueError,'UNSUPPORTED_CAPABILITY'):call()
        preparation.status.assert_not_called();preparation._runtime.assert_not_called()
        self.assertIsNone(owner.runtime)

    def test_numerical_source_fingerprint_binds_delegated_selection_policy(self):
        current=PolicyProgram();key='backtest/selection.py'
        self.assertEqual(current.source_hashes[key],hashlib.sha256(Path(selection.__file__).read_bytes()).hexdigest())
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'selection.py';source.write_text('synthetic selection policy one')
            with patch.object(selection,'__file__',str(source)):
                first=PolicyProgram();source.write_text('synthetic selection policy two')
                second=PolicyProgram()
            self.assertNotEqual(first.source_hashes[source.as_posix()],second.source_hashes[source.as_posix()])
            self.assertNotEqual(first.signature,second.signature)
        self.assertEqual(PolicyProgram().signature,current.signature)


if __name__=='__main__':unittest.main()
