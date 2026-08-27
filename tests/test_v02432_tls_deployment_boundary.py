from pathlib import Path
import pytest
from atlas.security.deployment import DeploymentPolicy


def test_proxy_mode_requires_secure_cookie_and_proxy_trust():
    with pytest.raises(RuntimeError):
        DeploymentPolicy('PROXY_STAGING','atlastradingexpert.com','app.atlastradingexpert.com',False,True).validate_startup()
    with pytest.raises(RuntimeError):
        DeploymentPolicy('PROXY_STAGING','atlastradingexpert.com','app.atlastradingexpert.com',True,False).validate_startup()


def test_host_route_separation_and_host_cookie():
    p=DeploymentPolicy('PROXY_STAGING','atlastradingexpert.com','app.atlastradingexpert.com',True,True)
    p.validate_startup()
    assert p.session_cookie_name == '__Host-atlas_session'
    assert p.route_allowed('atlastradingexpert.com','POST','/api/leads')
    assert not p.route_allowed('atlastradingexpert.com','GET','/api/dashboard')
    assert p.route_allowed('app.atlastradingexpert.com','GET','/api/dashboard')
    assert not p.route_allowed('app.atlastradingexpert.com','POST','/api/leads')
    assert not p.route_allowed('evil.example','GET','/')


def test_forwarded_headers_only_trusted_from_loopback():
    p=DeploymentPolicy('PROXY_STAGING','atlastradingexpert.com','app.atlastradingexpert.com',True,True)
    assert p.client_ip(peer_ip='127.0.0.1', forwarded_for='203.0.113.5, 127.0.0.1') == '203.0.113.5'
    assert p.client_ip(peer_ip='198.51.100.8', forwarded_for='203.0.113.5') == '198.51.100.8'
    assert p.request_is_https(peer_ip='127.0.0.1', forwarded_proto='https')
    assert not p.request_is_https(peer_ip='198.51.100.8', forwarded_proto='https')


def test_csp_assets_no_public_inline_script_or_style_block():
    html=Path('web/public/index.html').read_text(encoding='utf-8')
    assert '<style>' not in html
    assert '<script>' not in html
    assert Path('web/public/landing.css').exists()
    assert Path('web/public/landing.js').exists()
