"""V1 Facebook media to X preview is synthetic and preserves asset identity."""
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


def sample(kind='image'):
    data = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_facebook_to_x_simulation.json').read_text(encoding='utf-8'))
    publication = data['publication']
    post = next(row for row in publication['posts'] if row['post_id'] == 'fixture-fb-post')
    filename = 'graphic.png' if kind == 'image' else 'clip.mp4'
    post['asset_ref'] = filename
    return {'source': data['source'], 'publication': publication, 'post_id': post['post_id'],
            'media_kind': kind, 'manifest': [{'content_id': 'fixture-content', 'post_id': post['post_id'],
                'relative_path': filename, 'kind': kind, 'id': 'fixture-source-asset', 'path': '/fixture/' + filename}],
            'user_id': '123', 'media_id': 'fixture-x-media-456', 'adapted_text': 'Bài X đã biên tập'}


def test_x_v1_image_preview_keeps_source_and_media_separate():
    try:
        module = importlib.import_module('scripts.social.x_v1_media_preview')
    except ModuleNotFoundError:
        pytest.fail('X V1 media preview missing')
    result = module.preview_v1_media(**sample())
    assert result['source_binding']['anchor'] == 'post:facebook_post'
    assert result['asset']['id'] == 'fixture-source-asset'
    assert result['candidate']['request']['body']['media']['media_ids'] == ['fixture-x-media-456']
    assert 'media_processing_and_ownership_unverified' in result['warnings']


def test_x_v1_video_preview_keeps_video_kind():
    module = importlib.import_module('scripts.social.x_v1_media_preview')
    result = module.preview_v1_media(**sample('video'))
    assert result['asset']['kind'] == 'video'
    assert result['candidate']['request']['body']['media']['media_ids'] == ['fixture-x-media-456']


def test_x_v1_media_result_identifies_campaign_and_content():
    module = importlib.import_module('scripts.social.x_v1_media_preview')
    result = module.preview_v1_media(**sample())
    assert result['source_binding']['content_id'] == 'fixture-content'
    assert result['source_binding']['campaign_id'] == 'fixture-campaign'


@pytest.mark.parametrize('mutation', ['missing_ref', 'wrong_post', 'wrong_kind', 'real_media_id'])
def test_x_v1_media_rejects_ambiguous_or_nonfixture_assets(mutation):
    module = importlib.import_module('scripts.social.x_v1_media_preview')
    data = sample()
    if mutation == 'missing_ref':
        data['publication']['posts'][-1]['asset_ref'] = ''
    elif mutation == 'wrong_post':
        data['manifest'][0]['post_id'] = 'fixture-other'
    elif mutation == 'wrong_kind':
        data['manifest'][0]['kind'] = 'video'
    else:
        data['media_id'] = '1234567890'
    with pytest.raises(ValueError):
        module.preview_v1_media(**data)


def test_x_v1_media_cli_previews_without_scheduling():
    result = subprocess.run([sys.executable, '-m', 'scripts.social.cli', 'prepare-x-v1-media'],
                            input=json.dumps(sample('video'), ensure_ascii=False), text=True, encoding='utf-8',
                            capture_output=True, check=False)
    assert result.returncode == 0
    preview = json.loads(result.stdout)
    assert preview['asset']['kind'] == 'video'
    assert 'not_persisted_or_scheduled' in preview['warnings']


def test_x_v1_media_cli_rejects_fake_schedule_and_reply():
    data = sample()
    data['scheduled_at'] = '2026-11-20T03:00:00Z'
    result = subprocess.run([sys.executable, '-m', 'scripts.social.cli', 'prepare-x-v1-media'],
                            input=json.dumps(data), text=True, encoding='utf-8', capture_output=True, check=False)
    assert result.returncode == 2
    assert result.stdout == ''
