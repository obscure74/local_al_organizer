"""Тесты нормализации названий (чтобы одна компания = одна папка)."""
import pytest

from app.core.classifier import _normalize_doc_type, normalize_company


@pytest.mark.parametrize("raw,expected", [
    ("ООО «ПромЭкоСистемы»", "ПромЭкоСистемы"),
    ("ООО ПромЭкоСистемы", "ПромЭкоСистемы"),
    ('ООО "ПромЭкоСистемы"', "ПромЭкоСистемы"),
    ("ООО «НПП «Полихим»", "Полихим"),
    ("ИП Иванов", "Иванов"),
    ("Ромашка", "Ромашка"),
    ("", ""),
])
def test_normalize_company(raw, expected):
    assert normalize_company(raw) == expected


def test_company_variants_collapse_to_one():
    """Разные написания одной компании дают одинаковый результат."""
    variants = ["ООО «ПромЭкоСистемы»", "ООО ПромЭкоСистемы", 'ООО "ПромЭкоСистемы"']
    normalized = {normalize_company(v) for v in variants}
    assert len(normalized) == 1


@pytest.mark.parametrize("raw,expected", [
    ("Проектная", "Проектная документация"),
    ("проектная документация", "Проектная документация"),
    ("СЧЁТ", "Счёт"),
    ("счет", "Счёт"),
    ("Акт", "Акт"),
    ("", "Прочее"),
])
def test_normalize_doc_type(raw, expected):
    assert _normalize_doc_type(raw) == expected
