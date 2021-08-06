from datetime import datetime as dt, timedelta

import backoff
import requests

from singer import get_logger

LOGGER = get_logger()

API_AUTH_DOMAIN = 'na1'
API_AUTH_URI = 'https://{}.nice-incontact.com/authentication/v1/token/access-key'
API_REFRESH_URI = 'https://{}.nice-incontact.com/public/user/refresh'
API_BASE_URI = 'https://api-{}.nice-incontact.com/inContactAPI/services/v{}'
API_VERSION = '21.0'
MAX_RETRIES = 5

def log_backoff_attempt(details):
    LOGGER.info(
        "Connection error detected, triggering backoff: %d try",
        details.get("tries")
        )


# pylint: disable=missing-class-docstring
class NiceInContactException(Exception):
    pass

# pylint: disable=missing-class-docstring
class NiceInContact5xxException(NiceInContactException):
    pass

# pylint: disable=missing-class-docstring
class NiceInContact4xxException(NiceInContactException):
    pass

# pylint: disable=missing-class-docstring
class NiceInContact429Exception(NiceInContactException):
    def __init__(self, message=None, response=None):
        super().__init__(message)
        self.message = message
        self.response = response

# pylint: disable=missing-class-docstring,too-many-instance-attributes,too-few-public-methods
class NiceInContactClient:
    def __init__(self,
                api_key: str = None,
                api_secret: str = None,
                api_cluster: str = None,
                api_version: str = None,
                auth_domain: str = None,
                user_agent: str = None,
                start_date: str = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_version = str(api_version) if api_version else API_VERSION
        self.api_base_uri = API_BASE_URI.format(api_cluster, self.api_version)
        self.user_agent = user_agent

        self.session = requests.Session()

        api_auth_domain = auth_domain if auth_domain else API_AUTH_DOMAIN
        self.auth_endpoint = API_AUTH_URI.format(api_auth_domain)
        self.refresh_endpoint = API_REFRESH_URI.format(api_auth_domain)

        self.access_token = None
        self.refresh_token = None
        self.expires_at = None

        self.start_date = start_date

    def _ensure_access_token(self, refresh_token: str = None):
        """
        Internal method for keeping access token current.

        :param refresh_token: The refresh token from a previous request.
        """
        if refresh_token and self.expires_at <= dt.utcnow():
            response = self.session.post(self.refresh_endpoint, json={"token": self.refresh_token})

            data = response.json()

            # `refresh_endpoint` returns slightly different `access_token` and `refresh_token` keys
            self.access_token = data.get('token')
            self.refresh_token = data.get('refreshToken')

            # `refresh_endpoint` returns slightly different `expires_in` key
            self.expires_at = dt.utcnow() + \
                timedelta(seconds=int(data.get('refreshTokenExpirationTimeSec')) - 10)
        else:
            if self.access_token is None or self.expires_at <= dt.utcnow():
                response = self.session.post(
                    self.auth_endpoint,
                    json={
                        "accessKeyId": self.api_key,
                        "accessKeySecret": self.api_secret
                    })

                if response.status_code != 200:
                    raise NiceInContactException(
                        'Non-200 response fetching NICE inContact access token'
                        )

                data = response.json()

                self.access_token = data.get('access_token')
                self.refresh_token = data.get('refresh_token')

                self.expires_at = dt.utcnow() + \
                    timedelta(seconds=int(data.get('expires_in')) - 10)

    def _get_standard_headers(self):
        return {
            "Authorization": "Bearer {}".format(self.access_token),
            "User-Agent": self.user_agent,
        }

    @backoff.on_exception(backoff.expo,
                        (NiceInContact5xxException,
                        NiceInContact4xxException,
                        requests.ConnectionError),
                        max_tries=MAX_RETRIES,
                        factor=2,
                        on_backoff=log_backoff_attempt)
    def _make_request(self,
                    method: str,
                    endpoint: str,
                    paging: bool = False,
                    headers: dict = None,
                    params: dict = None,
                    data: dict = None):
        """
        Internal NiceInContactClient method for making HTTP requests.

        :param method: The HTTP method to use: Ex. GET or POST.
        :param endpoint: The url for the HTTP request.
        :param paging: A boolean for whether or not this is a sub-sequent
                            paginated request.
        :param headers: Any non-standard HTTP request headers required
                            to make request.
        :param params: Any URI encoded query params required to make request.
        :param data: Any request body required to make request.
        """
        if not paging:
            full_url = f'{self.api_base_uri}/{endpoint}'
        else:
            full_url = endpoint

        LOGGER.info(
            "%s - Making request to %s endpoint %s, with params %s",
            full_url,
            method.upper(),
            endpoint,
            params,
        )

        self._ensure_access_token(self.refresh_token)

        default_headers = self._get_standard_headers()

        if headers:
            headers = {**default_headers, **headers}
        else:
            headers = {**default_headers}

        response = self.session.request(method,
                                        full_url,
                                        headers=headers,
                                        params=params,
                                        data=data)

        # pylint: disable=no-else-raise
        if response.status_code >= 500:
            raise NiceInContact5xxException(response.text)
        elif response.status_code == 429:
            raise NiceInContact429Exception("rate limit exceeded", response)
        elif response.status_code >= 400:
            raise NiceInContact4xxException(response.text)

        if response.status_code == 204:
            LOGGER.info(
                "No Content (204) returnted for {} API call to endpoint {}, with params {}".format(
                    method.upper(), endpoint, params
                ))
            results = None
        else:
            results = response.json()

        return results

    def get(self, endpoint, paging=False, headers=None, params=None):
        """
        NiceInContactClient's primary external method for making GET requests.
        """
        return self._make_request("GET", endpoint, paging, headers=headers, params=params)
