"""Actual native form validity after restoring a wide weekly saved calendar."""
import json
import os
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from candidate_browser_fixture import FictionalWorkspace,CandidateService
from native_browser_fixture import BrowserStorage,NativeBrowser


@unittest.skipUnless(os.name=='nt','Actual native Chrome requires Windows.')
class RestoreTests(unittest.TestCase):
    def test_weekly_restore_resets_month_maximum_without_calculation(self):
        with FictionalWorkspace() as workspace:
            service=CandidateService(workspace,scenario='ordinary').start()
            storage=workspace.own(BrowserStorage());browser=workspace.own(NativeBrowser(storage,service))
            try:
                browser.start();browser.navigate('http://127.0.0.1:'+str(service.port)+'/')
                browser.wait("!!ResultArtifacts.forView('latest')")
                browser.wait('EngineControls.calendarSupported()')
                # A month change sets the old cap. Restoration must replace it.
                state=browser.evaluate("""(()=>{const u=document.querySelector('#calendar-unit'),n=document.querySelector('#calendar-count');u.value='month';u.dispatchEvent(new Event('change',{bubbles:true}));const previous=n.max;restoreBacktestSettings({mode:'custom',calendar:{version:1,start:'2015-01-02',end:'2016-12-30',interval:{unit:'week',count:104}}});return {previous,unit:u.value,count:n.value,max:n.max,valid:n.checkValidity(),supported:EngineControls.calendarSupported()};})()""")
                self.assertEqual(state,dict(previous='24',unit='week',count='104',max='104',valid=True,supported=True))
                for width,height,label in [(1440,1000,'calendar-desktop'),(390,844,'calendar-mobile')]:
                    browser.viewport(width,height)
                    browser.evaluate("document.querySelector('#calendar-controls').scrollIntoView({block:'center'})")
                    self.assertTrue(browser.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    browser.screenshot(label)
                self.assertEqual(browser.errors,[])
                print(json.dumps(dict(check='native-week104-restoration',state=state)),flush=True)
            finally:
                browser.close();service.close();print(json.dumps(dict(artifacts=storage.preserve())),flush=True)
                print(json.dumps(dict(closed=service.owner.closure(),browser=browser.owned.closure())),flush=True)


if __name__=='__main__':unittest.main()
