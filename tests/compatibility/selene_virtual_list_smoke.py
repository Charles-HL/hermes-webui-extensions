"""Native Core session-list regression; no agent, model, or fixture renderer."""
import json
import os
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright
from browser_smoke import _start_server, _terminate

ROOT = Path(__file__).resolve().parents[2]
CORE = Path(os.environ['HERMES_CORE_DIR']).resolve()
EXTENSIONS = Path(os.environ.get('HERMES_EXTENSION_ROOT', ROOT / 'extensions')).resolve()
OUT = Path(os.environ.get('COMPATIBILITY_EVIDENCE_DIR', 'compatibility-evidence')) / 'selene-virtual-list'
OUT.mkdir(parents=True, exist_ok=True)


def snapshot(page):
    return page.evaluate("""() => {
      const list=sessionList, box=list.getBoundingClientRect();
      const rows=[...list.querySelectorAll('.session-item')];
      const visible=rows.filter(n=>{const r=n.getBoundingClientRect();return r.bottom>box.top&&r.top<box.bottom});
      return {scrollTop:list.scrollTop,height:list.clientHeight,overflow:getComputedStyle(list).overflowY,
        total:Number(list.dataset.sessionVirtualTotal),start:Number(list.dataset.sessionVirtualStart),
        end:Number(list.dataset.sessionVirtualEnd),rendered:rows.length,visible:visible.length,
        last:rows.at(-1)?.dataset.sid,expectedLast:_sessionVisibleSidebarIds.at(-1),
        profileParent:profileChipWrap.parentElement.className};
    }""")


with tempfile.TemporaryDirectory(prefix='selene-core-regression-') as trial:
    proc, log, url, _ = _start_server(core_dir=CORE, extension_root=EXTENSIONS,
        manifest_relative='selene/manifest.json', state_root=Path(trial),
        log_path=OUT / 'server.log', requested_port=0)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True,
                executable_path=os.environ.get('HERMES_REVIEW_BROWSER_EXECUTABLE'))
            context = browser.new_context(viewport={'width':390,'height':844})
            context.route('**/*', lambda r: r.continue_() if r.request.url.startswith(url) else r.abort())
            for i in range(120):
                imported=context.request.post(url+'/api/session/import',data={
                    'title':f'Virtual regression {i:03d}',
                    'messages':[{'role':'user','content':'Review'},{'role':'assistant','content':'Native Core transcript.'}]
                }).json()
                assert imported.get('ok'), imported
            page=context.new_page()
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(url)
            page.wait_for_selector('#msg')
            page.wait_for_timeout(1000)
            page.evaluate("()=>_pickSkin('default')")
            page.locator('#btnHamburger').click()
            page.wait_for_timeout(300)
            page.locator('#sessionList').evaluate('l=>l.scrollTop=l.scrollHeight')
            page.wait_for_timeout(500)
            before=snapshot(page)
            assert before['total']==120 and before['end']==120, before
            page.evaluate("()=>_pickSkin('selene')")
            page.wait_for_timeout(500)
            mounted=snapshot(page)
            assert mounted['height']>0 and mounted['overflow']=='auto',mounted
            assert mounted['visible']>0 and 'sidebar' in mounted['profileParent'].split(),mounted
            # The old theme can leave scrollTop=0 with an end-of-list window.
            # Setting the same scrollTop cannot manufacture the missing event.
            page.locator('#sessionList').evaluate('l=>l.scrollTop=0')
            page.wait_for_timeout(500)
            top=snapshot(page)
            assert top['start']==0 and top['visible']>0,top
            page.locator('#sessionList').evaluate('l=>l.scrollTop=l.scrollHeight')
            page.wait_for_timeout(500)
            bottom=snapshot(page)
            assert bottom['end']==120 and bottom['last']==bottom['expectedLast'],bottom
            page.set_viewport_size({'width':1280,'height':900})
            page.wait_for_timeout(500)
            resized=snapshot(page)
            assert resized['visible']>0 and resized['rendered']<120,resized
            page.evaluate("()=>_pickSkin('default')")
            page.wait_for_timeout(500)
            restored=snapshot(page)
            assert restored['visible']>0,restored
            assert not errors,errors
            result={'before':before,'mounted':mounted,'top':top,'bottom':bottom,
                'resized':resized,'restored':restored,'pageErrors':errors}
            (OUT/'results.json').write_text(json.dumps(result,indent=2))
            print(json.dumps(result,indent=2))
            page.screenshot(path=str(OUT/'restored-default.png'))
            browser.close()
    finally:
        _terminate(proc,log)
