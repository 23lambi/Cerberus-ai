# Web search (Stage 3, step 2): download one web page and keep only its
# text. This is the most careful file in Cerberus, because the addresses
# come from the internet, not from you.
#
# Three dangers, and what we do about each:
#
# 1. Private addresses ("SSRF"). A search result, or a page redirecting
#    somewhere, could point at http://127.0.0.1:11434 (your Ollama) or
#    http://192.168.1.1 (your router). Cerberus would then read your own
#    network for a stranger. So every address is checked, after every
#    redirect too, and only public internet addresses are allowed.
#
# 2. DNS rebinding. A name like evil.example is turned into an address by
#    DNS. A tricky DNS server can say "a public address" when we check and
#    "127.0.0.1" a moment later when we download. So we look the name up
#    ONCE, check that address, and connect to exactly that address
#    ("pinning"), while still telling the server which site we want.
#
# 3. Huge or endless pages. A time limit, a size limit, and only text and
#    HTML. Nothing on the page is ever run: no JavaScript, just its text.

import asyncio
import ipaddress
import socket
from html.parser import HTMLParser

import httpx

from cerberus import websearch
from cerberus.config import (
    MAX_PAGE_BYTES,
    MAX_REDIRECTS,
    PAGE_TEXT_CHARS,
    WEB_PAGE_TIMEOUT,
)
from cerberus.websearch import WebError

# Some sites refuse the default "python-httpx" name, so we say who we are.
USER_AGENT = "Mozilla/5.0 (compatible; Cerberus; private local assistant)"
READABLE = ("text/html", "application/xhtml+xml", "text/plain")


# ---------- 1 and 2: only public addresses, pinned ----------


def is_public(ip):
    """True only for a normal internet address, not anything local or private."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    # "::ffff:127.0.0.1" is 127.0.0.1 written as IPv6. Check the real one.
    if address.version == 6 and address.ipv4_mapped:
        address = address.ipv4_mapped
    # is_global is False for loopback (127.x), private networks (10.x,
    # 192.168.x...), link-local (169.254.x, cloud metadata) and reserved ranges.
    return address.is_global and not address.is_multicast


async def resolve(host):
    # DNS: the name -> its addresses (a name can have several).
    try:
        found = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise WebError(f"{host} could not be found.") from None
    # Each item is (family, type, proto, name, (ip, port, ...)).
    return [item[4][0] for item in found]


async def checked(address):
    """The address as an httpx.URL, plus the public IP to connect to."""
    try:
        url = httpx.URL(address)
    except httpx.InvalidURL:
        raise WebError(f"{address} is not a valid web address.") from None
    if url.scheme not in ("http", "https") or not url.host:
        raise WebError("Only http and https web pages can be read.")
    try:
        ipaddress.ip_address(url.host)
        ips = [url.host]  # already a number, like http://93.184.216.34/
    except ValueError:
        ips = await resolve(url.host)
    # ALL of its addresses must be public, not just the first one.
    if not ips or not all(is_public(ip) for ip in ips):
        raise WebError(f"{url.host} is a local or private address. Cerberus doesn't open those.")
    return url, ips[0]


# ---------- Downloading ----------


async def fetch_page(address):
    """{"url", "title", "text"} of one web page. Raises WebError when it can't."""
    try:
        # One time limit for everything, redirects included.
        async with asyncio.timeout(WEB_PAGE_TIMEOUT):
            return await fetch(address)
    except TimeoutError:
        raise WebError(f"{address} took too long to answer.") from None


async def fetch(address):
    async with websearch.new_client(WEB_PAGE_TIMEOUT) as client:
        # We follow redirects ourselves, so each new address is checked too.
        for _ in range(MAX_REDIRECTS + 1):
            url, ip = await checked(address)
            headers = {
                # Connect to the checked IP, but ask for the site by name:
                # one server often hosts many sites.
                "Host": url.netloc.decode("ascii"),
                "User-Agent": USER_AGENT,
                "Accept": "text/html, text/plain;q=0.9",
            }
            # For https, the certificate must match the NAME, not the IP.
            # sni_hostname tells httpx which name to use for that check.
            extensions = {"sni_hostname": url.host} if url.scheme == "https" else {}
            request = client.build_request(
                "GET", url.copy_with(host=ip), headers=headers, extensions=extensions
            )
            try:
                # stream=True: the body isn't downloaded yet, so read() can stop early.
                response = await client.send(request, stream=True)
            except httpx.HTTPError as error:
                if "CERTIFICATE_VERIFY_FAILED" in str(error):
                    # Reached, but it can't prove it's really that site.
                    raise WebError(f"{url.host} has an invalid security certificate.") from None
                raise WebError(f"{url.host} could not be reached.") from None
            try:
                if response.is_redirect:
                    # Location can be relative ("/new-page"), so join it
                    # to the page's real address (the name, not the IP).
                    address = str(url.join(response.headers["location"]))
                    continue
                return await read(url, response)
            finally:
                await response.aclose()
    raise WebError(f"{address} redirected too many times.")


