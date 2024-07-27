# Gateway proxy server.
# Author: Denis n0a Simonov, 2024
# https://n0a.pw

import ipaddress
from pprint import pprint
import os
from flask import Flask, request, jsonify
from flask_httpauth import HTTPBasicAuth
from threading import Thread
import random
import time
import logging
from proxy import Proxy
from proxy.plugin import ProxyPoolPlugin
from proxy.http.parser import HttpParser
from proxy.http.url import Url
from typing import Optional
import requests
import redis
import json
from urllib.parse import urlparse, urlunparse

# Пример использования переменных окружения
FLASK_PORT = os.getenv('FLASK_PORT', 5550)
FLASK_USER = os.getenv('FLASK_USER')
FLASK_PASS = os.getenv('FLASK_PASS')
PROXY_PORT = os.getenv('PROXY_PORT', 8181)
HOSTNAME = os.getenv('HOSTNAME', '0.0.0.0')
BASIC_AUTH = os.getenv('BASIC_AUTH', 'gateway:P@ssw0rd!***')
NUM_WORKERS = os.getenv('NUM_WORKERS', 5)

# Настройка логирования
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

# Для теста прокси
test_urls = ['https://ifconfig.me/ip', 'https://www.google.com', 'https://ya.ru']

# Инициализация Flask приложения
app = Flask(__name__)
auth = HTTPBasicAuth()


def get_redis_client():
    while True:
        try:
            # Попытка подключения к Redis
            redis_client = redis.StrictRedis(host=os.getenv('REDIS_HOST', 'localhost'),
                                             port=os.getenv('REDIS_PORT', 6379), db=0, decode_responses=True)
            # Проверка соединения
            redis_client.ping()
            logger.info("Connected to Redis")
            return redis_client
        except redis.ConnectionError as e:
            logger.error(f"Redis connection failed: {e}")
            logger.info("Retrying connection to Redis in 5 seconds...")
            time.sleep(5)


# Получение клиента Redis с проверкой доступности
redis_client = get_redis_client()


