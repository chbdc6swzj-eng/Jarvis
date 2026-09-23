import msal

from .config import Config

_GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]


class AuthError(RuntimeError):
    pass


def get_access_token(config: Config) -> str:
    """Client-credentials (app-only) auth against Microsoft Graph.

    Requires the app registration to have the Mail.Read application permission
    with admin consent granted. Scope the app to a single mailbox with an
    Exchange ApplicationAccessPolicy (see README) rather than relying on
    Graph permissions alone.
    """
    app = msal.ConfidentialClientApplication(
        client_id=config.client_id,
        client_credential=config.client_secret,
        authority=f"https://login.microsoftonline.com/{config.tenant_id}",
    )
    result = app.acquire_token_silent(_GRAPH_SCOPE, account=None)
    if not result:
        result = app.acquire_token_for_client(scopes=_GRAPH_SCOPE)
    if "access_token" not in result:
        raise AuthError(
            f"Failed to acquire Graph token: {result.get('error')}: "
            f"{result.get('error_description')}"
        )
    return result["access_token"]
