"""Browser-to-ledger fixture exercise. No social provider or real data."""
from pathlib import Path

import pytest
pytest.importorskip("playwright.sync_api", reason="playwright không cài trong CI; chạy trên máy dev")
from playwright.sync_api import sync_playwright

from scripts.social.fixture_ledger import FixtureLedger
from scripts.social.fixture_ui import FixturePreviewCoordinator


@pytest.mark.parametrize('wrong_video', [False, True])
def test_group_video_fixture_distinguishes_two_video_ids(wrong_video):
    ledger = FixtureLedger()
    identity = dict(station='fixture-station', brand='fixture-brand', campaign='fixture-campaign',
                    content='fixture-content', post='fixture-post', platform='facebook',
                    account='fixture-account', destination='fixture-target', occurrence='fixture-slot')
    snapshot = dict(action='group_video', text='Video gia', media_kind='video', media_id='fixture-video',
                    destination_type='group', source=None, reuse_permission=False)
    item = ledger.prepare(identity, snapshot)
    ledger.approve_batch([(item, ledger.get(item)['version'])])
    coordinator = FixturePreviewCoordinator(ledger)

    def bridge(_source, request):
        if request['operation'] == 'preview':
            preview_id = coordinator.preview(item, snapshot, request['view'], revision=request['revision'])
            return {'preview_id': preview_id}
        if request['operation'] == 'confirm':
            attempt = coordinator.confirm(request['preview_id'], request['view'])
            coordinator.finish(request['preview_id'], 'awaiting_moderation',
                               receipt={'attempt': attempt, 'destination': 'fixture-target', 'remote_id': 'fixture-group-post'})
            return {'status': coordinator.status(request['preview_id'])}
        raise ValueError('unexpected fixture operation')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.expose_binding('fixtureBridge', bridge)
        page = context.new_page()
        page.goto((Path(__file__).parent / 'fixtures' / 'social_ui_simulator.html').resolve().as_uri())
        page.locator('#scenario').select_option('group_video')
        page.locator('#content').fill('Video gia')
        page.locator('#media').select_option('video-other' if wrong_video else 'video')
        page.locator('#preview').click()
        if wrong_video:
            page.get_by_text('Không thể xem trước fixture.', exact=False).wait_for()
            assert ledger.get(item)['state'] == 'prepared'
            assert page.locator('#confirm').is_disabled()
        else:
            page.locator('#confirm').click()
            page.get_by_text('awaiting_moderation', exact=False).wait_for()
            assert ledger.get(item)['state'] == 'awaiting_moderation'
        browser.close()


def test_group_preview_stops_if_fixture_confirm_control_is_missing():
    ledger = FixtureLedger()
    identity = dict(station='fixture-station', brand='fixture-brand', campaign='fixture-campaign',
                    content='fixture-content', post='fixture-post', platform='facebook',
                    account='fixture-account', destination='fixture-target', occurrence='fixture-slot')
    snapshot = dict(action='group_video', text='Video gia', media_kind='video', media_id='fixture-video',
                    destination_type='group', source=None, reuse_permission=False)
    item = ledger.prepare(identity, snapshot)
    ledger.approve_batch([(item, ledger.get(item)['version'])])
    coordinator = FixturePreviewCoordinator(ledger)

    def bridge(_source, request):
        assert request['operation'] == 'preview'
        return {'preview_id': coordinator.preview(item, snapshot, request['view'], revision=request['revision'])}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.expose_binding('fixtureBridge', bridge)
        page = context.new_page()
        page.goto((Path(__file__).parent / 'fixtures' / 'social_ui_simulator.html').resolve().as_uri())
        page.locator('#scenario').select_option('group_video')
        page.locator('#content').fill('Video gia')
        page.locator('#media').select_option('video')
        page.locator('#confirm').evaluate('(element) => element.remove()')
        page.locator('#preview').click()
        page.get_by_text('Không thể xem trước fixture.', exact=False).wait_for(timeout=5000)
        assert ledger.get(item)['state'] == 'prepared'
        browser.close()


