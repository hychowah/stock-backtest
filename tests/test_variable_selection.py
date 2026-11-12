"""Formula condition thresholds and formula-root admission in Original selection."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import unittest
from backtest.application import scalar_execution as x, strategy_requests as s
from backtest.variables import definitions as d
import test_strategy_requests as requests
import test_variable_definitions as language
from test_scalar_execution import Fixture


def program(expression=None, unit='scalar', display='number'):
    return d.validate(language.bundle(language.entry(language.definition(expression, unit, display))))


def capture(conditions, value='.1', unit='scalar', display='number'):
    """A constant formula ranking with conditions on the same formula root."""
    authored=language.entry(language.definition(language.constant(value,unit),unit,display),'draft:ranking')
    source=requests.formula(authored)
    rows=[dict(requests.condition(source),**change) for change in conditions]
    intent=requests.intent(source,rows);intent['pool']='cached'
    return s.capture_strategy(intent,submitted=[authored])


class FormulaThresholdTests(unittest.TestCase):
    def error(self,code,call,*args,**kwargs):
        with self.assertRaises(d.FormulaError) as caught:call(*args,**kwargs)
        self.assertEqual(caught.exception.code,code)
        return caught.exception

    def test_threshold_exact_decimal_scaling_and_captured_submission(self):
        captured=capture([dict(threshold=dict(value='+8e0',unit='percent'))])
        normalized=captured.to_dict()['selection']['conditions'][0]
        self.assertEqual(normalized['submitted_threshold'],dict(value='+8e0',unit='percent'))
        self.assertEqual(normalized['threshold'],dict(value='0.08',unit='scalar'))
        self.assertEqual((normalized['comparison_value'],normalized['storage_comparison_value']),(.08,.08))
        fixture=Fixture(4);self.addCleanup(fixture.close)
        stocks,_=fixture.select(captured)
        self.assertEqual(len(stocks),4)
        # Conditions are strict: a formula value equal to the threshold fails.
        stocks,_=fixture.select(capture([dict(threshold=dict(value='1e1',unit='percent'))]))
        self.assertEqual(stocks,[])
        self.assertEqual(d.normalize_quantity(dict(value='-1.25',unit='usd_million'),'USD')['comparison_value'],-1250000.)
        self.assertEqual(d.normalize_quantity(dict(value='12',unit='usd_per_share'),'USD/share')['comparison_value'],12.)
        self.assertEqual(d.normalize_quantity(dict(value='-0',unit='scalar'),'scalar')['threshold']['value'],'0')

    def test_threshold_unit_literal_agreement(self):
        for quantity in (dict(value='1',unit='usd'),dict(value='NaN',unit='scalar'),dict(value='1e9999999',unit='scalar'),
                         dict(value='1'*65,unit='scalar'),dict(value='5e-324',unit='percent')):
            with self.subTest(quantity=quantity):
                with self.assertRaises(d.FormulaError):capture([dict(threshold=quantity)])
        bad=dict(submitted_threshold=dict(value='8',unit='percent'),threshold=dict(value='0.09',unit='scalar'))
        self.error('INVALID_STRATEGY',capture,[bad])

    def test_threshold_range_is_checked_after_exact_canonical_scaling(self):
        for value,display,unit,canonical in (
                ('1e310','percent','scalar','1e308'),
                ('1e-325','usd_million','USD','1e-319')):
            with self.subTest(value=value,display=display):
                converted=d.normalize_quantity(dict(value=value,unit=display),unit)
                direct=d.normalize_quantity(dict(value=canonical,unit=unit),unit)
                self.assertEqual(converted['threshold'],direct['threshold'])
                self.assertEqual(converted['comparison_value'],float(canonical))
                self.assertEqual(converted['submitted_threshold'],dict(value=value,unit=display))
                captured=capture([dict(threshold=dict(value=value,unit=display))],'1',unit,
                    'number' if unit=='scalar' else 'usd')
                row=captured.to_dict()['selection']['conditions'][0]
                self.assertEqual((row['comparison_value'],row['storage_comparison_value']),(float(canonical),float(canonical)))
        for value,display,unit in (
                ('1e309','scalar','scalar'),('1e-325','scalar','scalar'),
                ('1e308','usd_million','USD'),('5e-324','percent','scalar')):
            self.error('INVALID_LITERAL',d.normalize_quantity,dict(value=value,unit=display),unit)
        # Formula constants already use canonical units and retain their range checks.
        for value in ('1e310','1e-325'):
            self.error('INVALID_LITERAL',program,language.constant(value))


class FormulaRootAdmissionTests(unittest.TestCase):
    def test_admission_denials_survive_constant_only_selection(self):
        fixture=Fixture(4);self.addCleanup(fixture.close)
        fixture.db.research.execute("UPDATE companies SET listed=0 WHERE symbol='A0000'")
        # The open book stores listed companies only (books.book); a stored row is its root's admission.
        fixture.db.execute("DELETE FROM book_rows WHERE book=? AND symbol='A0000'",(fixture.latest,))
        constant=fixture.capture(language.constant('7'))
        stocks,_=fixture.select(constant,latest=True)
        self.assertEqual([row['symbol'] for row in stocks],['A0001','A0002','A0003'])


if __name__=='__main__':unittest.main()
