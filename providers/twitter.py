"""X (Twitter) API v2 provider — OAuth 2.0 with PKCE."""

from __future__ import annotations

import base64
import hashlib
import logging
import mimetypes
import os
import time
from urllib.parse import urlencode

from .base import SocialProvider
from .exceptions import OAuthError, PublishError
from .types import (
    AccountProfile,
    AuthType,
    CommentResult,
    MediaType,
    OAuthTokens,
    PostType,
    PublishContent,
    PublishResult,
    RateLimitConfig,
)

logger = logging.getLogger(__name__)

AUTH_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
API_BASE = "https://api.x.com"
UPLOAD_URL = "https://api.x.com/2/media/upload"

SCOPES = [
    "tweet.read",
    "tweet.write",
    "users.read",
    "media.write",
    "offline.access",
]

CHUNK_SIZE = 5 * 1024 * 1024  # 5 MB


class TwitterProvider(SocialProvider):
    """X (Twitter) API v2 provider using OAuth 2.0 with PKCE."""

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    @property
    def platform_name(self) -> str:
        return "X (Twitter)"

    @property
    def auth_type(self) -> AuthType:
        return AuthType.OAUTH2

    @property
    def max_caption_length(self) -> int:
        return 280

    @property
    def supported_post_types(self) -> list[PostType]:
        return [PostType.TEXT, PostType.IMAGE, PostType.VIDEO]

    @property
    def supported_media_types(self) -> list[MediaType]:
        return [MediaType.JPEG, MediaType.PNG, MediaType.GIF, MediaType.MP4]

    @property
    def required_scopes(self) -> list[str]:
        return SCOPES

    @property
    def rate_limits(self) -> RateLimitConfig:
        return RateLimitConfig(
            requests_per_hour=100,
            requests_per_day=10000,
            publish_per_day=17,  # Free tier hard cap per user per 24h
        )

    # ------------------------------------------------------------------
    # PKCE helpers
    # ------------------------------------------------------------------

    @staticmethod
    def generate_pkce_pair() -> tuple[str, str]:
        """Generate a (code_verifier, code_challenge) pair for PKCE."""
        verifier = base64.urlsafe_b64encode(os.urandom(96)).rstrip(b"=").decode("ascii")
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return verifier, challenge

    # ------------------------------------------------------------------
    # OAuth 2.0 with PKCE
    # ------------------------------------------------------------------

    def get_auth_url(self, redirect_uri: str, state: str, **kwargs) -> str:
        code_challenge = kwargs.get("code_challenge", "")
        params = {
            "response_type": "code",
            "client_id": self.credentials["client_id"],
            "redirect_uri": redirect_uri,
            "scope": " ".join(SCOPES),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str, **kwargs) -> OAuthTokens:
        code_verifier = kwargs.get("code_verifier", "")
        creds_b64 = base64.b64encode(
            f"{self.credentials['client_id']}:{self.credentials['client_secret']}".encode()
        ).decode()

        resp = self._request(
            "POST",
            TOKEN_URL,
            headers={
                "Authorization": f"Basic {creds_b64}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
        )
        body = resp.json()
        if "access_token" not in body:
            raise OAuthError(
                f"X token exchange failed: {body}",
                platform=self.platform_name,
                raw_response=body,
            )
        return OAuthTokens(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token"),
            expires_in=body.get("expires_in"),
            scope=body.get("scope"),
            raw_response=body,
        )

    def refresh_token(self, refresh_token: str) -> OAuthTokens:
        creds_b64 = base64.b64encode(
            f"{self.credentials['client_id']}:{self.credentials['client_secret']}".encode()
        ).decode()

        resp = self._request(
            "POST",
            TOKEN_URL,
            headers={
                "Authorization": f"Basic {creds_b64}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.credentials["client_id"],
            },
        )
        body = resp.json()
        if "access_token" not in body:
            raise OAuthError(
                f"X token refresh failed: {body}",
                platform=self.platform_name,
                raw_response=body,
            )
        return OAuthTokens(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token"),
            expires_in=body.get("expires_in"),
            raw_response=body,
        )

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------

    def get_profile(self, access_token: str) -> AccountProfile:
        resp = self._request(
            "GET",
            f"{API_BASE}/2/users/me",
            access_token=access_token,
            params={"user.fields": "profile_image_url,public_metrics,username"},
        )
        data = resp.json().get("data", {})
        avatar = data.get("profile_image_url", "")
        # X returns _normal (48x48) thumbnails — strip suffix for full resolution
        if avatar and "_normal." in avatar:
            avatar = avatar.replace("_normal.", ".")
        return AccountProfile(
            platform_id=data.get("id", ""),
            name=data.get("name", ""),
            handle=data.get("username"),
            avatar_url=avatar,
            follower_count=data.get("public_metrics", {}).get("followers_count", 0),
        )

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish_post(self, access_token: str, content: PublishContent) -> PublishResult:
        media_ids: list[str] = []
        for path in content.media_files:
            media_ids.append(self._upload_media(access_token, path))

        payload: dict = {}
        if content.text:
            payload["text"] = content.text[: self.max_caption_length]
        if media_ids:
            payload["media"] = {"media_ids": media_ids}

        if not payload.get("text") and not media_ids:
            raise PublishError(
                "X requires text or media",
                platform=self.platform_name,
            )

        resp = self._request(
            "POST",
            f"{API_BASE}/2/tweets",
            access_token=access_token,
            json=payload,
        )
        body = resp.json()
        tweet_id = body.get("data", {}).get("id", "")
        return PublishResult(
            platform_post_id=tweet_id,
            url=f"https://x.com/i/web/status/{tweet_id}",
            extra=body,
        )

    def publish_comment(self, access_token: str, post_id: str, text: str) -> CommentResult:
        resp = self._request(
            "POST",
            f"{API_BASE}/2/tweets",
            access_token=access_token,
            json={
                "text": text[: self.max_caption_length],
                "reply": {"in_reply_to_tweet_id": post_id},
            },
        )
        body = resp.json()
        comment_id = body.get("data", {}).get("id", "")
        return CommentResult(
            platform_comment_id=comment_id,
            extra=body,
        )

    # ------------------------------------------------------------------
    # Media upload (chunked — v2 API)
    # ------------------------------------------------------------------

    def _upload_media(self, access_token: str, file_path: str) -> str:
        """Upload a media file using chunked upload. Returns media_id."""
        mime, _ = mimetypes.guess_type(file_path)
        mime = mime or "application/octet-stream"
        file_size = os.path.getsize(file_path)

        if mime == "image/gif":
            category = "tweet_gif"
        elif mime.startswith("video/"):
            category = "tweet_video"
        else:
            category = "tweet_image"

        # INIT
        init_resp = self._request(
            "POST",
            UPLOAD_URL,
            access_token=access_token,
            data={
                "command": "INIT",
                "media_type": mime,
                "total_bytes": str(file_size),
                "media_category": category,
            },
        )
        media_id = init_resp.json().get("data", {}).get("id")
        if not media_id:
            raise PublishError(
                f"X media INIT failed: {init_resp.json()}",
                platform=self.platform_name,
                raw_response=init_resp.json(),
            )

        # APPEND chunks
        with open(file_path, "rb") as f:
            segment = 0
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                self._request(
                    "POST",
                    f"{UPLOAD_URL}/{media_id}/append",
                    access_token=access_token,
                    files={"media": ("chunk", chunk, mime)},
                    data={
                        "command": "APPEND",
                        "media_id": media_id,
                        "segment_index": str(segment),
                    },
                )
                segment += 1

        # FINALIZE
        final_resp = self._request(
            "POST",
            f"{UPLOAD_URL}/{media_id}/finalize",
            access_token=access_token,
            data={
                "command": "FINALIZE",
                "media_id": media_id,
            },
        )
        proc = final_resp.json().get("data", {}).get("processing_info")

        # Poll STATUS until processing completes (video/GIF only)
        while proc and proc.get("state") not in ("succeeded", "failed", None):
            wait = proc.get("check_after_secs", 5)
            logger.info("X media %s processing: %s, waiting %ds", media_id, proc.get("state"), wait)
            time.sleep(wait)
            status_resp = self._request(
                "GET",
                f"{UPLOAD_URL}/{media_id}",
                access_token=access_token,
            )
            proc = status_resp.json().get("data", {}).get("processing_info")

        if proc and proc.get("state") == "failed":
            raise PublishError(
                f"X media processing failed: {proc}",
                platform=self.platform_name,
            )

        return media_id

    # ------------------------------------------------------------------
    # Token revocation
    # ------------------------------------------------------------------

    def revoke_token(self, access_token: str) -> bool:
        try:
            creds_b64 = base64.b64encode(
                f"{self.credentials['client_id']}:{self.credentials['client_secret']}".encode()
            ).decode()
            self._request(
                "POST",
                f"{API_BASE}/2/oauth2/revoke",
                headers={
                    "Authorization": f"Basic {creds_b64}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "token": access_token,
                    "token_type_hint": "access_token",
                },
            )
            return True
        except Exception:
            logger.exception("Failed to revoke X token")
            return False
