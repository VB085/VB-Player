"""UPnP SOAP client for sending actions to UPnP services.

Sends SOAP 1.1 HTTP POST requests to UPnP service control URLs.
"""

from __future__ import annotations

import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

SOAP_ENVELOPE = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:{action} xmlns:u="{service_type}">
      {args}
    </u:{action}>
  </s:Body>
</s:Envelope>"""


def soap_request(
    control_url: str,
    service_type: str,
    action: str,
    args: dict[str, str] | None = None,
    timeout: int = 5,
) -> dict[str, str]:
    """Send a SOAP action request and return response arguments.

    Args:
        control_url: Full URL of the service control endpoint
        service_type: UPnP service type URN
        action: SOAP action name
        args: Action arguments as {name: value}
        timeout: HTTP timeout in seconds

    Returns:
        Response arguments as {name: value}

    Raises:
        UPnPError on failure
    """
    # Build argument XML
    arg_xml = ""
    if args:
        for name, value in args.items():
            arg_xml += f"<{name}>{value}</{name}>\n      "

    body = SOAP_ENVELOPE.format(
        action=action,
        service_type=service_type,
        args=arg_xml,
    )

    headers = {
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPAction": f'"{service_type}#{action}"',
        "User-Agent": "VBPlayer/1.0",
    }

    req = urllib.request.Request(
        control_url,
        data=body.encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            response_data = resp.read()
    except urllib.error.HTTPError as e:
        # Try to parse UPnP error from response
        error_body = e.read().decode("utf-8", errors="replace")
        raise UPnPError(_parse_soap_error(error_body, action)) from e
    except urllib.error.URLError as e:
        raise UPnPError(f"网络错误: {e.reason}") from e
    except Exception as e:
        raise UPnPError(f"请求失败: {e}") from e

    return _parse_soap_response(response_data)


class UPnPError(Exception):
    """UPnP SOAP request error."""
    pass


def _parse_soap_response(data: bytes) -> dict[str, str]:
    """Parse SOAP response body into {name: value} dict."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return {}

    # Find response body (SOAP 1.1 namespace)
    ns = {"s": "http://schemas.xmlsoap.org/soap/envelope/"}
    body = root.find(".//s:Body", ns)
    if body is None:
        return {}

    result = {}
    # Iterate over response children (skip namespace declarations)
    for child in body:
        # Strip namespace from tag
        tag = child.tag
        if "}" in tag:
            tag = tag.split("}", 1)[1]
        if tag == "Fault":
            continue
        if child.text:
            result[tag] = child.text.strip()

    return result


def _parse_soap_error(data: str, action: str) -> str:
    """Parse UPnP error from SOAP fault response."""
    try:
        root = ET.fromstring(data.encode())
        ns = {"s": "http://schemas.xmlsoap.org/soap/envelope/"}
        fault = root.find(".//s:Fault", ns)
        if fault is not None:
            faultcode = fault.findtext("faultcode", "")
            faultstring = fault.findtext("faultstring", "")
            detail = fault.findtext("detail", "")
            return f"{action} 失败: {faultstring} ({faultcode})"
    except Exception as _e:
        import sys; print(f"[{__name__}] {_e}", file=sys.stderr)
    return f"{action} 失败"