# Класс для работы с прокси через Redis
class ProxyStorage:
    @staticmethod
    def initialize_proxies():
        logger.info("Initializing ProxyStorage with initial proxies")
        # Initial startup proxy list
        proxy_env = os.getenv('INITIAL_PROXIES', '')
        if proxy_env:
            proxies = []
            proxy_strings = proxy_env.split(',')
            for i, proxy_str in enumerate(proxy_strings):
                proxies.append({
                    "id": i,
                    "proxy": proxy_str.strip(),
                    "alive": False,
                    "last_timeout": None,
                    "hosts": []
                })

            # Сохраняем прокси в Redis
            for proxy in proxies:
                redis_client.hset('proxies', proxy['proxy'], json.dumps(proxy))
                logger.info(f"Added initial proxy: {proxy['proxy']}")
        else:
            logger.info("No initial proxies found in environment.")

    @staticmethod
    def update_proxies(proxies_list):
        logger.info("Updating proxies in Redis")
        for proxy_url in proxies_list:
            if not redis_client.hexists('proxies', proxy_url):
                proxy = {
                    "id": len(redis_client.hkeys('proxies')),
                    "proxy": proxy_url,
                    "alive": False,
                    "last_timeout": None,
                    "hosts": []
                }
                redis_client.hset('proxies', proxy_url, json.dumps(proxy))
        logging.info("Proxies updated.")

    @staticmethod
    def get_proxies():
        proxies = [json.loads(v) for v in redis_client.hvals('proxies')]
        return proxies

    @staticmethod
    def set_proxy_alive(proxy_url, alive, timeout=None):
        proxy_data = redis_client.hget('proxies', proxy_url)
        if proxy_data:
            proxy = json.loads(proxy_data)
            proxy['alive'] = alive
            proxy['last_timeout'] = timeout if alive else None
            redis_client.hset('proxies', proxy_url, json.dumps(proxy))
            logger.info(f"Set proxy {proxy_url} alive={alive} with timeout={timeout}")

    @staticmethod
    def get_next_proxy_id():
        # Получение всех прокси из Redis
        all_proxies = redis_client.hvals('proxies')
        if not all_proxies:
            return 0  # Если прокси нет, возвращаем ID 0
        max_id = max(json.loads(proxy).get('id', -1) for proxy in all_proxies)
        return max_id + 1

    @staticmethod
    def update_host_info(proxy_url, host, alive=True):
        proxy_data = redis_client.hget('proxies', proxy_url)
        if proxy_data:
            proxy = json.loads(proxy_data)
            logger.info(f"Current proxy data: {proxy}")
            host_info = next((h for h in proxy['hosts'] if h['host'] == host), None)
            if host_info:
                host_info["last_usage"] = time.time()
                host_info["usage_count"] = host_info.get("usage_count", 0) + 1
                host_info["alive"] = alive
            else:
                proxy['hosts'].append({
                    "host": host,
                    "last_usage": time.time(),
                    "usage_count": 1,
                    "alive": alive
                })
            redis_client.hset('proxies', proxy_url, json.dumps(proxy))
            logger.info(f"Updated proxy data: {proxy}")
        else:
            logger.info(f"No data found for proxy {proxy_url}")

    @staticmethod
    def mark_proxy_dead(proxy_url: str, host: str):
        # Получаем данные о прокси из Redis
        proxy_data = redis_client.hget('proxies', proxy_url)
        pprint(proxy_data)
        print(proxy_url, host)
        if proxy_data:
            proxy = json.loads(proxy_data)
            logger.info(f"Current proxy data before update: {proxy}")

            # Находим запись о конкретном хосте и обновляем alive
            for host_info in proxy.get('hosts', []):
                print(host_info['host'])
                if host_info['host'] == host:
                    host_info["alive"] = False
                    logger.info(f"Updated alive status to False for host: {host} on proxy: {proxy_url}")
                    break
            else:
                # Если хост не найден, добавляем новую запись
                proxy['hosts'].append({
                    "host": host,
                    "alive": False
                })
                logger.info(f"Added new host entry with alive=False for host: {host} on proxy: {proxy_url}")

            # Сохраняем обновленные данные обратно в Redis
            updated_data = json.dumps(proxy)
            redis_client.hset('proxies', proxy_url, updated_data)
            logger.info(f"Updated proxy data after setting alive=False: {proxy}")
        else:
            logger.warning(f"Proxy {proxy_url} not found in storage.")

    @staticmethod
    def get_best_proxy(host: Optional[str]):
        proxies = ProxyStorage.get_proxies()
        if not proxies:
            logger.info('No proxies available')
            return None

        # Фильтрация прокси, которые активны для данного хоста
        alive_proxies = []
        for proxy in proxies:
            is_alive_for_host = False
            for host_info in proxy.get('hosts', []):
                if host_info['host'] == host:
                    if host_info.get('alive', True):
                        is_alive_for_host = True
                    break
            if is_alive_for_host:
                alive_proxies.append(proxy)
            elif not any(h['host'] == host for h in proxy.get('hosts', [])):
                # Если прокси не использовалась для этого хоста, она считается активной
                alive_proxies.append(proxy)

        if not alive_proxies:
            logger.info(f'No live proxies available for host: {host}')
            return None

        # Сначала ищем прокси, которые не использовались с данным хостом
        unused_proxies = [p for p in alive_proxies if not any(h['host'] == host for h in p['hosts'])]

        if unused_proxies:
            selected_proxy = random.choice(unused_proxies)
            logger.debug(f"Selected unused proxy: {selected_proxy['proxy']} for host {host}")
        else:
            # Если все прокси уже использовались, выбираем ту, которая дольше всего не использовалась
            def last_usage_time(proxy):
                for h in proxy['hosts']:
                    if h['host'] == host:
                        return h.get('last_usage', float('inf'))
                return float('inf')

            selected_proxy = min(alive_proxies, key=last_usage_time)
            logger.debug(
                f"Selected used proxy: {selected_proxy['proxy']} with last usage time: {last_usage_time(selected_proxy)} for host {host}")

        return selected_proxy["proxy"]


