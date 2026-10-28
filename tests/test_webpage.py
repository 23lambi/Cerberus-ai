# Tests for reading web pages. Most of them are attacks: a page or a
# search result trying to make Cerberus open something on your own
# computer or network. Each must be refused BEFORE anything is downloaded.
#
# No internet: DNS is faked with a dict, the network with httpx.MockTransport.

import asyncio

import httpx
import pytest

from cerberus import webpage, websearch
from cerberus.websearch import WebError

PUBLIC = "93.184.216.34"


def fake_web(monkeypatch, handler, dns=None):
    """Fake DNS and network. Returns the list of requests that were sent."""
    dns = dns or {}
    requests = []

    async def resolve(host):
        return dns.get(host, [PUBLIC])

    def record(request):
        requests.append(request)
        return handler(request)

    monkeypatch.setattr(webpage, "resolve", resolve)
    monkeypatch.setattr(
        websearch, "new_client",
        lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(record)),
    )
    return requests


def html(body, status=200, **headers):
    return lambda request: httpx.Response(
        status, text=body, headers={"content-type": "text/html; charset=utf-8", **headers}
    )


def fetch(address):
    return asyncio.run(webpage.fetch_page(address))


# ---------- Which addresses are allowed ----------


@pytest.mark.parametrize("ip", [
    "127.0.0.1",          # this computer
    "::1",                # this computer, IPv6
    "::ffff:127.0.0.1",   # this computer, hidden inside IPv6
    "10.0.0.5",           # private network
    "192.168.1.1",        # your router
    "169.254.169.254",    # link-local (cloud servers keep secrets here)
    "100.64.0.1",         # shared address space (carrier networks)
    "0.0.0.0",
    "224.0.0.1",          # multicast
    "not an ip",
])
def test_local_and_private_addresses_are_not_public(ip):
    assert not webpage.is_public(ip)


@pytest.mark.parametrize("ip", [PUBLIC, "1.1.1.1", "2606:4700:4700::1111"])
def test_internet_addresses_are_public(ip):
    assert webpage.is_public(ip)


# ---------- Attacks: nothing may be downloaded ----------


@pytest.mark.parametrize("address", [
    "http://127.0.0.1:11434/api/tags",  # your Ollama
    "http://[::1]:8000/backup",         # Cerberus itself, IPv6
    "file:///etc/passwd",
    "ftp://example.com/file",
])
def test_local_addresses_and_other_schemes_are_refused(monkeypatch, address):
    requests = fake_web(monkeypatch, html("secret"))
    with pytest.raises(WebError):
        fetch(address)
    assert requests == []


def test_a_name_that_points_inside_your_network_is_refused(monkeypatch):
    requests = fake_web(monkeypatch, html("secret"), dns={"router.evil.example": ["192.168.1.1"]})
    with pytest.raises(WebError, match="local or private"):
        fetch("http://router.evil.example/")
    assert requests == []


def test_one_private_address_among_public_ones_is_enough_to_refuse(monkeypatch):
    requests = fake_web(monkeypatch, html("x"), dns={"mixed.example": [PUBLIC, "127.0.0.1"]})
    with pytest.raises(WebError):
        fetch("http://mixed.example/")
    assert requests == []


def test_a_redirect_into_your_network_is_refused(monkeypatch):
    # A public page that says "go to http://localhost/" instead.
    requests = fake_web(
        monkeypatch,
        lambda request: httpx.Response(302, headers={"location": "http://localhost:11434/"}),
        dns={"localhost": ["127.0.0.1"]},
    )
    with pytest.raises(WebError, match="local or private"):
        fetch("http://example.com/")
    assert len(requests) == 1  # the public page only, never the local one


def test_endless_redirects_stop(monkeypatch):
    fake_web(monkeypatch, lambda request: httpx.Response(302, headers={"location": "/again"}))
    with pytest.raises(WebError, match="too many"):
        fetch("http://example.com/")


# ---------- Pinning: connect to the checked address ----------


def test_connects_to_the_checked_ip_but_asks_for_the_site_by_name(monkeypatch):
    requests = fake_web(monkeypatch, html("<p>Hi</p>"))
    fetch("https://example.com/page?x=1")
    sent = requests[0]
    assert sent.url.host == PUBLIC  # no second DNS lookup can change this
    assert sent.url.path == "/page" and sent.url.params["x"] == "1"
    assert sent.headers["host"] == "example.com"
    assert sent.extensions["sni_hostname"] == "example.com"  # certificate check by name


def test_a_relative_redirect_is_followed(monkeypatch):
    def handler(request):
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return html("<p>Moved here</p>")(request)

    page = fetch_with(monkeypatch, handler, "http://example.com/old")
    assert page["url"] == "http://example.com/new" and page["text"] == "Moved here"


def fetch_with(monkeypatch, handler, address):
    fake_web(monkeypatch, handler)
    return fetch(address)


# ---------- What is read ----------


def test_only_web_pages_are_read(monkeypatch):
    fake_web(monkeypatch, lambda r: httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"}))
    with pytest.raises(WebError, match="not a web page"):
        fetch("http://example.com/file.pdf")


def test_errors_are_reported(monkeypatch):
    fake_web(monkeypatch, html("gone", status=404))
    with pytest.raises(WebError, match="404"):
        fetch("http://example.com/")


def test_a_huge_page_is_cut(monkeypatch):
    monkeypatch.setattr(webpage, "MAX_PAGE_BYTES", 1000)
    fake_web(monkeypatch, lambda r: httpx.Response(200, text="a" * 50000, headers={"content-type": "text/plain"}))
    assert len(fetch("http://example.com/")["text"]) == 1000


def test_html_becomes_readable_text():
    title, text = webpage.html_to_text("""
        <html><head><title> My  page </title><style>p{color:red}</style></head>
        <body><nav>Home | About</nav>
        <h1>Hello</h1><p>Fish &amp; chips,   cheap.</p><p>Second<br>line</p>
        <script>alert("never run")</script>
        <footer>© 2026</footer></body></html>
    """)
    assert title == "My page"
    assert text == "Hello\nFish & chips, cheap.\nSecond\nline"


def test_menus_made_of_divs_are_skipped_with_everything_nested_inside():
    _, text = webpage.html_to_text("""
        <div role="navigation"><div>Topics</div><div><div>Careers</div></div></div>
        <div>Real content</div>
        <div role="banner">Sign up!</div>
    """)
    assert text == "Real content"


def test_the_marked_main_content_wins_when_it_has_enough_text():
    story = "<p>" + "Zebras are striped. " * 40 + "</p>"
    page = f"<div>Topics Careers Python</div><article>{story}</article><div>Related posts</div>"
    _, text = webpage.html_to_text(page)
    assert text.startswith("Zebras are striped.")
    assert "Topics" not in text and "Related" not in text

    # A tiny <main> (a teaser) is not trusted: then the whole page is kept.
    _, text = webpage.html_to_text("<div>Intro text</div><main><p>Short</p></main>")
    assert text == "Intro text\nShort"


def test_broken_html_never_loses_the_rest_of_the_page():
    # A </div> too many must not end a region early or make the depth negative.
    _, text = webpage.html_to_text("<div role='navigation'>Menu</div></div></div><p>Still here</p>")
    assert text == "Still here"
