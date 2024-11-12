import enum


__all__ = ('ResponseTypeChoices', )


class ResponseTypeChoices(enum.Enum):
    json = 'JSON'
    pdf = 'PDF'
