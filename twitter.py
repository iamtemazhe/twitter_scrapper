import re
import typing
from asyncio import (
    sleep as async_sleep,
    TimeoutError as AsyncTimeoutError,
)
from datetime import datetime
from functools import wraps
from hashlib import sha256
from time import time as time_now
from urllib.parse import urlencode, urlunparse

from aiohttp import (
    ClientSession,
    ClientTimeout,
    ClientError,
)
from bs4 import BeautifulSoup

from .exceptions import (
    ApiError,
    NonCriticalError,
    InvalidOwnerId,
    InvalidProfile,
    PrivateProfile,
)
from .loggers import getLogger

logger = getLogger()


def emitter(asyncgen):
    @wraps(asyncgen)
    async def wrapper(*args, **kwargs):
        try:
            async for response in asyncgen(*args, **kwargs):
                yield response

        # ошибка истекло время ожидания ответа от сервера
        except AsyncTimeoutError as err:
            logger.warning(f'TimeoutError exception: {err}.')
            await async_sleep(1)

        # ошибка клиента aiohttp
        except ClientError:
            raise NonCriticalError(f'ClientError exception')

    return wrapper


class TwitterAPI:
    VERSION = 1.0
    # Request timeout
    TIMEOUT = 0
    # Response delay
    RESPONSE_DELAY = 300
    # Определяем заголовки User Agent,
    # чтобы запретить Twitter возвращать карточку профиля
    HEADERS = {
        'user-agent': ('Mozilla/5.0 (X11; Linux x86_64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/46.0.2490.86 Safarii/537.36'),
    }
    # Twitter main URL
    URL = 'https://www.twitter.com'
    MOBILE_URL = 'https://mobile.twitter.com/'
    # Twitter API 1.0 URL without query:
    # Searching
    SEARCH_URL = URL + '/i/search/timeline'
    # Videos
    VIDEOS_URL = URL + '/i/videos/'
    # Default Twitter URL
    TWEET_URL = URL + '/{username}/status/{item_id}'
    PROFILE_URL = URL + '/{username}/with_replies'
    # Query date format
    DATE_FORMAT = '%Y-%m-%d'

    __slots__ = ('_session', '_timeout', 'counter')

    def __init__(self, session: ClientSession = None):
        self._session = session or ClientSession
        self._timeout = ClientTimeout(total=self.TIMEOUT)
        # Счетчик загруженных материалов
        self.counter = 0

    def __repr__(self):
        return f'<class {self.__class__.__name__} version={self.VERSION}>'

    def __str__(self):
        return f'Twitter api v{self.VERSION} requester.'

    async def init_sessions(self):
        """Для Twitter не требуется инициализировать сессии."""
        pass

    async def close_sessions(self):
        """Для Twitter не требуется закрывать сессии."""
        pass

    @staticmethod
    def parse_url(source_url: str) -> str:
        """Пaрсер URL-адресов на вытягивание имени профиля.

        Args:
            source_url (str): Исходный URL.

        Returns:
            str: Имя профиля (alias).

        """
        url = source_url
        # Если URL, парсим
        if url.startswith('http'):
            pattern = re.compile(
                r'https?:\/\/(www\.)?twitter\.com\/[a-zA-Z_0-9]+$',
                re.I
            )

            if not pattern.search(url):
                raise InvalidProfile(url)

            return url.split('/').pop(-1)
        elif re.search(r'^[a-zA-Z_0-9]+$', url):
            return url
        else:
            raise InvalidOwnerId(url)

    @staticmethod
    def to_soup(items_html: str, feature: str = 'html.parser') -> BeautifulSoup:
        """HTML-парсер для построения дерева элементов
        посредством BeautifulSoup.

        Args:
            item_html (str): HTML-блок кода.
            feature (str, optional): Параметры/механизм парсера.

        Returns:
            str: Распаршенное HTML-дерево.

        """
        return BeautifulSoup(items_html, feature)

    @staticmethod
    def construct_query(search_query: str = '', profile: str = '',
                        reply: bool = False, since: str = '',
                        until: str = '', since_id: int = 0) -> str:
        """Конструктор поискового URL по query и/или profile.
        Собирает query для расширенного поиска Twitter
        по конструкции https://twitter.com/search-advanced
        (!search_query не может быть пустым!).

        Args:
            search_query (str, optional): Поисковый текст запроса.
            profile (str, optional): Отображаемое имя пользователя
                [screen name].
            reply (bool, optional): Флаг ответа (default=False).
            since (str, optional): Временная отметка начала поиска.
            until (str, optional): Временная отметка конца поиска.
            since_id (int, optional): Идентификатор сообщения
                начала поиска.

        Returns:
            str: Возвращает query-строку для поискового запроса.

        """
        query = search_query or ''

        if profile:
            query += ' to:' if reply else ' from:'
            query += profile
        if reply:
            query += ' filter:replies'
        if until:
            query += f' until:{until}'
        if since:
            query += f' since:{since}'
        if since_id:
            query += f' since_id:{since_id}'

        if not query:
            raise ApiError('Query is missing.')

        return query.lstrip()

    def construct_video_url(self, video_material_id: int) -> str:
        """Конструктор URL для просмотра video, gif,
        загруженных в Twitter.

        Args:
            video_material_id (int): Идентификатор материала,
                содержащего video, gif.

        Returns:
            str: Возвращает URL.

        """
        return self.VIDEOS_URL + str(video_material_id)

    async def _get_query_response(self, query: str,
                                  max_position: str = '') -> dict:
        """Расширенный поиск в Twitter.

        Args:
            query (str): Поисковый query.
            max_position (str, optional): Величина пагинации для
                получения твитов.

        Returns:
            dict: Ответ.

        """
        # Задаем параметры запроса
        params = {
            # Формат - все твиты (tweets, retweets, replies)
            'f': 'tweets',
            # Поисковый запрос query
            'q': query
        }

        # Если есть пагинация, добавим
        if max_position:
            params['max_position'] = max_position

        # Распаршиваем поисковый URL
        url_tupple = (
            '', '', self.SEARCH_URL, '', urlencode(params), ''
        )
        url = urlunparse(url_tupple)
        async with self._session() as session:
            async with session.get(
                    url, headers=self.HEADERS, timeout=self._timeout,
            ) as response:
                if response.status != 200:
                    # We have 15k requests in 15min:
                    if response.status == 503:
                        logger.warning(
                            f'Have more than 15k downloaded '
                            f'twits by current IP, '
                            f'response_status={response.status}.'
                        )

                        return await self._get_query_response(
                            query,
                            max_position=max_position
                        )

                    # Too Many Requests:
                    if response.status == 429:
                        # Переводим задачу в сон на RESPONSE_DELAY сек
                        # и повторяем запрос
                        logger.warning(
                            f'Task with query="{query}" goes into '
                            f'sleep mode for {self.RESPONSE_DELAY} sec, '
                            f'response_status={response.status}.'
                        )
                        await async_sleep(self.RESPONSE_DELAY)

                        return await self._get_query_response(
                            query,
                            max_position=max_position
                        )

                    # Internal Server Error:
                    if response.status in range(500, 527):
                        logger.warning(
                            f'Internal server error for {url}, '
                            f'response_status={response.status}.'
                        )
                        await async_sleep(self.RESPONSE_DELAY)

                        return await self._get_query_response(
                            query,
                            max_position=max_position
                        )

                    raise ApiError(
                        f'URL="{url}" is not available, '
                        f'response_status={response.status}.'
                    )

                response = await response.json()

        return response

    async def _search(self, query: str, stage: dict,
                      task_id: int = 0) -> typing.AsyncGenerator:
        """Генератор для скраппинга Twitter.

        Args:
            query (str):    Поисковый query.
            stage (dict):   Параметры/стадия выполнения задачи.
            task_id (int):  Номер задачи для логгера.

        Yields:
            dict:   Возвращает словарь, содержащий список материалов.

        """
        # Получаем значение пагинации для последней полученной пачки твитов
        max_position = stage.get('max_position', '')
        # Получаем значение счётчика для последней полученной пачки твитов
        self.counter = stage.get('counter', 0)
        # Получаем время публикации последнего полученного твита в милисекундах
        last_tweet_time = stage.get(
            'last_tweet_pub_time',
            time_now() * 1000,
        )

        # Получаем параметры поисковой страницы
        response = await self._get_query_response(
            query,
            max_position=max_position,
        )

        # Парсим полученный HTML-блок на поиск твитов
        try:
            twits = self.parse_tweets(response['items_html'])
        except (TypeError, KeyError) as err:
            raise ApiError(f'Iternal server response error: {err}.')

        # Если материалов не было обнаружено, заканчиваем
        if not twits:
            return None

        has_no_more_items = not response.get('has_more_items', False)

        # Если сессия была оборвана или она последняя
        if max_position or has_no_more_items:
            # Парсим полученный HTML-массив
            for twit in twits:
                # Если этот твит мы ещё не сохраняли, сохраним
                if last_tweet_time > twit['stage']['last_tweet_pub_time']:
                    self.counter += 1
                    twit['stage']['counter'] = self.counter
                    twit['stage']['max_position'] = max_position
                    yield twit

            logger.debug(
                f'Progress for Task={task_id} -> '
                f'Currently downloaded twits: {self.counter:6}.'
            )

            # Если это последняя страница твитов, дальше не идём
            if has_no_more_items:
                return None

        min_tweet_id = twits[0]['id']
        while twits:
            max_tweet_id = twits[-1]['id']

            # Меняем значение пагинации
            max_position = response.get(
                'min_position',
                f'TWEET-{max_tweet_id}-{min_tweet_id}'
            )

            # Запрашиваем пачку твитов
            response = await self._get_query_response(
                query,
                max_position=max_position,
            )

            # Парсим полученный HTML-блок на поиск твитов
            try:
                twits = self.parse_tweets(response['items_html'])
            except (TypeError, KeyError) as err:
                raise ApiError(f'Iternal response error: {err}.')

            for twit in twits:
                if last_tweet_time > twit['stage']['last_tweet_pub_time']:
                    self.counter += 1
                    twit['stage']['counter'] = self.counter
                    twit['stage']['max_position'] = max_position
                    yield twit

            logger.debug(
                f'Progress for Task={task_id} -> '
                f'Currently downloaded twits: {self.counter:6}.'
            )

    @emitter
    async def search(self, *args, **kwargs) -> typing.AsyncGenerator:
        """Генератор, возвращающий материалы из поиска.

        Args:
            **kwargs: Параметры задания:
                last_execution_time (int): Время последнего выполнения задания.
                id (int): Номер задания (задачи) в Manager.
                extra (dict): Json-поле, содержащее параметры текущего задания:
                    query (str): Поисковый запрос.
                    stage (dict): Стадия выполнения текущего задания.

        Yields:
            dict: Словарь, содержащий список материалов.

        """
        search_until = kwargs.get('last_execution_time', 0)

        if search_until:
            since = datetime.fromtimestamp(search_until)
            since = since.strftime(self.DATE_FORMAT)
        else:
            since = ''

        task_id = kwargs.get('id', 0)
        extra = kwargs.get('extra', {})
        stage = extra.get('stage', {})

        search_query = extra.get('query', '')
        if not search_query:
            raise ApiError('Error: Query is missing!')

        # Собираем поисковый запрос для скрапинга поиска
        query = self.construct_query(search_query=search_query, since=since)

        # Запускаем скраппинг по поиску
        logger.debug(
            f'START Task={task_id}: '
            f'<Download twits from search_query="{search_query}">.'
        )
        async for twit in self._search(query, stage, task_id):

            # Если время публикации меньше времени последнего выполнения
            # задачи, завершаем
            if twit['publication_datetime'] < search_until:
                return None

            yield {
                'twits': [twit, ],
                'stage': twit.pop('stage', {})
            }

        logger.debug(
            f'END Task={task_id}: <Download twits from '
            f'search_query="{search_query}"> succesfully completed.'
        )

    async def check_profile(self, profile: str):
        """Проверка профиля на существование и приватность.

        Args:
            profile (str): Профиль (alias).

        Raises:
            InvalidProfile: Если профиль не существует.
            PrivateProfile: Если профиль приватный.

        """
        url = self.MOBILE_URL + profile
        async with self._session() as session:
            async with session.get(url, timeout=self._timeout) as response:
                if response.status != 200:
                    # We have 15k requests in 15min:
                    if response.status == 503:
                        logger.warning(
                            'Have more than 15k '
                            'downloaded materialsby current IP, '
                            f'response_status={response.status}.'
                        )
                        return await self.check_profile(profile)

                    # Too Many Requests:
                    if response.status == 429:
                        # Переводим задачу в сон на RESPONSE_DELAY сек
                        # и повторяем запрос
                        logger.warning(
                            f'Profile <{profile}> checking goes into '
                            f'sleep mode for {self.RESPONSE_DELAY} sec, '
                            f'response_status={response.status}.'
                        )
                        await async_sleep(self.RESPONSE_DELAY)

                        return await self.check_profile(profile)

                    # Internal Server Error:
                    if response.status in range(500, 527):
                        logger.warning(
                            f'Internal server error for {url}, '
                            f'response_status={response.status}.'
                        )
                        await async_sleep(self.RESPONSE_DELAY)
                        return await self.check_profile(profile)

                    # Not Found:
                    if response.status == 404:
                        raise InvalidProfile(profile)

                    raise ApiError(
                        f'URL="{url}" is not available, '
                        f'response_status={response.status}.'
                    )

                response = await response.text()

        soup = self.to_soup(response)

        # Проверяем профиль на приватность
        private_div = soup.find("div", class_="protected")
        if private_div:
            raise PrivateProfile(profile)

    @emitter
    async def get_owner(self, *args, **kwargs) -> typing.AsyncGenerator:
        """Генератор, возвращающий материалы из профиля.

        Args:
            *args: Аргументы генератора.
            **kwargs: Параметры задания:
                last_execution_time (int): Время последнего
                    выполнения задания.
                id (int): Номер задания (задачи) в Manager.
                extra (dict): Json-поле, содержащее параметры
                        текущего задания:
                    owner_id (str): Профиль (alias).
                    stage (dict): Стадия выполнения текущего задания.

        Yields:
            dict: Словарь, содержащий список материалов.

        """
        search_until = kwargs.get('last_execution_time', 0)

        if search_until:
            since = datetime.fromtimestamp(search_until)
            since = since.strftime(self.DATE_FORMAT)
        else:
            since = ''

        task_id = kwargs.get('id', 0)
        extra = kwargs.get('extra', {})
        stage = extra.get('stage', {})

        profile = extra.get('owner_id', '')
        if not profile:
            raise ApiError('Owner_id (profile) is missing.')

        await self.check_profile(profile)

        logger.debug(
            f'START Task={task_id}: '
            f'<Download twits From:profile="{profile}">.'
        )

        task_stage = stage.get('task_stage', 1)

        # Стадия 1: скраппинг по твитам пользователя
        if task_stage == 1:
            # Собираем поисковый запрос для скрапинга страницы пользователя
            query = self.construct_query(profile=profile, since=since)

            # Запускаем скраппинг по твитам (tweets, retweets, replies)
            # пользователя
            logger.debug(
                f'START STAGE I Task={task_id}: '
                f'<Download tweets From:profile="{profile}">.'
            )
            async for twit in self._search(query, stage, task_id):
                stage = twit.pop('stage', {})
                stage['task_stage'] = task_stage

                # Если время публикации меньше времени последнего выполнения
                # задачи, завершаем
                if twit['publication_datetime'] < search_until:
                    return None

                yield {
                    'twits': [twit, ],
                    'stage': stage
                }

            # Чистим словарь состояний
            stage = {}
            logger.debug(
                f'END STAGE I Task={task_id}: <Download tweets '
                f'From:profile="{profile}"> successfully completed.'
            )

        # Стадия 2: скраппинг по ответам, адресованным пользователю
        task_stage = 2

        # Собираем поисковый запрос для скрапинга страницы пользователя
        query = self.construct_query(profile=profile, reply=True, since=since)

        # Запускаем скраппинг по твитам (replies), адресованным пользователю
        logger.debug(
            f'START STAGE II Task={task_id}: '
            f'<Download replies To:profile="{profile}">.'
        )
        async for twit in self._search(query, stage, task_id):
            stage = twit.pop('stage', {})
            stage['task_stage'] = task_stage

            # Если время публикации меньше времени последнего выполнения
            # задачи, завершаем
            if twit['publication_datetime'] < search_until:
                return None

            yield {
                'twits': [twit, ],
                'stage': stage
            }

        logger.debug(
            f'END STAGE II Task={task_id}: <Download replies '
            f'To:profile="{profile}"> succesfully completed.'
        )
        logger.debug(
            f'END Task={task_id}: <Download twits '
            f'From:profile={profile}> successfully completed.'
        )

    def parse_tweets(self, items_html: str) -> list:
        """Парсер твитов по заданному HTML-коду.

        Args:
            items_html (str): HTML-блок кода с твитами.

        Returns:
            list: Список, содержащий твиты.

        """
        twits = []
        soup: BeautifulSoup = self.to_soup(items_html)
        # Скрапим блок с признаком твита
        for li in soup.find_all("li", class_='js-stream-item'):

            # Если li не содержит tweet-id, значит, это не тело твита
            if 'data-item-id' not in li.attrs:
                continue

            # Твиты в формате для Материалов
            twit = {
                'id': int(li.get('data-item-id')),
                'url': '',
                'detected_at': int(time_now()),
                'text': {
                    'text': '',
                    'attachments': {},
                },
                'is_reply': False,
                'author': '',
                'stage': {
                    'last_tweet_pub_time': 0.0,
                    'max_position': '',
                    'counter': 0
                },
            }

            # Ссылка на вложения
            attachments = twit['text']['attachments']

            # Определяем, является ли твит комментарием (reply)
            tweet_params_div = li.find("div", class_="original-tweet")
            if 'data-is-reply-to' in tweet_params_div.attrs:
                twit['is_reply'] = True

            # Дата публикации твита
            date_span = li.find("span", class_="_timestamp")
            if date_span is not None:
                twit['publication_datetime'] = int(date_span['data-time'])
                twit['stage']['last_tweet_pub_time'] = float(
                    date_span['data-time-ms']
                )
            else:
                twit['publication_datetime'] = time_now()

            # Tweet Content
            text_p = li.find("p", class_="tweet-text")
            if text_p is not None:
                twit['text']['text'] = text_p.get_text()

                # Tweet Attachments: links
                twit['link'] = [
                    a['data-expanded-url'] for a in text_p.find_all(
                        'a', class_='twitter-timeline-link'
                    ) if 'data-expanded-url' in a.attrs
                ]

            # Tweet User ID, User Screen Name (имя профиля), User Name (ФИО)
            user_details_div = li.find("div", class_="tweet")
            if user_details_div is not None:
                url = self.URL + user_details_div['data-permalink-path']
                twit['url'] = url
                twit['hash'] = sha256(url.encode('utf-8')).hexdigest()
                twit['author'] = user_details_div['data-screen-name']

            # В тексте сообщения могут быть:
            # 1.Tweet Attachments: video
            tweet_video_div = li.find("div", class_="PlayableMedia--video")
            tweet_gif_div = li.find("div", class_="PlayableMedia--gif")
            if tweet_video_div is not None:
                video_div = tweet_video_div.find(
                    "div",
                    class_="PlayableMedia-player",
                )
                image = re.search(
                    'https?://(.*)\.(jpe?g|gif|bmp|png)',
                    video_div.get('style'),
                    re.IGNORECASE
                )
                image = image.group(0) if image is not None else ''

                video = {
                    'url': self.construct_video_url(twit['id']),
                    'image': image
                }

                try:
                    twit['video'].append(video)
                except KeyError:
                    twit['video'] = [video, ]

            # 2.Tweet Attachments: gif
            elif tweet_gif_div is not None:
                gif_div = tweet_gif_div.find(
                    "div",
                    class_="PlayableMedia-player",
                )
                image = re.search(
                    'https?://(.*)\.(jpe?g|gif|bmp|png)',
                    gif_div.get('style'),
                    re.IGNORECASE
                )
                image = image.group(0) if image is not None else ''

                video = {
                    'url': self.construct_video_url(twit['id']),
                    'image': image
                }

                try:
                    twit['video'].append(video)
                except KeyError:
                    twit['video'] = [video, ]

            # 3.Tweet Attachments: photos
            else:
                tweet_photo_div = li.find("div", class_="AdaptiveMedia")
                if tweet_photo_div is not None:
                    for photo in tweet_photo_div.find_all('img'):
                        photo_attach = photo.get('alt')

                        if photo_attach:
                            try:
                                attachments['photo'].append(photo_attach)
                            except KeyError:
                                attachments['photo'] = [photo_attach, ]

                        photo = photo.get('src')
                        if photo:
                            photo = {'url': photo}

                            try:
                                twit['photo'].append(photo)
                            except KeyError:
                                twit['photo'] = [photo, ]

            twits.append(twit)

        return twits
