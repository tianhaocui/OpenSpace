from typing import Dict, Any
from openspace.grounding.core.types import BackendType, SessionConfig
from openspace.grounding.core.provider import Provider
from openspace.config.utils import get_config_value
from .session import WebSession
from openspace.utils.logging import Logger

logger = Logger.get_logger(__name__)


class WebProvider(Provider[WebSession]):

    DEFAULT_SID = BackendType.WEB.value

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(BackendType.WEB, config)

    async def initialize(self) -> None:
        """Initialize Web Provider and create default session"""
        if not self.is_initialized:
            logger.info("Initializing Web provider (Knowledge Research)")
            # Auto-create default session
            await self.create_session(SessionConfig(
                session_name=self.DEFAULT_SID,
                backend_type=BackendType.WEB,
                connection_params={}
            ))
            self.is_initialized = True

    async def create_session(self, session_config: SessionConfig) -> WebSession:
        """Create Web session"""
        session_name = session_config.session_name

        if session_name in self._sessions:
            logger.warning(f"Session {session_name} already exists, returning existing session")
            return self._sessions[session_name]

        # Extract configurable deep research settings from provider config
        base_url = get_config_value(self.config, "deep_research_base_url", None)
        model = get_config_value(self.config, "deep_research_model", None)
        api_key_env = get_config_value(self.config, "deep_research_api_key_env", "OPENROUTER_API_KEY")

        # Create WebSession with auto-connect and auto-initialize enabled
        session = WebSession(
            session_id=session_name,
            config=session_config,
            deep_research_base_url=base_url,
            deep_research_model=model,
            deep_research_api_key_env=api_key_env,
            auto_connect=True,
            auto_initialize=True
        )

        self._sessions[session_name] = session

        logger.info(f"Created Web session (Knowledge Research): {session_name}")
        return session
    
    async def close_session(self, session_name: str) -> None:
        """Close Web session"""
        session = self._sessions.pop(session_name, None)
        if session:
            await session.disconnect()
            logger.info(f"Closed Web session: {session_name}")