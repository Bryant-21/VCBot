import requests


class DiscordClient:
    def __init__(self, webhook_url: str) -> None:
        if not webhook_url:
            raise ValueError("Missing DISCORD_WEBHOOK_URL")
        self.webhook_url = webhook_url

    def send_message(self, content: str) -> None:
        response = requests.post(self.webhook_url, json={"content": content}, timeout=30)
        response.raise_for_status()
