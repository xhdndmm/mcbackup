import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import ssl

# --- TLS 强化 Session ---
class TLS12Adapter(HTTPAdapter):
    def __init__(self, *args, **kwargs):
        self.ssl_context = ssl.create_default_context()
        try:
            self.ssl_context.set_ciphers("DEFAULT:@SECLEVEL=1")
        except Exception:
            pass
        try:
            self.ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        except Exception:
            pass
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self.ssl_context
        return super().init_poolmanager(*args, **kwargs)

def make_robust_session(total_retries=5, backoff_factor=1.0):
    session = requests.Session()
    retry = Retry(
        total=total_retries,
        read=total_retries,
        connect=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=[500,502,503,504],
        allowed_methods=frozenset(['GET','POST','PUT','DELETE','HEAD','OPTIONS']),
        raise_on_status=False,
        respect_retry_after_header=True
    )
    adapter = TLS12Adapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"})
    return session

_http = make_robust_session()