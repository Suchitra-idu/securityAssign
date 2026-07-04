class AccountNotFound(Exception):
    pass


class NotAccountOwner(Exception):
    pass


class Forbidden(Exception):
    pass


class InsufficientFunds(Exception):
    pass


class AccountFrozen(Exception):
    pass


class InvalidTransfer(Exception):
    pass


class TamperedRecord(Exception):
    pass
