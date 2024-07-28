# Gateway Proxy Server

## Overview

The Gateway Proxy Server is a robust and scalable solution designed to manage and distribute traffic through a pool of proxy servers. It includes functionalities for dynamically adding and removing proxies, monitoring their availability, and intelligently routing traffic based on proxy status and host-specific rules. This server is particularly useful for scenarios where reliable proxy management and distribution are critical, such as web scraping, SEO monitoring, or accessing geo-restricted content.

## Key Features

1. **Dynamic HTTP Proxy Management**: 
   - Add and remove proxies on the fly using RESTful API endpoints.
   - Each proxy is stored with detailed metadata, including its status (`alive`), response times, and usage statistics per host.

2. **Host-Specific Proxy Status**:
   - Track the availability of proxies not just globally but also on a per-host basis.
   - Proxies can be marked as unavailable for specific hosts if they are detected as blocked or non-functional.

3. **Intelligent Proxy Selection**:
   - Proxies are selected based on their availability and usage statistics, ensuring a balanced distribution of traffic.
   - If a proxy fails for a specific host, the system automatically retries with a different proxy.

4. **Monitoring and Health Checks**:
   - Periodic checks on all proxies to ensure they are functional.
   - Logs detailed information about the status and response times of each proxy.

5. **Integration with Redis**:
   - All proxy information is stored and managed using Redis, ensuring high performance and easy scalability.


## Installation

1. **Clone the repository**:
```
git clone https://github.com/n0a/gateway-proxy.git
cd gateway-proxy
```
2. **Install dependencies**:
Ensure you have Python installed. Then install the required packages:
```
pip install -r requirements.txt
```
3. **Configure Redis**:
Make sure Redis is running on your local machine or adjust the `get_redis_client` function in the code to point to your Redis instance.

Environment Variables

The following environment variables can be set to configure the server:

  - `FLASK_PORT`: The port on which the Flask API will run. Default is 5550.
  - `PROXY_PORT`: The port on which the Proxy server will run. Default is 8181.
  - `HOSTNAME`: The hostname or IP address the server will bind to. Default is 0.0.0.0.
  - `BASIC_AUTH`: Basic authentication credentials in the format user:pass for gateway proxy access.
  - `INITIAL_PROXIES`: Comma-separated list of initial proxy URLs to add to the server on startup.

These variables can be set in a .env file or passed directly to Docker.

**Example .env file**
```
FLASK_PORT=5550         # Flask port
FLASK_USER=admin        # Flask basic auth username
FLASK_PASS=secret       # Flask basic auth password
PROXY_PORT=8181         # Proxy gateway port
HOSTNAME=0.0.0.0        # Interface for listening port
NUM_WORKERS=5           # Number of worker threads for the proxy server
BASIC_AUTH=user:pass    # Basic auth credentials for the gateway proxy server
INITIAL_PROXIES=http://user1:pass@161.0.1.1:8000,http://user2:pass2@46.3.55.108:8000,another_n_servers
```
## Usage

1. **Start the Proxy Server:**:
    ```
    docker-compose --env-file .env up --build
    docker-compose up -d
    ```
    This command will start the services in the background (detached mode).

2. **Start the Proxy Server:**:
    ```
    docker-compose down
    ```
    This will stop and remove all containers, networks, and volumes created by docker-compose up.
3. **Restart Policy:**:
    The `docker-compose.yml` file includes a restart policy restart: unless-stopped, ensuring that the containers are automatically restarted if they fail, but they won't be restarted if stopped manually.



## API Endpoints

- **Add a Proxy**: 
  - Endpoint: `/add_proxy`
  - Method: `POST`
  - Payload: `{"proxy": "http://username:password@proxy:port"}`
  - Description: Adds a new proxy to the pool. Checks its availability before adding.

- **Remove a Proxy**:
  - Endpoint: `/remove_proxy`
  - Method: `DELETE`
  - Payload: `{"proxy": "http://username:password@proxy:port"}`
  - Description: Removes a proxy from the pool.

- **Get Proxy Info**:
  - Endpoint: `/proxy_info`
  - Method: `GET`
  - Description: Retrieves detailed information about all proxies in the pool.

3. **Proxy Management**:
- The server periodically checks the availability of each proxy using predefined test URLs.
- Proxies are marked as dead for specific hosts if they fail to connect, ensuring that traffic is not routed through non-functional proxies.

## Example Code Usage

### Adding a Proxy

```python
import requests

response = requests.post('http://localhost:5550/add_proxy', json={'proxy': 'http://username:password@proxy:port'})
print(response.json())
```
### Removing a Proxy
```python
import requests

response = requests.delete('http://localhost:5550/remove_proxy', json={'proxy': 'http://username:password@proxy:port'})
print(response.json())
```

### Fetching Proxy Info
```python
import requests

response = requests.get('http://localhost:5550/proxy_info')
print(response.json())
```

### Future Enhancements

- Advanced Proxy Selection: Integrate machine learning algorithms to predict the best proxy based on historical data. 
- Detailed Analytics: Provide more in-depth analytics and reporting on proxy performance and usage.

### Contributing

Contributions are welcome! Please submit a pull request or open an issue for any bugs or feature requests.


