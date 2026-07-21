"""Header photo / avatar: upload from a URL or file, set, remove, toggle.

Two-step flow:
  1. POST resumes/upload_profile_pic (multipart: resumeId + `file`) -> {imageId}
  2. save the imageId into personalDetails.photo (whole-image crop).
Display is toggled via the customization delta `header.photo.show`.

Depends on PersonalMixin (_pd / save_personal) and CustomizationMixin (set).
"""
import json
import os
import struct
import urllib.error
import urllib.request
import uuid

MAX_IMAGE_BYTES = 10 * 1024 * 1024

from .client import API, ORIGIN, UA
from .errors import ApiError

# whole-image crop (matches what FlowCV writes for an un-cropped photo)
FULL_CROP = {"xPct": 0.0004995004995004271, "yPct": 0.0004995004995004271,
             "widthPct": 0.9990009990009991, "heightPct": 0.9990009990009991}


def image_size(data):
    """Best-effort (width, height) from PNG/JPEG bytes; (0, 0) if unknown."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24]) if len(data) >= 24 else (0, 0)
    if data[:2] == b"\xff\xd8":  # JPEG: find a start-of-frame marker
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    return 0, 0


class PhotoMixin:
    def upload_photo(self, data):
        """Upload image bytes to upload_profile_pic; return the imageId string."""
        self._ensure_auth()                       # opener attaches the session cookies
        b = "----flowcvcli" + uuid.uuid4().hex
        body = (
            f"--{b}\r\nContent-Disposition: form-data; name=\"resumeId\"\r\n\r\n{self.resume_id}\r\n"
            f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"photo\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + data + f"\r\n--{b}--\r\n".encode()
        req = urllib.request.Request(
            f"{API}/resumes/upload_profile_pic", data=body, method="POST",
            headers={"accept": "application/json", "user-agent": UA, "origin": ORIGIN,
                     "content-type": f"multipart/form-data; boundary={b}"})
        try:
            with self._opener.open(req, timeout=60) as r:
                env = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            env = json.loads(e.read().decode())
        if not env.get("success"):
            raise ApiError(f"photo upload failed: {json.dumps(env)[:200]}")
        return env["data"]["imageId"]

    def set_photo(self, src, shape="round"):
        """Set the header photo from a local file path or an http(s) URL. Returns env."""
        if os.path.exists(src):                       # a real file wins (e.g. http_avatar.png)
            with open(src, "rb") as f:
                data = f.read(MAX_IMAGE_BYTES + 1)
        elif src.startswith(("http://", "https://")):
            with urllib.request.urlopen(
                    urllib.request.Request(src, headers={"user-agent": UA}), timeout=60) as r:
                data = r.read(MAX_IMAGE_BYTES + 1)
        else:
            raise ApiError(f"photo source not found (not a file or http(s) URL): {src!r}")
        if len(data) > MAX_IMAGE_BYTES:
            raise ApiError("photo too large (> 10 MB)")
        image_id = self.upload_photo(data)
        w, h = image_size(data)
        pd = self._pd()
        pd["photo"] = dict(FULL_CROP, imageId=image_id, shape=shape,
                           originalWidth=w, originalHeight=h)
        env = self.save_personal(pd)
        self.set("header.photo.show", True)   # make sure it displays
        return env

    def remove_photo(self):
        """Clear the header photo and hide the photo slot."""
        pd = self._pd()
        pd["photo"] = {}
        env = self.save_personal(pd)
        self.set("header.photo.show", False)
        return env
