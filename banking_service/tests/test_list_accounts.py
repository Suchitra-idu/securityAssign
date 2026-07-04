import pytest

from banking_service.application.list_accounts import list_all_accounts
from banking_service.application.open_account import open_account
from banking_service.domain.errors import Forbidden


def test_admin_lists_all_accounts(bag, alice, bob, admin):
    a = open_account(caller=alice, deps=bag.deps)
    b = open_account(caller=bob, deps=bag.deps)
    got = list_all_accounts(caller=admin, deps=bag.deps)
    assert {x.id for x in got} == {a.id, b.id}


def test_customer_cannot_list_all_accounts(bag, alice):
    open_account(caller=alice, deps=bag.deps)
    with pytest.raises(Forbidden):
        list_all_accounts(caller=alice, deps=bag.deps)
