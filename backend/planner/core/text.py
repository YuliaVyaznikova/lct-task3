"""Согласование русских слов с числом."""


def plural(count: int, one: str, few: str, many: str) -> str:
    """Форма слова для числа: 1 заявка, 2 заявки, 5 заявок."""
    if count % 10 == 1 and count % 100 != 11:
        return one
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return few
    return many
