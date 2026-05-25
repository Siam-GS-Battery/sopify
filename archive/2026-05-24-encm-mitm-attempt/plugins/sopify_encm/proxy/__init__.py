"""ENCM proxy addons.

mitmproxy is loaded inside the ENCM container; consumers of this package
do NOT need mitmproxy installed unless they're running the proxy itself.
The addons are imported by ``mitmdump -s http_proxy.py`` at container boot.
"""
