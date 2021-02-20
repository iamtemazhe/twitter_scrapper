"""Logging style utils."""
import logging

from .settings import get_config

class Msg:
    """Добавляет header prefix и footer postfix к каждому сообщению.

    Args:
        prefix (any, optional): Префикс сообщения, устанавливаемый в '[prefix] '
            (по умолчанию - '').
        postfix (any, optional): Постфикс сообщения
            (по умолчанию - '').

    """
    def __init__(
        self,
        prefix = None,
        postfix = None,
    ):
        self.prefix = self.get_prefix(prefix)
        self.postfix = self.get_postfix(postfix)

    @classmethod
    def get_prefix(cls, prefix=None) -> str:
        return '' if prefix is None else f'[{str(prefix).title()}] '

    @classmethod
    def get_postfix(cls, postfix=None) -> str:
        return '' if postfix is None else f' {postfix}'

    def set(self, msg: str, prefix=None, postfix=None) -> str:
        """Вовзращает результирующее сообщение.

        Args:
            msg (str): Логируемое сообщение.

        Returns:
            str: Строка в формате:
                '[{msg_prefix}] {msg} {msg_postfix}'

        """
        return f'{self.prefix}{msg}{self.postfix}'

    @classmethod
    def set_msg(self, msg: str, prefix=None, postfix=None) -> str:
        """Вовзращает результирующее сообщение.

        Args:
            msg (str): Логируемое сообщение.

        Returns:
            str: Строка в формате:
                '[{msg_prefix}] {msg} {msg_postfix}'

        """
        return f'{self.get_prefix(prefix)}{msg}{self.get_postfix(postfix)}'


class LogMsg(Msg, logging.Logger):
    """Добавляет header prefix и footer postfix к каждому сообщению.

    Args:
        name (any, optional): Имя логера
            (по умолчанию - DEFAULT_LOGGER='masm').
        level (int, optional): Уровень логируемых сообщений
            (по умолчанию - NOTSET).
        prefix (any, optional): Префикс сообщения, устанавливаемый в '[prefix] '
            (по умолчанию - '[name] ').
        postfix (any, optional): Постфикс сообщения
            (по умолчанию - '').

    """
    NOTSET = 0
    DEBUG = 10
    INFO = 20
    WARNING = 30
    WARN = WARNING
    ERROR = 40
    CRITICAL = 50
    FATAL = CRITICAL
    CONFIG = get_config()['logging']
    DEFAULT_LOGGER = CONFIG['formatters']['logstash']['extra']['application']

    def __init__(
        self,
        name = DEFAULT_LOGGER,
        level: int = NOTSET,
        prefix = None,
        postfix = None,
    ):
        name = name or self.DEFAULT_LOGGER
        prefix = prefix or name
        Msg.__init__(self, prefix, postfix)
        logging.Logger.__init__(self, name, level)

    def _log(self, level, msg, *args, **kwargs):
        super(LogMsg, self)._log(level, self.set(msg), *args, **kwargs)


def getLogger(name: str=None, prefix=None, postfix=None):
    default_logger = logging.getLogger(LogMsg.DEFAULT_LOGGER)

    logger = LogMsg(name, prefix=prefix, postfix=postfix)
    logger.handlers = default_logger.handlers
    logger.level = default_logger.level
    return logger
