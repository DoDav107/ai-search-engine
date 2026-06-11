"""Placeholder tests for extractor functions."""

from src.engine import extractors


def test_extractors_exist() -> None:
    assert hasattr(extractors, "title")
    assert hasattr(extractors, "meta_description")
    assert hasattr(extractors, "h1")
    assert hasattr(extractors, "canonical")
    assert hasattr(extractors, "image_alt")
    assert hasattr(extractors, "word_count")
    assert hasattr(extractors, "structured_data")
