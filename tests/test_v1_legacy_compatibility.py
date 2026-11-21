"""Preserve the established V1 split contract on synthetic content."""
import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[1] / 'scripts/pipeline/gen_article.py'
    spec = importlib.util.spec_from_file_location('gen_article_legacy_compat', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_duplicate_legacy_sections_keep_longest():
    source = '## post:facebook_post\nBai 1\n## post:facebook_post\nBai 2 dai hon\n'
    assert _module().split_content(source) == {'fb_post': 'Bai 2 dai hon'}


def test_legacy_fenced_heading_matches_original_outputs():
    source = '## post:blog_article\n```\n## post:facebook_post\n```\n'
    assert _module().split_content(source) == {'blog': '```', 'fb_post': '```'}
