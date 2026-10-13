"""Local files for stdio, bounded public HTTPS media for hosted MCP."""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import mimetypes
import socket
from pathlib import Path
from urllib.parse import unquote

import httpx

from nativ_mcp.runtime import hosted_request


async def _public_address(host: str, port: int) -> str:
    try:
        addresses = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM),
            timeout=10,
        )
    except (OSError, asyncio.TimeoutError) as exc:
        raise RuntimeError("Unable to resolve the media URL.") from exc
    ips = [ipaddress.ip_address(record[4][0]) for record in addresses]
    # Reject the entire hostname if any answer is private (including metadata,
    # loopback and IPv4-mapped IPv6), then pin the connection to a checked IP.
    if not ips or any(
        not ip.is_global or ip.is_multicast or (
            ip.version == 6 and (
                ip.ipv4_mapped is not None or ip.sixtofour is not None or ip.teredo is not None
                or ip in ipaddress.ip_network("64:ff9b::/96")
                or ip in ipaddress.ip_network("64:ff9b:1::/48")
            )
        ) for ip in ips
    ):
        raise RuntimeError("Media URLs must resolve only to public IP addresses.")
    return str(ips[0])


async def download_media(url: str, max_bytes: int) -> tuple[bytes, str, str]:
    try:
        return await asyncio.wait_for(_download_media(url, max_bytes), timeout=120)
    except asyncio.TimeoutError as exc:
        raise RuntimeError("Media download timed out.") from exc


async def _download_media(url: str, max_bytes: int) -> tuple[bytes, str, str]:
    async with httpx.AsyncClient(timeout=120, follow_redirects=False, trust_env=False) as client:
        for _ in range(6):
            try:
                target = httpx.URL(url)
            except httpx.InvalidURL as exc:
                raise RuntimeError("Provide a valid public HTTPS media URL.") from exc
            if target.scheme != "https" or not target.host or target.userinfo or target.port not in (None, 443):
                raise RuntimeError("Provide a public HTTPS media URL on port 443, without embedded credentials.")
            address = await _public_address(target.host, 443)
            request = client.build_request(
                "GET", target.copy_with(host=address), headers={"Host": target.netloc.decode("ascii")},
            )
            # Preserve TLS verification of the original hostname while using a
            # pinned public IP. No Nativ credentials are sent to media hosts.
            request.extensions["sni_hostname"] = target.host
            try:
                response = await client.send(request, stream=True)
                try:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise RuntimeError("Media URL redirected without a destination.")
                        url = str(target.join(location))
                        continue
                    response.raise_for_status()
                    length = response.headers.get("content-length", "")
                    if length.isdigit() and int(length) > max_bytes:
                        raise RuntimeError("Media file exceeds the hosted upload size limit.")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > max_bytes:
                            raise RuntimeError("Media file exceeds the hosted upload size limit.")
                        data.extend(chunk)
                    filename = Path(unquote(target.path)).name or "media"
                    mime = response.headers.get("content-type", "").split(";", 1)[0].strip()
                    mime = mime or mimetypes.guess_type(filename)[0] or "application/octet-stream"
                    # Existing image tools identify the format by extension.
                    if not Path(filename).suffix:
                        filename += mimetypes.guess_extension(mime) or ""
                    return bytes(data), filename, mime
                finally:
                    await response.aclose()
            except httpx.HTTPError as exc:
                # Exceptions can contain signed URL credentials: never echo them.
                raise RuntimeError("Unable to download media from the supplied URL.") from exc
    raise RuntimeError("Media URL exceeded the redirect limit.")


async def read_file(path: str) -> tuple[bytes, str, str]:
    remote = hosted_request.get()
    if remote is not None:
        return await download_media(path, remote.max_media_bytes)
    expanded = Path(path).expanduser()
    if not expanded.is_file():
        raise RuntimeError(f"File not found: {path}")
    mime = mimetypes.guess_type(expanded.name)[0] or "application/octet-stream"
    if expanded.suffix.lower() == ".itt":
        mime = "application/xml"
    return await asyncio.to_thread(expanded.read_bytes), expanded.name, mime


async def read_image(path: str) -> tuple[bytes, str, str]:
    data, filename, mime = await read_file(path)
    supported = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
    image_type = supported.get(Path(filename).suffix.lower())
    if image_type is None:
        raise RuntimeError("Unsupported image type. Supported: PNG, JPEG, WebP.")
    return data, filename, image_type


async def save_bytes(data: bytes, path: str, content_type: str | None = None) -> str:
    remote = hosted_request.get()
    if remote is not None:
        # Treat output_path as a filename hint only. Never write caller paths on
        # the hosted filesystem; object names are random and expire.
        name = Path(path).name or "output"
        mime = content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
        url = await remote.artifact_store.save(data, name, mime)
        remote.artifacts.append({
            "url": url, "filename": name, "mime_type": mime,
            "expires_in_seconds": 3600,
        })
        return url
    expanded = Path(path).expanduser()
    await asyncio.to_thread(expanded.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(expanded.write_bytes, data)
    return str(expanded)


async def save_base64(b64: str, path: str) -> str:
    if b64.strip().startswith("data:") and "," in b64:
        b64 = b64.split(",", 1)[1]
    return await save_bytes(base64.b64decode(b64), path)


async def save_subtitle(srt: str, path: str) -> str:
    return await save_bytes(srt.encode("utf-8"), path, "application/x-subrip")
