import httpx
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

PROXY_SERVER = 'http://user:pass@10.10.10.10:8181'  # Адрес нашего прокси-сервера
TARGET_URL = 'https://ifconfig.me/ip'

REQUESTS_PER_SECOND = 1

async def fetch_ip():
    try:
        proxies = {"http://": PROXY_SERVER, "https://": PROXY_SERVER}
        async with httpx.AsyncClient(proxies=proxies) as client:
            response = await client.get(TARGET_URL)
            if response.status_code == 200:
                ip = response.text.strip()
                logging.info(f"Current IP: {ip}")
            else:
                logging.warning(f"Failed to fetch IP: {response.status_code}")
    except httpx.RequestError as e:
        logging.error(f"Request error: {e}")
    except Exception as e:
        logging.error(f"Error fetching IP: {e}")


async def main():
    while True:
        tasks = [fetch_ip() for _ in range(REQUESTS_PER_SECOND)]
        await asyncio.gather(*tasks)
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
