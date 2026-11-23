import os
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from phone.native import enabled
from phone.backend import FILES, bundle, validate_bundle

class NativeRuntimeTests(unittest.TestCase):
    def test_native_is_explicit(self):
        for value,expected in [('',False),('0',False),('1',True)]:
            with patch.dict(os.environ,{'THS_NATIVE':value}):self.assertEqual(enabled(),expected)

    def test_native_module_is_in_versioned_upgrade(self):
        import json
        self.assertIn('phone/native.py',FILES)
        digest,files=validate_bundle(json.dumps(bundle(Path('.'))).encode())
        self.assertIn('phone/native.py',files)

    def test_runtime_contains_no_state_and_native_files_are_apk_libraries(self):
        import json
        with zipfile.ZipFile('android/runtime/runtime.zip') as runtime, zipfile.ZipFile('android/runtime/native.zip') as native:
            names=runtime.namelist()
            self.assertFalse(any(n.startswith(('state/','.config/')) for n in names))
            self.assertTrue(all(n.startswith(('prefix/','zoneinfo/')) or n in ('ca.pem','native-links.json') for n in names))
            mapping=json.loads(runtime.read('native-links.json'))
            self.assertTrue(mapping)
            for source,target in mapping.items():
                self.assertNotIn(source,names)
                self.assertIn('lib/arm64-v8a/'+target,native.namelist())
            for name in native.namelist():
                self.assertTrue(name.startswith('lib/arm64-v8a/lib') and name.endswith('.so'))
                self.assertEqual(native.read(name)[:4],b'\x7fELF')

    def test_native_click_uses_exactly_one_observed_gesture(self):
        from phone.local import Element
        from unittest.mock import Mock
        xml='<hierarchy><node package="com.hexin.plat.android" text="交易" bounds="[10,20][30,40]"/></hierarchy>'
        rpc=Mock(side_effect=[True,xml,True])
        with patch.dict(os.environ,{'THS_NATIVE':'1'}),patch('phone.local.rpc',rpc):
            Element(packageName='com.hexin.plat.android',text='交易').click()
        self.assertEqual([c.args[0] for c in rpc.call_args_list],['waitForExists','dumpWindowHierarchy','swipe'])
        self.assertEqual(rpc.call_args_list[-1].args,('swipe',20,30,20,30,0))

    def test_native_click_refuses_disappeared_target(self):
        from phone.local import Element
        from unittest.mock import Mock
        rpc=Mock(side_effect=[True,'<hierarchy/>'])
        with patch.dict(os.environ,{'THS_NATIVE':'1'}),patch('phone.local.rpc',rpc):
            with self.assertRaisesRegex(RuntimeError,'控件已变化'):
                Element(text='确认买入').click()
        self.assertEqual(rpc.call_count,2)
