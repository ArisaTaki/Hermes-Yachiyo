"""Product recovery action adapters."""

from apps.shell.agent.runtime.recovery_adapters.app_resolution import (
    DesktopAppResolutionAdapter,
)
from apps.shell.agent.runtime.recovery_adapters.background_window import (
    BackgroundWindowRecoveryAdapter,
)
from apps.shell.agent.runtime.recovery_adapters.apple_music_alias import (
    AppleMusicAliasRecoveryAdapter,
)
from apps.shell.agent.runtime.recovery_adapters.entity_alias import (
    EntityAliasRecoveryAdapter,
)
from apps.shell.agent.runtime.recovery_adapters.file_resolution import (
    WorkspaceFileResolutionAdapter,
)

__all__ = [
    "AppleMusicAliasRecoveryAdapter",
    "BackgroundWindowRecoveryAdapter",
    "DesktopAppResolutionAdapter",
    "EntityAliasRecoveryAdapter",
    "WorkspaceFileResolutionAdapter",
]