@pytest.mark.parametrize(('lost_response', 'lost_session'), [(False, False), (True, False), (True, True)])
def test_browser_reload_reads_unknown_from_ledger(lost_response, lost_session):
    ledger = FixtureLedger()
    identity = dict(station='fixture-station', brand='fixture-brand', campaign='fixture-campaign',
                    content='fixture-content', post='fixture-post', platform='facebook',
                    account='fixture-account', destination='fixture-target', occurrence='fixture-slot')
    snapshot = dict(action='group_video', text='Video gia', media_kind='video', media_id='fixture-video',
                    destination_type='group', source=None, reuse_permission=False)
    item = ledger.prepare(identity, snapshot)
    ledger.approve_batch([(item, ledger.get(item)['version'])])
    coordinator = FixturePreviewCoordinator(ledger)

    def bridge(_source, request):
        operation = request['operation']
        if operation == 'preview':
            data = request['view']
            preview_id = coordinator.preview(item, snapshot, data, revision=request['revision'])
            return {'preview_id': preview_id, 'status': coordinator.status(preview_id)}
        if operation == 'invalidate':
            coordinator.invalidate(request['preview_id'])
            return {}
        if operation == 'confirm':
            coordinator.confirm(request['preview_id'], request['view'])
            coordinator.finish(request['preview_id'], 'unknown')
            if lost_response:
                raise ValueError('synthetic lost response')
            return {'status': coordinator.status(request['preview_id'])}
        if operation == 'state':
            if lost_session:
                raise ValueError('synthetic missing session')
            return {'status': coordinator.status(request['preview_id'])}
        raise ValueError('unsupported fixture operation')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.expose_binding('fixtureBridge', bridge)
        page = context.new_page()
        page.goto((Path(__file__).parent / 'fixtures' / 'social_ui_simulator.html').resolve().as_uri())
        page.locator('#scenario').select_option('group_video')
        page.locator('#content').fill('Video gia')
        page.locator('#media').select_option('video')
        page.locator('#preview').click()
        page.locator('#confirm').wait_for(state='visible')
        assert page.locator('#preview').is_disabled()
        page.locator('#confirm').click()
        if lost_response:
            page.get_by_text('Chưa rõ kết quả fixture.', exact=False).wait_for()
        else:
            page.get_by_text('unknown', exact=False).wait_for()
        assert ledger.get(item)['state'] == 'unknown'
        page.locator('#content').fill('thay doi sau xac nhan')
        page.reload()
        if lost_session:
            page.get_by_text('Phiên fixture không khả dụng', exact=False).wait_for()
        else:
            page.get_by_text('unknown', exact=False).wait_for()
        assert page.locator('#confirm').is_disabled()
        assert page.locator('#preview').is_disabled()
        assert ledger.get(item)['state'] == 'unknown'
        browser.close()


@pytest.mark.parametrize('old_fails', [False, True])
def test_late_old_preview_does_not_change_new_preview(old_fails):
    import asyncio
    from playwright.async_api import async_playwright

    async def exercise():
        entered = asyncio.Event()
        release = asyncio.Event()
        confirmed = []

        async def bridge(_source, request):
            if request['operation'] == 'preview':
                text = request['view']['snapshot']['text']
                if text == 'A':
                    entered.set()
                    await release.wait()
                    if old_fails:
                        raise ValueError('synthetic delayed failure')
                return {'preview_id': 'fixture-' + text}
            if request['operation'] == 'invalidate':
                return {}
            if request['operation'] == 'confirm':
                confirmed.append(request['preview_id'])
                return {'status': {'intent': 'unknown'}}
            raise ValueError('unsupported fixture operation')

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context()
            await context.expose_binding('fixtureBridge', bridge)
            page = await context.new_page()
            await page.goto((Path(__file__).parent / 'fixtures' / 'social_ui_simulator.html').resolve().as_uri())
            await page.locator('#content').fill('A')
            await page.locator('#preview').click()
            await asyncio.wait_for(entered.wait(), 5)
            await page.locator('#content').fill('B')
            await page.locator('#preview').click()
            await page.get_by_text('Xem trước giả:', exact=False).wait_for()
            release.set()
            await page.get_by_text('B', exact=False).first.wait_for()
            await asyncio.sleep(0.2)
            assert await page.locator('#preview').is_disabled()
            await page.locator('#confirm').click()
            await page.get_by_text('unknown', exact=False).wait_for()
            assert confirmed == ['fixture-B']
            await browser.close()

    asyncio.run(exercise())


