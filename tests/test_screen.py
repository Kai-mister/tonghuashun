import unittest
from unittest.mock import Mock, PropertyMock, patch

from ths.simulator import Simulator


class ScreenTests(unittest.TestCase):
    def check(self, readings):
        trader = Mock()
        type(trader.d).info = PropertyMock(side_effect=[{"screenOn": on} for on in readings])
        return Simulator(trader)

    def test_awake(self):
        sim = self.check([True])
        sim.ensure_screen_on()
        sim.d.screen_on.assert_not_called()

    def test_wakes_before_navigation(self):
        sim = self.check([False, True])
        sim.ensure_screen_on()
        sim.d.screen_on.assert_called_once_with()

    @patch("ths.simulator.time.sleep")
    def test_failed_wake_stops_navigation(self, sleep):
        sim = self.check([False] * 11)
        with self.assertRaisesRegex(RuntimeError, "未能唤醒"):
            sim.tab("卖出")
        sim.d.app_start.assert_not_called()
