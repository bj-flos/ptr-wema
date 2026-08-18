"""
Photon Ranch API access for the WEMA.

The base URL used to be hardwired to LCO production in two places, so a WEMA
could only ever talk to the live service. It now comes from ptr_endpoints,
which reads PTR_API_ROOT (typically from .env) and falls back to that same
production URL, leaving behaviour unchanged when nothing is set.

Note the class name: authenticated_request sends no credentials. That is
inherited from upstream, where the config endpoints carry no API Gateway
authorizer, and is left as-is rather than quietly changed here.
"""
import json

import requests

from ptr_endpoints import PTR_API_ROOT


class API_calls:

    def __init__(self):
        self.api = PTR_API_ROOT

    def base_url(self):
        return PTR_API_ROOT

    def authenticated_request(self, method: str, uri: str, payload: dict = None) -> str:

        # Populate the request parameters. Include data only if it was sent.
        request_kwargs = {
            "method": method,
            "url": f"{self.base_url()}/{uri}",
        }
        if payload is not None:
            request_kwargs["data"] = json.dumps(payload)

        response = requests.request(**request_kwargs)
        return response.json()
