from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os


def _clean_host(value: str) -> str:
    host = (value or '').strip().lower().split(',', 1)[0].strip()
    if host.startswith('['):
        return host.split(']', 1)[0].lstrip('[')
    return host.split(':', 1)[0]


def _is_loopback(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return value in {'localhost'}


@dataclass(frozen=True)
class DeploymentPolicy:
    mode: str = 'LOCAL_STAGING'
    public_host: str = 'localhost'
    app_host: str = 'localhost'
    cookie_secure: bool = False
    trust_proxy: bool = False

    @classmethod
    def from_env(cls) -> 'DeploymentPolicy':
        mode = os.environ.get('ATLAS_DEPLOYMENT_MODE', 'LOCAL_STAGING').strip().upper()
        public_host = _clean_host(os.environ.get('ATLAS_PUBLIC_HOST', 'localhost'))
        app_host = _clean_host(os.environ.get('ATLAS_APP_HOST', 'localhost'))
        cookie_secure = os.environ.get('ATLAS_COOKIE_SECURE', '0') == '1'
        trust_proxy = os.environ.get('ATLAS_TRUST_PROXY', '0') == '1'
        policy = cls(mode, public_host, app_host, cookie_secure, trust_proxy)
        policy.validate_startup()
        return policy

    @property
    def proxied(self) -> bool:
        return self.mode in {'PROXY_STAGING', 'PRODUCTION_STAGING'}

    @property
    def session_cookie_name(self) -> str:
        return '__Host-atlas_session' if self.proxied else 'atlas_session'

    def validate_startup(self) -> None:
        if self.proxied:
            if not self.cookie_secure:
                raise RuntimeError('ATLAS_COOKIE_SECURE=1 is mandatory behind the TLS deployment boundary')
            if not self.trust_proxy:
                raise RuntimeError('ATLAS_TRUST_PROXY=1 is mandatory behind the loopback reverse proxy')
            if not self.public_host or not self.app_host or self.public_host == self.app_host:
                raise RuntimeError('distinct ATLAS_PUBLIC_HOST and ATLAS_APP_HOST are required')

    def normalize_host(self, host_header: str) -> str:
        return _clean_host(host_header)

    def host_role(self, host_header: str) -> str:
        host = self.normalize_host(host_header)
        if not self.proxied:
            return 'LOCAL'
        if host == self.public_host:
            return 'PUBLIC'
        if host == self.app_host:
            return 'APP'
        return 'REJECT'

    def route_allowed(self, host_header: str, method: str, path: str) -> bool:
        role = self.host_role(host_header)
        method = method.upper()
        if role == 'REJECT':
            return False
        if role == 'LOCAL':
            return True
        if role == 'PUBLIC':
            if method == 'POST' and path == '/api/leads':
                return True
            return method in {'GET', 'HEAD'} and not path.startswith('/api/') and not path.startswith('/app')
        # APP host: no public lead submission and no public-root content other than redirects/assets.
        if path == '/api/leads' and method == 'POST':
            return False
        return path.startswith('/app') or path.startswith('/api/') or path.startswith('/assets/') or path == '/health' or path == '/'

    def request_is_https(self, *, peer_ip: str, forwarded_proto: str) -> bool:
        if not self.proxied:
            return True
        return self.trust_proxy and _is_loopback(peer_ip) and forwarded_proto.split(',', 1)[0].strip().lower() == 'https'

    def client_ip(self, *, peer_ip: str, forwarded_for: str) -> str:
        if not (self.proxied and self.trust_proxy and _is_loopback(peer_ip)):
            return peer_ip
        candidate = forwarded_for.split(',', 1)[0].strip()
        try:
            ipaddress.ip_address(candidate)
            return candidate
        except ValueError:
            return peer_ip

    def login_url(self) -> str:
        if self.proxied:
            return f'https://{self.app_host}/app/login'
        return '/app/login'
