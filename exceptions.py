class BaseApiException(Exception):
    """Базовый класс ислкючений."""
    pass


class CriticalError(BaseApiException):
    """Критическая ошибка при загрузке по заданию.
    """
    pass


class NonCriticalError(BaseApiException):
    """Некритическая ошибка при загрузке по заданию.
    """
    pass


class InvalidOwnerId(BaseApiException):
    """Некорректный идентификатор цели загрузки.
    """
    pass


class InvalidProfile(InvalidOwnerId):
    """Некорректный профайл цели загрузки.
    """
    pass


class PrivateProfile(InvalidOwnerId):
    """Профиль пользователя приватный.
    """
    pass


class InvalidGroup(InvalidOwnerId):
    """Некорректный идентификатор группы цели загрузки.
    """
    pass


class PrivateGroup(InvalidOwnerId):
    """Группа закрытая.
    """
    pass


class InvalidTaskParams(BaseApiException):
    """Некорректный параметр задания."""
    pass


class ApiError(BaseApiException):
    """Все остальные ошибки.
    """
    pass


class PermissionDenied(BaseApiException):
    """Ошибка доступа к запросу.
    """
    pass