# Проверка доступности прокси
def check_proxy_availability(proxy_url):
    for test_url in test_urls:
        try:
            start_time = time.time()
            response = requests.get(test_url, proxies={"http": proxy_url, "https": proxy_url},
                                    timeout=2)  # Таймаут 2 секунды
            elapsed_time = time.time() - start_time
            logger.info(f"Proxy {proxy_url} is alive. Response time for {test_url}: {elapsed_time:.2f}s")
            return True, elapsed_time
        except requests.RequestException as e:
            logger.warning(f'Proxy {proxy_url} failed to reach {test_url}: {e}')
    return False, None


# API эндпоинты
@auth.verify_password
def verify_password(username, password):
    if username == FLASK_USER and password == FLASK_PASS:
        return username
    return None


@app.route('/add_proxy', methods=['POST'])
@auth.login_required
def add_proxy():
    data = request.json
    proxy_url = data.get('proxy')
    if not proxy_url:
        return jsonify({"error": "Proxy URL is required"}), 400

    if redis_client.hexists('proxies', proxy_url):
        return jsonify({"error": "Proxy already exists"}), 400

    # Проверка доступности нового прокси
    is_alive, elapsed_time = check_proxy_availability(proxy_url)

    if not is_alive:
        return jsonify({"error": "Proxy is not reachable"}), 400

    # Генерация нового ID для прокси
    new_id = ProxyStorage.get_next_proxy_id()

    # Обновление статуса прокси перед добавлением
    proxy_data = {
        "id": new_id,
        "proxy": proxy_url,
        "alive": is_alive,
        "last_timeout": elapsed_time,
        "hosts": []
    }
    redis_client.hset('proxies', proxy_url, json.dumps(proxy_data))

    return jsonify({"message": "Proxy added successfully", "id": new_id, "alive": is_alive}), 201


@app.route('/remove_proxy', methods=['DELETE'])
@auth.login_required
def remove_proxy():
    data = request.json
    proxy_url = data.get('proxy')
    if not proxy_url:
        return jsonify({"error": "Proxy URL is required"}), 400

    if not redis_client.hexists('proxies', proxy_url):
        return jsonify({"error": "Proxy not found"}), 404

    redis_client.hdel('proxies', proxy_url)
    return jsonify({"message": "Proxy removed successfully"}), 200


@app.route('/proxy_info', methods=['GET'])
@auth.login_required
def get_proxy_info():
    proxies = ProxyStorage.get_proxies()
    return jsonify(proxies), 200


# Проверка прокси
def check_proxy():
    while True:
        proxies = ProxyStorage.get_proxies()
        for proxy in proxies:
            proxy_url = proxy["proxy"]
            proxy_is_alive = False

            # Проверка прокси на общих тестовых URL
            for test_url in test_urls:
                try:
                    start_time = time.time()
                    response = requests.get(test_url, proxies={"http": proxy_url, "https": proxy_url}, timeout=5)
                    elapsed_time = time.time() - start_time
                    ProxyStorage.set_proxy_alive(proxy_url, True, elapsed_time)
                    logger.info(f"Proxy {proxy_url} is alive. Response time for {test_url}: {elapsed_time:.2f}s")
                    proxy_is_alive = True
                    break  # Прекращаем проверку других URL, если прокси работает
                except requests.RequestException as e:
                    logger.error(f'Proxy {proxy_url} failed to reach {test_url}: {e}')

            # Если прокси прошла общую проверку, проверяем доступность для отдельных хостов
            if proxy_is_alive:
                for host_info in proxy.get('hosts', []):
                    if not host_info.get('alive', True):
                        try:
                            host = host_info['host']
                            response = requests.get(f'http://{host}', proxies={"http": proxy_url, "https": proxy_url},
                                                    timeout=5)
                            if response.status_code == 200:
                                ProxyStorage.update_host_info(proxy_url, host, True)
                                logger.info(f"Proxy {proxy_url} is now reachable for host {host}.")
                        except requests.RequestException as e:
                            logger.error(f"Proxy {proxy_url} is still not reachable for host {host}: {e}")
            else:
                ProxyStorage.set_proxy_alive(proxy_url, False)
                logger.error(f'Proxy {proxy_url} is not working for any tested URL.')

        time.sleep(10)


