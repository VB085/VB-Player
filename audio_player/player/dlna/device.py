"""UPnP device description parsing.

Fetches XML from device LOCATION URL and extracts:
- Device name, manufacturer, model
- AVTransport service control URL
- Icon URL
"""

from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET

# UPnP service type namespaces
NS_UPNP = "urn:schemas-upnp-org:device-1-0"
NS_AVTRANSPORT = "urn:schemas-upnp-org:service:AVTransport:1"
NS_RENDERING_CONTROL = "urn:schemas-upnp-org:service:RenderingControl:1"


class DeviceDescription:
    """Parsed UPnP device description."""

    def __init__(self):
        self.udn: str = ""              # Unique Device Name (uuid:...)
        self.friendly_name: str = ""    # Human-readable name
        self.manufacturer: str = ""
        self.model_name: str = ""
        self.model_number: str = ""
        self.device_type: str = ""
        self.icon_url: str = ""
        self.location: str = ""
        self.avtransport_url: str = ""   # AVTransport control URL (relative)
        self.rendering_url: str = ""     # RenderingControl control URL (relative)
        self.base_url: str = ""          # Base URL for resolving relative URLs


def fetch_description(location: str, timeout: int = 5) -> DeviceDescription | None:
    """Fetch and parse UPnP device description XML from LOCATION URL.

    Returns DeviceDescription or None on failure.
    """
    try:
        req = urllib.request.Request(location, headers={"User-Agent": "VBPlayer/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            xml_data = resp.read()
    except Exception as e:
        import sys; print(f"[dlna] 设备描述获取失败: {e}", file=sys.stderr)
        return None

    return parse_description(xml_data, location)


def parse_description(xml_data: bytes, location: str = "") -> DeviceDescription | None:
    """Parse UPnP device description XML."""
    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError:
        return None

    desc = DeviceDescription()
    desc.location = location

    # Extract base URL from URLBase element or location
    url_base = root.find(f"{{{NS_UPNP}}}URLBase")
    if url_base is not None and url_base.text:
        desc.base_url = url_base.text.rstrip("/")
    elif location:
        from urllib.parse import urlparse
        parsed = urlparse(location)
        desc.base_url = f"{parsed.scheme}://{parsed.netloc}"

    # Find device element
    device = root.find(f"{{{NS_UPNP}}}device")
    if device is None:
        return None

    desc.udn = _text(device, f"{{{NS_UPNP}}}UDN")
    desc.friendly_name = _text(device, f"{{{NS_UPNP}}}friendlyName")
    desc.manufacturer = _text(device, f"{{{NS_UPNP}}}manufacturer")
    desc.model_name = _text(device, f"{{{NS_UPNP}}}modelName")
    desc.model_number = _text(device, f"{{{NS_UPNP}}}modelNumber")
    desc.device_type = _text(device, f"{{{NS_UPNP}}}deviceType")

    # Icon URL
    icon_list = device.find(f"{{{NS_UPNP}}}iconList")
    if icon_list is not None:
        for icon in icon_list.findall(f"{{{NS_UPNP}}}icon"):
            mime = _text(icon, f"{{{NS_UPNP}}}mimetype")
            if mime.startswith("image/"):
                url = _text(icon, f"{{{NS_UPNP}}}url")
                if url:
                    if url.startswith("/"):
                        desc.icon_url = desc.base_url + url
                    else:
                        desc.icon_url = url
                    break

    # Service URLs
    _find_service_urls(device, desc)

    return desc


def _find_service_urls(device: ET.Element, desc: DeviceDescription) -> None:
    """Find AVTransport and RenderingControl service control URLs."""
    service_list = device.find(f"{{{NS_UPNP}}}serviceList")
    if service_list is None:
        return

    for service in service_list.findall(f"{{{NS_UPNP}}}service"):
        stype = _text(service, f"{{{NS_UPNP}}}serviceType")
        ctrl = _text(service, f"{{{NS_UPNP}}}controlURL")

        if NS_AVTRANSPORT in stype:
            desc.avtransport_url = ctrl
        elif NS_RENDERING_CONTROL in stype:
            desc.rendering_url = ctrl


def _text(elem: ET.Element, tag: str) -> str:
    """Get text content of a child element, or empty string."""
    child = elem.find(tag)
    return child.text.strip() if child is not None and child.text else ""
