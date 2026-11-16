import unittest
from unittest.mock import Mock, patch
from decimal import Decimal
from ths.simulator import Simulator


def nodes(**changes):
    data = dict(dialog_title='委托买入确认', stock_code_value='301209',
                stock_name_value='联合化学', number_value='200', price_value='46.130')
    data.update(changes)
    return [{'resource-id': Simulator.pkg + ':id/' + k, 'text': v} for k, v in data.items()]


@patch('ths.simulator.time.sleep')
class ConfirmationTests(unittest.TestCase):
    def sim(self, frames):
        s = Simulator(Mock())
        s.nodes = Mock(side_effect=frames)
        s.check_account = Mock()
        return s

    def test_delayed_dialog_and_stale_name(self, sleep):
        s = self.sim([[], nodes(stock_name_value='旧股票'), nodes(), nodes()])
        s.wait_confirmation('买入', '301209', '联合化学', 200, Decimal('46.13'))
        self.assertEqual(s.nodes.call_count, 4)

    def test_transient_match_does_not_pass(self, sleep):
        s = self.sim([nodes()] + [nodes(number_value='100')] * 24)
        with self.assertRaisesRegex(ValueError, 'number_value'):
            s.wait_confirmation('买入', '301209', '联合化学', 200, Decimal('46.13'))
        s.check_account.assert_not_called()

    def test_price_mismatch_reports_expected_and_actual(self, sleep):
        s = self.sim([nodes(price_value='46.14')] * 25)
        with self.assertRaisesRegex(ValueError, '46.14'):
            s.wait_confirmation('买入', '301209', '联合化学', 200, Decimal('46.13'))
        s.check_account.assert_not_called()
