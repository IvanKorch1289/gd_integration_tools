__all__ = ("singleton",)


def singleton(cls):
    """Декоратор для создания Singleton-класса.

    Args:
        cls: Класс, который нужно сделать Singleton.

    Returns:
        Функция, которая возвращает единственный экземпляр класса.
    """
    instances = {}

    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance
