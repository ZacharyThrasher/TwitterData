"""Site parsers. Each exposes parse(page, url="", observed_at="") -> list[Campaign]."""

from . import clipping_net, vyro

PARSERS = {
    vyro.SOURCE: vyro.parse,
    clipping_net.SOURCE: clipping_net.parse,
}