async def read(url, response):
    if response.status_code != 200:
        raise WebError(f"{url.host} answered with error {response.status_code}.")
    # "text/html; charset=utf-8" -> "text/html"
    kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if kind not in READABLE:
        raise WebError(f"{url} is not a web page ({kind or 'unknown type'}).")

    # Read in pieces and stop at the size limit. aiter_bytes also unpacks
    # compressed pages piece by piece, so a tiny "zip bomb" can't explode.
    data = bytearray()
    async for piece in response.aiter_bytes():
        data += piece
        if len(data) >= MAX_PAGE_BYTES:
            break  # a big page: its start is enough
    try:
        text = bytes(data[:MAX_PAGE_BYTES]).decode(response.charset_encoding or "utf-8", errors="replace")
    except LookupError:  # the page named a character set Python doesn't know
        text = bytes(data[:MAX_PAGE_BYTES]).decode("utf-8", errors="replace")

    if kind == "text/plain":
        title, body = "", text
    else:
        title, body = html_to_text(text)
    return {"url": str(url), "title": title, "text": body[:PAGE_TEXT_CHARS]}


# ---------- 3: HTML -> plain text ----------


class TextOnly(HTMLParser):
    """Collects the text a person would read, and the page's title.

    HTMLParser calls handle_starttag for <p>, handle_data for the text
    inside, and handle_endtag for </p>. We only keep the text, and skip
    parts that aren't content: code, styles, menus, headers and footers.

    Many sites build their menus from plain <div>s, marked only with
    role="navigation". To skip one, we must find ITS </div> among all the
    <div>s nested inside it, so each region counts its own nesting depth.
    """

    SKIP = {"head", "script", "style", "noscript", "template", "svg",
            "nav", "header", "footer", "aside", "form", "iframe"}
    # role="..." values that mean "menu, header or sidebar", on any tag.
    SKIP_ROLES = {"navigation", "banner", "contentinfo", "search",
                  "complementary", "menu", "menubar", "dialog"}
    # The page's real content, when the site marks it.
    MAIN = {"main", "article"}
    # Tags that start a new line, so words from two paragraphs don't stick together.
    BREAKS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
              "section", "article", "main", "pre", "blockquote", "table", "dt", "dd"}
    # Tags that never have a closing tag, so they can't start a region.
    VOID = {"br", "img", "input", "meta", "link", "hr", "source", "wbr", "area", "col"}

    def __init__(self):
        super().__init__()  # convert_charrefs: "&amp;" arrives as "&"
        self.parts = []  # all readable text
        self.main_parts = []  # only the text inside <main>/<article>
        self.title = []
        self.in_title = False
        # Open regions, like {"tag": "div", "depth": 2, "kind": "skip"}.
        self.regions = []

    def inside(self, kind):
        return any(region["kind"] == kind for region in self.regions)

    def handle_starttag(self, tag, attrs):
        # A <div> inside a region that started with <div>: one level deeper.
        for region in self.regions:
            if region["tag"] == tag:
                region["depth"] += 1
        role = (dict(attrs).get("role") or "").lower()
        if tag not in self.VOID:
            if tag in self.SKIP or role in self.SKIP_ROLES:
                self.regions.append({"tag": tag, "depth": 1, "kind": "skip"})
            elif tag in self.MAIN or role == "main":
                self.regions.append({"tag": tag, "depth": 1, "kind": "main"})
        if tag == "title":
            self.in_title = True
        elif tag in self.BREAKS:
            self.newline()

    def handle_endtag(self, tag):
        for region in self.regions:
            if region["tag"] == tag:
                region["depth"] -= 1
        # A region whose depth is back to 0 just closed.
        self.regions = [region for region in self.regions if region["depth"] > 0]
        if tag == "title":
            self.in_title = False
        elif tag in self.BREAKS:
            self.newline()

    def newline(self):
        self.parts.append("\n")
        self.main_parts.append("\n")

    def handle_data(self, data):
        # The title lives inside <head>, which is skipped, so check it first.
        if self.in_title:
            self.title.append(data)
        elif not self.inside("skip"):
            self.parts.append(data)
            if self.inside("main"):
                self.main_parts.append(data)


MAIN_MIN_CHARS = 500  # a <main> with less text is probably just a teaser


def clean_lines(parts):
    # Squash runs of spaces in each line, and drop empty lines.
    lines = (" ".join(line.split()) for line in "".join(parts).splitlines())
    return "\n".join(line for line in lines if line)


def html_to_text(html):
    """(title, text) of an HTML page. Nothing in it is run."""
    parser = TextOnly()
    parser.feed(html)
    parser.close()
    text = clean_lines(parser.parts)
    main = clean_lines(parser.main_parts)
    # When the site marks its real content, take only that: no menus,
    # cookie banners or "related articles" that came without a marker.
    if len(main) >= MAIN_MIN_CHARS:
        text = main
    return " ".join("".join(parser.title).split()), text