def construct_full_url(endpoint, user=None, passwd=None):
    parsed = urlparse(endpoint)
    scheme = parsed.scheme
    hostname = parsed.hostname
    port = parsed.port

    # Декодирование байтовых строк, если они есть
    username = user.decode() if user else ''
    password = passwd.decode() if passwd else ''

    # Формирование части URL с учетными данными
    if username and password:
        auth = f"{username}:{password}@"
    else:
        auth = ''

    # Формирование сетевого расположения (netloc)
    if port:
        netloc = f"{auth}{hostname}:{port}"
    else:
        netloc = f"{auth}{hostname}"

    return urlunparse((scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


# Плагин для работы с прокси
class RandomProxyPlugin(ProxyPoolPlugin):
    def _select_proxy(self):
        return None

    def _set_endpoint_for_request(self, request: HttpParser) -> None:
        try:
            host = request.host.decode() if isinstance(request.host, bytes) else request.host
            if not host:
                logger.error("No host found in the request")
                self._endpoint = None
                return

            logger.info(f"Finding proxy for host: {host}")
            proxy_url = ProxyStorage.get_best_proxy(host)
            if proxy_url:
                self._endpoint = Url.from_bytes(proxy_url.encode())
                logger.info(f'Using proxy {proxy_url} for host {host}')
            else:
                self._endpoint = None
        except Exception as e:
            logger.error(f"Error in _set_endpoint_for_request: {e}")
            self._endpoint = None

    def before_upstream_connection(self, request: HttpParser) -> Optional[HttpParser]:
        retry_count = 10  # Количество попыток смены прокси
        while retry_count > 0:
            self._set_endpoint_for_request(request)
            if self._endpoint:
                full_url = str(self._endpoint)
                if self._endpoint.has_credentials:
                    full_url = construct_full_url(full_url, self._endpoint.username, self._endpoint.password)
                logger.info(f"Connecting via proxy: {full_url}")
                host = request.host.decode() if isinstance(request.host, bytes) else request.host
                try:
                    response = super().before_upstream_connection(request)
                    ProxyStorage.update_host_info(full_url, host)
                    return response
                except Exception as e:
                    logger.error(f"Failed to connect via proxy: {full_url}. Error: {e}")
                    ProxyStorage.mark_proxy_dead(full_url, host)
                    retry_count -= 1
                    logger.info(f"Retrying with a different proxy. {retry_count} attempts left.")
                    continue  # Попробовать другую прокси
            else:
                logger.error("No proxy available")
                break  # Нет доступных прокси

        # Если не удалось подключиться через прокси, продолжаем без прокси
        logger.info("Continuing without proxy.")
        return request


# Запуск API и сервера
if __name__ == '__main__':
    logger.info("Starting proxy server...")

    # Запуск потока проверки прокси
    checker_thread = Thread(target=check_proxy)
    checker_thread.daemon = True
    checker_thread.start()

    # Инициализация начальных прокси
    ProxyStorage.initialize_proxies()

    # Запуск Flask API в отдельном потоке
    api_thread = Thread(target=lambda: app.run(host=HOSTNAME, port=int(FLASK_PORT)))
    api_thread.daemon = True
    api_thread.start()

    ip_address = ipaddress.ip_address(HOSTNAME)

    try:
        with Proxy(
                threadless=True,
                num_workers=int(NUM_WORKERS),
                hostname=ip_address,
                port=int(PROXY_PORT),
                basic_auth=BASIC_AUTH,
                plugins=[
                    RandomProxyPlugin,
                ]
        ) as proxy:
            logger.info("Proxy server started.")
            while True:
                time.sleep(1)
    except Exception as e:
        logger.error(f"Error starting proxy server: {str(e)}")
