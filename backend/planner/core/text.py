"""Согласование русских слов с числом и запись чисел по-русски."""


def plural(count: int, one: str, few: str, many: str) -> str:
    """Форма слова для числа: 1 заявка, 2 заявки, 5 заявок."""
    if count % 10 == 1 and count % 100 != 11:
        return one
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return few
    return many


def decimal(value: float, digits: int = 1) -> str:
    """Число с десятичной запятой: 3,8."""
    return f"{value:.{digits}f}".replace(".", ",")


def short_number(value: float) -> str:
    """Число без лишних нулей с десятичной запятой: 1,35 и 60."""
    return f"{value:g}".replace(".", ",")
