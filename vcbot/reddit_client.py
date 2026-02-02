from typing import Optional, Tuple

import praw


class RedditClient:
    def __init__(
        self,
        client_id: Optional[str],
        client_secret: Optional[str],
        username: Optional[str],
        password: Optional[str],
        user_agent: Optional[str],
        subreddit: Optional[str],
        refresh_token: Optional[str] = None,
    ) -> None:
        missing = [
            name
            for name, value in (
                ("REDDIT_CLIENT_ID", client_id),
                ("REDDIT_CLIENT_SECRET", client_secret),
                ("REDDIT_USER_AGENT", user_agent),
                ("REDDIT_SUBREDDIT", subreddit),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"Missing Reddit configuration: {', '.join(missing)}")

        self.subreddit_name = subreddit
        if refresh_token:
            self.reddit = praw.Reddit(
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token,
                user_agent=user_agent,
            )
        else:
            if not username or not password:
                raise ValueError(
                    "Missing Reddit refresh token or username/password credentials"
                )
            self.reddit = praw.Reddit(
                client_id=client_id,
                client_secret=client_secret,
                username=username,
                password=password,
                user_agent=user_agent,
            )

    def submit_post(self, title: str, body: str) -> Tuple[str, str]:
        submission = self.reddit.subreddit(self.subreddit_name).submit(
            title=title,
            selftext=body,
        )
        return submission.id, submission.url
