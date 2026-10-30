import pytest
from ledger import summarize


def test_header_order_quotes_and_scientific_price():
    assert summarize(' unit_price ,sku, quantity ,extra\n1e-2,"x,y",+3,z\n') == [
        {'sku': 'x,y', 'quantity': 3, 'revenue': '0.03'}]
    assert summarize('sku,quantity,unit_price\n"two\nlines",0,9\n')[0]['sku'] == 'two\nlines'


def test_empty_and_half_even_and_signed_zero():
    assert summarize('sku,quantity,unit_price\n\n') == []
    assert summarize('sku,quantity,unit_price\na,1,1.225\nb,1,1.235\nc,-1,0.001\n') == [
        {'sku': 'a', 'quantity': 1, 'revenue': '1.22'},
        {'sku': 'b', 'quantity': 1, 'revenue': '1.24'},
        {'sku': 'c', 'quantity': -1, 'revenue': '0.00'}]


@pytest.mark.parametrize('row', ['a,1,-1', 'a,1,Infinity', 'a,١,2', 'a,1.0,2',
                               'a,,2', ',1,2', 'a,1', 'a,1,2,extra'])
def test_bad_records(row):
    with pytest.raises(ValueError):
        summarize('sku,quantity,unit_price\n' + row + '\n')


def test_duplicate_stripped_header():
    with pytest.raises(ValueError):
        summarize('sku, quantity ,quantity,unit_price\na,1,1,2\n')
