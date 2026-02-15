import time
from typing import Optional, Tuple, List, Dict, Any
import logging
import requests
import json
from pathlib import Path
import praw
from .utils import download_image

logger = logging.getLogger("vcbot.reddit")

class RedditClient:
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        user_agent: Optional[str] = None,
        subreddit: Optional[str] = None,
        refresh_token: Optional[str] = None,
        session_cookies: Optional[str] = None,
        csrf_token: Optional[str] = None,
        flair_id: Optional[str] = None,
    ) -> None:
        self.subreddit_name = subreddit
        self.user_agent = user_agent or "python:vcbot:v1.0 (by /u/unknown)"
        self.session_cookies = session_cookies
        self.csrf_token = csrf_token
        self.flair_id = flair_id
        
        # Use PRAW if client credentials are provided
        if client_id and client_secret:
            if refresh_token:
                self.reddit = praw.Reddit(
                    client_id=client_id,
                    client_secret=client_secret,
                    refresh_token=refresh_token,
                    user_agent=self.user_agent,
                )
            elif username and password:
                self.reddit = praw.Reddit(
                    client_id=client_id,
                    client_secret=client_secret,
                    username=username,
                    password=password,
                    user_agent=self.user_agent,
                )
            else:
                raise ValueError("Missing Reddit refresh token or username/password credentials")
        elif session_cookies and csrf_token:
            self.reddit = None
            self.session = requests.Session()
            self.session.headers.update({
                "User-Agent": self.user_agent,
                "Content-Type": "application/json",
                "x-reddit-csrf": self.csrf_token,
            })
            # Parse cookies string into a dict
            cookies = {}
            for cookie in session_cookies.split(";"):
                if "=" in cookie:
                    name, value = cookie.strip().split("=", 1)
                    cookies[name] = value
            self.session.cookies.update(cookies)
            logger.info("Initialized RedditClient in Web Mode using session cookies")
        else:
            raise ValueError("Missing Reddit configuration (official credentials or session cookies)")

    def submit_post(self, title: str, body: str, flair_id: Optional[str] = None, image_paths: Optional[List[Path]] = None) -> Tuple[str, str]:
        flair_id = flair_id or self.flair_id
        if self.reddit:
            if image_paths:
                # PRAW gallery upload
                images = [{"image_path": str(p)} for p in image_paths]
                submission = self.reddit.subreddit(self.subreddit_name).submit_gallery(
                    title=title,
                    images=images,
                    flair_id=flair_id,
                )
                # PRAW doesn't allow selftext in submit_gallery directly in some versions, 
                # but we can try to add it as a comment or use a different method if needed.
                # For now, let's stick to images if they are provided.
            else:
                submission = self.reddit.subreddit(self.subreddit_name).submit(
                    title=title,
                    selftext=body,
                    flair_id=flair_id,
                )
            return submission.id, submission.url
        else:
            return self._submit_post_web(title, body, flair_id=flair_id, image_paths=image_paths)

    def _upload_image_web(self, image_path: Path) -> str:
        # 1. Create Media Upload Lease
        url = "https://www.reddit.com/svc/shreddit/graphql"
        mimetype = "image/jpeg" # We convert all to jpg in utils.py
        
        payload = {
            "operation": "CreateMediaUploadLease",
            "variables": {
                "input": {
                    "mimetype": "JPEG" # Use uppercase as seen in HAR
                }
            },
            "csrf_token": self.csrf_token
        }
        
        response = self.session.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        
        if data.get("errors"):
             raise Exception(f"Failed to create media upload lease: {json.dumps(data['errors'])}")

        lease_data = data.get("data", {}).get("createMediaUploadLease", {})
        if not lease_data or not lease_data.get("ok"):
            raise Exception(f"Failed to create media upload lease: {json.dumps(lease_data or 'Unknown error')}")
            
        media_id = lease_data["mediaId"]
        upload_url = lease_data["uploadLease"]["uploadLeaseUrl"]
        headers = {h["header"]: h["value"] for h in lease_data["uploadLease"]["uploadLeaseHeaders"]}
        
        # 2. Upload to S3
        with open(image_path, "rb") as f:
            files = {"file": (image_path.name, f, mimetype)}
            # S3 POST expects headers as form data fields
            upload_response = requests.post(upload_url, data=headers, files=files)
            upload_response.raise_for_status()
            
        return media_id

    def _submit_post_web(self, title: str, body: str, flair_id: Optional[str] = None, image_paths: Optional[List[Path]] = None) -> Tuple[str, str]:
        # Implementation of post submission via GraphQL (Web/Shreddit API)
        url = "https://www.reddit.com/svc/shreddit/graphql"
        
        media_ids = []
        if image_paths:
            logger.info("Uploading %d images for Reddit post", len(image_paths))
            for path in image_paths:
                try:
                    media_id = self._upload_image_web(path)
                    media_ids.append(media_id)
                    logger.debug("Uploaded image %s -> mediaId: %s", path, media_id)
                except Exception as e:
                    logger.error(f"Failed to upload image {path}: {e}")

        variables = {
            "input": {
                "subredditName": self.subreddit_name,
                "title": title,
                "content": {"markdown": body},
                # According to HAR, these might need to be outside input or structured differently
                # But Wait, the error said "In field "flairId": Unknown field. In field "postType": Unknown field."
                # and they WERE in $input.
                # Let's try matching the HAR more closely.
            }
        }
        
        if image_paths and media_ids:
            # HAR uses 'postType' in ValidateCreatePostInput but in CreatePost it might not be there
            # Actually, looking at CreatePost in HAR again:
            # {
            #   "operation": "CreatePost",
            #   "variables": {
            #     "input": {
            #       "isNsfw": false,
            #       "isSpoiler": false,
            #       "content": { "richText": "..." },
            #       "title": "...",
            #       "isCommercialCommunication": false,
            #       "targetLanguage": "",
            #       "recaptchaToken": "...",
            #       "gallery": { "items": [...] },
            #       "flair": { "id": "...", "text": "..." },
            #       "subredditName": "...",
            #       "correlationId": "..."
            #     }
            #   },
            #   "csrf_token": "..."
            # }
            # It uses "flair": { "id": "..." } NOT "flairId"
            # And there is NO "postType" in the final CreatePost operation!
            
            variables["input"]["gallery"] = {
                "items": [{"mediaId": mid} for mid in media_ids]
            }
        
        if flair_id:
            variables["input"]["flair"] = {"id": flair_id}
        
        payload = {
            "operation": "CreatePost",
            "variables": variables,
            "csrf_token": self.csrf_token
        }
        
        # Implement retry for transient GraphQL errors
        max_retries = 3
        retry_delay = 2 # seconds
        
        for attempt in range(max_retries):
            try:
                response = self.session.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                
                if data.get("errors"):
                    error_msg = json.dumps(data["errors"])
                    # Check if it's an "Upstream Service error" which might be transient
                    is_transient = any("Upstream Service error" in err.get("message", "") for err in data["errors"])
                    
                    if is_transient and attempt < max_retries - 1:
                        logger.warning(f"Reddit GraphQL transient error (attempt {attempt+1}/{max_retries}): {error_msg}. Retrying...")
                        time.sleep(retry_delay * (attempt + 1))
                        continue
                    
                    raise Exception(f"Reddit GraphQL Error: {error_msg}")
                
                break # Success
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Reddit GraphQL request failed (attempt {attempt+1}/{max_retries}): {e}. Retrying...")
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                raise
            
        # The mutation name in HAR is CreatePost, but sometimes Shreddit returns it under a different key.
        # Let's check the HAR for the response key.
        # Actually, my previous code used 'createSubredditPost'. 
        # Let's re-verify the response structure from HAR.
        
        create_post_data = data.get("data", {}).get("createSubredditPost", {})
            
        if not create_post_data or not create_post_data.get("ok"):
            field_errors = create_post_data.get("fieldErrors") if create_post_data else None
            raise Exception(f"Failed to create post: {json.dumps(field_errors or data.get('errors') or 'Unknown error')}")
            
        post = create_post_data.get("post", {})
        return post.get("id"), f"https://www.reddit.com{post.get('permalink')}"