def test_reload_while_preview_response_is_pending_stops_safely():
    import asyncio
    from playwright.async_api import async_playwright

    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def bridge(_source, request):
            calls.append(request['operation'])
            if request['operation'] == 'preview':
                entered.set()
                await release.wait()
                return {'preview_id': 'fixture-delayed'}
            raise ValueError('unexpected operation')

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context()
            await context.expose_binding('fixtureBridge', bridge)
            page = await context.new_page()
            await page.goto((Path(__file__).parent / 'fixtures' / 'social_ui_simulator.html').resolve().as_uri())
            await page.locator('#content').fill('Noi dung gia')
            await page.locator('#preview').click()
            await asyncio.wait_for(entered.wait(), 5)
            await page.reload()
            await page.get_by_text('Phiên fixture chưa rõ', exact=False).wait_for(timeout=3000)
            assert await page.locator('#preview').is_disabled()
            assert await page.locator('#confirm').is_disabled()
            assert calls == ['preview']
            release.set()
            await browser.close()

    asyncio.run(exercise())


def test_reload_while_invalidation_is_pending_stops_safely():
    import asyncio
    from playwright.async_api import async_playwright

    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()

        async def bridge(_source, request):
            if request['operation'] == 'preview':
                return {'preview_id': 'fixture-A'}
            if request['operation'] == 'invalidate':
                entered.set()
                await release.wait()
                return {}
            raise ValueError('unexpected operation')

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context()
            await context.expose_binding('fixtureBridge', bridge)
            page = await context.new_page()
            await page.goto((Path(__file__).parent / 'fixtures' / 'social_ui_simulator.html').resolve().as_uri())
            await page.locator('#content').fill('A')
            await page.locator('#preview').click()
            await page.locator('#confirm').wait_for(state='visible')
            await page.locator('#content').fill('B')
            await asyncio.wait_for(entered.wait(), 5)
            await page.reload()
            await page.get_by_text('Phiên fixture chưa rõ', exact=False).wait_for(timeout=3000)
            assert await page.locator('#preview').is_disabled()
            assert await page.locator('#confirm').is_disabled()
            release.set()
            await browser.close()

    asyncio.run(exercise())


def test_late_preview_cancellation_clears_its_own_pending_marker():
    import asyncio
    from playwright.async_api import async_playwright

    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()

        async def bridge(_source, request):
            if request['operation'] == 'preview':
                entered.set()
                await release.wait()
                return {'preview_id': 'fixture-A'}
            if request['operation'] == 'invalidate':
                return {}
            raise ValueError('unexpected operation')

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context()
            await context.expose_binding('fixtureBridge', bridge)
            page = await context.new_page()
            await page.goto((Path(__file__).parent / 'fixtures' / 'social_ui_simulator.html').resolve().as_uri())
            await page.locator('#content').fill('A')
            await page.locator('#preview').click()
            await asyncio.wait_for(entered.wait(), 5)
            await page.locator('#content').fill('B')
            release.set()
            await page.wait_for_function("sessionStorage.getItem('social-ui-bridge-pending') === null", timeout=3000)
            await page.reload()
            assert await page.locator('#preview').is_enabled()
            await browser.close()

    asyncio.run(exercise())
