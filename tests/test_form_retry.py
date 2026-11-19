import unittest
from unittest.mock import Mock,patch
from ths.simulator import Simulator
from phone.local import Element

class FormRetryTests(unittest.TestCase):
    @patch('ths.simulator.time.sleep')
    def test_retries_preparation_only(self,sleep):
        sim=Simulator(Mock())
        sim.prepare_form=Mock(side_effect=[RuntimeError('StaleObjectException'),RuntimeError('交易表单未加载完成'),('TCL科技','买 入(模拟炒股)')])
        self.assertEqual(sim.form('买入','000100')[0],'TCL科技')
        self.assertEqual(sim.prepare_form.call_count,3)

    @patch('ths.simulator.time.sleep')
    def test_account_change_and_exhausted_retry_stop(self,sleep):
        for error,count in [('模拟账号已变化',1),('交易表单未加载完成',3)]:
            sim=Simulator(Mock());sim.prepare_form=Mock(side_effect=RuntimeError(error))
            with self.assertRaises(RuntimeError):sim.form('买入','000100')
            self.assertEqual(sim.prepare_form.call_count,count)

    @patch('phone.local.time.sleep')
    @patch('phone.local.rpc')
    def test_stale_read_reacquires_element(self,rpc,sleep):
        rpc.side_effect=[True,RuntimeError('StaleObjectException'),True,'**1326']
        self.assertEqual(Element(text='account').get_text(),'**1326')
        self.assertEqual(rpc.call_count,4)

    @patch('ths.simulator.time.sleep')
    def test_search_click_false_but_selection_succeeded(self,sleep):
        sim=Simulator(Mock())
        popup=[{'resource-id':sim.pkg+':id/close_btn'},
               {'resource-id':sim.pkg+':id/stockcode_tv','text':'301236','bounds':'[0,0][100,100]'}]
        selected=[{'resource-id':sim.pkg+':id/page_title_view','text':'模拟炒股'},
                  {'resource-id':sim.pkg+':id/auto_stockcode','text':'301236'}]
        sim.nodes=Mock(side_effect=[popup,popup,selected])
        field=Mock();field.click.side_effect=RuntimeError('无法点击')
        sim.field=Mock(return_value=field)
        sim.select_search_result('301236')
        field.click.assert_called_once()

    @patch('ths.simulator.time.sleep')
    def test_search_refresh_recovers_without_blind_double_click(self,sleep):
        sim=Simulator(Mock())
        popup=[{'resource-id':sim.pkg+':id/close_btn'},
               {'resource-id':sim.pkg+':id/stockcode_tv','text':'301236','bounds':'[0,0][100,100]'}]
        selected=[{'resource-id':sim.pkg+':id/page_title_view','text':'模拟炒股'},
                  {'resource-id':sim.pkg+':id/auto_stockcode','text':'301236'}]
        sim.nodes=Mock(side_effect=[popup,popup,popup[:1],popup,popup,selected])
        field=Mock();field.click.side_effect=[RuntimeError('NullPointerException'),None]
        sim.field=Mock(return_value=field)
        sim.select_search_result('301236')
        self.assertEqual(field.click.call_count,2)

    @patch('ths.simulator.time.sleep')
    def test_wrong_result_never_clicked(self,sleep):
        sim=Simulator(Mock());sim.field=Mock()
        sim.nodes=Mock(return_value=[{'resource-id':sim.pkg+':id/close_btn'},
            {'resource-id':sim.pkg+':id/stockcode_tv','text':'000034','bounds':'[0,0][100,100]'}])
        with self.assertRaisesRegex(RuntimeError,'选择 301236 超时'):
            sim.select_search_result('301236')
        sim.field.assert_not_called()
