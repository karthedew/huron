"""The nginx configuration of the upload proxy has the shape that the upload design needs."""

import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[2] / "deploy/openshift/nginx-uploads.conf.template"
#: A quoted string, a word that can hold ``${NAME}``, or one of ``{``, ``}`` and ``;``.
_TOKEN = re.compile(r'"[^"]*"|(?:\$\{\w+\}|[^\s{};"])+|[{};]')


@dataclass
class Block:
    """One directive of the file, with its arguments and, for a block, its directives."""

    name: str
    args: list[str]
    children: list["Block"] = field(default_factory=list)

    def all(self, name: str) -> list["Block"]:
        """The directives ``name`` directly in this block."""
        return [child for child in self.children if child.name == name]

    def one(self, name: str, *args: str) -> "Block":
        """The one directive ``name`` with the arguments ``args`` directly in this block."""
        (found,) = [child for child in self.all(name) if child.args[: len(args)] == list(args)]
        return found

    def values(self, name: str) -> list[list[str]]:
        """The arguments of each directive ``name`` directly in this block."""
        return [child.args for child in self.all(name)]


def parse(text: str) -> Block:
    """The directives of an nginx configuration, without its comments."""
    tokens = _TOKEN.findall("\n".join(line.split("#", 1)[0] for line in text.splitlines()))
    root = Block("", [])
    stack, words = [root], []
    for token in tokens:
        if token in {";", "{"}:
            block = Block(words[0], words[1:])
            stack[-1].children.append(block)
            if token == "{":
                stack.append(block)
            words = []
        elif token == "}":
            stack.pop()
        else:
            words.append(token)
    assert stack == [root] and not words
    return root


CONFIG = parse(TEMPLATE.read_text())
HTTP = CONFIG.one("http")
SERVER = HTTP.one("server")
CREATION = SERVER.one("location", "=", "/files/")
FILES = SERVER.one("location", "/files/")
OPTIONS = SERVER.one("location", "@tus_options")
AUTH = SERVER.one("location", "=", "/_huron_auth")


def test_the_parser_reads_blocks_and_arguments_and_drops_comments() -> None:
    parsed = parse('a 1 "x y" h:${V}; # comment\nb { c; d 2 {} }')
    assert [(block.name, block.args) for block in parsed.children] == [
        ("a", ["1", '"x y"', "h:${V}"]),
        ("b", []),
    ]
    assert parsed.one("b").values("d") == [["2"]]


def test_the_proxy_listens_on_1080_with_tusd_on_1081_and_the_api_as_a_variable() -> None:
    assert SERVER.values("listen") == [["1080"]]
    assert HTTP.one("upstream", "tusd").values("server") == [["127.0.0.1:1081"]]
    assert HTTP.one("upstream", "api").values("server") == [["${HURON_API_UPSTREAM}"]]


def test_the_template_has_only_the_three_substituted_variables() -> None:
    names = set(re.findall(r"\$\{(\w+)\}", TEMPLATE.read_text()))
    assert names == {"HURON_API_UPSTREAM", "HURON_UPLOADS_HOST", "HURON_UPLOADS_PROTO"}


@pytest.mark.parametrize("location", [CREATION, FILES], ids=["creation", "upload"])
def test_both_files_locations_ask_the_api_and_send_options_without_it(location: Block) -> None:
    assert location.values("auth_request") == [["/_huron_auth"]]
    assert location.values("error_page") == [["418", "=", "@tus_options"]]
    branch = location.one("if")
    assert branch.args == ["($request_method", "=", "OPTIONS)"]
    assert [(child.name, child.args) for child in branch.children] == [("return", ["418"])]
    assert location.values("proxy_request_buffering") == [["off"]]
    assert location.values("proxy_read_timeout") == [["120s"]]
    assert location.values("proxy_pass") == [["http://tusd"]]


def test_options_reach_tusd_without_authorization() -> None:
    assert [(child.name, child.args) for child in OPTIONS.children] == [
        ("proxy_pass", ["http://tusd"])
    ]


def test_the_body_limits_are_1m_for_a_creation_65m_for_a_chunk_and_none_for_the_check() -> None:
    assert CREATION.values("client_max_body_size") == [["1m"]]
    assert FILES.values("client_max_body_size") == [["65m"]]
    assert AUTH.values("client_max_body_size") == [["0"]]


def test_the_server_sets_fixed_forwarded_values_and_clears_forwarded() -> None:
    headers = {args[0]: args[1] for args in SERVER.values("proxy_set_header")}
    assert headers["X-Forwarded-Host"] == '"${HURON_UPLOADS_HOST}"'
    assert headers["X-Forwarded-Proto"] == '"${HURON_UPLOADS_PROTO}"'
    assert headers["Forwarded"] == '""'
    assert headers["Host"] == "$http_host"
    assert "$http_x_forwarded" not in TEMPLATE.read_text()


@pytest.mark.parametrize(
    "location", [CREATION, FILES, OPTIONS], ids=["creation", "upload", "options"]
)
def test_the_tusd_locations_keep_the_headers_of_the_server(location: Block) -> None:
    assert location.all("proxy_set_header") == []


def test_the_check_is_internal_without_the_body_and_caches_allows_only() -> None:
    assert AUTH.values("internal") == [[]]
    assert AUTH.values("proxy_pass_request_body") == [["off"]]
    assert AUTH.values("proxy_cache_valid") == [["204", "30s"]]
    assert AUTH.values("proxy_cache_key") == [
        ['"$request_method|$huron_upload_id|$http_authorization"']
    ]
    assert AUTH.values("proxy_no_cache") == [["$huron_no_cache", "$huron_no_auth"]]
    assert AUTH.values("proxy_cache_bypass") == [["$huron_no_cache", "$huron_no_auth"]]
    headers = {args[0]: args[1] for args in AUTH.values("proxy_set_header")}
    assert headers["X-Original-Method"] == "$request_method"
    assert headers["X-Original-URI"] == "$request_uri"


def test_a_request_without_an_upload_id_or_a_token_is_never_cached() -> None:
    maps = {block.args[1]: block for block in HTTP.all("map")}
    assert maps["$huron_no_cache"].args[0] == "$huron_upload_id"
    assert maps["$huron_no_auth"].args[0] == "$http_authorization"
    for name in ("$huron_no_cache", "$huron_no_auth"):
        assert {(c.name, *c.args) for c in maps[name].children} == {('""', "1"), ("default", "0")}


def test_liveness_answers_204_without_a_call_to_tusd_or_the_api() -> None:
    liveness = SERVER.one("location", "=", "/livez")
    assert [(child.name, child.args) for child in liveness.children] == [("return", ["204"])]


def test_readiness_asks_tusd_for_its_options() -> None:
    readiness = SERVER.one("location", "=", "/readyz")
    assert readiness.values("proxy_method") == [["OPTIONS"]]
    assert readiness.values("proxy_pass") == [["http://tusd/files/"]]
