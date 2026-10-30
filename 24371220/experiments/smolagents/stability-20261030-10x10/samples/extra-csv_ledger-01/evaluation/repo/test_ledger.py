import pytest
from ledger import summarize


def test_aggregate_returns_and_order():
    assert summarize('sku,quantity,unit_price\na,2,0.10\nb,1,3\na,-1,0.10\n') == [
        {'sku': 'a', 'quantity': 1, 'revenue': '0.10'},
        {'sku': 'b', 'quantity': 1, 'revenue': '3.00'}]


def test_round_only_after_sum():
    assert summarize('sku,quantity,unit_price\na,1,0.005\na,1,0.005\n')[0]['revenue'] == '0.01'


@pytest.mark.parametrize('text', ['', 'sku,quantity\na,1\n', 'sku,quantity,unit_price\na,1,NaN\n'])
def test_invalid(text):
    with pytest.raises(ValueError):
        summarize(text)
