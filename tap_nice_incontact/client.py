from datetime import datetime as dt, timedelta

import backoff
import requests

from singer import get_logger

LOGGER = get_logger()

API_AUTH_DOMAIN = 'na1'
API_AUTH_URI = 'https://{}.nice-incontact.com/authentication/v1/token/access-key'
API_REFRESH_URI = 'https://{}.nice-incontact.com/public/user/refresh'


API_INCONTACT_URI = 'https://api-{}.niceincontact.com/inContactAPI/services/v{}'
API_INCONTACT_VERSION = '23.0'

# https://developer.niceincontact.com/API/DataExtractionAPI#/
API_DATA_EXTRACTION_URI = 'https://{}.nice-incontact.com/data-extraction/v{}'
API_DATA_EXTRACTION_VERSION = '1'

MAX_RETRIES = 8

def log_backoff_attempt(details):
    method = 'GET'
    url = ''
    args = details.get("args")
    if args:
        method = args[1]
        url = args[2]
    LOGGER.info(
        "Connection error detected for %s to /%s, triggering backoff: %d try",
        method,
        url,
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
    def __init__(self, status_header=None, response=None):
        super().__init__(status_header)
        self.status_header = status_header
        self.response = response

class NiceInContact401Exception(NiceInContact4xxException):
    pass

class NiceInContact403Exception(NiceInContact4xxException):
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
                api_incontact_version: str = None,
                api_data_extraction_version: str = None,
                auth_domain: str = None,
                user_agent: str = None,
                start_date: str = None):
        self.api_key = api_key
        self.api_secret = api_secret
        # Format InContact URI
        self.api_incontact_version = str(api_incontact_version) if api_incontact_version else API_INCONTACT_VERSION
        self.api_incontact_base_uri = API_INCONTACT_URI.format(api_cluster, self.api_incontact_version)

        # Format Data Extraction URI
        self.api_data_extraction_version = str(api_data_extraction_version) if api_data_extraction_version else API_DATA_EXTRACTION_VERSION
        self.api_data_extraction_base_uri = API_DATA_EXTRACTION_URI.format(api_cluster, self.api_data_extraction_version)

        self.user_agent = user_agent

        self.session = requests.Session()

        api_auth_domain = auth_domain if auth_domain else API_AUTH_DOMAIN
        self.auth_endpoint = API_AUTH_URI.format(api_auth_domain)
        self.refresh_endpoint = API_REFRESH_URI.format(api_auth_domain)

        self.access_token = None
        self.refresh_token = None
        self.access_expires_at = None
        self.refresh_expires_at = None

        self.start_date = start_date

    def _ensure_access_token(self, refresh_token: str = None):
        """
        Internal method for keeping access token current.

        :param refresh_token: The refresh token from a previous request.
        """
        if refresh_token and self.refresh_expires_at <= dt.utcnow():
            response = self.session.post(self.refresh_endpoint, json={"token": self.refresh_token})

            data = response.json()

            # `refresh_endpoint` returns slightly different `access_token` and `refresh_token` keys
            self.access_token = data.get('token')
            self.refresh_token = data.get('refreshToken')

            # `refresh_endpoint` returns slightly different `expires_in` key
            self.access_expires_at = dt.utcnow() + \
                timedelta(seconds=int(data.get('tokenExpirationTimeSec')) - 10)
            self.refresh_expires_at = dt.utcnow() + \
                timedelta(seconds=int(data.get('refreshTokenExpirationTimeSec')) - 10)
        elif self.access_token is None or self.access_expires_at >= dt.utcnow():
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

            self.access_expires_at = dt.utcnow() + \
                timedelta(seconds=int(data.get('expires_in')) - 10)
            self.refresh_expires_at = dt.utcnow() + \
                timedelta(seconds=int(data.get('expires_in')) - 10)

    def _get_standard_headers(self):
        return {
            "Authorization": "Bearer {}".format(self.access_token),
            "User-Agent": self.user_agent,
        }

    @backoff.on_exception(backoff.expo,
                        (NiceInContact5xxException,
                        NiceInContact4xxException,
                        NiceInContact403Exception,
                        NiceInContact401Exception,
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
                    data: dict = None,
                    is_data_extraction: bool = False):
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
        base_uri = self.api_data_extraction_base_uri if is_data_extraction else self.api_incontact_base_uri
        if not paging:
            full_url = f'{base_uri}/{endpoint}'
        else:
            full_url = endpoint

        if method == 'POST':
            LOGGER.info(
                "%s - Making %s request with data %s",
                full_url,
                method.upper(),
                data
            )
        elif params:
            LOGGER.info(
                "%s - Making %s request to endpoint %s, with params %s",
                full_url,
                method.upper(),
                endpoint,
                params,
            )
        else:
            LOGGER.info(
                "%s - Making %s request",
                full_url,
                method.upper()
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

        status_header = response.headers.get("icStatusDescription", response.status_code)

        # pylint: disable=no-else-raise
        if response.status_code >= 500:
            raise NiceInContact5xxException(response.text)
        elif response.status_code == 429:
            raise NiceInContact429Exception("rate limit exceeded", response)
        elif response.status_code == 401:
            # reseting `access_token` to reauthorize on retry
            self.access_token = None
            raise NiceInContact401Exception(
                "API returned a 401 - Unauthorized, confirm credentials are valid.",
                response.status_code)
        elif response.status_code == 403:
            raise NiceInContact403Exception(
                "API returned a 403 - Forbidden",
                response.text
            )
        elif response.status_code >= 400:
            # the 'icStatusDescription' header may contain an error message instead of the body
            status_header = response.headers.get("icStatusDescription", response.status_code)
            raise NiceInContact4xxException(status_header, response.text)

        if response.status_code == 204:
            LOGGER.info(
                "No Content (204) returnted for {} API call to endpoint {}, with params {}".format(
                    method.upper(), endpoint, params
                ))
            results = None
        else:
            results = response.json()

        return results

    def get(self, endpoint, paging=False, headers=None, params=None, is_data_extraction = False):
        """
        NiceInContactClient's primary external method for making GET requests.
        """
        return self._make_request("GET", endpoint, paging, headers=headers, params=params, is_data_extraction=is_data_extraction)

    def post(self, endpoint, paging=False, headers=None, data=None, is_data_extraction = False):
        """
        NiceInContactClient's primary external method for making POST requests.
        """
        return self._make_request("POST", endpoint, paging, headers=headers, data=data, is_data_extraction=is_data_extraction)
