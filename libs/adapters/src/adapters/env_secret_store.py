import os

from ports.interfaces import SecretStore


class EnvSecretStore(SecretStore):
    """
    Secret storage port implementation that reads from environment variables.
    """

    async def get(self, key: str) -> str:
        """
        Retrieves the plaintext secret string for the given key from os.environ.
        """
        try:
            return os.environ[key]
        except KeyError:
            raise KeyError(f"Secret '{key}' not found in environment")
