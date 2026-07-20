from banking_service.application.open_account import NEW_ACCOUNT_STARTING_BALANCE_MINOR, open_account


def test_open_account_assigns_owner_and_starting_balance(bag, alice):
    account = open_account(caller=alice, deps=bag.deps)
    assert account.owner_id == alice.user_id
    assert account.balance_minor == NEW_ACCOUNT_STARTING_BALANCE_MINOR
    assert account.status == "active"
    assert len(account.account_number) == 12
    assert len(account.card_number) == 16
    assert bag.accounts.get(account.id) is account


def test_open_account_audited(bag, alice):
    account = open_account(caller=alice, deps=bag.deps)
    events = [e for e in bag.audit.events if e["event"] == "account_opened"]
    assert len(events) == 1
    assert events[0]["account_id"] == account.id
    assert events[0]["owner_id"] == alice.user_id


def test_two_customers_get_distinct_account_numbers(bag, alice, bob):
    a = open_account(caller=alice, deps=bag.deps)
    b = open_account(caller=bob, deps=bag.deps)
    assert a.account_number != b.account_number
    assert a.card_number != b.card_number
